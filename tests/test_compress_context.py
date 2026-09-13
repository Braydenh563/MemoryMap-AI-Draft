"""Summarising a long conversation instead of losing the start of it (§35I).

Asked for directly: *"there should be a tool as well as a manual command or
something to be able to compress chat context on longer chats so the AI can
better continue."*

**What happens without it is not what the request assumes**, and the
difference is the whole design. A long chat does not overflow the window: the
client sends at most the last few turns, and `context.fit_history` drops whole
user/assistant pairs from the *oldest* end until the rest fits. So the failure
is silent forgetting: the model stops knowing what it was told at the start
and begins re-asking it.

A summary is strictly better than a drop, because the same few hundred
characters carry the gist of ten turns rather than the whole of one.

This is the **manual** half, which §35I argues should ship first: a button
whose output the user reads before it is used cannot misfire. Two properties
matter more than the summary's quality, and both are tested here:

- **nothing is deleted.** The endpoint stores nothing and touches no
  conversation; it returns text. The transcript on screen and the saved
  conversation keep every turn, so undo is the client forgetting a variable.
- **an empty summary is an error, not a result.** Handing back "" would let
  the client send nothing in place of ten real turns, a compression that
  loses the conversation completely, reported as success.
"""

from __future__ import annotations

import pytest


def _turns(count: int) -> list[dict]:
    return [
        {"question": f"question number {n}", "answer": f"answer number {n}"}
        for n in range(count)
    ]


def test_it_summarises_the_turns_it_is_given(ai_client, fake_ollama):
    response = ai_client.post("/chat/compress", json={"history": _turns(6)})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]
    assert body["turns"] == 6


def test_it_reports_what_it_saved(ai_client, fake_ollama):
    """The numbers are the reason to press the button again, or not to."""
    body = ai_client.post("/chat/compress", json={"history": _turns(8)}).json()
    assert body["chars_before"] > 0
    assert body["chars_after"] > 0


def test_the_whole_transcript_reaches_the_model(ai_client, fake_ollama):
    """A summary built from a clipped transcript is a summary of the recent
    half, which is the half that was never at risk."""
    ai_client.post("/chat/compress", json={"history": _turns(5)})
    sent = fake_ollama.chat_calls[-1]
    transcript = sent[-1]["content"]
    for n in range(5):
        assert f"question number {n}" in transcript


def test_nothing_is_stored(ai_client, fake_ollama):
    """The endpoint is pure. Everything it could have changed, the saved
    conversation, the turns on screen, is the client's, and keeping it that
    way is what makes undo free."""
    before = ai_client.get("/conversations").json()
    ai_client.post("/chat/compress", json={"history": _turns(4)})
    assert ai_client.get("/conversations").json() == before


def test_an_empty_summary_is_refused(ai_client, fake_ollama):
    """Otherwise the client sends nothing in place of ten real turns, and the
    conversation is gone as far as the model is concerned."""
    fake_ollama.librarian_reply = "   "
    response = ai_client.post("/chat/compress", json={"history": _turns(4)})
    assert response.status_code == 502


def test_it_says_so_when_the_model_is_off(client):
    """`client` has Ollama unavailable. A 503 with the offline message, rather
    than a blank summary the user might accept."""
    response = client.post("/chat/compress", json={"history": _turns(4)})
    assert response.status_code == 503


def test_an_empty_history_is_rejected(ai_client, fake_ollama):
    assert ai_client.post("/chat/compress", json={"history": []}).status_code == 422


def test_an_absurd_history_is_rejected(ai_client, fake_ollama):
    """Bounded because the summary itself would get long enough to be worth
    summarising, which is the wrong direction."""
    from memorymap.api.routes_chat import MAX_COMPRESS_TURNS

    response = ai_client.post(
        "/chat/compress", json={"history": _turns(MAX_COMPRESS_TURNS + 1)}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("count", [1, 2, 40])
def test_the_bounds_themselves_are_accepted(ai_client, fake_ollama, count):
    response = ai_client.post("/chat/compress", json={"history": _turns(count)})
    assert response.status_code == 200
