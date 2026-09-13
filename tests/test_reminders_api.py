"""Reminders: CRUD, priority/recurring, and Magic Add's parsing.

(The clock/timezone bug behind Magic Add's rule engine has its own focused
file, test_reminder_times.py: kept separate rather than merged in here so
that narrative stays readable on its own.)
"""

from __future__ import annotations

from datetime import timedelta

from memorymap.core.database import utcnow


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_reminder_lifecycle(client):
    entry = _save(client, "buy a birthday present")
    due = (utcnow() + timedelta(days=1)).isoformat()

    created = client.post(
        "/reminders",
        json={"text": "wrap the present", "due_at": due, "entry_id": entry["id"]},
    ).json()
    assert created["entry_preview"].startswith("buy a birthday")
    assert created["done"] is False

    client.post("/reminders", json={"text": "standalone", "due_at": due})
    listed = client.get("/reminders").json()
    assert len(listed) == 2

    done = client.put(f"/reminders/{created['id']}", json={"done": True}).json()
    assert done["done"] is True

    client.delete(f"/reminders/{created['id']}")
    assert len(client.get("/reminders").json()) == 1


def test_reminder_preview_does_not_leak_private_note_ciphertext(client):
    """`entry_preview` used to read the raw `content` column, which is
    ciphertext at rest for a private note, showing a garbled blob instead of
    the locked-vault placeholder every other preview surface uses (graph,
    library...). `readable_content` decides by the `crypto.PREFIX` marker on
    the stored text, not the `is_private` flag, so a fake-but-marked
    ciphertext string is enough to prove the preview goes through it rather
    than the raw column, a real encrypt/decrypt round-trip is covered
    elsewhere (crypto/vault tests)."""
    from memorymap.core import crypto, deps
    from memorymap.core.database import Entry

    session = deps.get_db().session()
    entry = Entry(content=crypto.PREFIX + "not-real-ciphertext", is_private=True)
    session.add(entry)
    session.commit()
    entry_id = entry.id
    session.close()

    due = (utcnow() + timedelta(hours=1)).isoformat()
    created = client.post(
        "/reminders", json={"text": "check this", "due_at": due, "entry_id": entry_id}
    ).json()
    # No vault open in this test, so `readable_content` gives the standard
    # locked placeholder: never the raw ciphertext-shaped column value.
    assert created["entry_preview"] == "Private note: unlock to read it."


def test_a_reminder_cannot_be_set_in_the_past(client):
    """A reminder due before now will never usefully fire, asked for
    directly. Covers both create and edit, since a due date can slip into
    the past through either."""
    past = (utcnow() - timedelta(hours=1)).isoformat()
    created = client.post("/reminders", json={"text": "too late", "due_at": past})
    assert created.status_code == 422

    future = (utcnow() + timedelta(hours=1)).isoformat()
    reminder = client.post("/reminders", json={"text": "on time", "due_at": future}).json()
    edited = client.put(f"/reminders/{reminder['id']}", json={"due_at": past})
    assert edited.status_code == 422
    # The reminder itself must be untouched by the rejected edit.
    assert client.get("/reminders").json()[0]["due_at"] == reminder["due_at"]


def test_reminder_for_missing_entry_404s(client):
    due = (utcnow() + timedelta(hours=1)).isoformat()
    response = client.post("/reminders", json={"text": "x", "due_at": due, "entry_id": 99})
    assert response.status_code == 404


def test_reminder_priority_and_recurring(client):
    due = (utcnow() + timedelta(hours=2)).isoformat()

    # Defaults when omitted.
    created = client.post("/reminders", json={"text": "water plants", "due_at": due}).json()
    assert created["priority"] == "normal"
    assert created["recurring"] == "none"

    # Explicit values round-trip.
    made = client.post(
        "/reminders",
        json={"text": "pay rent", "due_at": due, "priority": "high", "recurring": "monthly"},
    ).json()
    assert made["priority"] == "high"
    assert made["recurring"] == "monthly"

    # Updatable.
    updated = client.put(
        f"/reminders/{created['id']}", json={"priority": "low", "recurring": "weekly"}
    ).json()
    assert updated["priority"] == "low"
    assert updated["recurring"] == "weekly"

    # Invalid values are rejected by the schema.
    bad = client.post(
        "/reminders", json={"text": "x", "due_at": due, "priority": "urgent"}
    )
    assert bad.status_code == 422


def test_reminder_times_come_back_marked_as_utc(client):
    """A reminder due in five minutes read as ten hours overdue (user-reported).

    SQLite has no timezone type, so a plain DateTime column handed back a NAIVE
    datetime. FastAPI serialised it with no offset, and JavaScript parses a
    timezone-less date-time string as LOCAL, so a user in UTC+10 saw every
    stored UTC time ten hours in the past.

    The trap was that it looked fine at first: the POST response carried the
    offset, because SQLAlchemy returned the object still in memory. Only a
    later read from disk lost it. So this asserts on the LIST response.
    """
    from datetime import datetime, timezone

    due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    client.post("/reminders", json={"text": "soon", "due_at": due})

    listed = client.get("/reminders").json()[0]
    assert listed["due_at"].endswith("Z") or "+" in listed["due_at"][10:], listed["due_at"]

    # And it round-trips to the same instant, not one shifted by the offset.
    parsed = datetime.fromisoformat(listed["due_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert abs((parsed - datetime.now(timezone.utc)).total_seconds() - 300) < 30


# --- Magic Add's JSON parsing (success/fallback): the clock rules that back
# it live in test_reminder_times.py ---------------------------------------


def test_magic_add_parses_and_creates(ai_client, fake_ollama):
    fake_ollama.librarian_reply = (
        '{"text": "call mum", "due_at": "2030-01-02T18:00", "priority": "high"}'
    )
    created = ai_client.post("/reminders/parse", json={"text": "call mum tomorrow evening"}).json()
    assert created["text"] == "call mum"
    assert created["priority"] == "high"
    assert created["due_at"].startswith("2030-01-02T18:00")
    assert len(ai_client.get("/reminders").json()) == 1


def test_magic_add_falls_back_on_unparseable_reply(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "sorry, I can't help with that"
    created = ai_client.post("/reminders/parse", json={"text": "buy milk"}).json()
    # Falls back to the raw text + a default future due time, still created.
    assert created["text"] == "buy milk"
    assert created["priority"] == "normal"


def test_magic_add_resolves_times_on_the_users_clock(ai_client, fake_ollama):
    """The model is told the local time and answers on it; storage is UTC."""
    fake_ollama.librarian_reply = (
        '{"text": "call mum", "due_at": "2030-01-02T18:00", "priority": "normal"}'
    )
    # UTC+13 (New Zealand in summer): 6pm local is 05:00 UTC the same day.
    created = ai_client.post(
        "/reminders/parse",
        json={"text": "call mum tomorrow evening", "tz_offset_minutes": 780},
    ).json()
    assert created["due_at"].startswith("2030-01-02T05:00")

    # And the prompt carried the local wall clock, not the server's UTC.
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "The current date and time is" in system


def test_magic_add_honours_an_offset_the_model_supplies(ai_client, fake_ollama):
    """An explicit offset in the reply is trusted rather than shifted again."""
    fake_ollama.librarian_reply = (
        '{"text": "standup", "due_at": "2030-01-02T18:00+02:00", "priority": "normal"}'
    )
    created = ai_client.post(
        "/reminders/parse", json={"text": "standup", "tz_offset_minutes": 780}
    ).json()
    assert created["due_at"].startswith("2030-01-02T16:00")


def test_magic_add_needs_ai_running(ai_client, fake_ollama):
    fake_ollama.running = False
    assert ai_client.post("/reminders/parse", json={"text": "x"}).status_code == 503


# --- pagination (INBOX 117: this list used to hand back the whole table,
# 300 reminders measured at 52.5 KB in one response) -----------------------


def test_reminders_page_and_report_the_real_total(client):
    due = utcnow() + timedelta(days=1)
    for i in range(5):
        client.post(
            "/reminders",
            json={"text": f"thing {i}", "due_at": (due + timedelta(minutes=i)).isoformat()},
        )

    first = client.get("/reminders", params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    assert len(first.json()) == 2
    assert first.headers["X-Total-Count"] == "5"

    second = client.get("/reminders", params={"limit": 2, "offset": 2})
    assert len(second.json()) == 2

    last = client.get("/reminders", params={"limit": 2, "offset": 4})
    assert len(last.json()) == 1
    assert last.headers["X-Total-Count"] == "5"

    # Every reminder is reachable exactly once by paging: a cap without a
    # working offset would make everything past the first page invisible.
    paged = [r["id"] for r in first.json() + second.json() + last.json()]
    assert len(set(paged)) == 5
    assert set(paged) == {r["id"] for r in client.get("/reminders", params={"limit": 100}).json()}


def test_reminders_past_the_page_size_are_still_reachable(client):
    """The page size is a bound on one response, never on how many
    reminders can exist: `X-Total-Count` says how many there are and
    `offset` fetches the rest."""
    from memorymap.api import routes_reminders

    size = routes_reminders.REMINDERS_PAGE_SIZE
    due = utcnow() + timedelta(days=1)
    from memorymap.core import deps
    from memorymap.core.database import Reminder

    # Seeded through the model rather than the endpoint: 200-odd POSTs is a
    # slow way to say "more rows than one page", and this test is about the
    # reading, not the writing.
    session = deps.get_db().session()
    session.add_all(
        Reminder(text=f"thing {i}", due_at=due + timedelta(minutes=i)) for i in range(size + 5)
    )
    session.commit()
    session.close()

    first = client.get("/reminders")
    assert len(first.json()) == size
    assert first.headers["X-Total-Count"] == str(size + 5)

    rest = client.get("/reminders", params={"offset": size})
    assert len(rest.json()) == 5
    seen = {r["id"] for r in first.json()} | {r["id"] for r in rest.json()}
    assert len(seen) == size + 5


def test_reminders_limit_is_validated(client):
    from memorymap.api import routes_reminders

    assert client.get("/reminders", params={"limit": 0}).status_code == 422
    assert client.get("/reminders", params={"offset": -1}).status_code == 422
    over = routes_reminders.REMINDERS_PAGE_SIZE_MAX + 1
    assert client.get("/reminders", params={"limit": over}).status_code == 422
