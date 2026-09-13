"""The agent can stop and ask, instead of guessing (§33, IDEAS.md).

The failure this replaces is the quiet one. Told "file this properly" or "delete
the one about the beans" when there are three, the agent had exactly one move:
pick something and act. A confident wrong action on someone's notebook is worse
than a question, and the user only finds out afterwards.

`ask_user` is the smallest possible fix. It ends the turn, that is the feature,
not a limitation: the model asked because it does not know what to do next, so
carrying on would mean carrying on with the guess the question exists to avoid.

**No state is parked on the server.** The choice is sent as the user's next
message, so the answer arrives through the ordinary history the model already
reads. Nothing to expire, nothing lost on a reload, and the exchange saves into
the conversation like any other. That property is what most of these tests are
really about.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import tools


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


# --- validating what the model sent -----------------------------------------


def test_a_well_formed_question_passes_through():
    question, options = tools.validate_ask(
        {"question": "Which note did you mean?", "options": ["The 2019 one", "The 2021 one"]}
    )
    assert question == "Which note did you mean?"
    assert options == ["The 2019 one", "The 2021 one"]


def test_a_comma_separated_string_is_recovered():
    """A small model that sent "yes, no" rather than ["yes", "no"]. Recovering
    is free and the alternative is a dead card the user can only ignore, 
    with the model still waiting for an answer that can never come."""
    _, options = tools.validate_ask({"question": "Replace it?", "options": "yes, no"})
    assert options == ["yes", "no"]


def test_options_written_as_objects_are_accepted():
    """`{"label": ...}` is the shape several models reach for. Rejecting a call
    that meant exactly the right thing would be pedantry with a cost."""
    _, options = tools.validate_ask(
        {"question": "Which?", "options": [{"label": "A"}, {"label": "B"}]}
    )
    assert options == ["A", "B"]


def test_one_option_is_not_a_question():
    with pytest.raises(tools.ToolError, match="at least"):
        tools.validate_ask({"question": "Shall I?", "options": ["yes"]})


def test_duplicate_options_do_not_count_twice():
    """Two buttons reading "yes" is not a choice."""
    with pytest.raises(tools.ToolError):
        tools.validate_ask({"question": "Shall I?", "options": ["yes", "yes"]})


def test_an_empty_question_is_refused():
    with pytest.raises(tools.ToolError, match="question"):
        tools.validate_ask({"question": "   ", "options": ["a", "b"]})


def test_too_many_options_are_trimmed_rather_than_refused():
    """Past six, a list of buttons stops being quicker to read than typing, 
    but a model that offered nine still asked something sensible, so the call
    is trimmed rather than failed."""
    _, options = tools.validate_ask(
        {"question": "Which?", "options": [f"option {i}" for i in range(9)]}
    )
    assert len(options) == tools.MAX_ASK_OPTIONS


def test_a_very_long_option_is_cut_not_rejected():
    _, options = tools.validate_ask({"question": "Which?", "options": ["x" * 500, "b"]})
    assert len(options[0]) == tools.MAX_ASK_OPTION


# --- it cannot be run like an ordinary tool ---------------------------------


def test_the_tool_is_marked_as_ending_the_turn():
    assert tools.TOOLS["ask_user"].ends_turn is True
    assert not tools.TOOLS["ask_user"].destructive  # a question is not a risk


def test_every_turn_ending_tool_has_a_handover():
    """This used to assert `ask_user` was the only one, with the note that a
    second would mean re-reading the agent-loop branch rather than reusing it
    on faith. `run_skill` is that second one, and the branch was rewritten: it
    now asks `tools.handoff_event` what to hand over instead of knowing.

    So the property worth holding is no longer "there is one", it is "every
    tool that stops a turn has something to stop it *for*", a spec marked
    `ends_turn` with no entry in HANDOFFS would end turns and yield nothing.
    """
    ending = {name for name, spec in tools.TOOLS.items() if spec.ends_turn}
    assert ending == set(tools.HANDOFFS)
    assert "ask_user" in ending


def test_running_it_directly_fails_loudly(session):
    """Returning something plausible instead would let a path that bypasses
    the agent loop silently "answer" a question the user never saw."""
    with pytest.raises(tools.ToolError, match="answered by the person"):
        tools.TOOLS["ask_user"].handler(session, {"question": "q", "options": ["a", "b"]})


def test_the_confirm_endpoint_will_not_run_it(ai_client):
    """`POST /chat/tools/execute` is the other way into a tool. It must not be
    a back door into fabricating an answer."""
    response = ai_client.post(
        "/chat/tools/execute",
        json={"name": "ask_user", "arguments": {"question": "q", "options": ["a", "b"]}},
    )
    assert response.status_code >= 400


# --- always offered ----------------------------------------------------------


def test_it_is_offered_whatever_the_question_is_about():
    """A cue-based rule has nothing to match on here: a request can be
    ambiguous whatever its subject. So this is one of the few tools offered
    unconditionally: the alternative is the model guessing."""
    for question in ("tidy up my notes", "what did I write about beans", "hello"):
        focused = tools.focus_for(question)
        assert focused is None or "ask_user" in focused


def test_its_schema_is_small_enough_to_carry_everywhere():
    """It is in the always-offered set, so it is paid for on every single turn.
    That is only defensible while it stays cheap."""
    schema = next(
        t for t in tools.ollama_tools(["ask_user"]) if t["function"]["name"] == "ask_user"
    )
    assert len(json.dumps(schema)) < 900


# --- through the agent -------------------------------------------------------


def test_the_agent_stops_and_asks(ai_client, fake_ollama):
    ai_client.post("/entries", json={"content": "a note about beans"})
    fake_ollama.tool_script = [
        [
            {
                "name": "ask_user",
                "arguments": {
                    "question": "Which beans note did you mean?",
                    "options": ["The 2019 one", "The 2021 one"],
                },
            }
        ]
    ]
    events = _events(ai_client, "delete the beans note", use_tools=True)
    ask = next(e for e in events if e["type"] == "ask")
    assert ask["question"] == "Which beans note did you mean?"
    assert ask["options"] == ["The 2019 one", "The 2021 one"]


def test_the_turn_really_ends_there(ai_client, fake_ollama):
    """The model asked because it does not know what to do next. Letting it
    carry on would mean carrying on with the guess the question exists to
    avoid: so no answer follows, and no further round runs."""
    ai_client.post("/entries", json={"content": "a note about beans"})
    fake_ollama.tool_script = [
        [{"name": "ask_user", "arguments": {"question": "Which?", "options": ["a", "b"]}}],
        # A second round the agent must never reach.
        [{"name": "create_note", "arguments": {"content": "should never be created"}}],
    ]
    events = _events(ai_client, "do the thing", use_tools=True)
    kinds = [e["type"] for e in events]
    assert "ask" in kinds
    assert kinds.index("ask") == len(kinds) - 2  # only "done" follows
    assert not any(e["type"] == "answer" for e in events)
    # And nothing was written.
    entries = ai_client.get("/entries").json()
    rows = entries["entries"] if isinstance(entries, dict) else entries
    assert not any("should never be created" in e["content"] for e in rows)


def test_a_malformed_question_is_recoverable_not_fatal(ai_client, fake_ollama):
    """A model that offers one option has made a fixable mistake. Ending the
    turn on it would strand the user with nothing, so the reason goes back to
    the model and the run continues."""
    ai_client.post("/entries", json={"content": "a note about beans"})
    fake_ollama.tool_script = [
        [{"name": "ask_user", "arguments": {"question": "Shall I?", "options": ["yes"]}}]
    ]
    fake_ollama.librarian_reply = "I went ahead and checked your notes instead."
    events = _events(ai_client, "have a look", use_tools=True)
    kinds = [e["type"] for e in events]
    assert "ask" not in kinds
    failed = [e for e in events if e["type"] == "tool" and not e.get("ok")]
    assert failed, "the model should be told why its question was rejected"
    assert any(e["type"] == "answer" for e in events), "the turn should continue"


def test_the_hallucinated_write_warning_does_not_fire_on_a_question(
    ai_client, fake_ollama
):
    """The safety net that catches "I saved that!" when nothing was saved must
    not treat a turn that ended in a question as a broken promise, nothing was
    claimed, and the run is deliberately unfinished."""
    ai_client.post("/entries", json={"content": "a note"})
    fake_ollama.tool_script = [
        [{"name": "ask_user", "arguments": {"question": "Which?", "options": ["a", "b"]}}]
    ]
    events = _events(ai_client, "save something", use_tools=True)
    assert not any(
        "didn't actually save" in (e.get("delta") or "") for e in events
    )
