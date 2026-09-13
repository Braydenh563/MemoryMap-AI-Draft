"""Turning an offhand mention in chat into a draft, ANALYSIS.md §60 item 2.

The odysseus read's own one-line answer to "any features overlooked?" was
this one: *"nothing in this app turns an offhand mention in ordinary chat
into a filed note"*. MemoryMap files a note on an explicit instruction or an
explicit tool call and never otherwise.

Three properties carry the design and are what these tests are for. Each is a
thing that, if it broke, would still leave a feature that looked like it
worked:

* **Drafts, never notes.** The pass writes to the notebook with nobody
  watching, so a mis-capture has to be a suggestion to dismiss rather than
  something in your notebook you did not write.
* **A fingerprint short-circuit.** Odysseus's own comment records 30–120s per
  call before they added one. An unchanged conversation must cost a hash and
  no model call at all.
* **The user's words, not the assistant's.** Capturing an answer the model
  wrote would fill the notebook with the model quoting itself back.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import passive_capture
from memorymap.core import deps
from memorymap.core.database import Conversation


@pytest.fixture
def chat_with(session):
    def make(messages, title="A chat"):
        conversation = Conversation(title=title, messages=json.dumps(messages))
        session.add(conversation)
        session.commit()
        return conversation

    return make


class _Model:
    def utility_model(self):
        return "utility"


class _Ollama:
    """Answers with a fixed JSON array and counts how often it is asked."""

    def __init__(self, reply='["They booked a dentist appointment for Thursday."]'):
        self.reply = reply
        self.calls = 0

    def chat(self, model, messages):
        self.calls += 1
        self.prompt = messages[-1]["content"]
        return {"content": self.reply}


def test_it_writes_a_draft_and_not_a_note(session, chat_with, app_state):
    chat_with([{"role": "user", "content": "I need to book the dentist for Thursday."}])
    config = deps.get_config()

    written = passive_capture.capture_pass(session, _Model(), _Ollama(), config)

    assert written == 1
    from memorymap.core.database import Entry

    entry = session.query(Entry).order_by(Entry.id.desc()).first()
    assert entry.is_draft is True, "a capture must arrive as a draft, never a filed note"
    assert passive_capture.CAPTURE_TAG in json.loads(entry.tags)


def test_an_unchanged_conversation_costs_no_model_call(session, chat_with, app_state):
    chat_with([{"role": "user", "content": "I need to book the dentist for Thursday."}])
    config = deps.get_config()
    ollama = _Ollama()

    passive_capture.capture_pass(session, _Model(), ollama, config)
    assert ollama.calls == 1

    passive_capture.capture_pass(session, _Model(), ollama, config)
    assert ollama.calls == 1, "the fingerprint did not short-circuit an unchanged chat"


def test_a_new_turn_reopens_the_conversation(session, chat_with, app_state):
    conversation = chat_with([{"role": "user", "content": "First thing."}])
    config = deps.get_config()
    ollama = _Ollama()
    passive_capture.capture_pass(session, _Model(), ollama, config)

    conversation.messages = json.dumps(
        [{"role": "user", "content": "First thing."}, {"role": "user", "content": "Second."}]
    )
    session.commit()
    passive_capture.capture_pass(session, _Model(), ollama, config)
    assert ollama.calls == 2


def test_only_the_users_own_words_are_offered(session, chat_with, app_state):
    chat_with(
        [
            {"role": "user", "content": "What did I say about the dentist?"},
            {"role": "assistant", "content": "SECRET-ASSISTANT-TEXT you have an appointment"},
        ]
    )
    config = deps.get_config()
    ollama = _Ollama(reply="[]")

    passive_capture.capture_pass(session, _Model(), ollama, config)
    assert "SECRET-ASSISTANT-TEXT" not in ollama.prompt
    assert "dentist" in ollama.prompt


def test_a_reply_it_cannot_read_captures_nothing(session, chat_with, app_state):
    """The right failure for a job that writes to the notebook. A local model
    asked for JSON will sometimes answer in prose, and salvaging sentences out
    of that is how you end up filing the model's apology."""
    chat_with([{"role": "user", "content": "Something worth keeping."}])
    config = deps.get_config()

    written = passive_capture.capture_pass(
        session, _Model(), _Ollama(reply="Sure! Here are some thoughts."), config
    )
    assert written == 0


def test_a_fenced_array_is_still_read(session, chat_with, app_state):
    chat_with([{"role": "user", "content": "Something worth keeping."}])
    config = deps.get_config()
    reply = 'Here you go:\n```json\n["They prefer tea to coffee."]\n```'

    assert passive_capture.capture_pass(session, _Model(), _Ollama(reply=reply), config) == 1


def test_a_backend_failure_skips_rather_than_raising(session, chat_with, app_state):
    """This runs at the top of a worker thread. A backend that is down must
    cost the pass, not the app."""
    chat_with([{"role": "user", "content": "Something worth keeping."}])

    class _Down:
        def chat(self, model, messages):
            raise RuntimeError("connection refused")

    assert passive_capture.capture_pass(session, _Model(), _Down(), deps.get_config()) == 0


def test_scraps_and_essays_are_both_refused(session):
    assert passive_capture._parse_facts('["ok", "' + "x" * 400 + '"]') == []
    assert passive_capture._parse_facts('["a real fact worth keeping"]') == [
        "a real fact worth keeping"
    ]


def test_it_is_off_by_default(app_state):
    """The most deliberate opt-in of the five background jobs: the other four
    react to notes the user wrote, and this one decides on its own that
    something said in passing was worth keeping."""
    assert deps.get_config().get_preference("auto_capture_enabled", None) is False
