"""The agent can ask to compress the chat, but the summary is still reviewed
by a person before it replaces anything (§37I).

*"make compressing the chat an agent tool so the agent can do it
automatically."* The machinery already existed as a **human-gated** two-step
flow: `POST /chat/compress` summarises, `showCompressReview` shows the
result before `applyCompression` uses it: built that way on purpose: a
summary nobody can correct is one they have to trust blindly.

`compress_chat` is the agent's way in, and it keeps the same shape: the tool
never applies anything. It ends the turn and hands the summary to the UI
exactly like `ask_user`/`run_skill`/`make_plan` do, and the same review panel
the manual button already fills in is what shows it.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import tools


def _turns(count: int) -> list[dict]:
    return [
        {"question": f"question number {n}", "answer": f"answer number {n}"}
        for n in range(count)
    ]


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


# --- validating what there is to compress -------------------------------------


def test_too_little_history_is_refused():
    with pytest.raises(tools.ToolError, match="enough conversation"):
        tools.validate_compress_chat({}, _turns(2))


def test_no_history_at_all_is_refused():
    with pytest.raises(tools.ToolError, match="enough conversation"):
        tools.validate_compress_chat({}, None)


def test_the_two_most_recent_turns_are_left_alone(ai_client, fake_ollama):
    """Compressing the exchange still in progress is how a summary loses the
    thing being talked about right now, the same reason app.js's
    KEEP_RECENT_TURNS exists."""
    fake_ollama.librarian_reply = "a summary"
    result = tools.validate_compress_chat({}, _turns(6))
    assert result["turns"] == 4  # 6 turns, last 2 kept aside
    sent = fake_ollama.chat_calls[-1][-1]["content"]
    assert "question number 3" in sent  # the last covered turn
    assert "question number 4" not in sent  # kept aside, not summarised
    assert "question number 5" not in sent


def test_beyond_the_ceiling_covers_only_the_first_max(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "a summary"
    result = tools.validate_compress_chat({}, _turns(tools.MAX_COMPRESS_TURNS + 10))
    assert result["turns"] == tools.MAX_COMPRESS_TURNS


def test_a_well_formed_result_is_marked_for_review(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "Decided X, still open: Y."
    result = tools.validate_compress_chat({}, _turns(6))
    assert result["type"] == "compress_review"
    assert result["summary"] == "Decided X, still open: Y."
    assert result["chars_before"] > 0
    assert result["chars_after"] > 0


def test_an_empty_summary_is_a_tool_error(ai_client, fake_ollama):
    """Otherwise the turn ends on a review card with nothing to review."""
    fake_ollama.librarian_reply = "   "
    with pytest.raises(tools.ToolError, match="empty summary"):
        tools.validate_compress_chat({}, _turns(6))


def test_the_model_being_off_is_still_a_tool_error(client):
    """`client` has Ollama unavailable. The agent loop only knows how to
    recover from a `ToolError`, an `OllamaError` escaping here would crash
    the turn instead of letting the model try something else."""
    with pytest.raises(tools.ToolError):
        tools.validate_compress_chat({}, _turns(6))


# --- it cannot be run like an ordinary tool ------------------------------------


def test_the_tool_is_marked_as_ending_the_turn():
    assert tools.TOOLS["compress_chat"].ends_turn is True
    assert not tools.TOOLS["compress_chat"].destructive


def test_it_is_in_the_handover_table_like_its_siblings():
    ending = {name for name, spec in tools.TOOLS.items() if spec.ends_turn}
    assert ending == set(tools.HANDOFFS)
    assert "compress_chat" in ending


def test_running_it_directly_fails_loudly(session):
    with pytest.raises(tools.ToolError, match="cannot be executed directly"):
        tools.TOOLS["compress_chat"].handler(session, {})


def test_the_confirm_endpoint_will_not_run_it(ai_client):
    response = ai_client.post(
        "/chat/tools/execute", json={"name": "compress_chat", "arguments": {}}
    )
    assert response.status_code >= 400


# --- offered by cue, not on every turn -----------------------------------------


def test_it_is_not_offered_for_an_ordinary_question():
    """Not in CORE_TOOLS: a registry that offered this on every turn would
    pay for it on the turns that are never about the chat's own length."""
    focused = tools.focus_for("what did I write about beans")
    assert focused is not None
    assert "compress_chat" not in focused


def test_it_is_offered_when_asked_to_compress_the_chat():
    focused = tools.focus_for("please compress this chat, it's getting long")
    assert focused is not None
    assert "compress_chat" in focused


def test_summarising_notes_does_not_cue_it():
    """The two are different jobs, summarising what's *in* the notebook is
    not the same as shrinking the conversation itself."""
    focused = tools.focus_for("summarise my notes about the trip")
    assert focused is not None
    assert "compress_chat" not in focused


# --- through the agent ---------------------------------------------------------


def test_the_agent_can_hand_the_summary_to_the_review_panel(ai_client, fake_ollama):
    history = _turns(6)
    fake_ollama.tool_script = [[{"name": "compress_chat", "arguments": {}}]]
    fake_ollama.librarian_reply = "Recapped the last few turns."
    events = _events(ai_client, "compress this chat", use_tools=True, history=history)
    review = next(e for e in events if e["type"] == "compress_review")
    assert review["summary"] == "Recapped the last few turns."
    assert review["turns"] == 4


def test_the_turn_really_ends_there(ai_client, fake_ollama):
    history = _turns(6)
    fake_ollama.tool_script = [
        [{"name": "compress_chat", "arguments": {}}],
        # A second round the agent must never reach.
        [{"name": "create_note", "arguments": {"content": "should never be created"}}],
    ]
    fake_ollama.librarian_reply = "Recap."
    events = _events(ai_client, "compress this chat", use_tools=True, history=history)
    kinds = [e["type"] for e in events]
    assert "compress_review" in kinds
    assert kinds.index("compress_review") == len(kinds) - 2  # only "done" follows
    assert not any(e["type"] == "answer" for e in events)
    entries = ai_client.get("/entries").json()
    rows = entries["entries"] if isinstance(entries, dict) else entries
    assert not any("should never be created" in e["content"] for e in rows)


def test_not_enough_conversation_is_recoverable_not_fatal(ai_client, fake_ollama):
    fake_ollama.tool_script = [[{"name": "compress_chat", "arguments": {}}]]
    fake_ollama.librarian_reply = "I'll just answer directly instead."
    events = _events(ai_client, "compress this chat", use_tools=True, history=_turns(1))
    kinds = [e["type"] for e in events]
    assert "compress_review" not in kinds
    failed = [e for e in events if e["type"] == "tool" and not e.get("ok")]
    assert failed, "the model should be told there isn't enough to compress yet"
    assert any(e["type"] == "answer" for e in events), "the turn should continue"
