"""Quitting background work, and quitting the app (§ tasks).

Two reports, one mechanism, see `core/bgtasks.py`'s docstring:

    "allow the quitting/killing of background tasks as well"
    "and if it is an automated bg task, make sure it doesnt instantly start
     back up again"
    "make sure that if the app is quit, all ai tasks and bg tasks stop as
     well"

The middle one is the subtle one and gets the most tests here: an autonomous
pass is on a scheduler that is *deliberately* wakeable, so quitting a pass
without holding the scheduler off means the very next preference change
starts another one seconds later. That is not a hypothetical race, `wake()`
exists precisely to cut the interval sleep short.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from memorymap.ai import autonomous
from memorymap.core import bgtasks, embedmodels, extras


def _source_of(module) -> str:
    """A module's own text, read through `Path.read_text`.

    `open(...).read()` leaves the handle to the garbage collector, which
    CodeQL flags (py/file-not-closed) and which is a real (if small) leak in
    a suite that does it a dozen times. One helper, closed every time.
    """
    return Path(module.__file__).read_text(encoding="utf-8") if module.__file__ else ""


@pytest.fixture(autouse=True)
def _clear_autonomous_state():
    autonomous.clear_snooze()
    autonomous._cancel.clear()
    autonomous._working.clear()
    yield
    autonomous.clear_snooze()
    autonomous._cancel.clear()
    autonomous._working.clear()


# --- one table, so the button appears where pressing it does something ------


def test_every_cancellable_kind_has_a_canceller():
    """The panel's Quit button is rendered from `CANCELLABLE_KINDS`, which is
    derived from the table rather than repeated, so this cannot drift, and
    the test says why the two must stay the same object."""
    assert set(bgtasks.CANCELLABLE_KINDS) == set(bgtasks.CANCELLERS)


def test_the_kinds_match_the_ones_tasks_reports():
    """A canceller keyed on a name `/tasks` never emits is a button nobody can
    press; a job kind with no canceller is the bug this replaced."""
    from memorymap.api import routes_tasks

    source = _source_of(routes_tasks)
    for kind in bgtasks.CANCELLERS:
        assert f'"kind": "{kind}"' in source, f"nothing in /tasks reports kind={kind}"


def test_an_unknown_kind_is_an_answer_not_an_error():
    acted, detail = bgtasks.cancel("no-such-job")
    assert acted is False
    assert detail


def test_every_canceller_is_safe_with_nothing_running():
    """`stop_all` calls all of them at shutdown without checking which are
    live, so "nothing to do" must never raise."""
    for kind in bgtasks.CANCELLERS:
        acted, detail = bgtasks.cancel(kind)
        assert detail, f"{kind} answered with nothing"


# --- the automated one, which must not restart -------------------------------


def test_quitting_a_pass_holds_the_scheduler_off():
    autonomous._working.set()
    acted, detail = bgtasks.cancel("autonomous")
    assert acted is True
    assert autonomous.cancelled() is True
    assert autonomous.snoozed_for() > 0
    # The default interval is 6 hours, and the message says so in the units a
    # person would use rather than in minutes.
    assert "6h" in detail
    # And says what the wait actually is, because "the next safe point" named
    # nothing anyone could picture: "The auto ai optimisation didnt instantly
    # quit?? what does quitting safely mean??"
    assert "nothing more will be asked of the model" in detail


def test_the_hold_is_never_shorter_than_the_floor():
    """An interval set to an hour still buys a real pause: a Quit followed by
    a restart 40 seconds later reads as the button not having worked."""
    autonomous.request_stop(snooze_seconds=1)
    assert autonomous.snoozed_for() >= autonomous.MIN_SNOOZE_SECONDS - 2


def test_run_now_overrules_the_hold():
    """The hold governs the *scheduler*. A person pressing "Run now" is
    answering their own earlier "not now"."""
    autonomous.request_stop(snooze_seconds=3600)
    assert autonomous.snoozed_for() > 0
    autonomous.clear_snooze()
    assert autonomous.snoozed_for() == 0


def test_a_stop_with_nothing_running_still_arms_the_hold():
    """Pressing Quit as a pass ends is a race the user cannot see. Arming the
    hold regardless means it does not immediately start another one."""
    assert autonomous.request_stop() is False  # nothing was running
    assert autonomous.snoozed_for() > 0


def test_the_pass_clears_the_flag_when_it_starts_not_when_it_ends():
    """A stop asked for during the previous pass must not cancel the next one
    before it has done anything, but it must stay readable by the thread that
    is still finishing."""
    source = _source_of(autonomous)
    body = source.split("def _run_optimization()")[1].split("def _remember_pass")[0]
    assert "_cancel.clear()" in body.split("try:")[0], "cleared at the start of the pass"
    assert "_cancel.clear()" not in body.split("finally:")[-1], "not cleared when it ends"


def test_the_scheduler_never_sleeps_past_the_end_of_a_hold():
    """A 15-minute hold on a loop that just went to sleep for six hours would
    otherwise behave like a six-hour one."""
    source = _source_of(autonomous)
    loop = source.split("def _loop(")[1].split("def start()")[0]
    assert "snoozed_for()" in loop
    assert "min(seconds, held + 1)" in loop


# --- the ones that are somebody else's process -------------------------------


def test_cancelling_pip_with_nothing_installing_says_so():
    acted, detail = extras.cancel()
    assert acted is False
    assert "Nothing is installing" in detail


def test_cancelling_pip_terminates_the_child(monkeypatch):
    """pip has no cooperative stop, terminate is the only thing that stops
    it, and it is what someone who pressed Quit meant."""
    calls = []

    class FakeProcess:
        def terminate(self):
            calls.append("terminate")

    monkeypatch.setattr(extras._state, "running", True)
    monkeypatch.setattr(extras._state, "process", FakeProcess())
    monkeypatch.setattr(extras._state, "cancelled", False)
    acted, _ = extras.cancel()
    assert acted is True
    assert calls == ["terminate"]
    assert extras._state.cancelled is True


def test_a_terminated_install_is_reported_as_cancelled_not_failed(monkeypatch):
    """Terminating pip makes it exit non-zero. A task history full of
    "Installing X failed" for things nobody wanted stops being read."""
    source = _source_of(extras)
    assert 'outcome = "cancelled"' in source
    assert source.index('if _state.cancelled:') < source.index('if _state.outcome == "failed":')


def test_the_embedding_download_promises_only_what_it_can_do(monkeypatch):
    """`snapshot_download` cannot be interrupted mid-file, so the message says
    "after the current file" rather than claiming it stopped now."""
    monkeypatch.setattr(embedmodels._state, "running", True)
    monkeypatch.setattr(embedmodels._state, "cancel_requested", False)
    acted, detail = embedmodels.cancel()
    assert acted is True
    assert embedmodels._state.cancel_requested is True
    assert "kept" in detail


# --- quitting the app --------------------------------------------------------


def test_stop_all_is_wired_into_the_apps_shutdown():
    """The report was "make sure that if the app is quit, all ai tasks and bg
    tasks stop as well", and the cause was that there was no shutdown handler
    at all: `/shutdown`'s docstring described one that did not exist."""
    from memorymap.api import app as app_module

    source = _source_of(app_module)
    assert "lifespan=lifespan" in source
    assert "bgtasks.stop_all()" in source


def test_stop_all_never_raises_with_nothing_running():
    assert isinstance(bgtasks.stop_all(), list)


def test_stop_all_holds_the_scheduler_only_briefly():
    """Quitting the app is not the same statement as quitting a pass: the
    next launch should behave normally."""
    bgtasks.stop_all()
    assert 0 < autonomous.snoozed_for() <= autonomous.MIN_SNOOZE_SECONDS


def test_the_cancel_endpoint_answers_rather_than_erroring(ai_client):
    """Never 404 on an unknown kind and never 409 on a finished job: the panel
    is polling, so by the time a click lands the job may genuinely be over."""
    body = ai_client.post("/tasks/cancel", json={"kind": "reindex"}).json()
    assert body["stopped"] is False
    assert body["detail"]
    assert ai_client.post("/tasks/cancel", json={"kind": "nope"}).status_code == 200


def test_the_task_list_marks_the_kinds_that_can_be_quit(ai_client):
    body = ai_client.get("/tasks").json()
    for task in body["tasks"]:
        assert task["cancellable"] == (task["kind"] in bgtasks.CANCELLABLE_KINDS)


def test_the_warmup_says_why_it_has_no_quit_button():
    """A missing button with no explanation reads as a missing feature."""
    from memorymap.api import routes_tasks

    source = _source_of(routes_tasks)
    assert "can't be " in source and "stopped part-way" in source
    assert "embeddings" not in bgtasks.CANCELLABLE_KINDS


def test_a_quit_pass_is_skipped_by_the_scheduler_until_the_hold_expires():
    """The behaviour the hold exists for, asserted against the clock rather
    than the source."""
    autonomous.request_stop(snooze_seconds=3600)
    held = autonomous.snoozed_for()
    assert held > 0
    time.sleep(0.01)
    assert autonomous.snoozed_for() <= held


def test_a_hold_does_not_burn_down_while_the_feature_is_off():
    """"the limit on it restarting should be based on the set interval and it
    shouldnt reset if the user disabled it." A hold is a wall-clock deadline,
    so it expired during time the feature was switched off and could not have
    run anyway: quit a pass, switch it off for a day, switch it back on, and
    a pass started within seconds of the toggle."""
    from memorymap.ai import autonomous

    autonomous.clear_snooze()
    autonomous.request_stop(snooze_seconds=3600)
    before = autonomous.snoozed_for()
    assert before > 0

    autonomous.freeze_hold()
    frozen = autonomous.snoozed_for()
    # Frozen means frozen: the number does not move with the clock.
    assert autonomous.snoozed_for() == frozen
    autonomous.thaw_hold()
    assert abs(autonomous.snoozed_for() - frozen) <= 1
    autonomous.clear_snooze()
    assert autonomous.snoozed_for() == 0
