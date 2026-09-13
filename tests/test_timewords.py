"""What "tomorrow" meant on the day it was written (roadmap §10A).

"Notes say 'today', 'yesterday', 'last week', 'two days ago', phrasing that
is correct when written and misleading forever after. Today nothing records
what those phrases *resolved to*." These tests pin the resolution rules, the
capture hook, and the two places the answer surfaces: the note itself, and
what the AI is told about it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from memorymap.ai import tools
from memorymap.entry import manager, timewords

# A Tuesday, so weekday arithmetic has something to be wrong about.
NOW = datetime(2026, 7, 28, 10, 30)


def _first(text: str):
    found = timewords.find(text, NOW)
    return found[0] if found else None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call mum tomorrow", date(2026, 7, 29)),
        ("we spoke yesterday", date(2026, 7, 27)),
        ("finish this today", date(2026, 7, 28)),
        ("tonight I'll pack", date(2026, 7, 28)),
        ("it happened last night", date(2026, 7, 27)),
        ("the day after tomorrow", date(2026, 7, 30)),
        ("the day before yesterday", date(2026, 7, 26)),
        ("due in three days", date(2026, 7, 31)),
        ("in 2 weeks we move", date(2026, 8, 11)),
        ("saw them 2 weeks ago", date(2026, 7, 14)),
        ("a month ago I started", date(2026, 6, 28)),
        ("in a fortnight", date(2026, 8, 11)),
    ],
)
def test_the_common_phrases_resolve(text, expected):
    assert _first(text).at == expected


def test_a_phrase_keeps_the_precision_it_was_written_with():
    """"Last week" did not mean a day. Rendering it as one invents precision
    the writer never used."""
    week = _first("we met last week")
    assert week.at == date(2026, 7, 20) and week.precision == "week"
    assert _first("last month was hard").precision == "month"
    assert _first("tomorrow").precision == "day"


def test_weekdays_follow_a_written_down_rule():
    """Both readings of "next Friday" exist in speech and neither is wrong.
    The point is that the answer is consistent and shown beside the phrase."""
    assert _first("deadline is next friday").at == date(2026, 8, 7)  # next week's
    assert _first("on monday I start").at == date(2026, 8, 3)  # the coming one
    assert _first("we spoke last thursday").at == date(2026, 7, 23)


def test_the_longer_phrase_wins_over_the_one_inside_it():
    found = timewords.find("the day after tomorrow, and then tomorrow again", NOW)
    assert [m.phrase for m in found] == ["the day after tomorrow", "tomorrow"]
    assert [m.at for m in found] == [date(2026, 7, 30), date(2026, 7, 29)]


def test_text_with_no_time_in_it_produces_nothing():
    assert timewords.find("buy milk and eggs", NOW) == []
    assert timewords.find("", NOW) == []


def test_a_month_end_does_not_overflow_into_the_next_month():
    assert timewords.find("in a month", datetime(2026, 1, 31))[0].at == date(2026, 2, 28)


# --- capture ------------------------------------------------------------------


def test_saving_a_note_records_what_its_phrases_meant(client, session):
    created = client.post("/entries", json={"content": "call the vet tomorrow"}).json()
    assert len(created["dates"]) == 1
    assert created["dates"][0]["phrase"] == "tomorrow"
    assert created["dates"][0]["at"] == str(date.today() + timedelta(days=1))


def test_the_dates_come_back_with_the_note(client):
    client.post("/entries", json={"content": "the roof was fixed last week"})
    listed = client.get("/entries").json()
    assert listed[0]["dates"][0]["precision"] == "week"


def test_editing_a_note_re_reads_its_dates(client):
    created = client.post("/entries", json={"content": "call mum tomorrow"}).json()
    edited = client.put(
        f"/entries/{created['id']}", json={"content": "call mum in three days"}
    ).json()
    assert [d["phrase"] for d in edited["dates"]] == ["in three days"]


def test_a_note_with_no_time_phrases_carries_none(client):
    created = client.post("/entries", json={"content": "buy milk"}).json()
    assert created["dates"] == []


def test_a_private_notes_phrases_are_not_lifted_into_a_plain_table(client, session):
    """Its text is encrypted at rest; copying phrases out of it would leak the
    one thing the encryption is for. A note is marked private *after* it is
    created, so this has to be cleared out then, exactly like its embedding.
    """
    from memorymap.core import vault
    from memorymap.core.database import EntryDate

    # Tests don't go through setup/unlock, so open the vault by hand.
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()

    created = client.post(
        "/entries", json={"content": "the appointment is tomorrow"}
    ).json()
    assert created["dates"], "nothing to leak means nothing proved"

    marked = client.post(
        f"/entries/{created['id']}/privacy", json={"private": True}
    ).json()

    assert marked["dates"] == []
    assert session.query(EntryDate).filter_by(entry_id=created["id"]).count() == 0
    # And they come back when it is made readable again.
    public = client.post(
        f"/entries/{created['id']}/privacy", json={"private": False}
    ).json()
    assert [d["phrase"] for d in public["dates"]] == ["tomorrow"]


def test_a_broken_resolution_never_stops_a_note_being_saved(client, monkeypatch):
    """Principle 2: saving a note must not fail because something else did."""
    monkeypatch.setattr(
        timewords, "find", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    response = client.post("/entries", json={"content": "call mum tomorrow"})
    assert response.status_code == 201
    assert response.json()["dates"] == []


# --- what the AI is told ------------------------------------------------------


def test_the_model_is_told_what_the_note_meant(client, session):
    """Without this it reads "the deadline is next Friday" in a note from
    March and answers about the Friday coming up."""
    created = client.post(
        "/entries", json={"content": "the deadline is next friday"}
    ).json()
    result = tools.execute_tool(session, "get_note", {"note_id": created["id"]})
    assert result["dates"][0]["phrase"] == "next friday"
    assert result["dates"][0]["meant"]


def test_a_note_with_no_phrases_adds_nothing_to_what_the_model_reads(client, session):
    """Every field in a tool result is resent on every later round."""
    created = client.post("/entries", json={"content": "buy milk"}).json()
    result = tools.execute_tool(session, "get_note", {"note_id": created["id"]})
    assert "dates" not in result


def test_the_stored_phrase_survives_a_round_trip_through_the_database(client, session):
    """A POST response can lie about stored state, assert on the next read."""
    client.post("/entries", json={"content": "we move in 2 weeks"})
    entry = manager.list_entries(session)[0]
    stored = manager.entry_dates(session, entry)
    assert [d.phrase for d in stored] == ["in 2 weeks"]
