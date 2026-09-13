"""Shared test fixtures.

Every test gets a throwaway data directory so nothing ever touches a
real database, and singletons are rebuilt between tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memorymap.ai import model_manager
from memorymap.core import deps, taskhistory


@pytest.fixture()
def app_state(tmp_path, monkeypatch):
    """Fresh singletons pointed at a temp dir. Yields the ConfigManager."""
    # Make sure a developer's real .env can't leak into tests.
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path / "data"))
    deps.reset_app_state()
    model_manager.reset_jobs()
    # Process-global like the log buffer, so it leaks between tests exactly the
    # way the job registry does, and a test asserting "no jobs have finished"
    # would otherwise pass or fail on what ran before it.
    taskhistory.clear()
    deps.init_app_state(data_dir=tmp_path / "data")
    yield deps.get_config()
    deps.reset_app_state()
    model_manager.reset_jobs()
    taskhistory.clear()


@pytest.fixture()
def session(app_state):
    s = deps.get_db().session()
    yield s
    s.close()


@pytest.fixture()
def client(app_state):
    """TestClient with ALL AI unavailable, proves capture and keyword
    search work with zero AI, and keeps results identical whether or not
    the developer happens to have Ollama running."""
    from memorymap.api.app import create_app
    from tests.fakes import FakeEmbeddingService, FakeOllama

    deps.override_ai(
        ollama=FakeOllama(running=False),
        embeddings=FakeEmbeddingService(available=False),
    )
    return TestClient(create_app())


@pytest.fixture()
def fake_ollama(app_state):
    from tests.fakes import FakeOllama

    fake = FakeOllama(running=True)
    deps.override_ai(ollama=fake)
    return fake


@pytest.fixture()
def fake_embeddings(app_state):
    from tests.fakes import FakeEmbeddingService

    fake = FakeEmbeddingService(available=True)
    deps.override_ai(embeddings=fake)
    return fake


@pytest.fixture()
def ai_client(app_state, fake_ollama, fake_embeddings):
    """TestClient with working (fake) AI: full Phase 2 behaviour."""
    from memorymap.api.app import create_app

    return TestClient(create_app())


# --- a fake OpenAI-compatible transport (§6) ---------------------------------
#
# The fixtures live here so pytest finds them by name; `FakeResponse` and `sse`
# are ordinary helpers and live in `fakes_http.py`, because importing a *test*
# module to get them re-binds everything else that import carries, which is
# how `client` from `test_providers` came to shadow the `client` fixture above
# and silently decide which HTTP client three files' tests were handed.


@pytest.fixture
def capture_post(monkeypatch):
    """Swap `requests.post` inside the OpenAI client and record the payloads."""
    from fakes_http import FakeResponse

    sent: list[dict] = []
    queued: list = []

    def fake_post(url, json=None, headers=None, stream=False, timeout=None):
        sent.append({"url": url, "json": json})
        return queued.pop(0) if queued else FakeResponse(payload={})

    monkeypatch.setattr("memorymap.ai.openai_client.requests.post", fake_post)
    return type("Capture", (), {"sent": sent, "queue": queued})()


@pytest.fixture
def openai_client():
    """An `OpenAICompatClient` that can never reach the network."""
    from memorymap.ai.openai_client import OpenAICompatClient

    c = OpenAICompatClient(base_url="http://localhost:1234/v1")
    c._catalog = []
    c._context_lengths = {"m": 8192}
    return c


# --- no test may run pip ------------------------------------------------------
#
# The suite once installed torch. `EmbeddingService` auto-installs the
# "semantic" extra when the sentence-transformers backend is selected and the
# import fails, and one test reached that path with a real thread: the full
# run then carried a live `pip install sentence-transformers` for twenty
# minutes, `/debug/health` reported it as a running job (which failed
# test_debug_health), and the sandbox venv grew by 700 MB of packages
# CLAUDE.md says never to install. Every test that means to exercise the
# installer already fakes `extras.subprocess.Popen` itself (a monkeypatch
# inside the test overrides this one); everything else gets a Popen that
# refuses, so an accidental install is a loud failure instead of a silent
# download.


@pytest.fixture(autouse=True)
def _no_test_runs_pip(monkeypatch):
    from memorymap.core import extras

    # `extras.subprocess` is the one shared `subprocess` module, so a blanket
    # refusal broke every other Popen in the process: `platform.platform()`
    # runs `file` through it, and the support bundle test failed in isolation
    # while passing in the full run only because an earlier test had filled
    # platform's cache. Refuse pip; let everything else through.
    real_popen = extras.subprocess.Popen

    def guard(args, *rest, **kwargs):
        argv = args if isinstance(args, (list, tuple)) else [args]
        if any("pip" in str(part) for part in argv):
            raise RuntimeError(
                "a test reached the real installer; fake extras.subprocess.Popen "
                "or extras.start in the test (see conftest._no_test_runs_pip)"
            )
        return real_popen(args, *rest, **kwargs)

    monkeypatch.setattr(extras.subprocess, "Popen", guard)
    yield


# --- Brief 13: the harness fixtures (tests/test_harness_verifier_spec.py) -----
#
# Both are `FakeOllama` with a script, and both stand in for a *reported* small
# model behaviour rather than for a model in general:
#
# - `fake_model_with_paged_list` fetches one page and stops, which is the
#   behaviour CHAT_PLAN decision 10 is about. The run's paging nudge is what
#   gets it to page two, and the point of the spec is that the app does the
#   nudging rather than hoping.
# - `fake_model_that_loops` calls the same tool for ever, which is the shape
#   the run budget exists to bound.
#
# Neither says anything about what a real small model does with either prompt:
# every provider test here runs against a fake transport (CLAUDE.md section 4).


@pytest.fixture()
def fake_model_with_paged_list(app_state, fake_embeddings):
    """Pages `list_notes` twenty at a time, one page per turn, then reads one
    note and answers."""
    from tests.fakes import FakeOllama

    fake = FakeOllama(running=True)
    script: list[list[dict]] = []
    for page in range(4):
        script.append(
            [{"name": "list_notes", "arguments": {"offset": page * 20, "limit": 20}}]
        )
        script.append([])  # the round that answers, ending the turn
    script.append([{"name": "get_note", "arguments": {"note_id": 1}}])
    script.append([])
    fake.tool_script = script
    deps.override_ai(ollama=fake)
    return fake


@pytest.fixture()
def fake_model_that_loops(app_state, fake_embeddings):
    """Calls one tool for ever, and reports a thousand tokens a round.

    The token figures are the fixture's own, not a measurement: they are
    chosen so the budget in the spec (2,000 tokens) is reached in two rounds
    and the test is about the enforcement rather than about arithmetic.
    """
    from tests.fakes import FakeOllama

    fake = FakeOllama(running=True)
    fake.tool_script = [
        [{"name": "notebook_overview", "arguments": {}}] for _ in range(40)
    ]
    fake.stats = {**fake.stats, "prompt_tokens": 600, "output_tokens": 400}
    deps.override_ai(ollama=fake)
    return fake
