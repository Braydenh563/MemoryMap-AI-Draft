"""Chat intent routing: a greeting must not be answered with a note dump.

The bug this covers: every message went through retrieval and was then
answered "using ONLY the notes provided", so "hey" came back as a summary of
the user's notebook.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import intent


@pytest.mark.parametrize(
    "message",
    ["hey", "hi", "hello there", "yo", "good morning", "thanks!", "cheers",
     "how are you?", "ok", "bye", "lol", "sorry", "are you there"],
)
def test_greetings_are_smalltalk(message):
    assert intent.classify(message) == intent.SMALLTALK


@pytest.mark.parametrize(
    "message",
    ["what can you do?", "what tools do you have", "how does this work",
     "what should I ask", "what are you able to do"],
)
def test_capability_questions_are_about_the_app(message):
    assert intent.classify(message) == intent.ABOUT_APP


@pytest.mark.parametrize(
    "message",
    ["what did I write about pasta", "summarise my notes", "what jokes have I saved?",
     "remind me to call mum", "tell me about my week", "pasta recipe",
     "hey, what have I saved about jokes"],
)
def test_real_questions_go_to_the_notebook(message):
    """Including one wearing a greeting, the question is what matters."""
    assert intent.classify(message) == intent.NOTES


def test_unknown_messages_fall_back_to_notes():
    """The fallback must be the old behaviour, never something worse."""
    assert intent.classify("the quarterly figures for the Henderson account") == intent.NOTES
    assert intent.needs_retrieval(intent.NOTES) is True
    assert intent.needs_retrieval(intent.SMALLTALK) is False


def test_greeting_does_not_retrieve_or_list_notes(ai_client, fake_ollama):
    """The end-to-end version of the bug."""
    ai_client.post("/entries", json={"content": "a note about pasta recipes"})
    ai_client.post("/entries", json={"content": "another note about cycling"})
    fake_ollama.librarian_reply = "Hello! What would you like to do?"

    body = ai_client.post("/chat", json={"question": "hey"}).json()

    # Nothing was retrieved, so nothing can be dumped at the user.
    assert body["raw_results"] == []
    assert body["search_mode"] == "none"
    # And the prompt never mentioned notes or told the model to ground in them.
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "small talk" in system.lower()
    assert "ONLY the notes provided" not in system


def test_a_real_question_still_retrieves(ai_client, fake_ollama):
    ai_client.post("/entries", json={"content": "pasta carbonara needs guanciale"})
    fake_ollama.librarian_reply = "You wrote about carbonara."

    body = ai_client.post("/chat", json={"question": "what did I write about pasta?"}).json()

    assert body["raw_results"]  # retrieval still happens for real questions
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "ONLY the notes provided" in system


def test_capability_question_describes_the_app_not_the_notes(ai_client, fake_ollama):
    ai_client.post("/entries", json={"content": "a private note"})
    fake_ollama.librarian_reply = "I can find and write notes, and set reminders."

    body = ai_client.post("/chat", json={"question": "what can you do?"}).json()

    assert body["raw_results"] == []
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "asking what you can do" in system.lower()


def test_greeting_answers_even_with_an_empty_notebook(ai_client, fake_ollama):
    """"hey" used to hit "I couldn't find any saved notes matching that"."""
    fake_ollama.librarian_reply = "Hi there!"
    body = ai_client.post("/chat", json={"question": "hi"}).json()
    assert body["ai_response"] == "Hi there!"
    assert "couldn't find any saved notes" not in body["ai_response"]


def test_greeting_streams_without_the_no_results_message(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "Hello!"
    with ai_client.stream("POST", "/chat/stream", json={"question": "hey"}) as response:
        events = [json.loads(line) for line in response.iter_lines() if line.strip()]
    answer = "".join(e.get("delta", "") for e in events if e.get("type") == "answer")
    assert "couldn't find any saved notes" not in answer
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["raw_results"] == []
    assert meta["answered_by"]  # it did answer, rather than declining


def test_greeting_without_the_model_still_greets(ai_client, fake_ollama):
    """No model is no reason to answer a hello with an error."""
    fake_ollama.running = False
    body = ai_client.post("/chat", json={"question": "hey"}).json()
    assert "Hello" in body["ai_response"]
    assert "notes are all still here" in body["ai_response"]


# --- answering_agent (Tier 1 §4) -----------------------------------------------
#
# The reverse of the bug this file is otherwise about: the agent's own
# `ask_user` question gets a one-word reply, "yes", "ok", that
# intent.classify correctly calls small talk in isolation. Routed as small
# talk it lands in the tool-less conversational path, so even a model that
# understood the reply perfectly could not act on it.


def test_a_bare_yes_is_ordinarily_smalltalk_not_the_agent(ai_client, fake_ollama):
    """The baseline the fix has to preserve: without the flag, "yes" behaves
    exactly as intent.classify says it should, no tools offered."""
    with ai_client.stream("POST", "/chat/stream", json={"question": "yes"}) as response:
        list(response.iter_lines())  # drain
    assert not fake_ollama.tool_rounds  # chat_tools_stream was never reached


def test_answering_agent_routes_a_bare_yes_through_the_agent(ai_client, fake_ollama):
    """With the flag the client sets when a reply answers a pending `ask`
    event, the same bare "yes" reaches the tool-enabled agent instead."""
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": 1, "add": ["confirmed"]}}]
    ]
    with ai_client.stream(
        "POST", "/chat/stream", json={"question": "yes", "answering_agent": True}
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]
    assert fake_ollama.tool_rounds  # reached the agent, not the conversational path
    assert any(e["type"] == "tool" for e in events)
