"""When no note answers a question, say what else in the notebook mentions it.

Asked for directly: *"idk if the ai should be able to look for related
semantic results for alternate items like reminders, chat sessions, docs etc
related to the notes if no notes are found?? like similar items??"*

Retrieval only ever searched notes, so a question whose answer sits in a
document, a saved chat or a reminder came back as a flat "I couldn't find any
saved notes matching that question", true, useless, and misleading about how
much the app actually holds.
"""

from __future__ import annotations

from memorymap.api.routes_chat import _related_elsewhere
from memorymap.core.database import Conversation, Document, Reminder
from memorymap.core import deps
from datetime import datetime, timezone


def _session():
    return deps.get_db().session()


def test_a_document_is_found_by_its_title(ai_client):
    session = _session()
    try:
        session.add(Document(title="Tangible Interaction Design", content="unit plan"))
        session.commit()
        found = _related_elsewhere(session, "what did I write about tangible design?")
    finally:
        session.close()
    assert [f["kind"] for f in found] == ["document"]
    assert found[0]["label"] == "Tangible Interaction Design"


def test_a_document_is_found_by_its_body_too(ai_client):
    session = _session()
    try:
        session.add(Document(title="Untitled", content="notes about seraphine and warwick"))
        session.commit()
        found = _related_elsewhere(session, "seraphine")
    finally:
        session.close()
    assert found and found[0]["kind"] == "document"


def test_chats_and_reminders_are_searched_as_well(ai_client):
    session = _session()
    try:
        session.add(Conversation(title="Assessment 2 planning", messages="[]"))
        session.add(
            Reminder(text="submit assessment 2", due_at=datetime.now(timezone.utc))
        )
        session.commit()
        found = _related_elsewhere(session, "assessment")
    finally:
        session.close()
    kinds = {f["kind"] for f in found}
    assert "chat" in kinds
    assert "reminder" in kinds


def test_nothing_matching_returns_nothing(ai_client):
    session = _session()
    try:
        session.add(Document(title="Cooking", content="pasta"))
        session.commit()
        assert _related_elsewhere(session, "quantum chromodynamics") == []
    finally:
        session.close()


def test_a_question_with_no_real_words_is_not_a_search(ai_client):
    """Two-letter words are skipped, so "hi" must not drag the whole
    notebook back as "related"."""
    session = _session()
    try:
        session.add(Document(title="Anything", content="anything at all"))
        session.commit()
        assert _related_elsewhere(session, "hi") == []
        assert _related_elsewhere(session, "") == []
    finally:
        session.close()


def test_one_item_is_listed_once_however_many_words_match(ai_client):
    session = _session()
    try:
        session.add(Document(title="Seraphine build", content="seraphine support build"))
        session.commit()
        found = _related_elsewhere(session, "seraphine support build")
    finally:
        session.close()
    assert len(found) == 1


# --- the wiring, not just the query ---------------------------------------------
#
# The branch this hangs off is genuinely hard to reach on a real notebook:
# hybrid search almost always returns *some* weak semantic match, so driving
# it through the browser never produced an empty result to test against. That
# is exactly the "feature that never ran once" risk CLAUDE.md warns about, so
# the empty case is forced here instead.


def test_the_stream_offers_related_items_when_no_note_matched(ai_client, monkeypatch):
    session = _session()
    try:
        session.add(Document(title="Quokka festival brief", content="the ultra rare one"))
        session.commit()
    finally:
        session.close()

    from memorymap.api import routes_chat

    real_prepare = routes_chat._prepare

    def _no_notes(*args, **kwargs):
        prepared = real_prepare(*args, **kwargs)
        prepared["notes"] = []
        return prepared

    monkeypatch.setattr(routes_chat, "_prepare", _no_notes)

    response = ai_client.post(
        "/chat/stream",
        # `use_tools=False` on purpose: with tools on, the turn goes down the
        # agent path instead and never reaches the direct-Q&A empty branch
        # this covers. The Ask box sends `notes_only`, which is what this
        # fallback is for.
        json={
            "question": "quokka festival",
            "notes_only": True,
            "use_tools": False,
            "history": [],
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "I couldn't find any saved notes" in body
    assert '"type": "related"' in body
    assert "Quokka festival brief" in body
    # And it says so in the answer text, not only in a payload the UI has to
    # know to look for.
    assert "other" in body and "document" in body


def test_no_related_event_when_nothing_else_matches_either(ai_client, monkeypatch):
    from memorymap.api import routes_chat

    real_prepare = routes_chat._prepare

    def _no_notes(*args, **kwargs):
        prepared = real_prepare(*args, **kwargs)
        prepared["notes"] = []
        return prepared

    monkeypatch.setattr(routes_chat, "_prepare", _no_notes)
    response = ai_client.post(
        "/chat/stream",
        json={
            "question": "zzzznothingmatchesthis",
            "notes_only": True,
            "use_tools": False,
            "history": [],
        },
    )
    assert '"type": "related"' not in response.text


def test_one_query_per_kind_however_many_words_the_question_has(session, monkeypatch):
    """The panel costs three scans, not three per word.

    `ILIKE '%word%'` has a leading wildcard, so no index can serve it and each
    one is a full scan of `documents.content` or `conversations.messages`, the
    two widest text columns in the schema. This used to run inside the word
    loop: six usable words meant eighteen scans on the path every chat answer
    takes when no note answered. The count is the assertion because the timing
    is the sandbox's, not the user's: measured here at 145.3 ms before and
    118.8 ms after on 2,000 documents, 2,000 chats and 2,000 reminders.
    """
    from sqlalchemy import event

    from memorymap.api.routes_chat import _related_elsewhere

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        _related_elsewhere(session, "nightly batch retry budget priya ingest parse store")
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 3, f"expected one query per kind, got {len(selects)}: {selects}"
