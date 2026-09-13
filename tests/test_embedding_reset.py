"""Switching search engine clears a cached embedding failure immediately."""

from __future__ import annotations

import time

from memorymap.core import deps, extras


def test_reset_failure_state_clears_cached_error(app_state):
    service = deps.get_embeddings()  # the real EmbeddingService (no fakes)
    service.last_error = "OSError: torch_xpu.dll could not be found"
    service._load_failed_at = 123.0

    service.reset_failure_state()

    assert service.last_error is None
    assert service._load_failed_at is None


def test_switch_backend_clears_stale_error(ai_client):
    # A stale failure from a previous backend must not survive the switch.
    deps.get_embeddings().last_error = "stale torch error"
    response = ai_client.post(
        "/models/embedding-backend",
        json={"backend": "sentence-transformers", "model": None},
    )
    assert response.status_code == 200
    assert deps.get_embeddings().last_error is None


# --- auto-installing a genuinely missing sentence-transformers -------------


def test_a_missing_package_triggers_extras_start_once(app_state, monkeypatch):
    """`_load_st_model` is mocked to raise the exact failure this sandbox
    produces naturally when sentence-transformers isn't installed (CLAUDE.md's
    own instruction): mocked explicitly, not left to the ambient
    environment, since CI's own workflow installs the full requirements.txt
    including the real package, where the natural failure never happens and
    this test silently stopped testing anything (reported: CI passed
    `embed_text` for real, downloading the model from Hugging Face, so
    `extras.start` was never called at all). `extras.start` is also mocked
    so this stays a unit test, not a network call either way."""
    service = deps.get_embeddings()
    monkeypatch.setattr(
        service,
        "_load_st_model",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'sentence_transformers'")),
    )
    calls = []
    monkeypatch.setattr(
        extras, "start", lambda extra_id, reinstall=False: (calls.append(extra_id) or (False, "mocked"))
    )

    service.embed_text("something to embed")
    service.embed_text("something else")  # a second failure must not retrigger

    assert calls == ["semantic"]


def test_a_different_failure_never_triggers_an_install(app_state, monkeypatch):
    """Only a genuine "the package isn't there" error is worth reinstalling
    over: a different failure (corrupted install, OOM, a real bug) retrying
    the exact same pip install would do nothing but waste time and hide the
    real problem."""
    service = deps.get_embeddings()
    monkeypatch.setattr(
        service, "_load_st_model", lambda: (_ for _ in ()).throw(RuntimeError("out of memory"))
    )
    started = []
    monkeypatch.setattr(extras, "start", lambda extra_id, reinstall=False: (started.append(1), (False, ""))[1])

    service.embed_text("something to embed")

    assert not started


def test_auto_install_does_nothing_when_extras_refuses_to_start(app_state, monkeypatch):
    """Already running, already installed (a different, real failure), or
    genuinely unavailable: extras.start says so via its own return value,
    and this must not crash or loop on any of those, just accept it.

    `_load_st_model` mocked explicitly: see the sibling test above for why
    relying on the ambient environment (no sentence-transformers installed)
    silently stopped exercising this on CI, where the real package is
    present."""
    service = deps.get_embeddings()
    monkeypatch.setattr(
        service,
        "_load_st_model",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'sentence_transformers'")),
    )
    monkeypatch.setattr(extras, "start", lambda extra_id, reinstall=False: (False, "Already installed."))

    service.embed_text("something to embed")  # must not raise

    assert service._auto_install_attempted is True


def test_auto_install_retries_the_load_once_the_background_install_finishes(
    app_state, monkeypatch
):
    """End to end, without a real pip: extras.start is mocked to report a
    completed install almost immediately, and the service's own watcher
    thread is what's under test: it has to notice completion and clear the
    cached failure so the *next* embed attempt actually retries, without the
    caller having to do anything.

    `_load_st_model` mocked explicitly: see the first test above in this
    file for why relying on the ambient environment (no sentence-
    transformers installed) silently stopped exercising this on CI, where
    the real package is present and the load just succeeds instead of
    raising."""
    service = deps.get_embeddings()
    monkeypatch.setattr(
        service,
        "_load_st_model",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'sentence_transformers'")),
    )
    fake_state = extras.InstallState(running=True, extra_id="semantic")
    monkeypatch.setattr(extras, "current", lambda: fake_state)
    monkeypatch.setattr(extras, "start", lambda extra_id, reinstall=False: (True, "Installing."))

    service.embed_text("something to embed")
    assert service.last_error is not None  # the original failure, recorded as usual

    # Simulate the background pip install finishing successfully.
    fake_state.running = False
    fake_state.outcome = "completed"

    deadline = time.time() + 3
    while service._load_failed_at is not None and time.time() < deadline:
        time.sleep(0.05)

    assert service._load_failed_at is None, "the watcher never cleared the retry cooldown"
