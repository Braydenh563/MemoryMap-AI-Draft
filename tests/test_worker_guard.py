"""Refusing to start under more than one worker.

Every singleton silently becomes per-worker: the log console would show a
fraction of what happened, unlocking would work only sometimes, and two
workers would each think they own the SearXNG they started. None of that
fails loudly, which is why a second worker is refused rather than warned
about: see `deps.refuse_multiple_workers`.
"""

from __future__ import annotations

import pytest

from memorymap.core import deps


@pytest.fixture()
def _no_worker_flags(monkeypatch):
    monkeypatch.setattr("sys.argv", ["uvicorn"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def test_a_normal_start_is_not_refused(_no_worker_flags):
    deps.refuse_multiple_workers()  # must not raise


@pytest.mark.parametrize(
    "argv",
    [
        ["uvicorn", "--workers", "2"],
        ["uvicorn", "--workers=4"],
        ["uvicorn", "-w", "3"],
    ],
)
def test_more_than_one_worker_is_refused(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with pytest.raises(deps.MultipleWorkersError) as raised:
        deps.refuse_multiple_workers()
    assert "single-user" in str(raised.value)


def test_one_worker_asked_for_explicitly_is_fine(monkeypatch):
    monkeypatch.setattr("sys.argv", ["uvicorn", "--workers", "1"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    deps.refuse_multiple_workers()


def test_the_environment_variable_is_honoured_too(monkeypatch):
    """WEB_CONCURRENCY is what uvicorn and gunicorn both read, and it is how a
    platform turns workers up without touching the command line."""
    monkeypatch.setattr("sys.argv", ["uvicorn"])
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    with pytest.raises(deps.MultipleWorkersError):
        deps.refuse_multiple_workers()


def test_a_nonsense_worker_count_does_not_stop_the_app(monkeypatch):
    """Refusing to start is a big hammer; it should only fall on a value that
    actually says "more than one"."""
    monkeypatch.setattr("sys.argv", ["uvicorn", "--workers", "lots"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    deps.refuse_multiple_workers()


def test_the_check_actually_runs_when_the_app_is_built(app_state, monkeypatch):
    """The tests above call the check directly, which proves it works and not
    that anything calls it, removing the one line from create_app left every
    one of them green. This is the test that notices.

    It must also run BEFORE any singleton is built, since those are the things
    a second worker would duplicate.
    """
    from memorymap.api import app as app_module

    monkeypatch.setattr("sys.argv", ["uvicorn", "--workers", "2"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with pytest.raises(deps.MultipleWorkersError):
        app_module.create_app()
