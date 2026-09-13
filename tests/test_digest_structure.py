"""The weekly digest knows how the week's notes sit in the notebook.

The digest could see the week's notes and their categories and nothing else, 
so it could tell you *what* you wrote and never notice that five of those notes
are joined to nothing, or that everything landed in one corner. Noticing that
is what a weekly recap is for, and it is exactly what the graph knows.

The rule these tests pin is that the sentence is **facts, not adjectives**:
counts the model can repeat and the user can verify by clicking. A digest that
says "your notebook feels disconnected" is an opinion nobody can check; one
that says "5 of this week's 12 notes connect to nothing" is a fact with an
action attached.
"""

from __future__ import annotations

import json
from datetime import timedelta

from memorymap.api.routes_insights import digest_structure_note
from memorymap.core.database import Entry, EntryLink, utcnow


def _note(session, content, days_ago=0, private=False):
    entry = Entry(
        content=content,
        tags=json.dumps([]),
        is_private=private,
        created_at=utcnow() - timedelta(days=days_ago),
    )
    session.add(entry)
    session.commit()
    return entry


def test_an_empty_week_says_nothing(session):
    """No notes, no sentence, the digest already has its own "nothing was
    saved" answer and does not need a second one bolted on."""
    _note(session, "written a month ago", days_ago=30)
    assert digest_structure_note(session) == ""


def test_it_counts_this_week_s_unconnected_notes(session):
    linked_a = _note(session, "the beans need netting")
    linked_b = _note(session, "netting is in the shed")
    session.add(EntryLink(source_entry_id=linked_a.id, target_entry_id=linked_b.id))
    session.commit()
    _note(session, "a stray thought")
    _note(session, "another stray thought")

    note = digest_structure_note(session)
    assert "4 notes" in note
    assert "2 are connected" in note
    # An instruction the model can follow, not a mood.
    assert "Do not guess at connections that are not there." in note


def test_a_fully_connected_week_is_worth_saying_too(session):
    a = _note(session, "one half of a pair")
    b = _note(session, "the other half")
    session.add(EntryLink(source_entry_id=a.id, target_entry_id=b.id))
    session.commit()

    note = digest_structure_note(session)
    assert "Every one of this week's 2 notes is connected" in note


def test_last_month_s_notes_are_not_counted(session):
    """"This week" has to mean this week, or the number is wrong in the one
    direction that makes the digest look broken."""
    old = _note(session, "an old unconnected note", days_ago=30)
    fresh_a = _note(session, "one half of a pair")
    fresh_b = _note(session, "the other half")
    session.add(EntryLink(source_entry_id=fresh_a.id, target_entry_id=fresh_b.id))
    session.commit()

    note = digest_structure_note(session)
    assert "2 notes" in note
    assert str(old.id) not in note


def test_private_notes_are_not_counted(session):
    """The digest is written by a model, and a private note is not available to
    one: counting it would put a number in the answer that the notes behind it
    cannot explain."""
    _note(session, "something I would rather keep to myself", private=True)
    _note(session, "an ordinary note")

    note = digest_structure_note(session)
    assert "1 notes" in note or "this week's 1" in note


def test_the_sentence_stays_short(session):
    """It rides in the prompt of a background job on a utility model, so §11a's
    budget applies here as much as anywhere."""
    for n in range(20):
        _note(session, f"note number {n}")
    assert len(digest_structure_note(session)) < 400


# --- the /insights/digest endpoint, plain and streamed ------------------------


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_digest_empty_week(client):
    assert "Nothing was saved" in client.post("/insights/digest").json()["digest"]


def test_digest_uses_recent_notes(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    body = ai_client.post("/insights/digest").json()
    assert body["digest"] == fake_ollama.librarian_reply
    prompt = fake_ollama.chat_calls[-1][-1]["content"]
    assert "scarecrow" in prompt  # the digest reads this week's notes


def test_digest_never_sends_a_private_note_to_the_model(ai_client, fake_ollama):
    """`digest_structure_note` already excludes private notes from its own
    sentence (see `test_private_notes_are_not_counted` above): but the notes
    handed to the model for the digest text itself came from a separate query
    that did not filter `is_private`, and a private note's `content` column is
    ciphertext at rest. That put encrypted bytes straight into the model's
    prompt, which is both a privacy leak (existence + category + timing of a
    private note, in a request sent to whatever backend the model is at) and a
    quality bug (the model summarising base64 gibberish it can't read)."""
    from memorymap.core import deps
    from memorymap.core.database import Entry

    _save(ai_client, "an ordinary note about the garden")
    session = deps.get_db().session()
    session.add(Entry(content="MY SECRET DIARY ENTRY", tags=json.dumps([]), is_private=True))
    session.commit()
    session.close()

    ai_client.post("/insights/digest")
    prompt = fake_ollama.chat_calls[-1][-1]["content"]
    assert "MY SECRET DIARY ENTRY" not in prompt


def test_digest_empty_week_is_cacheable(client):
    # An empty week is a stable fact → safe to cache (Wave J follow-up).
    assert client.post("/insights/digest").json()["cacheable"] is True


def test_digest_real_answer_is_cacheable(ai_client):
    _save(ai_client, "a funny scarecrow joke")
    assert ai_client.post("/insights/digest").json()["cacheable"] is True


def test_digest_offline_is_not_cacheable(client):
    # `client` has Ollama unavailable: the digest is the offline notice,
    # which must NOT be frozen for the day.
    _save(client, "a note from this week")
    assert client.post("/insights/digest").json()["cacheable"] is False


def _ndjson(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_digest_streams_in_chunks(ai_client, fake_ollama):
    _save(ai_client, "bought milk")
    fake_ollama.librarian_reply = "You saved a shopping note."
    response = ai_client.post("/insights/digest/stream")
    assert response.status_code == 200
    events = _ndjson(response)
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert answer == "You saved a shopping note."
    # Streamed, not delivered in one lump.
    assert len([e for e in events if e["type"] == "answer"]) > 1
    assert events[-1] == {"type": "done", "cacheable": True}


def test_digest_stream_handles_an_empty_week(ai_client):
    events = _ndjson(ai_client.post("/insights/digest/stream"))
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "Nothing was saved" in answer
    assert events[-1]["cacheable"] is True


def test_digest_stream_degrades_when_ai_is_down(ai_client, fake_ollama):
    _save(ai_client, "bought milk")
    fake_ollama.running = False
    events = _ndjson(ai_client.post("/insights/digest/stream"))
    # An offline notice must never be cached as if it were a real digest.
    assert events[-1]["cacheable"] is False
