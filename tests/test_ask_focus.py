"""The Notes tab's Ask box interrogates the notebook, and nothing else (§35A).

Asked for directly, and at length:

> *"the ask tab should be for reviewing, revisiting, and searching up/asking
> about your notes, the chatbot can be for the chat tab… make sure the ask
> section works properly and can be used effectively… it is one of the core
> features of the program."*

Two reports, one surface, and the fixes are opposite in kind.

**"hey" got a chatbot answer.** Both surfaces share `/chat/stream`, and
`intent.classify` correctly routes small talk away from retrieval, so the Ask
box dutifully chatted back. The fix is deliberately *not* a better classifier:
the classifier is right, and what was missing is that one of the two callers
does not want the conversational path to exist at all. A flag on the request
costs no model round and cannot misfire.

**The retrieved notes were cut off.** They were, and the escape hatch that
makes clipping safe was not there: a clipped note told the model to "call
get_note(12) to read it in full" on a turn where it had been offered no tools.
The missing text was simply missing and the instruction was noise. So the
marker stops naming a tool that isn't there, and the allowance grows, this
turn is not paying for any tool schemas, which is budget the box had and was
not spending.
"""

from __future__ import annotations

import json

from memorymap.ai import librarian


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _text(events):
    return "".join(e["delta"] for e in events if e["type"] == "answer")


# --- small talk belongs in the Chat tab -------------------------------------


def test_a_greeting_gets_a_hint_not_an_answer(ai_client, fake_ollama):
    """Its own event type, deliberately. Reported after the first version
    shipped as an `answer`: a paragraph of instructions sitting where the
    answer goes, beside a results panel reading "No matching records", reads
    as the app having failed rather than as guidance."""
    fake_ollama.librarian_reply = "Hello there! How are you today?"
    events = _events(ai_client, "hey", notes_only=True)
    hints = [e for e in events if e["type"] == "hint"]
    assert len(hints) == 1
    assert hints[0]["text"] == librarian.ASK_IS_FOR_NOTES
    assert _text(events) == ""  # nothing rendered as an answer
    assert "How are you today" not in json.dumps(events)


def test_the_hint_carries_questions_you_can_click(ai_client, fake_ollama):
    """A way forward from the same place, rather than a description of what
    you did wrong: and it teaches the shape of a question that works better
    than prose about one does."""
    hint = next(e for e in _events(ai_client, "hey", notes_only=True) if e["type"] == "hint")
    assert len(hint["examples"]) >= 2
    assert all(isinstance(x, str) and x.strip() for x in hint["examples"])


def test_nothing_was_searched_for(ai_client, fake_ollama):
    """`search_mode` is "none", which is what lets the client leave out the
    empty results panel instead of reporting a failed search that never ran."""
    meta = next(e for e in _events(ai_client, "hey", notes_only=True) if e["type"] == "meta")
    assert meta["search_mode"] == "none"
    assert meta["raw_results"] == []


def test_it_costs_no_model_round(ai_client, fake_ollama):
    """The point of a flag over a classifier: this answer is free, instant and
    cannot be got wrong by a model having an off day."""
    fake_ollama.chat_calls.clear()
    _events(ai_client, "thanks!", notes_only=True)
    assert fake_ollama.chat_models == []


def test_the_reply_points_somewhere_rather_than_scolding():
    """The useful thing for someone who typed the wrong sort of thing is where
    the right sort goes, not a description of their mistake."""
    assert "Chat tab" in librarian.ASK_IS_FOR_NOTES
    assert "?" in " ".join(librarian.ASK_EXAMPLES)


def test_the_chat_tab_is_completely_unaffected(ai_client, fake_ollama):
    """The flag is set by one caller. Without it, nothing changes, which is
    what makes this safe to add to a shared endpoint."""
    fake_ollama.librarian_reply = "Hello there! How are you today?"
    text = _text(_events(ai_client, "hey"))
    assert "How are you today" in text


def test_a_real_question_still_searches(ai_client, fake_ollama, session):
    """The flag must not turn the box off, only the chatting half."""
    from memorymap.entry import manager

    manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    events = _events(ai_client, "what did I write about beans", notes_only=True)
    assert "beans" in _text(events).lower()
    assert any(e["type"] == "meta" and e["raw_results"] for e in events)


def test_the_non_streaming_endpoint_agrees(ai_client, fake_ollama):
    """Both chat endpoints share `_prepare` and must not drift, the whole
    reason `build_messages` is shared in the first place."""
    body = ai_client.post("/chat", json={"question": "hey", "notes_only": True}).json()
    assert body["ai_response"] == librarian.ASK_IS_FOR_NOTES


# --- how much of a note the model actually sees -----------------------------


def test_an_untooled_turn_gets_far_more_of_each_note():
    """The reported truncation. Five notes and no tool schemas is a budget the
    Ask box was not spending."""
    assert librarian.UNTOOLED_NOTE_CHARS > librarian.MAX_NOTE_CHARS
    long_note = {"id": 3, "content": "x" * 2_000}
    plain = librarian.note_for_prompt(
        long_note, librarian.UNTOOLED_NOTE_CHARS, can_fetch=False
    )
    assert plain == "x" * 2_000  # not cut at all at this length
    assert "[cut" in librarian.note_for_prompt(long_note)  # the agent's limit still cuts


def test_a_cut_never_names_a_tool_the_turn_does_not_have():
    """"Call get_note(12)" to a model offered no tools is noise, and worse: it
    invites the model to promise a lookup it cannot perform."""
    note = {"id": 12, "content": "y" * (librarian.UNTOOLED_NOTE_CHARS + 50)}
    cut = librarian.note_for_prompt(note, librarian.UNTOOLED_NOTE_CHARS, can_fetch=False)
    assert "[cut" in cut
    assert "get_note" not in cut


def test_the_agent_keeps_its_escape_hatch():
    """Where the tool *is* offered, naming it is the thing that makes cutting
    safe: this must not be lost while fixing the other path."""
    note = {"id": 12, "content": "y" * 2_000}
    assert "get_note(12)" in librarian.note_for_prompt(note)


def test_the_plain_prompt_uses_the_larger_allowance():
    """End to end through the prompt builder, so the wiring is covered and not
    just the helper."""
    note = {"id": 1, "content": "z" * 1_500, "category": "Garden"}
    built = librarian.build_messages("what did I write", [note])
    assert "z" * 1_500 in built[-1]["content"]  # whole note, uncut
