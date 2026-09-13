"""The event log (WORLD_CLASS_PLAN 4 B1; SESSION_BRIEFS Brief 7): the spec.

Every test here was strict-xfail until Brief 7 built the feature. All five
now pass and their markers are gone, which is what a strict xfail is for: it
fails the build the moment the behaviour exists, so the spec cannot be
quietly ignored and cannot quietly stay "pending" either.

What is being specified, in the words of the plan: every write through the
managers records exactly one event in the same transaction, with an actor
and a whole-field payload; a note's events replay to its current state;
history is listable and a version restorable; a purge is one event with the
id list, not one per row. `AuditLog` (core/database.py) is the table; it
gains `actor` and `payload` rather than a new table being added.
"""
from __future__ import annotations

import inspect
import json
from datetime import timedelta

from memorymap.core.database import AuditLog
from memorymap.entry import manager

WRITE_PREFIXES = (
    "create_", "update_", "soft_delete_", "restore_", "archive_", "unarchive_",
    "purge_", "link_", "unlink_", "record_",
)


def _manager_writes():
    return sorted(
        name for name, fn in inspect.getmembers(manager, inspect.isfunction)
        if name.startswith(WRITE_PREFIXES) and fn.__module__ == manager.__name__
    )


def test_audit_log_carries_actor_and_payload():
    columns = {c.name for c in AuditLog.__table__.columns}
    assert {"actor", "payload"} <= columns, "extend AuditLog, do not add a table"


def test_every_manager_write_records_exactly_one_event(session):
    """Enumerates the public write functions so a new one cannot be missed."""
    from memorymap.core import events  # the helper module Brief 7 adds

    entry = manager.create_entry(session, "hello", tags=[])
    session.commit()
    writes = _manager_writes()
    assert writes, "the enumeration found nothing; the prefixes are wrong"
    for name in writes:
        before = session.query(AuditLog).count()
        events.exercise_for_test(session, name, entry)  # Brief 7 provides a per-function driver
        session.commit()
        after = session.query(AuditLog).count()
        assert after == before + 1, f"{name} recorded {after - before} events, not one"
        last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert last.payload, f"{name} recorded an event with no payload"
        assert last.actor in {"user"} or last.actor.startswith(("ai:", "system:"))


def test_a_notes_events_replay_to_its_current_state(session):
    from memorymap.core import events

    entry = manager.create_entry(session, "first", tags=["a"])
    session.commit()
    manager.update_entry(session, entry, content="second", tags=["a", "b"])
    session.commit()
    rebuilt = events.replay(session, "entry", entry.id)
    assert rebuilt["content"] == "second"
    assert rebuilt["tags"] == ["a", "b"]


def test_history_lists_and_restore_records_its_own_event(client, session):
    entry = manager.create_entry(session, "v1", tags=[])
    session.commit()
    manager.update_entry(session, entry, content="v2", tags=[])
    session.commit()
    history = client.get(f"/entries/{entry.id}/history").json()
    assert [h["action"] for h in history["items"]][:2] == ["edited", "created"] or len(history["items"]) >= 2
    first = history["items"][-1]["id"]
    restored = client.post(f"/entries/{entry.id}/restore/{first}").json()
    assert restored["content"] == "v1"
    last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert last.action == "restored"


def test_a_purge_is_one_event_with_the_id_list(session):
    entries = []
    for i in range(3):
        e = manager.create_entry(session, f"n{i}", tags=[])
        session.commit()
        manager.soft_delete_entry(session, e)
        entries.append(e)
    ids = [e.id for e in entries]
    session.commit()
    before = session.query(AuditLog).count()
    manager.purge_entries(session, entries)
    session.commit()
    assert session.query(AuditLog).count() == before + 1
    last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert last.action == "purged"
    assert sorted(last.payload["ids"]) == sorted(ids)


def test_a_tool_call_is_recorded_as_the_ai_doing_it(session):
    """Who changed the note is the first thing the log has to answer.

    The actor is set once, at the door every tool call comes through
    (`tools.execute_tool`), so a handler cannot forget it and file the AI's
    edit as something the user typed.
    """
    from memorymap.ai import tools

    tools.execute_tool(session, "create_note", {"content": "the AI wrote this"})
    session.commit()
    written = (
        session.query(AuditLog)
        .filter(AuditLog.entity_type == "entry", AuditLog.action == "created")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert written.actor == "ai:create_note"


def test_a_write_with_no_stated_actor_is_the_user(session):
    entry = manager.create_entry(session, "typed by a person", tags=[])
    session.commit()
    last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert last.entity_id == entry.id and last.actor == "user"


def test_the_feed_reads_forwards_from_a_cursor(client):
    """A viewer reads backwards from now; anything that follows the notebook
    has to read forwards from what it last saw, or it misses whatever
    happened while it was away."""
    first = client.post("/entries", json={"content": "one", "tags": []}).json()
    start = client.get("/events").json()
    client.post("/entries", json={"content": "two", "tags": []})

    after = client.get(f"/events?since={start['cursor']}").json()
    actions = [item["action"] for item in after["items"]]
    assert "created" in actions
    assert all(item["id"] > start["cursor"] for item in after["items"])
    assert all(item["actor"] == "user" for item in after["items"])
    assert not [item for item in after["items"] if item["entity_id"] == first["id"]]
    assert after["cursor"] >= start["cursor"]


def test_the_feed_leaves_the_bookkeeping_out(client):
    entry = client.post("/entries", json={"content": "before", "tags": []}).json()
    client.put(f"/entries/{entry['id']}", json={"content": "after"})

    items = client.get("/events").json()["items"]
    assert "revised" not in [item["action"] for item in items]
    assert "revised" in [row["action"] for row in client.get("/audit").json()]


# --- compaction (Brief 7 item 1, `events-retention`) -------------------------
#
# The decision the plan made and this pins down: a payload holds whole field
# values, so the log grows by a copy of a note's text on every edit, and the
# answer is compaction rather than deletion, because an entity's events have
# to keep replaying to its current state. What compaction promises is exactly
# that: the log gets smaller, replay does not move.


def _age_all_events(session, days: int) -> None:
    """Backdate every event, so a compaction window can be reached in a test."""
    from memorymap.core.database import utcnow

    when = utcnow() - timedelta(days=days)
    for row in session.query(AuditLog).all():
        row.created_at = when
    session.commit()


def test_compaction_leaves_replay_on_the_current_state(session):
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=["a"])
    session.commit()
    for i in range(1, 40):
        manager.update_entry(session, entry, content=f"version {i}", tags=["a"])
        session.commit()
    _age_all_events(session, 200)

    before_bytes = events.payload_bytes(session)
    before_rows = session.query(AuditLog).count()
    summary = events.compact(session, keep_last=5)
    after_bytes = events.payload_bytes(session)

    assert summary["events"] > 0, "nothing was compacted"
    assert after_bytes < before_bytes, "compaction did not make the log smaller"
    # Nothing is deleted: the audit trail still has every action, with its
    # actor and its time. Only the values behind the old ones are gone.
    assert session.query(AuditLog).count() == before_rows

    rebuilt = events.replay(session, "entry", entry.id)
    assert rebuilt["content"] == "version 39"
    assert rebuilt["tags"] == ["a"]


def test_compaction_keeps_the_newest_events_whole(session):
    """However old they are. A note edited twice years ago and not since
    would otherwise have no readable history at all."""
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=[])
    session.commit()
    for i in range(1, 20):
        manager.update_entry(session, entry, content=f"version {i}", tags=[])
        session.commit()
    _age_all_events(session, 500)

    events.compact(session, keep_last=5)
    newest = events.events_for(session, "entry", entry.id, limit=5)
    assert all(not events.is_compacted(row) for row in newest)
    assert any((row.payload or {}).get("after", {}).get("content") for row in newest)


def test_compaction_leaves_a_young_log_alone(session):
    from memorymap.core import events

    entry = manager.create_entry(session, "written today", tags=[])
    session.commit()
    for i in range(1, 30):
        manager.update_entry(session, entry, content=f"edit {i}", tags=[])
        session.commit()

    before = events.payload_bytes(session)
    # Its own statement, not the assertion's expression: `python -O` strips
    # asserts, and a write that only runs inside one stops running at all.
    summary = events.compact(session, keep_last=2)
    assert summary == {"entities": 0, "events": 0}
    assert events.payload_bytes(session) == before


def test_compaction_is_safe_to_run_twice(session):
    """It runs at startup, so a second pass over an already-compacted log has
    to be a no-op rather than something that compounds."""
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=[])
    session.commit()
    for i in range(1, 30):
        manager.update_entry(session, entry, content=f"version {i}", tags=[])
        session.commit()
    _age_all_events(session, 200)

    first = events.compact(session, keep_last=5)
    settled = events.payload_bytes(session)
    second = events.compact(session, keep_last=5)

    assert first["events"] > 0
    assert second == {"entities": 0, "events": 0}
    assert events.payload_bytes(session) == settled
    assert events.replay(session, "entry", entry.id)["content"] == "version 29"


def test_a_second_window_moves_the_snapshot_forward(session):
    """The case that actually recurs: more edits happen, they age, and the
    pass runs again. The boundary moves, the old snapshot is folded into the
    new one, and replay still lands on the current state."""
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=[])
    session.commit()
    for i in range(1, 20):
        manager.update_entry(session, entry, content=f"version {i}", tags=[])
        session.commit()
    _age_all_events(session, 200)
    events.compact(session, keep_last=5)
    first_snapshot = [
        row
        for row in events.events_for(session, "entry", entry.id, newest_first=False)
        if isinstance((row.payload or {}).get("after"), dict)
    ][0]

    for i in range(20, 40):
        manager.update_entry(session, entry, content=f"version {i}", tags=[])
        session.commit()
    _age_all_events(session, 200)
    second = events.compact(session, keep_last=5)
    assert second["events"] > 0

    session.refresh(first_snapshot)
    assert events.is_compacted(first_snapshot), "the old snapshot was not folded in"
    assert events.replay(session, "entry", entry.id)["content"] == "version 39"


def test_a_compacted_version_says_so_rather_than_restoring_nothing(client, session):
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=[])
    session.commit()
    for i in range(1, 30):
        manager.update_entry(session, entry, content=f"version {i}", tags=[])
        session.commit()
    _age_all_events(session, 200)
    events.compact(session, keep_last=5)

    oldest = events.events_for(session, "entry", entry.id, newest_first=False)[0]
    assert events.is_compacted(oldest)
    answer = client.post(f"/entries/{entry.id}/restore/{oldest.id}")
    assert answer.status_code == 410
    assert "no longer" in answer.json()["detail"].lower()

    # And the sheet is told, so the row can say it rather than showing a
    # version with no text and no explanation.
    items = client.get(f"/entries/{entry.id}/history").json()["items"]
    compacted = [item for item in items if item["id"] == oldest.id]
    assert compacted and compacted[0]["compacted"] is True


def test_the_feed_calls_a_snapshot_a_snapshot(client, session):
    """A compacted run is not an edit that happened to set every field.

    The feed names the fields an event set by reading `payload["after"]`. A
    snapshot's `after` is the entity's whole state, folded from a run of old
    events, so read that way one row claimed to have changed the content,
    the tags, the category and the rest at one instant, which never
    happened. It reports what it is instead, and the rows whose values the
    compactor took say that rather than reporting an empty edit.
    """
    from memorymap.core import events

    entry = manager.create_entry(session, "version 0", tags=["a"])
    session.commit()
    for i in range(1, 12):
        manager.update_entry(session, entry, content=f"version {i}", tags=["a"])
        session.commit()
    _age_all_events(session, 200)
    events.compact(session, keep_last=5)

    feed = client.get("/events?include_quiet=true&limit=500").json()["items"]
    items = {item["id"]: item for item in feed}
    rows = events.events_for(session, "entry", entry.id, newest_first=False)
    snapshots = [row for row in rows if events.snapshot_span(row)]
    stripped = [row for row in rows if events.is_compacted(row)]
    assert len(snapshots) == 1, "one run folds into one snapshot"
    assert stripped, "nothing was compacted, so there is nothing to report on"

    reported = items[snapshots[0].id]
    assert reported["changed"] == [], "a snapshot did not change anything"
    assert reported["snapshot"] == len(stripped) + 1, "it stands for its whole run"
    assert reported["compacted"] is False, "the snapshot still holds its values"
    for row in stripped:
        assert items[row.id]["compacted"] is True
        assert items[row.id]["changed"] == []

    # And an ordinary event still names the fields it set, which is the whole
    # reason `changed` is there.
    newest = items[rows[-1].id]
    assert "content" in newest["changed"]
    assert newest["snapshot"] is None


# --- the board's half of the spec (Brief 7 item 3, `events-whiteboard`) ------
#
# B1's own wording names "`routes_whiteboard.py`'s manager" beside the entry
# managers. Its writes recorded nothing at all: a card could be moved, a text
# box rewritten and a branch deleted with no record of who did it or what it
# said before. The enumeration below is the same idea as the entry one at the
# top of this file, driven through the API because these writes are routes:
# add a write to that module and this test fails until it records.

WHITEBOARD_WRITE_PREFIXES = (
    "create_", "update_", "delete_", "move_", "rename_", "duplicate_",
    "generate_", "import_",
)


def _whiteboard_writes():
    from memorymap.api import routes_whiteboard

    return sorted(
        name
        for name, fn in inspect.getmembers(routes_whiteboard, inspect.isfunction)
        if name.startswith(WHITEBOARD_WRITE_PREFIXES)
        # `functools.wraps` keeps `__module__` pointing at the module the
        # function was defined in, so the decorated routes are still found and
        # the manager helpers imported into that module are still excluded.
        and fn.__module__ == routes_whiteboard.__name__
    )


def _board_fixture(client):
    """A board with a card, a sketch, an object and a map node on it."""
    board = client.post("/whiteboard/boards", json={"name": "spec board"}).json()
    note = client.post("/entries", json={"content": "a note", "tags": []}).json()
    node = client.post(
        "/whiteboard/nodes", json={"entry_id": note["id"], "board_id": board["id"]}
    ).json()
    sketch = client.post(
        "/whiteboard/sketches", json={"board_id": board["id"], "data": "[]"}
    ).json()
    obj = client.post(
        "/whiteboard/objects",
        json={
            "board_id": board["id"],
            "kind": "text",
            "data": {"content": "a text box"},
            "x": 1,
            "y": 1,
        },
    ).json()
    mapped = client.post(
        f"/whiteboard/boards/{board['id']}/nodes",
        json={"kind": "topic", "text": "a topic"},
    ).json()
    return {
        "board": board,
        "note": note,
        "node": node,
        "sketch": sketch,
        "object": obj,
        "mapped": mapped,
    }


def _whiteboard_drivers(client, board, note):
    """`name -> (setup, call)`.

    Each driver that needs something to act on makes its own, in `setup`,
    which runs before the event count is taken: sharing one card between the
    update driver and the delete driver makes the enumeration depend on the
    order it happens to run in, and the order is alphabetical.
    """

    def a_node():
        return client.post(
            "/whiteboard/nodes", json={"entry_id": note, "board_id": board}
        ).json()

    def a_sketch():
        return client.post(
            "/whiteboard/sketches",
            json={"board_id": board, "data": '{"type": "stroke", "points": [[1, 2]]}'},
        ).json()

    def an_object():
        return client.post(
            "/whiteboard/objects",
            json={
                "board_id": board,
                "kind": "text",
                "data": {"content": "a text box"},
                "x": 1,
                "y": 1,
            },
        ).json()

    def a_map_node():
        return client.post(
            f"/whiteboard/boards/{board}/nodes",
            json={"kind": "topic", "text": "a topic"},
        ).json()

    return {
        "create_board": (None, lambda _: client.post(
            "/whiteboard/boards", json={"name": "another board"}
        )),
        "duplicate_board": (None, lambda _: client.post(
            f"/whiteboard/boards/{board}/duplicate"
        )),
        # Settings only. A rename also changes the board note's *text*, which
        # `manager.update_entry` records as that note's own event: two facts
        # on two entities, which `test_renaming_a_board_records_the_note_and_
        # the_board` below states rather than this count hiding.
        "rename_board": (None, lambda _: client.put(
            f"/whiteboard/boards/{board}", json={"layout": "radial"}
        )),
        "create_node": (None, lambda _: client.post(
            "/whiteboard/nodes", json={"entry_id": note, "board_id": board, "x": 5}
        )),
        "update_node": (a_node, lambda made: client.put(
            f"/whiteboard/nodes/{made['id']}",
            json={"entry_id": note, "board_id": board, "x": 9, "y": 9},
        )),
        "delete_node": (a_node, lambda made: client.delete(
            f"/whiteboard/nodes/{made['id']}"
        )),
        "create_sketch": (None, lambda _: client.post(
            "/whiteboard/sketches", json={"board_id": board, "data": "[[1,2]]"}
        )),
        "update_sketch": (a_sketch, lambda made: client.put(
            f"/whiteboard/sketches/{made['id']}",
            json={"board_id": board, "data": "[[3,4]]"},
        )),
        "delete_sketch": (a_sketch, lambda made: client.delete(
            f"/whiteboard/sketches/{made['id']}"
        )),
        "create_object": (None, lambda _: client.post(
            "/whiteboard/objects",
            json={
                "board_id": board,
                "kind": "text",
                "data": {"content": "another box"},
                "x": 2,
                "y": 2,
            },
        )),
        "update_object": (an_object, lambda made: client.put(
            f"/whiteboard/objects/{made['id']}",
            json={
                "board_id": board,
                "kind": "text",
                "data": {"content": "rewritten"},
                "x": 3,
                "y": 3,
            },
        )),
        "delete_object": (an_object, lambda made: client.delete(
            f"/whiteboard/objects/{made['id']}"
        )),
        "create_map_node": (None, lambda _: client.post(
            f"/whiteboard/boards/{board}/nodes",
            json={"kind": "topic", "text": "one more topic"},
        )),
        "move_map_node": (a_map_node, lambda made: client.put(
            f"/whiteboard/boards/{board}/nodes/{made['id']}/move",
            json={"parent_id": None},
        )),
        "generate_map": (None, lambda _: client.post(
            "/whiteboard/boards/generate",
            json={"name": "generated", "outline": "- root\n  - child\n", "note_ids": []},
        )),
        "import_board": (None, lambda _: client.post(
            "/whiteboard/boards/import",
            json={"format": "markdown", "content": "- root\n  - child\n"},
        )),
    }


def test_every_whiteboard_write_records_exactly_one_event(client, session):
    made = _board_fixture(client)
    drivers = _whiteboard_drivers(client, made["board"]["id"], made["note"]["id"])
    writes = _whiteboard_writes()
    assert writes, "the enumeration found nothing; the prefixes are wrong"

    #: The two map doors are the stated exception, and the reason is Brief 7's
    #: own open item 4: a `board`/`created` event whose payload held a node
    #: *count* replayed to an empty board, so each node it places now records
    #: its own `whiteboard_object`/`created` event. One board event plus one
    #: per node, which is what `generate_diagram` already did. The count is
    #: still exact, it is just 1 + N rather than 1: an unexplained extra event
    #: from either route still fails here.
    ONE_PER_NODE = {"generate_map", "import_board"}

    for name in writes:
        driver = drivers.get(name)
        assert driver is not None, (
            f"{name} is a write route in api/routes_whiteboard.py with no driver "
            "in this test. Make it record exactly one event (wrap it in "
            "@events.writes and give its events.record a whole-field payload), "
            "then add a driver for it here."
        )
        setup, call = driver
        target = setup() if setup is not None else None
        before = session.query(AuditLog).count()
        answer = call(target)
        assert answer.status_code < 400, f"{name} failed: {answer.text[:200]}"
        # The route committed in its own session; this one has to start a new
        # transaction to see it.
        session.commit()
        after = session.query(AuditLog).count()
        if name in ONE_PER_NODE:
            nodes = answer.json()["object_count"]
            assert after == before + 1 + nodes, (
                f"{name} recorded {after - before} events for {nodes} nodes, "
                f"not the board's own plus one each"
            )
        else:
            assert after == before + 1, f"{name} recorded {after - before} events, not one"
        last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert last.payload, f"{name} recorded an event with no payload"
        assert last.actor in {"user"} or last.actor.startswith(("ai:", "system:"))


def test_a_board_items_events_replay_to_their_current_state(client, session):
    """The same promise a note makes, for the things on a board."""
    from memorymap.core import events

    made = _board_fixture(client)
    box = made["object"]["id"]
    client.put(
        f"/whiteboard/objects/{box}",
        json={
            "board_id": made["board"]["id"],
            "kind": "text",
            "data": {"content": "the last word"},
            "x": 40,
            "y": 50,
        },
    )
    session.commit()

    rebuilt = events.replay(session, "whiteboard_object", box)
    assert json.loads(rebuilt["data"])["content"] == "the last word"
    assert (rebuilt["x"], rebuilt["y"]) == (40, 50)

    client.delete(f"/whiteboard/objects/{box}")
    session.commit()
    assert events.replay(session, "whiteboard_object", box)["deleted"] is True


def test_renaming_a_board_records_the_note_and_the_board(client, session):
    """Two facts, on two entities, and deliberately not folded into one.

    A board's title is its note's own heading, so a rename is an edit of that
    note and `manager.update_entry` records it as one: folding that into a
    board event would take the edit out of the note's history, which is where
    a person looks for it and where its own replay needs it.
    """
    made = _board_fixture(client)
    board = made["board"]["id"]
    before = session.query(AuditLog).count()
    client.put(f"/whiteboard/boards/{board}", json={"title": "renamed", "type": "map"})
    session.commit()

    assert session.query(AuditLog).count() == before + 2
    newest = session.query(AuditLog).order_by(AuditLog.id.desc()).limit(2).all()
    assert {row.entity_type for row in newest} == {"entry", "board"}
    assert all(row.entity_id == board for row in newest)


# --- the boards the model builds (Brief 7 item 4) ----------------------------


def _ai_board_writes() -> list[str]:
    """The write tools whose handlers live in `ai/tools/whiteboard.py`.

    Enumerated rather than listed, for the reason the two enumerations above
    exist: the day somebody adds a seventh board tool, this finds it, no
    driver is registered, and the failure says what to do.
    """
    from memorymap.ai import tools
    from memorymap.ai.tools import whiteboard as wb

    return sorted(
        name
        for name in tools.WRITE_TOOLS
        if tools.TOOLS[name].handler.__module__ == wb.__name__
    )


def test_every_ai_board_write_records_a_replayable_event(session):
    """A board the AI built has to replay the way one built by hand does.

    The tools recorded a detail and no payload, so the log knew a card had
    been placed and could not say where, which is a history that cannot put
    anything back. Each call below is checked for its events on the way
    past; the replay at the end is the point.
    """
    from memorymap.ai import tools
    from memorymap.core import events
    from memorymap.core.database import WhiteboardNode, WhiteboardObject, WhiteboardSketch

    note = manager.create_entry(session, "a note to put on the board", tags=[])
    second = manager.create_entry(session, "a second note", tags=[])
    session.commit()

    made: dict = {}

    def run(name: str, args: dict) -> dict:
        before = session.query(AuditLog).count()
        result = tools.execute_tool(session, name, args)
        session.commit()
        assert "error" not in result, f"{name} failed: {result}"
        written = (
            session.query(AuditLog)
            .order_by(AuditLog.id.asc())
            .offset(before)
            .all()
        )
        # Every tool call writes one `chat`/`ai_tool` row of its own
        # (`execute_tool`): the trail of what the model called, naming no
        # entity and so having nothing to replay. The writes are the rest.
        changes = [row for row in written if row.entity_type != "chat"]
        assert changes, f"{name} recorded nothing but the tool call itself"
        for row in changes:
            assert row.payload, f"{name} recorded {row.action} with no payload"
            assert row.entity_id, f"{name} recorded {row.action} with no entity"
            assert row.actor == f"ai:{name}", f"{name} recorded {row.actor}"
        return result

    board = run("create_mindmap", {"title": "a map the model made", "root_text": "root"})
    made["board"] = board["board_id"]
    made["root"] = board["root_id"]
    made["topic"] = run(
        "add_map_node",
        {"board_id": made["board"], "parent_id": made["root"], "text": "a branch"},
    )["node_id"]
    run(
        "link_map_nodes",
        {"board_id": made["board"], "from_id": made["root"], "to_id": made["topic"]},
    )
    made["card"] = run(
        "add_whiteboard_card",
        {"board_id": made["board"], "note_id": note.id, "x": 120, "y": 240},
    )["card_id"]
    made["card2"] = run(
        "add_whiteboard_card",
        {"board_id": made["board"], "note_id": second.id, "x": 300, "y": 240},
    )["card_id"]
    run(
        "add_whiteboard_link",
        {"from_card_id": made["card"], "to_card_id": made["card2"]},
    )
    run(
        "generate_diagram",
        {
            "board_id": made["board"],
            "nodes": [
                {"ref": "a", "title": "the root of the diagram"},
                {"ref": "b", "title": "a child", "parent_ref": "a"},
            ],
        },
    )

    covered = {
        "create_mindmap",
        "add_map_node",
        "link_map_nodes",
        "add_whiteboard_card",
        "add_whiteboard_link",
        "generate_diagram",
    }
    assert set(_ai_board_writes()) == covered, (
        "a write tool in ai/tools/whiteboard.py is not driven by this test. "
        "Give it the @events.writes treatment (the helpers at the top of that "
        "module), then call it here."
    )

    # The board itself, and then everything on it: a board's whole state is
    # the union of its items' replays (Brief 7 decision 4), so this is what
    # "an AI-built board replays" means in full.
    replayed_board = events.replay(session, "board", made["board"])
    assert replayed_board["title"] == "a map the model made"
    assert replayed_board["type"] == "map"

    items = 0
    for model, entity_type, state_of in (
        (WhiteboardNode, "whiteboard_node", events.node_state),
        (WhiteboardSketch, "whiteboard_sketch", events.sketch_state),
        (WhiteboardObject, "whiteboard_object", events.object_state),
    ):
        for row in session.query(model).filter(model.board_id == made["board"]).all():
            assert events.replay(session, entity_type, row.id) == state_of(row), (
                f"{entity_type} {row.id} does not replay to its current state"
            )
            items += 1
    # Two map nodes, two cards, two links, and the diagram's two cards and
    # one link: nine, and the count is here so a tool that quietly stops
    # writing its rows cannot pass by replaying nothing.
    assert items == 9


def test_a_generated_or_imported_map_replays_with_its_nodes_on_it(client, session):
    """Brief 7's open item 4, closed.

    Both map doors recorded one `board`/`created` event whose payload held
    the outline and a node *count*, so `events.replay` rebuilt the board and
    nothing on it: a generated or imported map replayed empty while every
    hand-placed object replayed fine. The AI's own `generate_diagram` already
    recorded one event per item; these two predate that decision.
    """
    from memorymap.core import events

    made = client.post(
        "/whiteboard/boards/import",
        json={
            "format": "markdown",
            "name": "Imported outline",
            "content": "- Roots\n  - First branch\n  - Second branch\n",
        },
    )
    assert made.status_code == 201, made.text
    board = made.json()
    assert board["object_count"] == 3
    session.commit()

    from memorymap.core.database import WhiteboardObject

    objects = (
        session.query(WhiteboardObject).filter_by(board_id=board["id"]).all()
    )
    assert len(objects) == 3
    for obj in objects:
        state = events.replay(session, "whiteboard_object", obj.id)
        assert state, f"object {obj.id} replays to nothing"
        assert json.loads(state["data"])["content"] == json.loads(obj.data)["content"], state

    board_state = events.replay(session, "board", board["id"])
    assert board_state["title"] == "Imported outline", board_state
