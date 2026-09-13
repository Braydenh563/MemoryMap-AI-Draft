"""Applying an update automatically, POST /update/apply.

Never touches a real GitHub release or spawns a real installer: every test
mocks `requests.get` and `subprocess.Popen`, and asserts on what the code
*tried* to do rather than any real network or process effect. The Win32
mechanics of a real install replacing a real running app are the one part
this suite cannot exercise, see routes_update.py's own module docstring.
"""

from __future__ import annotations

import time

import pytest

from memorymap.api import routes_update


@pytest.fixture(autouse=True)
def _clean_update_state():
    routes_update.reset_for_tests()
    yield
    routes_update.reset_for_tests()


class _FakeResponse:
    def __init__(self, json_body=None, status=200, content=b"", headers=None):
        self._json = json_body
        self.status_code = status
        self.headers = headers or {}
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json

    def iter_content(self, chunk_size=None):
        for i in range(0, len(self._content), chunk_size or len(self._content) or 1):
            yield self._content[i : i + (chunk_size or len(self._content))]


RELEASE_WITH_ASSET = {
    "tag_name": "v9.9.9",
    "assets": [
        {
            "name": "MemoryMap-AI-Setup-9.9.9.exe",
            # A real release link: `_download_url_is_allowed` refuses anything that
            # is not one of this app's own release hosts, so a fixture
            # pointing at example.com would exercise the refusal rather than
            # the apply path it means to test.
            "browser_download_url": (
                "https://github.com/Braydenh563/MemoryMap-AI/releases/download"
                "/v9.9.9/MemoryMap-AI-Setup-9.9.9.exe"
            ),
            "size": 12,
        }
    ],
}


def _wait_until_idle(timeout=5.0):
    deadline = time.time() + timeout
    while routes_update.current()["running"] and time.time() < deadline:
        time.sleep(0.02)
    assert not routes_update.current()["running"], "apply thread never finished"


def _wait_until_exit_called(exit_calls, timeout=3.0):
    """For a test on the "launched" path: `_exit_once_launched` runs on its
    own background thread and only calls `os._exit` *after* this test's own
    `_wait_until_idle` above already sees `_state.running` go False: so
    without this, the test can return (and `monkeypatch` revert its mock of
    `os._exit`) before that background thread ever gets there. The real
    `os._exit(0)` then fires a couple hundred ms later against no mock at
    all, silently killing the whole pytest process mid-suite. Found by
    running `pytest tests/test_update.py` alone: a truncated run, no
    failure reported, no traceback, exactly what an unmocked `os._exit(0)`
    looks like from the outside."""
    deadline = time.time() + timeout
    while not exit_calls and time.time() < deadline:
        time.sleep(0.02)
    assert exit_calls, "the exit-watcher thread never called the (mocked) os._exit"


# --- guards, none of which should ever touch the network -------------------


def test_apply_refuses_when_update_check_is_disabled(client):
    response = client.post("/update/apply")
    assert response.status_code == 403


def test_apply_refuses_when_auto_update_is_off(client, app_state, monkeypatch):
    """update_check_enabled alone is not enough, asked for directly, a
    separate switch for "turn auto update off entirely" that this endpoint
    has to respect even when checking is on and the build could otherwise
    apply one."""
    app_state.set_preference("update_check_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)
    response = client.post("/update/apply")
    assert response.status_code == 403
    assert "Update automatically" in response.json()["detail"]


def test_apply_refuses_off_a_source_or_non_windows_build(client, app_state):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    response = client.post("/update/apply")
    assert response.status_code == 409
    assert "packaged Windows" in response.json()["detail"]


def test_apply_refuses_a_second_attempt_while_one_is_running(client, app_state, monkeypatch):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        time.sleep(0.3)  # a window for the second request to arrive mid-download
        return _FakeResponse(content=b"x", headers={"Content-Length": "1"})

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(routes_update.os, "_exit", lambda code: None)

    started = client.post("/update/apply")
    assert started.status_code == 200
    again = client.post("/update/apply")
    assert again.status_code == 409
    _wait_until_idle()


# --- offline / network-failure safety, asked for directly ------------------


def test_apply_fails_cleanly_when_offline_fetching_the_release(client, app_state, monkeypatch):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _offline(*a, **k):
        raise ConnectionError("no route to host")

    monkeypatch.setattr(routes_update.requests, "get", _offline)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))

    response = client.post("/update/apply")

    assert response.status_code == 502
    assert not popen_calls, "must never spawn the installer without a real asset URL"


def test_apply_fails_cleanly_when_the_download_drops_mid_stream(client, app_state, monkeypatch):
    """The release check succeeds, but the download itself fails partway, 
    a truncated installer must never be handed to subprocess.Popen."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))

    response = client.post("/update/apply")
    assert response.status_code == 200
    _wait_until_idle()

    state = routes_update.current()
    assert state["outcome"] == "failed"
    assert state["error"]
    assert not popen_calls


def test_a_truncated_download_is_caught_even_without_a_network_exception(
    client, app_state, monkeypatch, tmp_path
):
    """The connection can drop without raising, iter_content just yields
    less than Content-Length promised. That has to be caught too, not only
    an outright exception."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        return _FakeResponse(content=b"only 5", headers={"Content-Length": "999"})

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))

    client.post("/update/apply")
    _wait_until_idle()

    assert routes_update.current()["outcome"] == "failed"
    assert "incomplete" in routes_update.current()["error"].lower()
    assert not popen_calls


# --- the successful path ----------------------------------------------------


def test_a_successful_apply_downloads_then_launches_the_official_installer_only(
    client, app_state, monkeypatch, tmp_path
):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        return _FakeResponse(content=b"MZ-fake-installer-bytes", headers={"Content-Length": "23"})

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
    # The exit-once-launched watcher calling the real os._exit(0) would
    # kill the test process, mocked, and EXIT_DELAY_SECONDS shrunk so the
    # watcher thread doesn't sit in its own 2s sleep long after this test
    # has already returned: see _wait_until_exit_called's own comment for
    # why both matter together, not just the mock alone.
    monkeypatch.setattr(routes_update, "EXIT_DELAY_SECONDS", 0)
    exit_calls = []
    monkeypatch.setattr(routes_update.os, "_exit", lambda code: exit_calls.append(code))

    response = client.post("/update/apply")
    assert response.status_code == 200
    _wait_until_idle()
    _wait_until_exit_called(exit_calls)

    state = routes_update.current()
    assert state["outcome"] == "launched"
    assert len(popen_calls) == 1
    command = popen_calls[0][0]
    # Never anything but the asset this release actually named, no path or
    # URL a request body could have influenced reaches subprocess.Popen.
    assert command[0].endswith("MemoryMap-AI-Setup-9.9.9.exe")
    assert "/VERYSILENT" in command
    assert "/NORESTART" in command
    downloaded = tmp_path / "MemoryMap-AI-Setup-9.9.9.exe"
    assert downloaded.read_bytes() == b"MZ-fake-installer-bytes"


def test_an_asset_pointing_off_the_release_hosts_is_never_downloaded(
    client, app_state, monkeypatch, tmp_path
):
    """This file downloads an executable and then runs it silently.

    `browser_download_url` is remote data: it is whatever the release row
    says. One asset pointing somewhere else, through a compromised account or
    a redirect service, would be an arbitrary executable downloaded and
    launched, and nothing else in this path would notice (the download is
    checked for truncation, not for a signature). So the host is checked
    before a single byte is written, and the check is here rather than only
    in a constant because a constant nobody asserts is a comment.
    """
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    elsewhere = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": "MemoryMap-AI-Setup-9.9.9.exe",
                "browser_download_url": "https://updates.example.com/MemoryMap-AI-Setup-9.9.9.exe",
                "size": 12,
            }
        ],
    }
    fetched = []

    def _fake_get(url, **kwargs):
        fetched.append(url)
        if "releases/latest" in url:
            return _FakeResponse(elsewhere)
        return _FakeResponse(content=b"MZ-evil", headers={"Content-Length": "7"})

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
    monkeypatch.setattr(routes_update, "EXIT_DELAY_SECONDS", 0)
    monkeypatch.setattr(routes_update.os, "_exit", lambda code: None)

    assert client.post("/update/apply").status_code == 200
    _wait_until_idle()

    state = routes_update.current()
    assert state["outcome"] == "failed"
    assert "does not point at this app" in state["step"]
    # Nothing was fetched but the release listing, and nothing was run.
    assert all("releases/latest" in url for url in fetched)
    assert popen_calls == []
    # `tmp_path` is also the notebook's own data dir under the `client`
    # fixture, so the question is not "is it empty" but "was an installer
    # written": it was not.
    assert list(tmp_path.glob("*.exe")) == []


def test_the_allowed_hosts_are_https_only():
    from memorymap.api.routes_update import _download_url_is_allowed

    assert _download_url_is_allowed(
        "https://objects.githubusercontent.com/x/MemoryMap-AI-Setup-1.0.0.exe"
    )
    # http, even to the right host: the bytes become an executable, so a
    # downgrade is the same hole with an extra step.
    assert not _download_url_is_allowed("http://github.com/x.exe")
    # A host that merely ends in the allowed one, which is how an allowlist
    # written with `endswith` is usually beaten.
    assert not _download_url_is_allowed("https://evil-github.com/x.exe")
    assert not _download_url_is_allowed("https://github.com.evil.test/x.exe")
    assert not _download_url_is_allowed("")
    assert not _download_url_is_allowed(None)


def test_no_matching_windows_asset_is_a_clean_failure_not_a_crash(client, app_state, monkeypatch):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        routes_update.requests,
        "get",
        lambda *a, **k: _FakeResponse({"tag_name": "v9.9.9", "assets": []}),
    )

    response = client.post("/update/apply")

    assert response.status_code == 502


def test_apply_status_reports_idle_before_anything_runs(client):
    response = client.get("/update/apply/status")
    assert response.status_code == 200
    assert response.json() == {
        "running": False,
        "step": "",
        "error": "",
        "done_bytes": 0,
        "total_bytes": 0,
        "outcome": "",
    }


# --- POST /update/apply?tag=...: picking a specific release ---------------


def test_apply_with_a_specific_tag_hits_the_tagged_release_not_latest(
    client, app_state, monkeypatch, tmp_path
):
    """`tag` is never interpolated into a request URL at all (CodeQL
    py/partial-ssrf): a specific tag is found by matching `tag_name` in
    the plain, fixed `/releases` listing instead of `/releases/tags/{tag}`,
    so the request this test observes is always the same fixed URL
    regardless of which tag was asked for."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    requested_urls = []
    other_release = dict(RELEASE_WITH_ASSET)  # v9.9.9: must NOT be the one picked
    tagged_release = {
        "tag_name": "v8.8.8",
        "assets": [
            {
                "name": "MemoryMap-AI-Setup-8.8.8.exe",
                "browser_download_url": (
                    "https://github.com/Braydenh563/MemoryMap-AI/releases/download"
                    "/v8.8.8/MemoryMap-AI-Setup-8.8.8.exe"
                ),
                "size": 12,
            }
        ],
    }

    def _fake_get(url, **kwargs):
        requested_urls.append(url)
        if url == f"{routes_update.GITHUB_REPO_API}/releases":
            return _FakeResponse([other_release, tagged_release])
        return _FakeResponse(content=b"old-installer", headers={"Content-Length": "13"})

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
    # See _wait_until_exit_called's own comment: both the shrunk delay and
    # waiting for the mocked call are needed, or the real os._exit(0) fires
    # after this test has already returned and unmocked it.
    monkeypatch.setattr(routes_update, "EXIT_DELAY_SECONDS", 0)
    exit_calls = []
    monkeypatch.setattr(routes_update.os, "_exit", lambda code: exit_calls.append(code))

    response = client.post("/update/apply", params={"tag": "v8.8.8"})
    assert response.status_code == 200
    _wait_until_idle()
    _wait_until_exit_called(exit_calls)

    # First call is the release lookup, always this one fixed URL,
    # regardless of which tag was asked for; the second is the download
    # itself, hitting the asset URL that lookup resolved to.
    assert requested_urls[0] == f"{routes_update.GITHUB_REPO_API}/releases"
    assert not any("releases/latest" in u or "releases/tags" in u for u in requested_urls)
    state = routes_update.current()
    assert state["outcome"] == "launched"


def test_apply_with_a_tag_that_has_no_matching_release_is_a_clean_404(
    client, app_state, monkeypatch
):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        routes_update.requests, "get", lambda *a, **k: _FakeResponse([RELEASE_WITH_ASSET])
    )

    response = client.post("/update/apply", params={"tag": "v1.2.3"})
    assert response.status_code == 404


def test_apply_refuses_a_tag_that_isnt_a_real_release_tag_shape(
    client, app_state, monkeypatch
):
    """`tag` used to go straight into a GitHub API URL, flagged by CodeQL
    as a partial SSRF (py/partial-ssrf): the host is fixed, but the path
    wasn't, so a crafted value could still steer the request somewhere this
    endpoint never meant to fetch. Every real tag this repo's release
    workflow ever creates looks like `v0.1.3`; anything else is refused
    before it ever reaches a URL, let alone a network call."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    calls = []
    monkeypatch.setattr(
        routes_update.requests, "get", lambda *a, **k: calls.append(a) or _FakeResponse({})
    )

    for hostile in ["../../etc/passwd", "v1.0.0/../../repos/other/repo", "v1.0#frag", "not-a-tag"]:
        response = client.post("/update/apply", params={"tag": hostile})
        assert response.status_code == 400, hostile

    assert calls == [], "a rejected tag must never reach a network call"


# --- GET /update/check: moved from app.py, now channel-aware --------------


def test_check_reports_disabled_when_the_preference_is_off(client):
    response = client.get("/update/check")
    assert response.status_code == 200
    assert response.json() == {"checked": False, "reason": "disabled"}


def test_check_honestly_refuses_to_fabricate_main_channel_updates(client, app_state):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "main")
    response = client.get("/update/check")
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] is False
    assert body["reason"] == "channel_unavailable"


def test_check_reports_unreachable_when_offline(client, app_state, monkeypatch):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "stable")

    def _offline(*a, **k):
        raise ConnectionError("no route to host")

    monkeypatch.setattr(routes_update.requests, "get", _offline)
    response = client.get("/update/check")
    assert response.status_code == 200
    assert response.json() == {"checked": False, "reason": "unreachable"}


def test_check_finds_an_update_and_reports_the_windows_asset(client, app_state, monkeypatch):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "stable")
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(routes_update.requests, "get", lambda *a, **k: _FakeResponse(RELEASE_WITH_ASSET))

    response = client.get("/update/check")
    assert response.status_code == 200
    body = response.json()
    assert body["checked"] is True
    assert body["update_available"] is True
    assert body["can_auto_apply"] is True
    assert body["asset"]["name"] == "MemoryMap-AI-Setup-9.9.9.exe"


def test_check_never_offers_auto_apply_off_a_source_build(client, app_state, monkeypatch):
    """Same release data, but not a frozen Windows build, can_auto_apply
    must be False and asset must be None, never a half-offer."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "stable")
    monkeypatch.setattr(routes_update.requests, "get", lambda *a, **k: _FakeResponse(RELEASE_WITH_ASSET))

    response = client.get("/update/check")
    body = response.json()
    assert body["update_available"] is True
    assert body["can_auto_apply"] is False
    assert body["asset"] is None


# --- GET /update/releases: the version picker ------------------------------


def test_releases_unavailable_when_check_is_disabled(client):
    response = client.get("/update/releases")
    assert response.status_code == 200
    assert response.json() == {"available": False, "reason": "disabled", "releases": []}


def test_releases_unavailable_on_the_main_channel(client, app_state):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "main")
    response = client.get("/update/releases")
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "channel_unavailable"


def test_releases_unavailable_off_a_source_build_on_the_stable_channel(client, app_state):
    """A source checkout defaults to the main channel (see
    ConfigManager._load_preferences), so this simulates someone who
    switched it back to stable by hand while still on a source build, 
    the frozen-Windows check has to be the one that refuses it then."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "stable")
    response = client.get("/update/releases")
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "not_supported"


def test_releases_unavailable_off_a_source_build_by_default(client, app_state):
    """A source checkout with no explicit channel choice defaults to
    "main" (it already auto-updates for real via start.sh/start.bat's own
    `git pull`), so /update/releases reports channel_unavailable, not
    not_supported: the honest reason, not a coincidentally-similar one."""
    app_state.set_preference("update_check_enabled", True)
    response = client.get("/update/releases")
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == "channel_unavailable"


def test_releases_lists_installable_versions_and_skips_source_only_tags(
    client, app_state, monkeypatch
):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("update_channel", "stable")
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)
    releases = [
        RELEASE_WITH_ASSET,
        {"tag_name": "v9.9.8", "name": "v9.9.8", "assets": [], "published_at": "2026-01-01"},
    ]
    monkeypatch.setattr(routes_update.requests, "get", lambda *a, **k: _FakeResponse(releases))

    response = client.get("/update/releases")
    body = response.json()
    assert body["available"] is True
    assert len(body["releases"]) == 1
    assert body["releases"][0]["tag"] == "v9.9.9"


# --- GET /update/source-status: start.sh/start.bat's own git-pull update --


def test_source_status_reports_nothing_when_no_update_happened(client):
    response = client.get("/update/source-status")
    assert response.status_code == 200
    assert response.json() == {"just_updated": False, "from": "", "to": ""}


def test_source_status_reports_a_real_version_change_once_then_goes_quiet(client, monkeypatch):
    monkeypatch.setenv("MM_UPDATED_FROM", "0.1.2")
    monkeypatch.setenv("MM_UPDATED_TO", "0.1.3")

    first = client.get("/update/source-status")
    assert first.json() == {"just_updated": True, "from": "0.1.2", "to": "0.1.3"}

    second = client.get("/update/source-status")
    assert second.json() == {"just_updated": False, "from": "", "to": ""}


def test_source_status_strips_quotes_left_by_start_bats_own_parsing(client, monkeypatch):
    """start.bat's :read_version leaves the surrounding quotes on rather
    than fight cmd.exe's quoting rules: see start.bat and this module's
    own comment. The Python side has to strip them."""
    monkeypatch.setenv("MM_UPDATED_FROM", '"0.1.2"')
    monkeypatch.setenv("MM_UPDATED_TO", '"0.1.3"')

    response = client.get("/update/source-status")
    assert response.json() == {"just_updated": True, "from": "0.1.2", "to": "0.1.3"}


def test_source_status_ignores_an_unchanged_version(client, monkeypatch):
    """`git pull` ran (env vars are set) but landed on the same version, 
    not a real update, must not pop the dialog."""
    monkeypatch.setenv("MM_UPDATED_FROM", "0.1.3")
    monkeypatch.setenv("MM_UPDATED_TO", "0.1.3")

    response = client.get("/update/source-status")
    assert response.json() == {"just_updated": False, "from": "", "to": ""}


# --- blocked download vs. blocked installer execution -----------------------


def test_a_download_blocked_by_a_firewall_gets_a_download_specific_message(
    client, app_state, monkeypatch
):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    popen_calls = []
    monkeypatch.setattr(routes_update.subprocess, "Popen", lambda *a, **k: popen_calls.append(a))

    client.post("/update/apply")
    _wait_until_idle()

    state = routes_update.current()
    assert state["outcome"] == "failed"
    assert "firewall" in state["step"].lower() or "download" in state["step"].lower()
    assert not popen_calls


def test_an_installer_blocked_by_antivirus_gets_an_execution_specific_message(
    client, app_state, monkeypatch, tmp_path
):
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        return _FakeResponse(content=b"MZ-fake-installer", headers={"Content-Length": "17"})

    def _blocked_popen(*a, **k):
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    monkeypatch.setattr(routes_update.subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))

    client.post("/update/apply")
    _wait_until_idle()

    state = routes_update.current()
    assert state["outcome"] == "failed"
    assert "antivirus" in state["step"].lower() or "smartscreen" in state["step"].lower()


def test_error_field_never_carries_a_raw_local_path_from_an_os_error(
    client, app_state, monkeypatch, tmp_path
):
    """Flagged by CodeQL (py/stack-trace-exposure): `_state.error` reaches
    the browser over GET /apply/status, and a real `PermissionError`'s own
    `str()` on Windows includes the full path it couldn't open: the exact
    shape `core/extras.py`'s own module docstring already documents fixing
    once for this app's other installer. The full detail still reaches the
    log (`logger.exception`); only the HTTP-facing field is sanitised."""
    app_state.set_preference("update_check_enabled", True)
    app_state.set_preference("auto_update_enabled", True)
    monkeypatch.setattr(routes_update.sys, "platform", "win32")
    monkeypatch.setattr(routes_update.sys, "frozen", True, raising=False)

    secret_path = str(tmp_path / "definitely-not-meant-to-leak" / "installer.exe")

    def _fake_get(url, **kwargs):
        if "releases/latest" in url:
            return _FakeResponse(RELEASE_WITH_ASSET)
        return _FakeResponse(content=b"MZ-fake-installer", headers={"Content-Length": "17"})

    def _blocked_popen(*a, **k):
        raise PermissionError(f"[WinError 5] Access is denied: '{secret_path}'")

    monkeypatch.setattr(routes_update.requests, "get", _fake_get)
    monkeypatch.setattr(routes_update.subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(routes_update.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))

    client.post("/update/apply")
    _wait_until_idle()

    state = routes_update.current()
    assert state["outcome"] == "failed"
    assert secret_path not in state["error"]
    assert "definitely-not-meant-to-leak" not in state["error"]
