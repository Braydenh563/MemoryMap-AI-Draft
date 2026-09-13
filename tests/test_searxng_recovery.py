"""Getting SearXNG unstuck without deleting folders by hand.

Reported directly: "I can't get my searxng to work, is there a way I can
reinstall it or make sure it is on the right port?" There was not: a
part-finished install looked installed and died on start, and the only advice
a failed start could give was "check the port isn't in use", which assumes the
person can check.
"""

from __future__ import annotations

import socket

import pytest

from memorymap.search import searxng_manager


# --- the port question, answered --------------------------------------------


def test_a_free_port_is_reported_as_free():
    report = searxng_manager.port_report()
    assert report["port"] == searxng_manager.HOST_PORT
    assert report["free"] is True
    assert report["held_by_searxng"] is False
    assert str(searxng_manager.HOST_PORT) in report["detail"]


def test_a_port_held_by_something_else_is_named_as_the_problem(monkeypatch):
    """Three states, and only this one is the user's to go and solve."""
    monkeypatch.setattr(searxng_manager.websearch, "probe_searxng", lambda url: False)
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", searxng_manager.HOST_PORT))
        holder.listen(1)
        report = searxng_manager.port_report()
    finally:
        holder.close()

    assert report["free"] is False
    assert report["held_by_searxng"] is False
    assert "isn't answering as SearXNG" in report["detail"]


def test_a_port_held_by_a_working_searxng_is_not_a_problem(monkeypatch):
    """Someone else's instance on the same port is a reason to use it, not an
    error to report."""
    monkeypatch.setattr(searxng_manager.websearch, "probe_searxng", lambda url: True)
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", searxng_manager.HOST_PORT))
        holder.listen(1)
        report = searxng_manager.port_report()
    finally:
        holder.close()

    assert report["free"] is False
    assert report["held_by_searxng"] is True
    assert "can use it as it is" in report["detail"]


def test_the_status_endpoint_carries_the_port_answer(client):
    body = client.get("/websearch/searxng/status").json()
    assert body["port"]["port"] == searxng_manager.HOST_PORT
    assert "free" in body["port"]


# --- getting back to a clean install ----------------------------------------


def _fake_install(data_dir):
    """A venv and checkout that look installed, as a broken one does."""
    venv = searxng_manager._venv_dir(data_dir)
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    (venv / "bin" / "python").write_text("#!/bin/sh\n")
    src = searxng_manager._source_dir(data_dir)
    src.mkdir(parents=True, exist_ok=True)
    (src / "setup.py").write_text("")
    searxng_manager._pid_file(data_dir).write_text('{"pid": 999999}')
    searxng_manager.log_path(data_dir).write_text("ImportError: no module named searx\n")


def test_uninstall_removes_the_install_but_keeps_your_settings(app_state):
    data_dir = app_state.data_dir
    searxng_manager.ensure_settings(data_dir)
    _fake_install(data_dir)

    result = searxng_manager.uninstall_source(data_dir)

    assert not searxng_manager._venv_dir(data_dir).exists()
    assert not searxng_manager._source_dir(data_dir).exists()
    assert not searxng_manager._pid_file(data_dir).exists()
    assert sorted(result["removed"]) == ["src", "venv"]
    # The settings file holds the instance's secret key and any edits, it is
    # not what breaks, and regenerating it would change the key for nothing.
    assert searxng_manager.settings_path(data_dir).exists()


def test_uninstalling_when_nothing_is_installed_is_not_an_error(app_state):
    assert searxng_manager.uninstall_source(app_state.data_dir)["removed"] == []


def test_reinstall_refuses_while_an_install_is_already_running(app_state, monkeypatch):
    monkeypatch.setitem(searxng_manager._install_state, "running", True)
    with pytest.raises(searxng_manager.SearxngError, match="already running"):
        searxng_manager.reinstall_source(app_state.data_dir)


def test_the_reinstall_endpoint_wipes_and_restarts(client, monkeypatch, app_state):
    started = {}
    monkeypatch.setattr(
        searxng_manager,
        "install_source",
        lambda d, on_ready=None: started.setdefault("dir", d),
    )
    _fake_install(app_state.data_dir)
    client.put("/preferences", json={"searxng_url": "http://localhost:8888"})

    response = client.post("/websearch/searxng/reinstall")

    assert response.status_code == 200
    assert response.json()["installing"] is True
    assert started["dir"] == app_state.data_dir
    # Web search must not keep pointing at an instance that no longer exists.
    assert client.get("/preferences").json()["searxng_url"] == ""


# --- a failed start now says what happened ----------------------------------


def test_a_failed_start_quotes_what_searxng_said(app_state, monkeypatch):
    """The whole point of capturing stdout: the message used to be a guess,
    and it guessed the same thing every time."""
    data_dir = app_state.data_dir
    monkeypatch.setattr(searxng_manager, "source_installed", lambda d: True)
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "_source_state", lambda d: "stopped")
    monkeypatch.setattr(searxng_manager, "_wait_until_ready", lambda *a, **k: False)
    monkeypatch.setattr(searxng_manager, "_stop_source", lambda d: {"stopped": True})

    def fake_start(d):
        searxng_manager.log_path(d).parent.mkdir(parents=True, exist_ok=True)
        searxng_manager.log_path(d).write_text(
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named 'searx.webapp'\n"
        )
        return {"url": searxng_manager.BASE_URL, "started": True, "backend": "source"}

    monkeypatch.setattr(searxng_manager, "_start_source", fake_start)

    with pytest.raises(searxng_manager.SearxngError) as caught:
        searxng_manager._start_from_source(data_dir)

    assert "No module named 'searx.webapp'" in str(caught.value)


def test_a_start_that_says_nothing_at_all_says_so(app_state, monkeypatch):
    """Silence is itself a diagnosis, the process died before writing."""
    monkeypatch.setattr(searxng_manager, "source_installed", lambda d: True)
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "_source_state", lambda d: "stopped")
    monkeypatch.setattr(searxng_manager, "_wait_until_ready", lambda *a, **k: False)
    monkeypatch.setattr(searxng_manager, "_stop_source", lambda d: {"stopped": True})
    monkeypatch.setattr(
        searxng_manager,
        "_start_source",
        lambda d: {"url": searxng_manager.BASE_URL, "started": True, "backend": "source"},
    )

    with pytest.raises(searxng_manager.SearxngError, match="wrote nothing"):
        searxng_manager._start_from_source(app_state.data_dir)


# --- a taken port is walked past, not handed to the user --------------------


_WINDOWS_PORT_CLASH = (
    "OSError: [WinError 10048] Only one usage of each socket address "
    "(protocol/network address/port) is normally permitted"
)


def _start_that_fails_on_taken_ports(monkeypatch, ready_answers):
    """A start where SearXNG dies with a bind error until an attempt is
    allowed to succeed. Returns the list of ports each attempt used."""
    monkeypatch.setattr(searxng_manager, "_chosen_port", None)
    monkeypatch.setattr(searxng_manager, "source_installed", lambda d: True)
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "_source_state", lambda d: "stopped")
    monkeypatch.setattr(searxng_manager, "_stop_source", lambda d: {"stopped": True})
    monkeypatch.setattr(
        searxng_manager, "recent_output", lambda d, lines=12: _WINDOWS_PORT_CLASH
    )
    answers = iter(ready_answers)
    monkeypatch.setattr(
        searxng_manager, "_wait_until_ready", lambda *a, **k: next(answers)
    )

    ports: list[int] = []

    def fake_start(d):
        ports.append(searxng_manager.host_port())
        return {
            "url": searxng_manager.base_url(),
            "started": True,
            "backend": "source",
        }

    monkeypatch.setattr(searxng_manager, "_start_source", fake_start)
    return ports


def test_a_taken_port_moves_to_the_next_until_one_works(app_state, monkeypatch):
    """choose_port() checks before the start, but checking is racy, the
    honest signal is SearXNG itself dying with a bind error, and the fix is
    to move along automatically, not to report a port number."""
    ports = _start_that_fails_on_taken_ports(monkeypatch, [False, False, True])

    result = searxng_manager._start_from_source(app_state.data_dir)

    assert ports == [8888, 8080, 8081]
    assert result["url"].endswith(":8081")


def test_every_port_taken_names_them_all_and_the_way_out(app_state, monkeypatch):
    ports = _start_that_fails_on_taken_ports(monkeypatch, [False] * 5)

    with pytest.raises(searxng_manager.SearxngError) as caught:
        searxng_manager._start_from_source(app_state.data_dir)

    assert ports == [8888, *searxng_manager.FALLBACK_PORTS]
    assert "Every port" in str(caught.value)
    assert "8899" in str(caught.value)
    assert "MEMORYMAP_SEARXNG_PORT" in str(caught.value)


# --- the reason a command failed, not the last thing it printed -------------


class _Result:
    def __init__(self, stderr="", stdout=""):
        self.stderr = stderr
        self.stdout = stdout


def test_pips_upgrade_notice_is_never_reported_as_the_failure():
    """Reported with a screenshot: "Couldn't install SearXNG: [notice] To
    update, run: …pip install --upgrade pip". pip prints that on almost every
    run and it is always last, so the last line was the wrong line to take, 
    and it sent people off to fix pip, which was never the problem."""
    result = _Result(
        stdout=(
            "Collecting searxng\n"
            "ERROR: Could not find a version that satisfies the requirement searxng\n"
            "\n"
            "[notice] A new release of pip is available: 24.0 -> 25.2\n"
            "[notice] To update, run: python.exe -m pip install --upgrade pip\n"
        )
    )
    message = searxng_manager._reason(result, "Couldn't install SearXNG")
    assert "upgrade pip" not in message
    assert "Could not find a version" in message


def test_the_error_line_beats_the_hints_printed_after_it():
    result = _Result(stderr="ERROR: no space left on device\nhint: free some up\n")
    assert "no space left" in searxng_manager._reason(result, "Couldn't install")


def test_a_command_that_said_nothing_useful_gets_no_invented_reason():
    assert searxng_manager._reason(_Result(), "Couldn't install") == "Couldn't install"
    noise = _Result(stdout="[notice] To update, run: pip install --upgrade pip")
    assert searxng_manager._reason(noise, "Couldn't install") == "Couldn't install"


def test_a_configured_port_is_used_instead_of_the_default(monkeypatch):
    """"Is there a way to change the port if it is full?? maybe like 8080."" """
    monkeypatch.setattr(searxng_manager, "_chosen_port", None)
    monkeypatch.setenv("MEMORYMAP_SEARXNG_PORT", "8080")
    assert searxng_manager.host_port() == 8080
    # An IP literal, never localhost: the probe must dial the exact address
    # SearXNG binds (SEARXNG_BIND_ADDRESS=127.0.0.1). On Windows, localhost
    # can resolve to IPv6 ::1 first, a door the instance is not behind.
    assert searxng_manager.base_url() == "http://127.0.0.1:8080"


def test_nonsense_in_the_port_variable_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setattr(searxng_manager, "_chosen_port", None)
    for junk in ("", "eight", "0", "99999", "8080; rm -rf /"):
        monkeypatch.setenv("MEMORYMAP_SEARXNG_PORT", junk)
        assert searxng_manager.host_port() == searxng_manager.DEFAULT_PORT, junk


def test_a_taken_port_moves_along_instead_of_failing(monkeypatch):
    """The old advice was "close whatever has it", which assumes you can."""
    monkeypatch.setattr(searxng_manager, "_chosen_port", None)
    monkeypatch.delenv("MEMORYMAP_SEARXNG_PORT", raising=False)
    monkeypatch.setattr(searxng_manager.websearch, "probe_searxng", lambda url: False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", searxng_manager.DEFAULT_PORT))
        holder.listen(1)
        chosen = searxng_manager.choose_port()
    assert chosen != searxng_manager.DEFAULT_PORT
    assert chosen in searxng_manager.FALLBACK_PORTS
    # And it sticks, so the started instance stays findable.
    assert searxng_manager.host_port() == chosen


def test_a_searxng_already_answering_wins_over_a_free_port(monkeypatch):
    """Ours, from a previous run. Taking a different port would start a
    second copy beside it."""
    monkeypatch.setattr(searxng_manager, "_chosen_port", None)
    monkeypatch.delenv("MEMORYMAP_SEARXNG_PORT", raising=False)
    monkeypatch.setattr(
        searxng_manager.websearch,
        "probe_searxng",
        lambda url: url.endswith(str(searxng_manager.DEFAULT_PORT)),
    )
    monkeypatch.setattr(searxng_manager, "_port_free", lambda port: True)
    assert searxng_manager.choose_port() == searxng_manager.DEFAULT_PORT


# --- which backend is available: Docker, source, or neither -------------------


def test_searxng_status_without_docker_falls_back_to_source(client, monkeypatch):
    """No Docker isn't a dead end, SearXNG also runs from a virtualenv."""
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: True)
    body = client.get("/websearch/searxng/status").json()
    assert body["docker"] is False
    assert body["source"] is True
    assert body["backend"] == "source"


def test_searxng_installs_without_docker_or_git(client, monkeypatch):
    """Neither Docker nor git is a dead end any more.

    This is what "I can't download searxng" meant: `source_available` required
    the git binary, so a machine with neither Docker nor git was offered an
    install button that could never work. pip fetches a source tarball over
    HTTPS on its own, so Python and a network connection are the only real
    requirements.
    """
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "docker_installed", lambda: False)
    body = client.get("/websearch/searxng/status").json()
    assert body["source"] is True
    assert body["backend"] == "source"


def test_searxng_status_with_no_backend_at_all(client, monkeypatch):
    """Only reachable if source installs are disabled outright."""
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "docker_installed", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: False)
    body = client.get("/websearch/searxng/status").json()
    assert body["backend"] is None
    assert "run yourself" in body["detail"]


def test_docker_installed_but_not_running_is_not_treated_as_available(client, monkeypatch):
    """The reported failure: Docker Desktop installed but never started.

    Only checking that the binary exists made the app choose the Docker
    backend, fail to reach the daemon, and never consider the from-source
    backend that would have worked.
    """
    monkeypatch.setattr(searxng_manager, "docker_installed", lambda: True)
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: True)

    body = client.get("/websearch/searxng/status").json()
    assert body["backend"] == "source"  # fell through instead of failing
    assert "not running" in body["detail"]


def test_docker_installed_but_stopped_and_no_git_says_which_problem(client, monkeypatch):
    """"Docker isn't installed" and "Docker isn't started" need different fixes."""
    monkeypatch.setattr(searxng_manager, "docker_installed", lambda: True)
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: False)

    detail = client.get("/websearch/searxng/status").json()["detail"]
    assert "daemon isn't running" in detail
    assert "Docker Desktop" in detail


def test_docker_availability_checks_the_daemon_not_just_the_binary(monkeypatch):
    monkeypatch.setattr(searxng_manager.shutil, "which", lambda name: "/usr/bin/docker")

    class Failed:
        returncode = 1

    monkeypatch.setattr(searxng_manager.subprocess, "run", lambda *a, **k: Failed())
    assert searxng_manager.docker_installed() is True
    assert searxng_manager.docker_available() is False


# --- starting and stopping through the HTTP API --------------------------------


def test_searxng_start_without_any_backend_is_a_clear_503(client, monkeypatch):
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: False)
    response = client.post("/websearch/searxng/start")
    assert response.status_code == 503
    assert "run yourself" in response.json()["detail"]


def test_searxng_start_from_source_installs_first(client, monkeypatch):
    """The first Start kicks off the install and says so, rather than hanging."""
    calls = []
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: True)
    monkeypatch.setattr(searxng_manager, "source_installed", lambda data_dir: False)
    monkeypatch.setattr(
        searxng_manager,
        "install_source",
        lambda data_dir, on_ready=None: calls.append(data_dir),
    )

    response = client.post("/websearch/searxng/start")
    assert response.status_code == 503
    assert "few minutes" in response.json()["detail"]
    assert len(calls) == 1  # the install really was kicked off


def test_searxng_start_from_source_spawns_the_process(client, monkeypatch):
    monkeypatch.setattr(searxng_manager, "docker_available", lambda: False)
    monkeypatch.setattr(searxng_manager, "source_available", lambda: True)
    monkeypatch.setattr(searxng_manager, "source_installed", lambda data_dir: True)
    monkeypatch.setattr(searxng_manager, "_source_state", lambda data_dir: "stopped")
    monkeypatch.setattr(
        searxng_manager,
        "_start_source",
        lambda data_dir: {"url": searxng_manager.BASE_URL, "started": True, "backend": "source"},
    )
    monkeypatch.setattr(searxng_manager, "_wait_until_ready", lambda *a, **k: True)

    body = client.post("/websearch/searxng/start").json()
    assert body["running"] is True
    assert body["backend"] == "source"
    assert client.get("/preferences").json()["searxng_url"] == searxng_manager.BASE_URL


def test_searxng_start_saves_the_url(client, monkeypatch):
    monkeypatch.setattr(
        searxng_manager,
        "start",
        lambda data_dir, on_ready=None: {"url": "http://localhost:8888", "started": True},
    )
    body = client.post("/websearch/searxng/start").json()
    assert body["running"] is True
    assert client.get("/preferences").json()["searxng_url"] == "http://localhost:8888"


def test_searxng_stop_reverts_to_duckduckgo(client, monkeypatch):
    client.put("/preferences", json={"searxng_url": "http://localhost:8888"})
    monkeypatch.setattr(searxng_manager, "stop", lambda data_dir=None: {"stopped": True})
    body = client.post("/websearch/searxng/stop").json()
    assert body["running"] is False
    # The dead instance must not stay configured.
    assert client.get("/preferences").json()["searxng_url"] == ""
