"""The onboarding tour's "add example notes" offer (ROADMAP.md's onboarding
item: seeded notes so the graph, timeline and dashboard have something to
show before the first real note exists).

The one property worth pinning hard: this must never run on a notebook that
already has a note, seeded or real, `GET /entries/count` is what the
frontend checks before even offering the button, and `POST /seed-examples`
refuses server-side too, so a stale UI state can't double-seed.
"""

from __future__ import annotations


def test_count_is_zero_on_a_fresh_notebook(client):
    assert client.get("/entries/count").json() == {"count": 0}


def test_seeding_creates_five_notes_across_two_categories(client):
    body = client.post("/entries/seed-examples").json()
    assert body == {"created": 5}

    entries = client.get("/entries").json()
    assert len(entries) == 5
    categories = {e["category"] for e in entries}
    assert categories == {"About MemoryMap", "Personal"}


def test_wiki_links_resolve(client, session):
    """Two of the five notes link to "Local-first, always" by name: if the
    seeding order or the opening words ever drift apart, these silently stop
    resolving (sync_wiki_links never raises on a miss), so this checks the
    actual link count rather than trusting the content alone."""
    client.post("/entries/seed-examples")
    from memorymap.core.database import EntryLink

    links = session.query(EntryLink).all()
    assert len(links) == 2, "Both [[Local-first, always]] mentions should have resolved"


def test_seeding_is_spread_across_days_for_the_timeline(client):
    client.post("/entries/seed-examples")
    entries = client.get("/entries").json()
    days = {e["created_at"][:10] for e in entries}
    assert len(days) == 5, "each example note should land on its own day"


def test_seeding_refuses_on_a_notebook_that_already_has_a_note(client):
    client.post("/entries", json={"content": "a real note, written first"})
    body = client.post("/entries/seed-examples").json()
    assert body == {"created": 0}
    # Refused, not silently topped up, still just the one real note.
    assert client.get("/entries/count").json() == {"count": 1}


def test_seeding_twice_is_a_no_op_the_second_time(client):
    client.post("/entries/seed-examples")
    second = client.post("/entries/seed-examples").json()
    assert second == {"created": 0}
    assert client.get("/entries/count").json() == {"count": 5}
