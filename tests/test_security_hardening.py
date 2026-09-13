"""The behaviours behind the CodeQL alert list, pinned as tests.

Each of these guards a property that is invisible in normal use and therefore
easy to lose in a refactor: a value that reaches a log unescaped, an exception
whose text escapes to a caller, an address checked once and connected to twice.
"""

from __future__ import annotations

import logging

import pytest

from memorymap.core import logbuffer
from memorymap.search import websearch


# --- log injection ---------------------------------------------------------


def test_a_logged_value_cannot_forge_a_second_line():
    forged = "hello\nERROR:root:your notes were deleted"
    cleaned = logbuffer.safe_value(forged)
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    # The text survives: it is flattened, not thrown away.
    assert "your notes were deleted" in cleaned


def test_carriage_returns_and_control_characters_go_too():
    """A lone \\r rewrites the current line in a terminal, which is the same
    forgery by another route."""
    cleaned = logbuffer.safe_value("a\r\nb\rc\x1b[31md\x00e")
    assert "\r" not in cleaned and "\n" not in cleaned and "\x1b" not in cleaned
    assert "\x00" not in cleaned


def test_a_very_long_value_is_capped():
    """A 500-record ring buffer is emptied by one long enough message."""
    assert len(logbuffer.safe_value("x" * 10_000, 80)) <= 80


def test_the_chat_route_sanitises_the_question_it_logs(ai_client, caplog):
    """The question is the user's own text and it reaches the terminal."""
    with caplog.at_level(logging.INFO, logger="memorymap.chat"):
        ai_client.post("/chat", json={"question": "one\ntwo\nthree"})
    logged = [r for r in caplog.records if r.name == "memorymap.chat"]
    assert logged, "the chat route should log the search it ran"
    assert "\n" not in logged[-1].getMessage()


# --- exception text that must not escape ------------------------------------


def test_a_tool_explains_the_failures_it_anticipates(session, app_state):
    """ToolError text is written for a reader, so it is passed straight on."""
    from memorymap.ai import tools

    result = tools.execute_tool(session, "get_note", {"note_id": 999999})
    assert "No note with id 999999" in result["error"]


def test_an_unexpected_exception_does_not_leak_its_text(session, app_state, caplog):
    """A bare ValueError from inside a handler is an internal detail, the
    caller gets the shape of the problem, the log gets the rest."""
    from memorymap.ai import tools

    with caplog.at_level(logging.WARNING, logger="memorymap.tools"):
        result = tools.execute_tool(session, "get_note", {"note_id": "not-a-number"})

    assert "invalid literal" not in result["error"]
    assert "int()" not in result["error"]
    assert "Re-read the tool's schema" in result["error"]
    # …and it is not simply discarded.
    assert any(r.name == "memorymap.tools" for r in caplog.records)


def test_the_confirm_endpoint_reports_a_tool_failure_without_a_traceback(client):
    """POST /chat/tools/execute turns a tool error into a 400. Its detail is
    shown to the user, so it must never carry internals."""
    response = client.post(
        "/chat/tools/execute",
        json={"name": "get_note", "arguments": {"note_id": "not-a-number"}},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "invalid literal" not in detail


# --- SearXNG: the address that is checked is the address that is used --------


def test_the_checked_address_is_the_one_connected_to():
    """Resolving to check and resolving again to connect leaves a DNS
    rebinding window between the two. The URL handed to requests is the
    address that passed."""
    target = websearch._searxng_target("http://localhost:8888")
    assert target is not None
    url, headers = target
    # An IP literal, never the name.
    assert "localhost" not in url
    # …and the name is preserved where TLS and vhosts need it.
    assert headers["Host"] == "localhost:8888"


@pytest.mark.parametrize(
    "address",
    [
        "https://searx.example.com",  # public
        "ftp://127.0.0.1:8888",  # not http(s)
        "http://127.0.0.1@93.184.216.34/",  # credentials disguise the host
        "http://127.0.0.1:99999",  # impossible port
        "http://127.0.0.1:notaport",  # unparseable port
        "not-a-url",
        "",
    ],
)
def test_an_unusable_searxng_address_is_refused(address):
    assert websearch._searxng_target(address) is None


def test_the_search_path_refuses_the_same_addresses_as_the_probe():
    """The two used to check separately, and the search path's version was the
    looser of the two."""
    assert websearch.probe_searxng("https://searx.example.com") is False
    with pytest.raises(websearch.WebSearchError):
        websearch._search_searxng("anything", 5, "https://searx.example.com")


# --- import graph -----------------------------------------------------------


def test_the_embedding_modules_do_not_import_each_other_in_a_circle():
    """`ai.embeddings` → `ai.model_manager` is one-way, and `core.deps` is not
    imported back from either. A cycle here is currently only survivable
    because of a deferred import, which is a workaround, not a shape."""
    import ast
    import pathlib

    def module_level_imports(path: str) -> set[str]:
        tree = ast.parse(pathlib.Path(path).read_text())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
            elif isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
        return found

    model_manager_imports = module_level_imports("src/memorymap/ai/model_manager.py")
    assert "memorymap.ai.embeddings" not in model_manager_imports

    embeddings_imports = module_level_imports("src/memorymap/ai/embeddings.py")
    assert not any(name.startswith("memorymap.core.deps") for name in embeddings_imports)


# --- security scanner findings (§41) -----------------------------------------


def test_removing_a_model_never_returns_the_filesystem_path(app_state, monkeypatch):
    """CodeQL `py/stack-trace-exposure` at routes_settings.py:473.

    `embedmodels.remove` returned `f"...: {exc}"` for an OSError, and that
    string goes straight to the browser as the API response. An OSError's text
    carries the full path it failed on, so a failed delete published where the
    model cache lives. The detail belongs in the log, where only the owner of
    the machine reads it.
    """
    import shutil

    from memorymap.core import embedmodels

    model = next(iter(embedmodels.EMBED_MODELS_BY_ID.values()))
    path = embedmodels._model_dir(model)
    path.mkdir(parents=True, exist_ok=True)

    secret = str(path)

    def explode(*args, **kwargs):
        raise OSError(f"Permission denied: {secret}/blobs/deadbeef")

    monkeypatch.setattr(shutil, "rmtree", explode)
    removed, message = embedmodels.remove(model.id)

    assert removed is False
    assert secret not in message
    assert "deadbeef" not in message


def test_cryptography_is_pinned_past_the_two_advisories():
    """<= 48.0.0 has an exponential path-building DoS and a wildcard-SAN
    escape from an intermediate's permittedSubtrees. Neither is reachable from
    this app, nothing here builds or verifies an X.509 chain, but the floor
    is free, and Dependabot was blocked by *our own* ceiling rather than by a
    real conflict, which is the part worth pinning so it cannot recur.
    """
    import re
    from pathlib import Path

    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    spec = re.search(r"^cryptography([^\n]*)$", requirements, re.M)
    assert spec, "cryptography is no longer in requirements.txt"
    floor = re.search(r">=(\d+)", spec.group(1))
    assert floor and int(floor.group(1)) >= 49, spec.group(0)
