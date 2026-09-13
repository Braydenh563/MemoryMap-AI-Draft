"""Resurfacing (WORLD_CLASS_PLAN 15, I4): the spec. Strict-xfail until built.

Three cards a day: notes that are fading (old, unlinked, unopened) and close
to what the person is doing now. The fading score is computed nightly into
`note_scores`; the request-time step multiplies by cosine to a context
vector and drops anything marked "never again" (a correction, I7).
"""

from __future__ import annotations

#: Kept as a header rather than a marker: every one of these passes now
#: (`ai/resurface.py`, `api/routes_resurface.py`), and the file stays the
#: contract they have to keep passing against.
BUILT = "WORLD_CLASS 15 I4: resurfacing, built 2026-09-12"


def test_an_old_unlinked_unopened_note_outranks_a_linked_recent_one(session):
    from datetime import datetime, timedelta

    from memorymap.ai import resurface
    from memorymap.entry import manager

    old = manager.create_entry(session, "interview prep notes from the spring", tags=[])
    old.created_at = datetime.now() - timedelta(days=120)
    fresh = manager.create_entry(session, "notes from today's standup", tags=[])
    other = manager.create_entry(session, "a note linked to today's", tags=[])
    # `create_link` is what this is called; the spec guessed a name.
    manager.create_link(session, fresh, other)
    fresh.access_count = 5
    session.commit()
    resurface.compute_scores(session)
    ranked = resurface.ranked(session, limit=10)
    assert [e.id for e in ranked].index(old.id) < [e.id for e in ranked].index(fresh.id)


def test_the_context_vector_reorders_the_top_three(session, fake_embeddings):
    from memorymap.ai import resurface
    from memorymap.entry import manager

    a = manager.create_entry(session, "sourdough starter feeding schedule", tags=[])
    b = manager.create_entry(session, "hiking boots for the weekend trip", tags=[])
    session.commit()
    resurface.compute_scores(session)
    with_context = resurface.for_context(session, context_entry_id=a.id, limit=3)
    assert with_context and with_context[0].id != a.id  # never the context note itself
    assert b.id in [e.id for e in with_context]


def test_never_again_is_honoured_across_restarts(ai_client):
    for i in range(12):
        ai_client.post("/entries", json={"content": f"an old idea number {i} about gardening"})
    ai_client.post("/resurface/compute")
    first = ai_client.get("/resurface").json()["items"]
    assert len(first) == 3
    ai_client.post("/learned/corrections", json={"kind": "dismiss_resurface", "subject": {"entry_id": first[0]["id"]}})
    ai_client.post("/resurface/compute")
    later = ai_client.get("/resurface").json()["items"]
    assert first[0]["id"] not in [item["id"] for item in later]


def test_the_daily_three_are_stable_within_a_day_and_change_across_days(ai_client):
    for i in range(30):
        ai_client.post("/entries", json={"content": f"idea {i} about something forgotten"})
    ai_client.post("/resurface/compute")
    today = ai_client.get("/resurface?as_of=2026-09-08").json()["items"]
    again = ai_client.get("/resurface?as_of=2026-09-08").json()["items"]
    tomorrow = ai_client.get("/resurface?as_of=2026-09-09").json()["items"]
    assert today == again
    assert today != tomorrow


def test_a_small_notebook_returns_nothing_rather_than_the_same_three_forever(ai_client):
    for i in range(5):
        ai_client.post("/entries", json={"content": f"note {i}"})
    ai_client.post("/resurface/compute")
    assert ai_client.get("/resurface").json()["items"] == []


def test_the_endpoint_is_fast_because_scores_are_precomputed(ai_client):
    import time

    for i in range(500):
        ai_client.post("/entries", json={"content": f"idea {i} about topic {i % 20}"})
    ai_client.post("/resurface/compute")
    start = time.perf_counter()
    reply = ai_client.get("/resurface")
    elapsed = time.perf_counter() - start
    assert reply.status_code == 200 and len(reply.json()["items"]) == 3
    assert elapsed < 0.05


def test_a_first_read_computes_its_own_scores(client):
    """**The feature has to work with the AI switched off.**

    The night shift that was supposed to fill `note_scores`
    (`ai/autonomous.py`) only runs when the AI is on, so on a notebook with
    no model this panel would have shown nothing, for ever, with a backend
    that tests green: the "feature that never ran once" shape. The read
    refreshes the table itself when it is missing or a day old.
    """
    for index in range(12):
        client.post("/entries", json={"content": f"Note {index}\n\nSomething written down."})

    # No POST /resurface/compute anywhere in this test, deliberately.
    items = client.get("/resurface").json()["items"]
    assert len(items) == 3
    assert all(item["title"] for item in items)
    # The card says why it was chosen, in facts a person can check.
    assert all("opened" in item["reason"] for item in items)


def test_a_second_read_does_not_recompute(client):
    """The scan is the expensive half and must not be on every request."""
    from memorymap.ai import resurface

    for index in range(12):
        client.post("/entries", json={"content": f"Note {index}\n\nSomething written down."})
    client.get("/resurface")

    from memorymap.core import deps

    with deps.get_db().session() as session:
        assert resurface.ensure_fresh(session) is False


def test_the_ranking_route_is_the_order_not_the_daily_three(client):
    """The Notes tab's "Forgotten first" sort wants the order itself.

    `GET /resurface` answers "what are today's three", which is a rotation
    over the top of the ranking and is deliberately stable within a day.
    Folding a sort into it by raising its limit would have given one of the
    two the other's behaviour, so the ranking has its own route.
    """
    made = [
        client.post("/entries", json={"content": f"Note {index}\n\nWritten down."}).json()["id"]
        for index in range(14)
    ]

    rows = client.get("/resurface/all", params={"limit": 500}).json()["items"]
    assert len(rows) == len(made)
    assert {row["id"] for row in rows} == set(made)
    # Every row carries the reason, so a list can say why a note is where it
    # is without asking again per note.
    assert all(row["reason"] for row in rows)

    # No rotation: the same call twice is the same order.
    again = client.get("/resurface/all", params={"limit": 500}).json()["items"]
    assert [row["id"] for row in again] == [row["id"] for row in rows]


def test_a_dismissed_note_leaves_the_forgotten_order(client):
    """"Never again" is honoured by the sort as well as by the panel, or the
    note it was said about comes straight back at the top of a list."""
    for index in range(14):
        client.post("/entries", json={"content": f"Note {index}\n\nWritten down."})

    first = client.get("/resurface/all").json()["items"][0]["id"]
    client.post(
        "/learned/corrections",
        json={"kind": "dismiss_resurface", "subject": {"entry_id": first}},
    )
    after = [row["id"] for row in client.get("/resurface/all").json()["items"]]
    assert first not in after


def test_never_again_outlives_six_hundred_later_corrections(app_state):
    """**"Never again" has to mean never**, and it used to mean "until you
    file six hundred notes".

    `learning.corrections` takes the newest 500 rows and `boosts` asked for
    every kind at once, keeping the family's afterwards. So a dismissal
    followed by enough re-files fell outside the window, and the card it was
    said about came back. The corrections table only ever grows, so this was a
    matter of time rather than of scale.
    """
    from memorymap.ai import learning, resurface
    from memorymap.core import deps
    from memorymap.core.database import Entry

    db = deps.get_db()
    with db.session() as session:
        note = Entry(content="A note to be dismissed")
        session.add(note)
        session.commit()
        note_id = note.id

        learning.record(session, kind="dismiss_resurface", subject={"entry_id": note_id})
        for _ in range(600):
            learning.record(
                session, kind="refile", subject={"entry_id": note_id},
                from_value="Inbox", to_value="Recipes",
            )
        session.commit()

        assert (note_id,) in learning.boosts(session, kind="resurface"), (
            "the dismissal fell out of the read window, so the card comes back"
        )
        # And the ranking honours it: the note is gone from the list itself.
        assert note_id not in {entry.id for entry in resurface.ranked(session, limit=50)}
