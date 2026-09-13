"""Settings → Background tasks has to show *every* background job.

It listed two, a re-index and a model download, because it was assembled in
`app.js` out of whatever happened to be in `/models/status`. The embedding
model loading at startup and the SearXNG install, which is the longest job in
the app at several minutes, ran with nothing on that screen to say so.
"""

from __future__ import annotations

import re
import time

import pytest

from memorymap.ai import model_manager


@pytest.fixture(autouse=True)
def _clean_jobs():
    model_manager.reset_jobs()
    yield
    model_manager.reset_jobs()


def _kinds(client) -> list[str]:
    return [task["kind"] for task in client.get("/tasks").json()["tasks"]]


def test_nothing_running_is_an_empty_list_not_an_error(client):
    """Both halves are lists rather than nulls: a screen that has to tell
    "nothing running" from "couldn't ask" would need two code paths for what
    is, to the user, one sentence.

    Asserted field by field rather than against the whole payload, the
    endpoint grew a `history` key, and a test pinned to the exact dict shape
    fails on an addition that broke nothing.
    """
    body = client.get("/tasks").json()
    assert body["tasks"] == []
    assert body["history"] == []


def test_a_reindex_shows_up_with_its_progress(client, monkeypatch):
    monkeypatch.setattr(
        model_manager,
        "reindex_status",
        lambda: {"kind": "reindex", "name": "", "total": 40, "done": 10,
                 "status": "running", "error": ""},
    )
    task = client.get("/tasks").json()["tasks"][0]
    assert task["kind"] == "reindex"
    assert task["detail"] == "10 of 40"
    assert task["progress"] == pytest.approx(0.25)
    assert task["cancellable"] is True


def test_a_model_download_shows_up(client, monkeypatch):
    monkeypatch.setattr(
        model_manager,
        "pull_statuses",
        lambda: {"llama3.2": {"kind": "pull", "name": "llama3.2", "total": 100,
                              "done": 62, "status": "running", "error": ""}},
    )
    task = client.get("/tasks").json()["tasks"][0]
    assert task["name"] == "llama3.2"
    assert task["detail"] == "62%"
    assert task["cancellable"] is True


def test_a_job_with_no_total_yet_says_so_rather_than_guessing(client, monkeypatch):
    """A progress bar that invents a number is worse than one that admits it
    cannot say."""
    monkeypatch.setattr(
        model_manager,
        "pull_statuses",
        lambda: {"big": {"kind": "pull", "name": "big", "total": 0, "done": 0,
                         "status": "running", "error": ""}},
    )
    task = client.get("/tasks").json()["tasks"][0]
    assert task["progress"] is None
    assert task["detail"] == "starting…"


def test_a_finished_job_is_not_a_task(client, monkeypatch):
    """A screen that accumulates finished work is a log, and there is one."""
    monkeypatch.setattr(
        model_manager,
        "reindex_status",
        lambda: {"kind": "reindex", "name": "", "total": 40, "done": 40,
                 "status": "success", "error": ""},
    )
    assert _kinds(client) == []


def test_the_embedding_warm_up_is_a_visible_job(client, monkeypatch):
    """~90 MB on first use, in a background thread, with nothing on screen, 
    which reads as the app being broken rather than busy."""
    from memorymap.ai import embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "warmup_running", lambda: True)
    task = next(t for t in client.get("/tasks").json()["tasks"] if t["kind"] == "embeddings")
    assert "90 MB" in task["detail"]
    # **The one job with no Quit button, and the only one.** It is a single
    # blocking model load with nothing to check a flag between, so a button
    # would be a lie. The detail text has to say so, or a missing button reads
    # as a missing feature.
    assert task["cancellable"] is False
    assert "stopped part-way" in task["detail"]


def test_a_vision_caption_shows_up_while_running(client, monkeypatch):
    """ROADMAP §89.6: a caption call is a real model round-trip with nothing
    visible anywhere while it runs, same "invisible until it's the Tasks
    panel's job to say so" shape as the embedding warm-up above."""
    from memorymap.ai import captioning

    monkeypatch.setattr(
        captioning,
        "running_captions",
        lambda: [{"upload_id": 7, "name": "vacation.png"}],
    )
    task = next(t for t in client.get("/tasks").json()["tasks"] if t["kind"] == "caption")
    assert "vacation.png" in task["label"]
    # Same reasoning as the embedding warm-up: one blocking model call, no
    # flag to check between, a Quit button here would do nothing.
    assert task["cancellable"] is False


def test_the_searxng_install_is_a_visible_job(client, monkeypatch):
    """Minutes long, and previously visible only on the Web search screen."""
    from memorymap.search import searxng_manager

    monkeypatch.setitem(searxng_manager._install_state, "running", True)
    monkeypatch.setitem(searxng_manager._install_state, "step", "Unpacking SearXNG…")
    task = next(t for t in client.get("/tasks").json()["tasks"] if t["kind"] == "searxng")
    assert task["detail"] == "Unpacking SearXNG…"
    # Quittable since `core/bgtasks.py`, it is the longest silence in the app
    # (pip building lxml for minutes) and was the job most worth stopping.
    assert task["cancellable"] is True


def test_a_long_job_carries_its_progress_and_its_output(client, monkeypatch):
    """Reported: "the searxng reinstall doesn't have a progress bar so idk if
    it has frozen or is working". The bar answers that while it moves; the
    lines answer it while the bar sits still."""
    from memorymap.search import searxng_manager

    monkeypatch.setitem(searxng_manager._install_state, "running", True)
    monkeypatch.setitem(searxng_manager._install_state, "stage", 4)
    monkeypatch.setitem(searxng_manager._install_state, "progress", 0.7)
    monkeypatch.setitem(
        searxng_manager._install_state, "log", ["Collecting lxml", "Building wheel"]
    )
    task = next(t for t in client.get("/tasks").json()["tasks"] if t["kind"] == "searxng")
    assert "step 4 of 5" in task["label"]
    assert task["progress"] == 0.7
    assert task["log"] == ["Collecting lxml", "Building wheel"]


def test_every_task_carries_a_log_field_even_when_it_is_empty(client, monkeypatch):
    """The frontend renders whatever it is given; a missing key is a crash."""
    monkeypatch.setattr(
        model_manager,
        "reindex_status",
        lambda: {"kind": "reindex", "name": "", "total": 4, "done": 1,
                 "status": "running", "error": ""},
    )
    for task in client.get("/tasks").json()["tasks"]:
        assert set(task) >= {
            "kind", "name", "label", "detail", "progress", "cancellable", "log"
        }


def test_several_jobs_at_once_all_appear(client, monkeypatch):
    from memorymap.ai import embeddings as embeddings_module
    from memorymap.search import searxng_manager

    monkeypatch.setattr(
        model_manager,
        "reindex_status",
        lambda: {"kind": "reindex", "name": "", "total": 4, "done": 1,
                 "status": "running", "error": ""},
    )
    monkeypatch.setattr(embeddings_module, "warmup_running", lambda: True)
    monkeypatch.setitem(searxng_manager._install_state, "running", True)

    assert set(_kinds(client)) == {"reindex", "embeddings", "searxng"}


def test_the_tasks_list_sits_behind_the_unlock_gate(client):
    """It names the models you run and what you are installing."""
    token = client.post("/auth/setup", json={"password": "gate-test"}).json()["token"]
    assert client.get("/tasks").status_code == 401
    assert client.get("/tasks", headers={"X-Auth-Token": token}).status_code == 200


def test_a_searxng_start_is_a_visible_task(client, monkeypatch):
    """The longest silence in the app from the user's side: a start waits up
    to 90 seconds for the service to answer. The install was listed here and
    this was not, so the panel looked broken to anyone watching a start."""
    from memorymap.search import searxng_manager

    monkeypatch.setitem(searxng_manager._start_state, "running", True)
    monkeypatch.setitem(searxng_manager._start_state, "backend", "source")
    monkeypatch.setitem(searxng_manager._start_state, "since", time.time() - 12)

    tasks = client.get("/tasks").json()["tasks"]
    start = [t for t in tasks if t["kind"] == "searxng-start"]
    assert start, [t["kind"] for t in tasks]
    assert start[0]["label"] == "Starting SearXNG"
    # Not an exact "12s": the route reports int(now - since), and `now` is read
    # when the request lands, not when `since` was set above. Any delay past a
    # one-second boundary between the two, trivially reached on a loaded CI
    # runner: reports 13 and failed the build, which is what happened. The
    # behaviour worth asserting is "it counts the elapsed seconds against the
    # 90s budget", so assert that, with enough slack to survive a slow machine.
    elapsed = re.search(r"\((\d+)s of 90s\)", start[0]["detail"])
    assert elapsed, start[0]["detail"]
    assert 12 <= int(elapsed.group(1)) <= 20, start[0]["detail"]
    assert 0 < start[0]["progress"] < 1
    # Quitting a start means stopping the thing being waited for, which is
    # what someone pressing Quit on "Starting SearXNG" means.
    assert start[0]["cancellable"] is True


def test_nothing_is_listed_once_the_start_finishes(client):
    from memorymap.search import searxng_manager

    searxng_manager._start_state["running"] = False
    kinds = [t["kind"] for t in client.get("/tasks").json()["tasks"]]
    assert "searxng-start" not in kinds


# --- job cancellation ---------------------------------------------------------------


def test_cancel_missing_job_is_404(client):
    assert client.post("/models/jobs/cancel?kind=reindex").status_code == 404


def test_cancel_unknown_kind_is_400(client):
    assert client.post("/models/jobs/cancel?kind=bogus").status_code == 400


def test_reindex_cancel_flag_stops_the_worker(app_state):
    from memorymap.core import deps

    job = model_manager.Job(kind="reindex", total=5)
    job.cancel_requested = True
    # A cancelled job reports 'cancelled', never crashes.

    class _Emb:
        def store_for_entry(self, *a, **k):
            raise AssertionError("should not embed after cancel")

        def backend_id(self):
            return "x"

    # With the flag pre-set and no entries, the loop exits cleanly.
    model_manager._run_reindex(deps.get_db(), _Emb(), job)
    assert job.status in {"cancelled", "success"}


# --- finished background jobs (asked for in use) -----------------------------
#
# The tasks screen listed only what was *running*, on the reasoning that a
# finished job is not a task. That is tidy and it hides the one case anyone
# cares about: a job that FAILS disappears at the moment it becomes
# interesting, leaving exactly the same empty list as one that succeeded.


def test_the_tasks_endpoint_reports_history_as_well(ai_client):
    from memorymap.core import taskhistory

    taskhistory.clear()
    taskhistory.record("reindex", "Re-indexing your notes", "failed", "disk full")
    body = ai_client.get("/tasks").json()
    assert "tasks" in body and "history" in body
    assert body["history"][0]["outcome"] == "failed"
    assert body["history"][0]["detail"] == "disk full"


def test_a_failure_keeps_its_reason(ai_client):
    """The reason used to exist only in the log console, a different screen
    that you have to know to look at."""
    from memorymap.core import taskhistory

    taskhistory.clear()
    taskhistory.record("pull", "Downloading llama3.2", "failed", "connection refused")
    assert "connection refused" in ai_client.get("/tasks").json()["history"][0]["detail"]


def test_the_newest_ending_comes_first(ai_client):
    from memorymap.core import taskhistory

    taskhistory.clear()
    taskhistory.record("pull", "first", "completed")
    taskhistory.record("pull", "second", "completed")
    assert [h["label"] for h in ai_client.get("/tasks").json()["history"]] == [
        "second",
        "first",
    ]


def test_cancelling_is_not_recorded_as_a_failure():
    """A user stopping something is not an error, and reporting it in red is
    how people learn to ignore red."""
    from memorymap.core import taskhistory

    taskhistory.clear()
    taskhistory.record("reindex", "Re-indexing", "cancelled")
    assert taskhistory.recent()[0]["outcome"] == "cancelled"


def test_the_history_cannot_grow_without_limit():
    """In memory, so it needs a hard bound, a machine that re-indexes on a
    loop must not be able to grow this forever."""
    from memorymap.core import taskhistory

    taskhistory.clear()
    for i in range(taskhistory.MAX_ENTRIES + 25):
        taskhistory.record("pull", f"job {i}", "completed")
    assert len(taskhistory.recent()) == taskhistory.MAX_ENTRIES


def test_an_unknown_outcome_does_not_become_a_scary_one():
    from memorymap.core import taskhistory

    taskhistory.clear()
    taskhistory.record("pull", "odd", "exploded")
    assert taskhistory.recent()[0]["outcome"] == "completed"


def test_recording_never_raises():
    """Called from worker threads at the moment a job ends. It must not be
    able to turn a finished job into a crashed one."""
    from memorymap.core import taskhistory

    taskhistory.record(None, None, None, None)  # type: ignore[arg-type]


def test_the_history_can_be_cleared(ai_client):
    from memorymap.core import taskhistory

    taskhistory.record("pull", "something", "completed")
    assert ai_client.post("/tasks/history/clear").json()["cleared"] is True
    assert ai_client.get("/tasks").json()["history"] == []


def test_quitting_is_a_post_not_a_get(ai_client):
    """A GET would be reachable from a link in another tab, and "the app quit
    when I clicked something" is a bug report nobody enjoys writing."""
    assert ai_client.get("/shutdown").status_code in (404, 405)
