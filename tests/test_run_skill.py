"""The agent can start a saved skill (roadmap §33, "worth building" item 1).

Before this, the model could *see* a job it was perfectly capable of doing and
had no way to begin it: `list_skills` said what existed, `when_to_use` said
which one fitted, and starting one was a click only the user could make. The
model's best available move was to describe the skill and hope.

`run_skill` closes that, and it deliberately reuses the two mechanisms that
were already there rather than inventing a third:

- **`ends_turn`**, built for `ask_user`. The agent's turn stops and the skill
  runner takes over: which is honest, because a run is not a tool result the
  model should carry on reasoning about. It is the rest of the work.
- **the allowlist**, built for the chip UI. A run started by the model offers
  exactly the tools the skill declared, enforced at execution, the same as one
  started by hand.

The property most of these tests are really about: **starting a skill this way
is indistinguishable from the user starting it.** Same resolution, same plan,
same ticked steps, same Undo on every change, because it is the same code
path, reached by the client sending the skill's name back down `/chat/stream`.
That is why there is no server-side parked state here, exactly as there is
none for `ask_user`.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import skills, tools
from memorymap.core import deps


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _save(skill: dict) -> None:
    """Put one skill in the user's own list, the way the settings route does."""
    config = deps.get_config()
    config.set_preference("skills", [*skills.stored(config), skill])


# --- resolving what the model asked for -------------------------------------


def test_a_built_in_skill_resolves_by_name(app_state):
    catalog = skills.catalog(deps.get_config(), set(tools.TOOLS))
    wanted = catalog[0]["name"]
    event = tools.validate_run_skill({"name": wanted})
    assert event["type"] == "run_skill"
    assert event["skill"] == wanted


def test_decoration_in_a_skill_name_may_be_dropped(app_state):
    """A model asked to pass a skill's name back drops the punctuation in it,
    changes the case, or both, the single most likely mistake, and free to
    recover from.

    This used to reach into the catalogue for a built-in whose name began with
    an emoji, because every audit skill was named "🏷 Auto-tag my notes". The
    emoji are gone app-wide (a skill name lands in an `<option>`, which cannot
    hold an icon element), so there is no such built-in left and the lookup
    raised StopIteration. The behaviour under test never depended on emoji
    specifically, it is about forgiving decoration of any kind, so the test
    now makes its own decorated skill instead of borrowing one.
    """
    _save({"name": "★ Weekly tidy-up!", "prompt": "Tidy the notebook."})
    stripped = "Weekly tidy up"
    assert tools.validate_run_skill({"name": stripped.lower()})["skill"] == "★ Weekly tidy-up!"


def test_an_exact_name_wins_over_the_forgiving_match(app_state):
    """Two skills differing only in punctuation must both stay reachable."""
    _save({"name": "Weekly review", "prompt": "Summarise the week."})
    _save({"name": "Weekly-review", "prompt": "Something else entirely."})
    assert tools.validate_run_skill({"name": "Weekly-review"})["skill"] == "Weekly-review"
    assert tools.validate_run_skill({"name": "Weekly review"})["skill"] == "Weekly review"


def test_an_unknown_skill_names_the_ones_that_exist(app_state):
    """A dead end is a wasted round. The error carries the names, so the
    model's next move is a working call rather than another guess."""
    with pytest.raises(tools.ToolError) as exc:
        tools.validate_run_skill({"name": "Do my taxes"})
    message = str(exc.value)
    assert "Do my taxes" in message
    assert "list_skills" in message
    first = skills.catalog(deps.get_config(), set(tools.TOOLS))[0]["name"]
    assert first in message


def test_a_missing_name_is_refused(app_state):
    with pytest.raises(tools.ToolError, match="name of a skill"):
        tools.validate_run_skill({"name": "  "})


# --- the inputs a run needs -------------------------------------------------


def test_a_required_input_left_blank_is_named_not_guessed(app_state):
    """The same rule `_resolve_skill` enforces with a 422: a run with a blank
    {{topic}} searches the whole notebook for nothing and reads to the user as
    having been ignored."""
    _save(
        {
            "name": "Topic digest",
            "prompt": "Summarise everything about {{topic}}.",
            "inputs": [{"name": "topic", "label": "Which topic?", "required": True}],
        }
    )
    with pytest.raises(tools.ToolError) as exc:
        tools.validate_run_skill({"name": "Topic digest"})
    assert "topic" in str(exc.value)
    assert "Which topic?" in str(exc.value)  # the label, so the model can ask it


def test_a_supplied_input_is_carried_through(app_state):
    _save(
        {
            "name": "Topic digest",
            "prompt": "Summarise everything about {{topic}}.",
            "inputs": [{"name": "topic", "required": True}],
        }
    )
    event = tools.validate_run_skill({"name": "Topic digest", "inputs": {"topic": "beans"}})
    assert event["inputs"] == {"topic": "beans"}
    assert "beans" in event["label"]


def test_an_input_the_skill_never_declared_is_dropped(app_state):
    """An invented key is noise, not a mistake worth spending a round on, 
    and `fill` leaves undeclared placeholders alone anyway."""
    _save({"name": "Tidy up", "prompt": "Tidy the notebook."})
    event = tools.validate_run_skill({"name": "Tidy up", "inputs": {"nonsense": "x"}})
    assert event["inputs"] == {}


def test_inputs_sent_as_a_json_string_are_recovered(app_state):
    """A quoting mistake should not cost a run. Same recovery as `validate_ask`
    makes for options sent as "yes, no"."""
    _save(
        {
            "name": "Topic digest",
            "prompt": "About {{topic}}.",
            "inputs": [{"name": "topic", "required": True}],
        }
    )
    event = tools.validate_run_skill(
        {"name": "Topic digest", "inputs": json.dumps({"topic": "beans"})}
    )
    assert event["inputs"] == {"topic": "beans"}


def test_a_default_satisfies_a_required_input(app_state):
    _save(
        {
            "name": "Recent digest",
            "prompt": "Summarise the last {{days}} days.",
            "inputs": [{"name": "days", "required": True, "default": "7"}],
        }
    )
    assert tools.validate_run_skill({"name": "Recent digest"})["skill"] == "Recent digest"


# --- what the event tells the UI --------------------------------------------


def test_the_event_says_whether_the_run_will_change_notes(app_state):
    """`changes_notes` was built for `list_skills` so the model could choose on
    something better than a name. The handover carries it too, so the UI can
    say what is about to happen rather than only that something is."""
    _save(
        {
            "name": "Read only",
            "prompt": "Summarise my notes.",
            "tools": ["search_notes", "get_note"],
        }
    )
    _save({"name": "Writes", "prompt": "Tag my notes.", "tools": ["tag_note"]})
    assert tools.validate_run_skill({"name": "Read only"})["changes_notes"] is False
    assert tools.validate_run_skill({"name": "Writes"})["changes_notes"] is True


def test_the_label_names_the_skill(app_state):
    _save({"name": "Tidy up", "prompt": "Tidy the notebook."})
    assert "Tidy up" in tools.validate_run_skill({"name": "Tidy up"})["label"]


# --- it cannot be run like an ordinary tool ---------------------------------


def test_the_tool_is_marked_as_ending_the_turn():
    assert tools.TOOLS["run_skill"].ends_turn is True


def test_running_it_directly_fails_loudly(session, app_state):
    """The handler exists because every ToolSpec has one, and it raises for the
    same reason `_ask_user` does: a path that bypasses the agent loop must not
    be able to "start" a run with no plan drawn and no steps ticked off."""
    with pytest.raises(tools.ToolError, match="cannot"):
        tools.TOOLS["run_skill"].handler(session, {"name": "Tidy up"})


def test_the_confirm_endpoint_will_not_run_it(ai_client):
    """`POST /chat/tools/execute` is the other way into a tool, and it must not
    be a back door into starting a run the user never saw begin."""
    response = ai_client.post(
        "/chat/tools/execute",
        json={"name": "run_skill", "arguments": {"name": "Tidy up"}},
    )
    assert response.status_code >= 400


# --- no skill may start a skill ---------------------------------------------


def test_a_skill_cannot_declare_run_skill(app_state):
    """A skill holding `run_skill` could start itself: each run brings its own
    fresh rounds, so the per-turn budget that bounds an ordinary loop would
    never bind. Refused at save, not at execution, the allowlist would only
    catch it once the run was already going."""
    with pytest.raises(skills.SkillError, match="never have to stop"):
        skills.normalise(
            {"name": "Loop", "prompt": "Run yourself.", "tools": ["run_skill"]},
            set(tools.TOOLS),
        )


def test_a_skill_run_is_not_offered_run_skill(app_state):
    """The allowlist is the second line of the same defence: whatever a stored
    skill claims, a run only ever sees the tools it declared."""
    offered = {t["function"]["name"] for t in tools.ollama_tools(["search_notes", "tag_note"])}
    assert "run_skill" not in offered


# --- end to end, through the agent loop -------------------------------------


def test_the_agent_ends_its_turn_with_a_run_skill_event(ai_client, fake_ollama, app_state):
    """The whole point, in one assertion: the model calls `run_skill`, the turn
    stops there, and the client is handed the name to start."""
    _save({"name": "Tidy up", "prompt": "Tidy the notebook.", "tools": ["search_notes"]})
    fake_ollama.tool_script = [
        [{"name": "run_skill", "arguments": {"name": "Tidy up"}}]
    ]
    events = _events(ai_client, "please tidy up my notebook using a skill", use_tools=True)
    handover = [e for e in events if e["type"] == "run_skill"]
    assert len(handover) == 1
    assert handover[0]["skill"] == "Tidy up"


def test_nothing_after_the_handover_is_run(ai_client, fake_ollama, app_state):
    """`ends_turn` means the run replaces the rest of the turn. A second call
    in the same round must not also fire, the skill is about to do the work,
    and a stray write beside it would be outside the plan the user sees."""
    _save({"name": "Tidy up", "prompt": "Tidy the notebook.", "tools": ["search_notes"]})
    fake_ollama.tool_script = [
        [
            {"name": "run_skill", "arguments": {"name": "Tidy up"}},
            {"name": "create_note", "arguments": {"content": "should never exist"}},
        ]
    ]
    events = _events(ai_client, "tidy up my notebook with a skill", use_tools=True)
    assert any(e["type"] == "run_skill" for e in events)
    assert not any(e.get("type") == "tool" and "note" in str(e.get("label", "")) for e in events)


def test_a_bad_skill_name_is_recoverable_rather_than_fatal(ai_client, fake_ollama, app_state):
    """A named skill that doesn't exist is a mistake the model can fix inside
    the same turn: so the loop hands back the reason and carries on, rather
    than ending on a tool that was supposed to end it."""
    # One scripted round, then the fake runs dry and gives its text answer, 
    # which is the point: the turn carries on rather than ending on a tool
    # that was supposed to end it.
    fake_ollama.tool_script = [[{"name": "run_skill", "arguments": {"name": "No such skill"}}]]
    events = _events(ai_client, "run a skill for me please", use_tools=True)
    assert not any(e["type"] == "run_skill" for e in events)
    failed = [e for e in events if e["type"] == "tool" and not e.get("ok")]
    assert failed and "No such skill" in failed[0]["error"]
    # And the turn still finished with words, rather than dying on the error.
    assert any(e["type"] == "answer" for e in events)


def test_an_unhandled_error_before_the_first_event_still_answers(
    ai_client, fake_ollama, app_state, monkeypatch
):
    """Reported directly: a skill run that "failed before even completing the
    first step ... no answer and no tool call", the stream just ended with
    nothing rendered. The route's own outer `next(agent_events, None)` had
    nothing catching an exception raised before the runner's first yield, so
    it killed the generator and FastAPI just closed the connection. This is
    not about what raised (skill_runner.run_skill itself is a thin wrapper;
    almost anything under it could), it's that whatever does must still
    reach the user as a real event, not silence."""
    from memorymap.ai import skill_runner

    _save({"name": "Tidy up", "prompt": "Tidy the notebook.", "tools": ["search_notes"]})

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure before the first event")
        yield  # pragma: no cover: makes this a generator function

    monkeypatch.setattr(skill_runner, "run_skill", _boom)
    events = _events(ai_client, "ph:lightning Tidy up", skill="Tidy up", use_tools=True)
    answers = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "simulated failure before the first event" in answers
    assert events[-1]["type"] == "done"


def test_an_unhandled_error_mid_run_still_reaches_done(
    ai_client, fake_ollama, app_state, monkeypatch
):
    """Same failure, later: something breaks after the plan/first step has
    already streamed. The stream must still end cleanly rather than cutting
    off with the rest of the run rendered as if it simply stopped."""
    from memorymap.ai import skill_runner

    _save({"name": "Tidy up", "prompt": "Tidy the notebook.", "tools": ["search_notes"]})

    def _boom(*args, **kwargs):
        yield {"type": "plan", "skill": "Tidy up", "steps": [], "tools": []}
        raise RuntimeError("simulated failure mid-run")

    monkeypatch.setattr(skill_runner, "run_skill", _boom)
    events = _events(ai_client, "ph:lightning Tidy up", skill="Tidy up", use_tools=True)
    assert any(e["type"] == "plan" for e in events)
    answers = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "simulated failure mid-run" in answers
    assert events[-1]["type"] == "done"


def test_list_skills_no_longer_tells_the_model_it_cannot_start_one(session, app_state):
    """The note used to read "You cannot start a skill yourself". Leaving that
    in place while shipping the tool would be worse than either state: a model
    that believes it cannot act will narrate instead of calling."""
    note = tools.TOOLS["list_skills"].handler(session, {})["note_to_model"]
    assert "cannot start" not in note.lower()
    assert "run_skill" in note


# --- a step has a contract (skills reform, Phase A) --------------------------
#
# The reported failure, verbatim: *"I ran a skill and it ran no tools... the
# models often dont even properly complete a step before they are prompted for
# the next step. its an absolute mess."*
#
# What the fake model does here is exactly that failure: it narrates. Every
# test below is about what the runner does when a step's declared condition is
# not met: and the answer must never be "tick it green and move on".
#
# **What these cannot prove**, and the standing caveat in CLAUDE.md is the
# reason: whether a real 4B model, handed the nudge, then calls the tool. The
# fake calls what the script tells it to. What is provable here is the
# mechanism: that the nudge is sent, that it names the right tool, that a
# call on the second attempt is accepted, and that running out of attempts
# stalls rather than passes.


CONTRACT_SKILL = {
    "name": "Tag audit",
    "prompt": "Check my tags.",
    "steps": [
        {"text": "List every tag I use.", "expects": "tool_called", "tools": ["list_tags"]},
        {"text": "Tell me which ones look duplicated.", "expects": "answer_only"},
    ],
    "tools": ["list_tags", "list_notes", "get_note"],
}


def _sent(fake) -> list[str]:
    """Every user message the fake was handed, across every round."""
    return [
        str(message.get("content", ""))
        for round_messages in fake.tool_rounds
        for message in round_messages
        if message.get("role") == "user"
    ]


def test_a_step_that_expects_a_tool_call_is_re_prompted_not_skipped(
    ai_client, fake_ollama, app_state
):
    """The heart of the reform. The model answers in prose and calls nothing;
    the step is not done, so it is asked again, literally, by name."""
    _save(CONTRACT_SKILL)
    events = _events(ai_client, "run", skill="Tag audit")
    steps = [e for e in events if e["type"] == "step" and e["index"] == 0]

    #: The first cycle, exactly. A run now also *re-plans* a step it could not
    #: finish (PLAN.md §4 A2, `skill_runner.MAX_REPLANS`), so the same four
    #: states repeat with a rewritten step behind each `replanned`, the
    #: property being pinned here is the shape of one attempt, and it is
    #: unchanged. The two assertions after it hold over the whole run: it
    #: still ends `stalled`, and it is still never ticked `done`.
    assert [s["state"] for s in steps][:4] == ["running", "retrying", "retrying", "stalled"]
    assert [s["attempt"] for s in steps if s["state"] == "retrying"][:2] == [2, 3]
    assert steps[-1]["state"] == "stalled"
    assert "done" not in [s["state"] for s in steps], (
        "a step whose contract was never met must never be ticked off, "
        "however many times the run re-planned it"
    )
    # The nudge names the tool, because that is the thing a small model acts
    # on: not a restatement of the step it has already failed to follow.
    nudges = [text for text in _sent(fake_ollama) if "You did not call" in text]
    assert nudges, "the step was never re-prompted"
    assert "`list_tags`" in nudges[0]
    # …and it comes before the step it is correcting, rather than being buried
    # under a restatement of the instruction the model already did not follow.
    assert nudges[0].index("You did not call") < nudges[0].index("Step 1")


def test_a_step_whose_contract_is_never_met_stalls_rather_than_passing(
    ai_client, fake_ollama, app_state
):
    """"Never silently done" is the whole point: a run that did nothing must
    not report success, and the reason has to name the contract that failed."""
    _save(CONTRACT_SKILL)
    events = _events(ai_client, "run", skill="Tag audit")
    stalled = [e for e in events if e["type"] == "step" and e["state"] == "stalled"]
    result = [e for e in events if e["type"] == "result"][0]

    assert stalled and stalled[0]["index"] == 0
    assert "list_tags" in stalled[0]["reason"]
    assert not any(e["type"] == "step" and e["state"] == "done" for e in events)
    # Stopped here, so Resume picks up from this step rather than the run
    # being reported as finished.
    assert result["stopped_at"] == 0


def test_a_step_that_calls_the_tool_on_the_second_attempt_is_done(
    ai_client, fake_ollama, app_state
):
    """The other half: the nudge is a *re-prompt*, not a slower failure. A
    model that narrates once and then complies gets a finished step."""
    _save(CONTRACT_SKILL)
    original = fake_ollama.chat_tools

    def complies_after_the_nudge(model, messages, tools, mode=None):
        # Stands in for the behaviour the nudge exists to produce. Whether a
        # real 4B model does this cannot be established from here, see the
        # note at the top of this section.
        last = str(messages[-1].get("content", ""))
        if "You did not call" in last and not fake_ollama.tool_script:
            fake_ollama.tool_script = [[{"name": "list_tags", "arguments": {}}]]
        return original(model, messages, tools, mode)

    fake_ollama.chat_tools = complies_after_the_nudge
    events = _events(ai_client, "run", skill="Tag audit")
    first_step = [e for e in events if e["type"] == "step" and e["index"] == 0]

    assert [s["state"] for s in first_step] == ["running", "retrying", "done"]
    assert any(e["type"] == "tool" and e.get("tool") == "list_tags" for e in events)
    # And the run carries on to the step after it, rather than ending there.
    assert any(e["type"] == "step" and e["index"] == 1 and e["state"] == "done" for e in events)


def test_a_step_that_owed_words_is_asked_for_words(ai_client, fake_ollama, app_state):
    """The `answer_only` half, and not a corner case: a model that calls a tool
    and then says nothing has left a step whose deliverable is words with none
    in it. Nudging *that* model about tool calls would be both false and the
    opposite of what it needs to hear."""
    _save(
        {
            "name": "Say something",
            "prompt": "Look and report.",
            "steps": [{"text": "Tell me what you see.", "expects": "answer_only"}],
            "tools": ["list_tags"],
        }
    )
    fake_ollama.librarian_reply = ""  # the model calls something and says nothing
    fake_ollama.tool_script = [[{"name": "list_tags", "arguments": {}}]]
    events = _events(ai_client, "run", skill="Say something")

    assert any(e["type"] == "step" and e["state"] == "retrying" for e in events)
    nudges = [text for text in _sent(fake_ollama) if "You did not answer" in text]
    assert nudges, "the step was never asked for its answer"
    assert not any(e["type"] == "step" and e["state"] == "done" for e in events)


def test_a_step_is_never_marked_done_without_its_contract(ai_client, fake_ollama, app_state):
    """The regression this whole phase exists to prevent, stated on its own:
    before contracts, this exact run ticked every step green having called
    nothing at all."""
    _save(CONTRACT_SKILL)
    events = _events(ai_client, "run", skill="Tag audit")
    assert not any(e["type"] == "tool" for e in events)  # the model called nothing
    assert not any(e["type"] == "step" and e["state"] == "done" for e in events)


# --- legacy steps are untouched ----------------------------------------------


def test_a_skill_whose_steps_are_plain_strings_still_runs(ai_client, fake_ollama, app_state):
    """Backwards compatibility, and not a small point: every skill anyone has
    ever saved is a list of strings, as is every ad-hoc plan. A string step has
    no contract, so it advances on what the model said, exactly as before."""
    _save(
        {
            "name": "Old style steps",
            "prompt": "Summarise my week.",
            "steps": ["Find this week's notes.", "Summarise them."],
            "tools": ["list_notes"],
        }
    )
    events = _events(ai_client, "run", skill="Old style steps")
    steps = [e for e in events if e["type"] == "step"]
    result = [e for e in events if e["type"] == "result"][0]

    assert [s["state"] for s in steps] == ["running", "done", "running", "done"]
    assert not any(s["state"] == "retrying" for s in steps)
    assert result["stopped_at"] is None


def test_a_string_step_normalises_to_an_unchecked_contract(app_state):
    skill = skills.normalise({"name": "S", "prompt": "p", "steps": ["one", "two"]})
    assert skill["steps"] == ["one", "two"]  # the shape the frontend reads
    assert [spec["expects"] for spec in skill["step_specs"]] == [None, None]
    assert [spec["text"] for spec in skill["step_specs"]] == ["one", "two"]


def test_a_declared_contract_survives_being_normalised_again(app_state):
    """`catalog()` re-normalises everything stored, so a skill that lost its
    contracts on a round trip would work the first time it ran and not the
    second: the worst shape of bug to be handed."""
    once = skills.normalise(CONTRACT_SKILL, set(tools.TOOLS))
    twice = skills.normalise(once, set(tools.TOOLS))
    assert twice["step_specs"] == once["step_specs"]
    assert twice["step_specs"][0]["tools"] == ["list_tags"]


def test_a_step_cannot_expect_a_tool_the_skill_never_declared(app_state):
    """A contract nothing could ever meet: the allowlist would refuse the call,
    so the step would be nudged twice and stall every single run."""
    with pytest.raises(skills.SkillError, match="does not declare"):
        skills.normalise(
            {
                "name": "Impossible",
                "prompt": "p",
                "steps": [{"text": "Tag them.", "expects": "tool_called", "tools": ["tag_note"]}],
                "tools": ["list_notes"],
            },
            set(tools.TOOLS),
        )


def test_a_step_cannot_expect_something_that_is_not_a_contract(app_state):
    with pytest.raises(skills.SkillError, match="not something a step can expect"):
        skills.normalise(
            {"name": "Odd", "prompt": "p", "steps": [{"text": "x", "expects": "vibes"}]}
        )


# --- what one step tells the next (Phase A: structured state) ----------------


def test_the_ids_a_step_touched_reach_the_next_steps_instruction(
    ai_client, fake_ollama, app_state
):
    """"Those notes" has to resolve to something. Before this, a later step got
    the previous one's *prose* about what it did and had to guess."""
    _save(
        {
            "name": "Two parter",
            "prompt": "Tag things.",
            "steps": ["Tag a note.", "Now say which notes you touched."],
            "tools": ["list_notes", "get_note", "tag_note"],
        }
    )
    note = ai_client.post("/entries", json={"content": "a note that wants tagging"}).json()
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note["id"], "add": ["filed"]}}]
    ]
    events = _events(ai_client, "run", skill="Two parter")

    second_step_instruction = _sent(fake_ollama)[-1]
    assert "State so far" in second_step_instruction
    assert f"#{note['id']}" in second_step_instruction
    assert "tags: filed" in second_step_instruction
    # …and the same state comes back with the result, for whatever picks the
    # run up next.
    state = [e for e in events if e["type"] == "result"][0]["state"]
    assert note["id"] in state["note_ids"]
    assert note["id"] in state["touched"]
    assert state["tags"] == ["filed"]
    assert state["last_tool"] == "tag_note"


def test_the_state_line_is_empty_until_something_is_known():
    assert skills.state_line({}) == ""
    assert skills.state_line(None) == ""
    assert skills.state_line({"note_ids": [3, 9]}) == "State so far: notes #3, #9."


# --- small-model mode (skills reform, Phase B) -------------------------------


def test_small_model_mode_offers_only_the_tool_the_step_names(
    ai_client, fake_ollama, app_state
):
    """A 4B model handed five schemas for a step that needs one picks the wrong
    one. In small-model mode the step is offered exactly what its contract
    names: the skill's allowlist, one level down."""
    app_state.set_preference("small_model_mode", "on")
    _save(CONTRACT_SKILL)
    offered: list[set[str]] = []
    original = fake_ollama.chat_tools

    def spy(model, messages, tools, mode=None):
        offered.append({t["function"]["name"] for t in tools})
        return original(model, messages, tools, mode)

    fake_ollama.chat_tools = spy
    _events(ai_client, "run", skill="Tag audit")

    assert offered and offered[0] == {"list_tags"}
    # The worked example is built from the tool's own schema, so it cannot go
    # stale when the schema changes.
    first_instruction = _sent(fake_ollama)[0]
    assert "list_tags({})" in first_instruction


def test_small_model_mode_off_offers_the_whole_skill_allowlist(
    ai_client, fake_ollama, app_state
):
    """The default is unchanged. Narrowing a capable model's toolbox is a real
    cost, so it happens only when asked for."""
    app_state.set_preference("small_model_mode", "off")
    _save(CONTRACT_SKILL)
    offered: list[set[str]] = []
    original = fake_ollama.chat_tools

    def spy(model, messages, tools, mode=None):
        offered.append({t["function"]["name"] for t in tools})
        return original(model, messages, tools, mode)

    fake_ollama.chat_tools = spy
    _events(ai_client, "run", skill="Tag audit")
    assert offered and offered[0] == {"list_tags", "list_notes", "get_note"}


def test_a_step_with_no_named_tool_still_gets_the_skills_tools(app_state):
    """The fallback that stops small-model mode from making a `tool_called`
    step impossible: offered nothing, it could never call anything."""
    from memorymap.ai import skill_runner

    spec = {"text": "x", "expects": "tool_called", "tools": []}
    assert skill_runner._step_tools(spec, ["a", "b"], True) == ["a", "b"]
    assert skill_runner._step_tools({"tools": ["a"]}, ["a", "b"], True) == ["a"]
    assert skill_runner._step_tools({"tools": ["a"]}, ["a", "b"], False) == ["a", "b"]


def test_auto_small_model_mode_reads_the_size_off_the_models_name(app_state):
    """Free, offline, and works for every backend, `/api/show` is Ollama's
    alone. An unrecognised name means "no idea", and no idea means off."""
    from memorymap.ai.model_manager import ModelManager, parameter_count

    assert parameter_count("qwen3.5:4b") == 4.0
    assert parameter_count("llama-3.2-3b-instruct") == 3.0
    assert parameter_count("llama3.2") is None

    manager = ModelManager(app_state)
    app_state.set_preference("chat_model", "granite4.1:3b")
    assert manager.chat_model_is_small() is True
    app_state.set_preference("chat_model", "qwen3.5:35b-a3b")
    assert manager.chat_model_is_small() is False
    app_state.set_preference("chat_model", "mistral-nemo")
    assert manager.chat_model_is_small() is None


def test_the_small_model_setting_round_trips(ai_client):
    assert ai_client.get("/preferences").json()["small_model_mode"] == "auto"
    ai_client.put("/preferences", json={"small_model_mode": "on"})
    assert ai_client.get("/preferences").json()["small_model_mode"] == "on"


def test_a_worked_example_is_built_from_the_tools_own_schema(app_state):
    """Never hand-written per tool: a table of examples goes stale silently
    the first time an argument is renamed."""
    assert tools.call_example("get_note") == (
        "A call to get_note looks like this, same shape, your own values: "
        'get_note({"note_id": 12})'
    )
    # Singular and plural forms of the same argument are alternatives, so an
    # example showing both would teach a call that gets refused.
    example = tools.call_example("tag_note")
    assert "note_id" in example and '"note_ids"' not in example
    assert tools.call_example("no_such_tool") == ""
