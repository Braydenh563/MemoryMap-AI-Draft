# Brief 7, the event log (WORLD_CLASS_PLAN B1): what is left

> Companions: [HISTORY.md](../HISTORY.md) ("From WORLD_CLASS_PLAN.md B1 and
> SESSION_BRIEFS Brief 7", "the event log's open items" for the second run,
> "the event log's last three gaps" for the third) ·
> [SESSION_BRIEFS.md](../SESSION_BRIEFS.md) Brief 7 · the spec,
> `tests/test_events.py`

Built in the first run: `AuditLog.actor` and `AuditLog.payload` with an
Alembic migration, `src/memorymap/core/events.py`, every public write in
`src/memorymap/entry/manager.py` recording exactly one event, `GET
/entries/{id}/history`, `POST /entries/{id}/restore/{event_id}`, `GET
/events?since=`, and the History sheet.

Built in the second run, and moved to HISTORY.md ("The event log's open
items"): compaction with its startup job (item 1), the
`(entity_type, entity_id, id DESC)` index (item 2), the whiteboard's writes
(item 3) and the History sheet's paging (item 6).

Built in the third run, and moved to HISTORY.md ("the event log's last three
gaps"): the AI's own board tools brought onto `@events.writes` so an AI-built
board replays (item 4), the feed's report of a compaction snapshot (item 5)
and the history sheet's per-row rebuild (item 7, found in this run).

## Decisions made (do not remake)

1. **Retention is compaction, and the policy is ninety days with the newest
   five kept.** Deletion would break replay. A run of events older than
   ninety days folds into one snapshot holding the whole state at that
   point; the rows behind it keep action, actor, detail and time and lose
   only their values. Five newest kept rather than twenty because
   `EntryRevision` already keeps the last twenty versions of every note for
   ever, so twenty here was a second copy of the same thing and collapsed
   nothing on an ordinary notebook.
2. **What compaction gives up, it says.** Restoring a version whose values
   are gone answers 410 with the reason; the History sheet renders "The text
   from this change is no longer kept." in that row.
3. **No `VACUUM` in the compaction pass.** The freed pages are reused
   immediately, so the file stops growing, and `ai/autonomous.py`'s
   `_vacuum` already returns them to the disk on its own schedule.
4. **A board's replayable entity is the item, not the board.** A note is one
   row and replays to one dict; a board is a note plus everything on it. So
   `whiteboard_node`, `whiteboard_sketch` and `whiteboard_object` each
   replay through `events.replay`, the board's own events (created,
   duplicated, generated, imported, settings changed) sit on `board`, and a
   board's whole state is the union of its items' replays.
5. **`rename_board` is not wrapped in a write scope.** Its title change goes
   through `manager.update_entry`; a scope would fold that note's own edit
   into the board's event and take it out of the note's history. The board's
   settings get their own event beside the note's, so that request records
   two events on two entities, by design.
6. **A compacted event reports what it is, not an edit.** A snapshot's
   `after` is the whole state, so `/events` read it as one change that set
   every field at once. The feed now reports `changed: []` and `snapshot`,
   the number of events the row stands for, and reports `compacted` on the
   rows whose values were dropped. A count rather than a span of time
   because the count is what the compactor knows and stays right when a
   later run folds more events into the same snapshot; the rows behind it
   keep their own timestamps for a reader that wants the dates.
7. **The AI's board tools write through the same helpers as the routes.**
   Four `@events.writes` helpers at the top of `ai/tools/whiteboard.py`
   (`_place_card`, `_draw_link`, `_place_object`, `_new_board`), and the
   payload builders (`events.node_state` and its two siblings, plus
   `events.board_state`) moved to `core/events.py` so both writers share
   one idea of an entity's state. The two batch tools stay undecorated and
   record one event per item: decorating a loop folds a whole batch into
   one event, which is the shape that lost the replay. The tools' entity
   types follow the routes' vocabulary (`whiteboard_node`,
   `whiteboard_sketch`, `whiteboard_object`, `board`); the old
   `mindmap`, `mindmap_node`, `mindmap_link`, `whiteboard_link` and
   `whiteboard_diagram` names had no reader.
8. **The index lives in `_INDEXES` and in a migration.** The startup path is
   what reaches an existing notebook; the migration is what reaches a
   database upgraded through Alembic alone. Both use IF NOT EXISTS, so they
   cannot disagree.

## Open, with the file and the next step

1. **Global undo of an AI action.** `file: src/memorymap/core/events.py`,
   `id: events-undo`. `replay` and `restore` cover one note. "Undo
   auto-filing" means selecting the events of one actor in one window and
   applying each `before` in reverse. **Next step:** `events.undo(session,
   actor, since_id)` plus the Settings surface that offers it; Brief 13
   expects it for a skill run's Undo. Note compaction now exists, so `undo`
   has to refuse an event whose values are gone (`events.is_compacted`)
   rather than applying an empty `before`. The AI's board writes now carry
   `before` as well, so undoing a board the model built is in reach: a
   deleted item is the one case with nothing to put back, since the
   whiteboard tables have no soft delete.
2. **The Timeline and Dashboard strips.** `file: frontend/dashboard.js`,
   `id: events-strip`. `GET /events?since=` exists and nothing reads it yet.
   The "Recently added" widget was deliberately left alone (it re-reads a
   list the dashboard has already loaded, and events would list notes that
   no longer exist). **Next step:** an activity strip that polls `/events`
   with the cursor, rendering actor and action. Boards are in the feed now,
   whoever built them, and the feed's own shape is settled: a row carries
   `changed`, `snapshot` (the events a compacted run stands for) and
   `compacted`, so a folded run renders as one line rather than a burst of
   edits.
3. **Sync (B6) as log shipping.** `id: events-sync`. Unstarted, and
   deliberately: it needs the retention rule, which now exists, so this is
   no longer blocked. A compacted snapshot ships as a snapshot.
4. ~~**A generated or imported map's nodes do not replay.**~~ **Closed
   2026-09-12 by the orchestrator.** `_place_map_nodes` returns the objects
   it placed and both routes record the board event and then one
   `whiteboard_object`/`created` per node, through `_record_map_creation`.
   The `@events.writes("board", "created")` decorator came off both, because
   "the outermost write wins": a decorated helper called from inside a
   decorated route opens no scope of its own and its event would be folded
   into the board's, which is the bug itself. `test_events.py` keeps an
   exact count (1 + N, not "at least one") and
   `test_a_generated_or_imported_map_replays_with_its_nodes_on_it` replays a
   three-node import. The original entry, for the record:

4. **A generated or imported map's nodes do not replay.** `file:
   src/memorymap/api/routes_whiteboard.py` (`generate_map`, `import_board`),
   `id: events-generated-nodes`. Found in the third run, not fixed: both
   routes place their nodes inside one `board`/`created` event, whose
   payload holds the outline rather than each node's state, so those
   objects have no event of their own and `events.replay` rebuilds nothing
   for them. The AI's `generate_diagram` records one event per item, which
   is the shape decision 4 asks for; these two predate it. **Next step:**
   `_place_map_nodes` records one `whiteboard_object`/`created` event per
   node (it is called outside the route's own scope, so it would have to
   place them through a decorated helper the way the AI tools now do), and
   the board event keeps the outline as the record of the run.

## Not verified

- No pre-Brief-7 database was upgraded. Both migrations are exercised by the
  suite and written to be idempotent against `_add_missing_columns()`; a
  real year-old file was not opened.
- Nothing about a real model driving the tool path: the actor threading and
  the board tools' events are verified by calling `execute_tool` directly
  (`tests/test_events.py`), and every provider test in this project runs
  against a fake transport. What a real small model does with these tools,
  and whether the boards it builds look like the ones the tests build, is
  not verified here.
- The history page's numbers are this sandbox's, on a note built by the
  app's own managers (4,000 edits of a 700-character note, so 4,000 events
  and none of them compacted). A page whose events are mostly compacted was
  not timed; it can only be faster, since a stripped payload is four bytes
  of JSON.
- Compaction's numbers come from a database this sandbox built (150 notes,
  40 edits each) and from one real running app's own notebook, not from a
  notebook anybody has used for a year.
- The startup job's own log line was not seen in a server log: the app's
  INFO lines do not reach uvicorn's stream. What was measured is its effect
  (one notebook's payloads went from 24,975 to 5,844 bytes across a
  restart, with its 247 rows untouched).
