"""The background librarian: a scheduled agent pass over the whole notebook.

Off unless `autonomous_tasks_enabled` is set, because it runs the agent with
nobody watching: the one place in this app where the model writes to notes
without a person having just asked it to. Everything here is shaped by that:
the destructive tools are barred rather than confirmed (there is no one to
confirm to), a run that asks for confirmation is abandoned rather than
answered, and the whole thing is skipped on battery power.

Three things this module learned the hard way, all worth keeping written down:

- **It has to actually be started.** The first version was never wired to
  anything: `app.py` imported it and called nothing, so the interval setting
  in Settings pointed at a loop that did not exist and the feature silently
  did nothing at all. `start()` is called from the app's lifespan now.
- **`VACUUM` must not run through a Session.** SQLite refuses to vacuum inside
  a transaction. `session.execute(text("VACUUM"))`, how this was written , 
  happens to work *only* while it is the first statement in a fresh session,
  because pysqlite defers its BEGIN until the first DML; add any read or write
  before it and the same line raises `cannot VACUUM from within a
  transaction`. That is a landmine, not a working call: it survives on the
  ordering of the lines around it. An autocommit connection is correct
  whatever else the session has done.
- **A manual trigger needs a guard.** `trigger_now()` used to spawn a thread
  unconditionally, so holding down the button in Settings started as many
  concurrent agent runs as you had patience for, all writing to the same
  notebook.
- **The loop has to be woken, not just started.** It used to sleep for the
  whole interval (default 6 hours) between preference reads, so turning
  Battery Efficient Mode off, switching the toggle back on, or shortening the
  interval did nothing until whatever sleep was already in progress ran out, 
  reported as "background tasks skip things thinking battery mode is on [after
  it was turned off]" and "finishing a task disables automatic tasks, forcing
  a re-toggle": neither was true, the loop just hadn't looked again yet.
  `wake()` interrupts the current sleep so a preference change the user just
  made is read on the next tick, not the next scheduled one.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from memorymap.ai import agent
from memorymap.core import deps, events
from memorymap.core.database import Conversation

logger = logging.getLogger("memorymap.autonomous")

#: How long a run may take before the loop stops waiting on it at shutdown.
_JOIN_TIMEOUT = 5.0

#: The agent gets a bounded number of rounds, this is a tidy-up, not an
#: open-ended session, and an unbounded one on a big notebook is a way to
#: spend a night's CPU.
MAX_ROUNDS = 15

#: How many vague link reasons `audit_vague_links` may rewrite in one
#: background tick. Same reasoning as `MAX_ROUNDS`: this runs unattended on
#: every interval, so a bound keeps one tick's model calls to a handful
#: rather than however many vague links happen to exist.
AUDIT_BATCH_SIZE = 20

#: How many stale/orphaned notes get tagged in one background tick
#: (ROADMAP.md item 31). Same bound as `AUDIT_BATCH_SIZE` and the same
#: reason: a backlog of hundreds of forgotten notes is worked through a
#: little at a time, one interval per batch, not all in one tick.
STALE_REVIEW_BATCH_SIZE = 20

_lock = threading.Lock()
_stop_event: threading.Event | None = None
#: Interrupts the interval sleep without stopping the loop, set by `wake()`
#: whenever a preference the loop cares about changes, and by `stop()` itself
#: so shutdown does not wait out the sleep too.
_wake_event: threading.Event | None = None
_loop_thread: threading.Thread | None = None
#: Set while an optimisation pass is actually executing, by whichever path
#: started it. `routes_tasks` reads this to show the job in the task list, and
#: `trigger_now` reads it to refuse a second concurrent run.
_working = threading.Event()

#: Set by `request_stop()` and cleared when a pass starts. Checked between the
#: phases of `_run_optimization` and between the agent's rounds, so pressing
#: Quit in the tasks panel stops the pass at the next boundary rather than
#: after however many model calls it had left. Asked for directly: "allow the
#: quitting/killing of background tasks as well".
_cancel = threading.Event()

#: Wall-clock time before which no *scheduled* pass may start. This is the
#: second half of the same request, "and if it is an automated bg task, make
#: sure it doesnt instantly start back up again", and it is not hypothetical:
#: `wake()` exists precisely to cut the interval sleep short whenever a
#: preference changes, so without a snooze, quitting a pass and then touching
#: any setting the loop watches would start a new one seconds later. Quitting
#: a pass therefore also buys the rest of an interval's quiet.
#:
#: Deliberately *not* a preference and not persisted: it is a "not now", not a
#: "not ever". Turning the feature off is what the Settings toggle is for, and
#: a stop that silently outlived a restart would be a feature nobody switched
#: off and nobody can find.
_snooze_until: float = 0.0

#: The hold's remaining seconds while the feature is switched *off*, or None
#: when it is running down normally.
#:
#: Reported: *"the limit on it restarting should be based on the set interval
#: and it shouldnt reset if the user disabled it."* The first half was already
#: true (`request_stop` reads `autonomous_tasks_interval_hours`); the second
#: was not, and the hole is easy to miss. A hold is a wall-clock deadline, so
#: it burns down while the feature is disabled, during which nothing could
#: have run anyway. Quit a pass, switch the feature off for a day, switch it
#: back on, and the hold you set is long expired: a pass starts within seconds
#: of the toggle, which is exactly the "it started straight back up" the hold
#: exists to prevent. So the countdown is frozen while the feature is off and
#: re-anchored when it comes back, the user gets the quiet they asked for,
#: measured in time the feature was actually able to run.
_snooze_frozen: float | None = None

#: A floor under the hold, for the odd caller that passes an explicit one.
#: The interval is in whole hours, so this never binds on the default path, 
#: it is here so a future "snooze 30s" cannot make Quit look broken.
MIN_SNOOZE_SECONDS = 15 * 60

#: What the last pass actually did, so the user can read it back and undo any
#: of it (ROADMAP §40, item 2).
#:
#: This is the answer to "you are asking me to let an agent edit my notebook
#: while I am not looking". A true dry-run, run the agent, apply nothing , 
#: does not work here: the model decides its next call from the *result* of the
#: last one, so a pass with every write stubbed out stops resembling the pass
#: that would really happen, and a preview that lies is worse than none.
#:
#: Review-after is honest and is nearly as useful, because every write tool
#: already captures the call that would put the note back (`tools._undo_edit`).
#: Keeping those here turns the pass from something that happened to the
#: notebook into something the user can read, disagree with, and reverse, one
#: item at a time, through the same endpoint the chat's own Undo buttons use.
_last_pass: dict = {"finished_at": None, "outcome": None, "changes": []}

#: A pass that made more changes than this had something go wrong with it, and
#: a review list nobody can read is not a review.
MAX_RECORDED_CHANGES = 200


def is_running() -> bool:
    """Is an optimisation pass executing right now?

    Deliberately not "is the scheduler alive", the task list is showing the
    user work in progress, and an idle scheduler sleeping until 3am is not
    work in progress.
    """
    return _working.is_set()


def cancelled() -> bool:
    """Has someone asked the running pass to stop?

    Read between phases below. Also handed to anything long-running a pass
    calls, so a stop is felt inside a batch rather than only between them.
    """
    return _cancel.is_set()


def request_stop(snooze_seconds: float | None = None) -> bool:
    """Ask the running pass to stop, and keep the scheduler off it for a while.

    Returns whether there was anything to stop. Never blocks: the pass ends at
    its next checkpoint, which is at most one model call away, the alternative
    is killing a thread mid-write to the notebook, which this app will not do.
    """
    global _snooze_until, _snooze_frozen
    if snooze_seconds is None:
        # The user's own interval, which is the only number that means
        # anything here: "don't start again before you would have anyway".
        try:
            hours = int(deps.get_config().get_preference("autonomous_tasks_interval_hours") or 6)
        except (TypeError, ValueError, RuntimeError):
            hours = 6
        snooze_seconds = max(hours, 1) * 3600
    _snooze_until = time.time() + max(snooze_seconds, MIN_SNOOZE_SECONDS)
    _snooze_frozen = None  # a fresh hold always runs from now
    was_running = _working.is_set()
    _cancel.set()
    return was_running


def freeze_hold() -> None:
    """Stop the hold counting down, the feature has been switched off.

    Idempotent, and safe to call on every tick of the loop, which is how it is
    actually called."""
    global _snooze_frozen
    if _snooze_frozen is None and _snooze_until:
        _snooze_frozen = max(0.0, _snooze_until - time.time())


def thaw_hold() -> None:
    """Start it counting down again, the feature is back on."""
    global _snooze_until, _snooze_frozen
    if _snooze_frozen is not None:
        _snooze_until = time.time() + _snooze_frozen
        _snooze_frozen = None


def snoozed_for() -> int:
    """Seconds until a scheduled pass may run again, 0 when nothing is held.

    Shown to the user rather than only obeyed: a background worker that
    silently declines to run for six hours is indistinguishable from one that
    is broken.
    """
    if _snooze_frozen is not None:
        return int(_snooze_frozen)
    return max(0, int(_snooze_until - time.time()))


def clear_snooze() -> None:
    """Forget any hold. Pressing "Run now" is an explicit answer to "not now"."""
    global _snooze_until, _snooze_frozen
    _snooze_until = 0.0
    _snooze_frozen = None


def scheduler_alive() -> bool:
    """Is the interval loop running? (For diagnostics, not the task list.)"""
    with _lock:
        return _loop_thread is not None and _loop_thread.is_alive()


def _enabled_tasks(config) -> list[str]:  # noqa: ANN001  # config is duck-typed
    tasks = []
    if config.get_preference("auto_tag_enabled", True):
        tasks.append("tag untagged notes")
    if config.get_preference("auto_link_enabled", True):
        tasks.append("create missing links between conceptually related notes")
    if config.get_preference("auto_dedupe_enabled", True):
        tasks.append("identify and flag duplicates")
    return tasks


def _run_optimization() -> None:
    """One pass. Never raises: it is the top of a worker thread.

    Everything it changes is recorded as `system:librarian` (Brief 7): this
    is the one place in the app that edits notes while nobody is looking,
    which makes "who did this" the first thing anyone asks about it. Set
    here rather than inherited, because a thread starts with a fresh
    context and would otherwise record the default, `user`.
    """
    if not _working.is_set():
        # Belt and braces: both entry points set this before starting the
        # thread, so reaching here without it means a new caller forgot.
        _working.set()
    # A stop asked for during the *previous* pass must not cancel this one
    # before it has done anything. Cleared here, at the start, rather than
    # when the previous pass ended: the flag's whole job is to be readable
    # by the thread that is finishing, right up until it finishes.
    _cancel.clear()
    started = time.monotonic()
    with events.acting_as("system:librarian"):
        _optimization_pass(started)


def _optimization_pass(started: float) -> None:
    """The body of one pass, split out so the actor above wraps all of it."""
    try:
        config = deps.get_config()
        if config.get_preference("battery_efficient_mode"):
            logger.info("skipped: battery efficient mode is on")
            return

        # ROADMAP.md item 34, run separately from the agent pass below, 
        # a plain per-note completion call (like suggest_tags), not a tool-
        # calling agent turn, and gated by its own preference so it isn't
        # silently skipped whenever tag/link/dedupe are all switched off.
        if config.get_preference("auto_entities_enabled", False):
            try:
                from memorymap.ai.entities import extract_entities_pass

                db = deps.get_db()
                with db.session() as session:
                    processed = extract_entities_pass(
                        session, deps.get_model_manager(), deps.get_ollama()
                    )
                if processed:
                    logger.info("entity extraction: scanned %d note(s)", processed)
            except Exception as exc:  # noqa: BLE001  # top of a worker thread
                logger.error("entity extraction failed: %s", exc, exc_info=True)

        # Its own preference, deliberately separate from `auto_link_enabled`:
        # that toggle is "should the agent create/remove links at all", and
        # this one is "should already-existing links get their vague reason
        # rewritten", someone who wants the agent to stop making new
        # judgement calls about their links but is happy for existing vague
        # reasons to keep improving (or vice versa) can't say that with one
        # shared flag. Defaults to True, matching every other auto_* toggle
        # here: opt-out, not opt-in.
        if _cancel.is_set():
            logger.info("stopped before link reason audit, someone quit this pass")
            return

        if config.get_preference("auto_link_reason_audit", True):
            try:
                from memorymap.ai.links import audit_vague_links
                db = deps.get_db()
                with db.session() as session:
                    # A small, fixed batch per tick, this runs on every
                    # interval for as long as the server is up, so an
                    # unbounded pass over a big notebook would mean one tick
                    # never finishes before the next is due. `AUDIT_BATCH_SIZE`
                    # keeps each tick short; a large backlog is worked through
                    # a bit at a time, one interval per batch.
                    updated = audit_vague_links(
                        session, deps.get_model_manager(), deps.get_ollama(),
                        limit=AUDIT_BATCH_SIZE,
                    )
                if updated:
                    logger.info("link reason audit: updated %d link(s)", updated)
            except Exception as exc:
                logger.error("link reason audit failed: %s", exc, exc_info=True)

        # ROADMAP.md item 31: "acting on stale/orphaned notes (nothing
        # currently reviews a note nobody has touched in months)". Arithmetic
        # like the link-reason audit above, not an agent turn, staleness and
        # connectedness are both plain columns and joins, see
        # `entry/staleness.py`'s own docstring for why that's deliberate.
        # Tagging rather than archiving or deleting: there's nobody here to
        # confirm a change to a note's visibility, but a tag is the same kind
        # of low-stakes, reversible mark `_tag_note` already makes for a
        # person who asks for one directly.
        # ANALYSIS.md §60 item 2. Its own preference and its own pass, not
        # part of the agent turn below: this reads *conversations*, not
        # notes, and the agent's job list is written in terms of notes.
        if _cancel.is_set():
            logger.info("stopped before passive capture, someone quit this pass")
            return

        if config.get_preference("auto_capture_enabled", False):
            try:
                from memorymap.ai.passive_capture import capture_pass

                db = deps.get_db()
                with db.session() as session:
                    captured = capture_pass(
                        session,
                        deps.get_model_manager(),
                        deps.get_ollama(),
                        config,
                    )
                if captured:
                    logger.info("passive capture: wrote %d draft(s)", captured)
            except Exception as exc:  # noqa: BLE001  # top of a worker thread
                logger.error("passive capture failed: %s", exc, exc_info=True)

        if _cancel.is_set():
            logger.info("stopped before stale/orphaned review, someone quit this pass")
            return

        if config.get_preference("auto_stale_review_enabled", False):
            try:
                from memorymap.entry import manager as entry_manager
                from memorymap.entry import staleness

                db = deps.get_db()
                tagged = 0
                with db.session() as session:
                    candidates = staleness.find_stale_orphaned_notes(session)
                    for entry in candidates[:STALE_REVIEW_BATCH_SIZE]:
                        tags = entry_manager.entry_tags(entry)
                        if "stale" in tags:
                            continue
                        entry_manager.update_entry(session, entry, tags=[*tags, "stale"])
                        tagged += 1
                if tagged:
                    logger.info("stale/orphaned review: tagged %d note(s)", tagged)
            except Exception as exc:
                logger.error("stale/orphaned review failed: %s", exc, exc_info=True)

        if _cancel.is_set():
            logger.info("stopped before the agent pass, someone quit this pass")
            return

        tasks = _enabled_tasks(config)
        if not tasks:
            logger.info("skipped: every autonomous task is switched off in Settings")
            return

        task_str = ", ".join(tasks)
        persona = (
            "You are an autonomous background process optimizing the user's "
            "knowledge base. You are running without user interaction. "
            f"Your task is to {task_str} using your tools. Do not ask questions "
            "or expect user replies. When you are finished making improvements, "
            "stop your turn."
        )
        if not config.get_preference("auto_tag_enabled", True):
            persona += " Do NOT change or add tags."
        if not config.get_preference("auto_link_enabled", True):
            persona += " Do NOT link notes."
        else:
            persona += (
                " When you link two notes, pass a reason if the connection "
                "isn't obvious from the titles alone (e.g. 'both about "
                "scheduling'), it's shown on the graph and explains the "
                "link to the person who wrote the notes."
            )

        outcome, detail = "completed", "Finished analysing and linking notes."
        changes: list[dict] = []
        db = deps.get_db()
        with db.session() as session:
            try:
                events = agent.run_agent(
                    session=session,
                    question=(
                        f"Analyze recent or isolated notes and {task_str}. Use "
                        "find_similar_notes to traverse the graph conceptually. "
                        "Stop when done."
                    ),
                    notes=[],
                    model_manager=deps.get_model_manager(),
                    ollama=deps.get_ollama(),
                    persona_prompt=persona,
                    # Nothing here can be confirmed and nothing here should be
                    # deleted: there is no user in the loop to ask.
                    blocked_tools=frozenset({"ask_user", "delete_note"}),
                    max_rounds=MAX_ROUNDS,
                    mode="autonomous",
                    use_utility_model=True,
                )
                for event in events:
                    if _cancel.is_set():
                        # Abandoning the generator rather than killing a
                        # thread: the round that is already in flight finishes
                        # and nothing further is asked of the model. Whatever
                        # it changed up to here is real, was recorded, and is
                        # in the review list like any other pass's changes.
                        logger.info("stopped mid-pass: someone quit this job")
                        outcome, detail = "cancelled", "Stopped part-way through."
                        break
                    if event.get("type") == "confirm":
                        logger.info(
                            "paused for confirmation on %s with nobody to ask, abandoning run",
                            event.get("name"),
                        )
                        outcome, detail = (
                            "failed",
                            f"Stopped: {event.get('name')} needs confirmation.",
                        )
                        break
                    if event.get("type") == "tool" and not event.get("ok"):
                        logger.warning("tool error: %s", event.get("error"))
                    # The agent hangs a `change` off every successful write,
                    # carrying the call that would put the note back. Collected
                    # here so the pass can be read and reversed afterwards, 
                    # see `_last_pass`.
                    change = event.get("change")
                    if change and len(changes) < MAX_RECORDED_CHANGES:
                        changes.append(change)
            except Exception as exc:  # noqa: BLE001  # top of a worker thread
                logger.error("autonomous execution failed: %s", exc, exc_info=True)
                # Recording "completed" here regardless of what happened is
                # what the first version did, and it made the task history
                # actively misleading: every failure showed up as a success.
                outcome, detail = "failed", str(exc)

        from memorymap.core import taskhistory

        if changes:
            detail = f"{detail} Changed {len(changes)} thing(s)."
        _remember_pass(outcome, changes)
        taskhistory.record(
            "autonomous",
            "Autonomous knowledge base optimisation",
            outcome,
            detail,
            name=deps.get_model_manager().utility_model(),
            duration_ms=(time.monotonic() - started) * 1000,
        )
        logger.info("autonomous optimisation %s, %d change(s)", outcome, len(changes))
    finally:
        _working.clear()


def _remember_pass(outcome: str, changes: list[dict]) -> None:
    """Record what the pass did, replacing the previous record.

    One pass deep on purpose. The point of this list is "read what just
    happened while it is still surprising you"; a scrolling history of every
    pass is what `taskhistory` and the audit log are for, and keeping undo
    payloads around for weeks invites someone to reverse an edit they have
    since deliberately redone.
    """
    with _lock:
        _last_pass["finished_at"] = datetime.now(timezone.utc).isoformat()
        _last_pass["outcome"] = outcome
        _last_pass["changes"] = list(changes)


def last_pass() -> dict:
    """What the last pass did, for the review panel in Settings."""
    with _lock:
        return {
            "finished_at": _last_pass["finished_at"],
            "outcome": _last_pass["outcome"],
            "changes": list(_last_pass["changes"]),
        }


def forget_last_pass() -> None:
    """Clear the review list, once the user has read it."""
    with _lock:
        _last_pass.update({"finished_at": None, "outcome": None, "changes": []})


def _vacuum() -> None:
    """Compact the database and drop vectors whose note is gone.

    `VACUUM` needs to be outside a transaction, which a `Session` will not give
    you: hence the raw connection with autocommit isolation. Written as its
    own function so the reason survives the next person who "simplifies" it
    back into `session.execute`.
    """
    engine = deps.get_db().engine
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("VACUUM"))
    logger.info("database VACUUM complete")

    from memorymap.ai import embeddings

    embeddings.clean_orphaned_vectors(deps.get_db().session)
    clean_orphaned_board_cards()
    purge_old_conversations()


def purge_old_conversations() -> int:
    """Drop saved chats older than the user's retention setting.

    **Why this exists.** Notes have had a recycle bin with a configurable
    auto-purge for a long time; chat history had nothing. It grew forever, and
    nothing in the app would ever have noticed, no cap, no warning, no
    "oldest first" anything. On a notebook used daily for a year that is the
    single largest table in the database, and every row of it is a
    conversation the user finished with months ago.

    **Off by default (`0` means keep everything), and that is deliberate.**
    Deleting somebody's history because a background job decided it was old is
    the kind of "helpful" behaviour a local-first notebook must not have. The
    user turns this on; until they do, nothing is removed.

    **Pinned chats are never purged, at any age.** Pinning is the existing,
    already-understood way to say "this one matters" (`Conversation.pinned`,
    used by the chat list's own sort), so it is the right signal to reuse
    rather than inventing a second one, and a retention rule that could
    delete the thread you deliberately kept would make pinning useless.

    Age is measured from `updated_at`, not `created_at`: a long-running thread
    you added to yesterday is not an old conversation, however long ago it
    started.
    """
    config = deps.get_config()
    days = int(config.get_preference("conversation_retention_days", 0) or 0)
    if days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    db = deps.get_db()
    with db.session() as session:
        # `workspace_id="all"`: this is maintenance over the whole database,
        # not a view of one space. Without it the session's own workspace
        # filter would scope the purge to whichever space happened to be
        # active, and the others would grow forever regardless of the setting.
        session.info["workspace_id"] = "all"
        stale = list(
            session.scalars(
                select(Conversation).where(
                    Conversation.updated_at < cutoff,
                    Conversation.pinned == False,  # noqa: E712
                )
            )
        )
        for conversation in stale:
            session.delete(conversation)
        session.commit()
    if stale:
        logger.info("conversation retention: removed %d chat(s) older than %d days", len(stale), days)
    return len(stale)


def clean_orphaned_board_cards() -> int:
    """Remove whiteboard cards whose note is gone.

    The same gap `clean_orphaned_vectors` closes, one table over: a card holds
    an `entry_id` with no cascade behind it, so purging a note from the recycle
    bin leaves the card on the board pointing at nothing. That is worse than a
    stale vector, because a vector nobody can see just wastes a comparison, a
    dead card is visible, is not removable through the UI (the thing you would
    click is the card that fails to render), and makes the board look broken.

    Sketches are deliberately left alone: a sketch has a `board_id` but no
    `entry_id`, so it belongs to the board rather than to any one note.
    """
    from memorymap.core.database import Entry, WhiteboardNode

    with deps.get_db().session() as session:
        orphans = list(
            session.scalars(
                select(WhiteboardNode).where(
                    WhiteboardNode.entry_id.notin_(select(Entry.id))
                )
            )
        )
        for card in orphans:
            session.delete(card)
        if orphans:
            session.commit()

    if orphans:
        logger.info("removed %d whiteboard card(s) whose note no longer exists", len(orphans))
    return len(orphans)


def _loop(stop_event: threading.Event, wake_event: threading.Event) -> None:
    while not stop_event.is_set():
        config = deps.get_config()
        enabled = config.get_preference("autonomous_tasks_enabled", False)
        # A hold must not burn down during time the feature could not have run
        # in: see `_snooze_frozen`. Done here rather than in the settings
        # route so it holds however the preference changed (Settings, the
        # tray, a restore, an import).
        if enabled:
            thaw_hold()
        else:
            freeze_hold()
        held = snoozed_for()
        if not enabled:
            pass  # nothing to do; the hold (if any) is frozen above
        elif held:
            # See `_snooze_until`: someone quit a pass, so the scheduler stays
            # off it until the hold expires, including when `wake()` cut the
            # sleep short, which is the case that made this necessary.
            logger.info("skipped: a quit pass holds the scheduler for %ds more", held)
        else:
            _working.set()
            try:
                _run_optimization()
            except Exception:  # noqa: BLE001  # the loop outlives one bad pass
                logger.error("autonomous loop error", exc_info=True)
                _working.clear()
            try:
                _vacuum()
            except Exception:  # noqa: BLE001
                logger.error("database maintenance error", exc_info=True)

        try:
            hours = int(config.get_preference("autonomous_tasks_interval_hours") or 6)
        except (TypeError, ValueError):
            hours = 6
        # Waited on `wake_event`, not `stop_event`: the old version blocked on
        # `stop_event.wait()` directly, so a preference changed mid-sleep (the
        # toggle, battery mode, the interval itself) was invisible until the
        # *whole* sleep ran out, up to six hours by default. `wake()` sets
        # this event to cut the sleep short without touching `stop_event`,
        # so the loop re-reads preferences on the next line without exiting.
        # `Event.wait` rather than a loop of one-second sleeps: the old version
        # woke 21,600 times to check a flag it could have been woken for, and
        # stopping the app meant waiting out the last of those seconds.
        wake_event.clear()
        # Never sleep past the end of a hold: the loop would wake at its next
        # scheduled time anyway, but a hold that expires 15 minutes in should
        # not have to wait out the remaining five and three-quarter hours
        # before anything can run again.
        seconds = max(1, hours) * 3600
        held = snoozed_for()
        # A frozen hold has no expiry to wake for, only the toggle coming
        # back on can end it, and that fires `wake()` on its own.
        if held and _snooze_frozen is None:
            seconds = min(seconds, held + 1)
        wake_event.wait(seconds)


def start() -> None:
    """Start the interval loop. Idempotent: a second call is a no-op."""
    global _stop_event, _wake_event, _loop_thread
    with _lock:
        if _loop_thread is not None and _loop_thread.is_alive():
            return
        _stop_event = threading.Event()
        _wake_event = threading.Event()
        _loop_thread = threading.Thread(
            target=_loop, args=(_stop_event, _wake_event), daemon=True, name="autonomous-agent"
        )
        _loop_thread.start()


def stop() -> None:
    """Ask the loop to finish. Used at shutdown and by the tests."""
    global _stop_event, _wake_event, _loop_thread
    with _lock:
        event, wake, thread = _stop_event, _wake_event, _loop_thread
        _stop_event = _wake_event = _loop_thread = None
    if event is not None:
        event.set()
    # The loop blocks on `wake_event`, not `stop_event`, without this it
    # would not notice `stop_event` was set until its current sleep expired.
    if wake is not None:
        wake.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=_JOIN_TIMEOUT)


def wake() -> None:
    """Cut the current interval sleep short so a preference change the user
    just made (enabling autonomous tasks, turning battery mode off, a shorter
    interval) is read on the next tick instead of the next scheduled one.
    A no-op if the scheduler isn't running: `start()` always creates a fresh
    `_wake_event`, so nothing is lost by calling this before the first start.
    """
    event = _wake_event
    if event is not None:
        event.set()


def trigger_now() -> bool:
    """Run a pass right now, off-schedule. False if one is already running."""
    if _working.is_set():
        return False
    # "Run now" is a person overruling their own earlier "not now", so it
    # clears the hold rather than being refused by it. The hold only ever
    # governs the *scheduler*.
    clear_snooze()
    # Set before the thread starts, not inside it: two clicks in the same
    # millisecond would both see a clear flag and both start a run otherwise.
    _working.set()
    threading.Thread(
        target=_run_optimization, daemon=True, name="autonomous-manual"
    ).start()
    return True
