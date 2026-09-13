"""The four boundaries between "local-only" and "actually private".

Each of these guards something that is invisible while it works and expensive
once it does not, and none of them is exercised by using the app normally, 
which is the whole reason they are pinned here. The roadmap's security tier
asked for all four; two of its seven items turned out to be built already
(WAL mode, and the unlock-gate backoff), and those live with their own code.

The through-line: binding 127.0.0.1 stops the network, not the browser. Every
test below is about something a browser on this machine could be made to do.
"""

from __future__ import annotations

import time

import pytest

from memorymap.api import routes_auth
from memorymap.core import security, vault


# --- session expiry ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_sessions():
    routes_auth._active_tokens.clear()
    routes_auth._failed_unlocks.clear()
    yield
    routes_auth._active_tokens.clear()
    routes_auth._failed_unlocks.clear()


def _unlocked(client) -> str:
    """Set a password and return a working token."""
    response = client.post("/auth/setup", json={"password": "correct horse"})
    assert response.status_code == 200
    return response.json()["token"]


def test_a_token_works_while_it_is_being_used(client):
    token = _unlocked(client)
    headers = {"X-Auth-Token": token}
    assert client.get("/entries", headers=headers).status_code == 200
    assert client.get("/entries", headers=headers).status_code == 200


def test_a_token_left_alone_too_long_stops_working(client, monkeypatch):
    """The notebook locks itself, the way a phone does.

    Restarting the app already cleared every token, which sounds like it
    covers this: but this app is a desktop notebook that stays open for
    weeks, so "until the next restart" is not a limit.
    """
    token = _unlocked(client)
    issued, _ = routes_auth._active_tokens[token]
    # Rewind the clock on the token rather than sleeping through the real TTL.
    routes_auth._active_tokens[token] = [
        issued,
        time.time() - routes_auth._SESSION_IDLE_TTL - 1,
    ]
    assert client.get("/entries", headers={"X-Auth-Token": token}).status_code == 401


def test_a_token_kept_busy_still_expires_eventually(client):
    """The ceiling that a leaked token hits regardless of how live it is."""
    token = _unlocked(client)
    routes_auth._active_tokens[token] = [
        time.time() - routes_auth._SESSION_MAX_AGE - 1,
        time.time(),  # used a moment ago, and still too old
    ]
    assert client.get("/entries", headers={"X-Auth-Token": token}).status_code == 401


def test_using_a_token_keeps_it_alive(client):
    token = _unlocked(client)
    routes_auth._active_tokens[token][1] = time.time() - 60
    client.get("/entries", headers={"X-Auth-Token": token})
    assert time.time() - routes_auth._active_tokens[token][1] < 5


def test_expiry_forgets_the_private_note_key_too(client):
    """An expiry that left the vault open would be a lock on one door only."""
    token = _unlocked(client)
    assert vault.is_open()
    routes_auth._active_tokens[token] = [
        time.time(),
        time.time() - routes_auth._SESSION_IDLE_TTL - 1,
    ]
    routes_auth._sweep_expired(routes_auth._SESSION_IDLE_TTL)
    assert not vault.is_open()


def test_the_account_screen_does_not_count_dead_sessions(client):
    token = _unlocked(client)
    stale = routes_auth._issue_token()
    routes_auth._active_tokens[stale] = [
        time.time(),
        time.time() - routes_auth._SESSION_IDLE_TTL - 1,
    ]
    body = client.get("/auth/account", headers={"X-Auth-Token": token}).json()
    assert body["active_sessions"] == 1


# --- the origin check -------------------------------------------------------
#
# The attack is specific: a page on another site cannot reach a server bound to
# 127.0.0.1 by itself, but it can ask the browser already running on this
# machine to send the request for it. The browser complies, because refusing is
# the target's job. Ollama and any number of local dev servers have been taken
# this way.


def test_a_request_from_another_site_is_refused(client):
    token = _unlocked(client)
    response = client.get(
        "/entries",
        headers={"X-Auth-Token": token, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert "another site" in response.json()["detail"]


def test_a_write_from_another_site_is_refused_too(client):
    token = _unlocked(client)
    response = client.post(
        "/entries",
        json={"content": "planted by a page in another tab"},
        headers={"X-Auth-Token": token, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_the_setup_route_is_protected_before_a_password_exists(client):
    """The window that matters most, and the one that looks like it doesn't.

    Until a password is set the unlock gate waves everything through, because
    there is nothing to protect yet. That is also the moment a drive-by POST
    could claim the notebook and lock the real owner out of their own app.
    """
    response = client.post(
        "/auth/setup",
        json={"password": "claimed by a stranger"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert client.get("/auth/status").json()["setup_required"] is True


def test_the_apps_own_page_is_allowed(client):
    token = _unlocked(client)
    response = client.get(
        "/entries",
        headers={
            "X-Auth-Token": token,
            "Origin": "http://testserver",
            "Host": "testserver",
        },
    )
    assert response.status_code == 200


def test_a_request_with_no_origin_is_allowed(client):
    """curl, the pywebview desktop shell and the test client all send none.

    Allowing these is not the hole it looks like: a browser attaches Origin to
    exactly the cross-site requests this rejects, so the requests arriving
    without one are the local tools that never had an origin to state.
    """
    token = _unlocked(client)
    assert client.get("/entries", headers={"X-Auth-Token": token}).status_code == 200


def test_a_referer_from_another_site_is_refused_when_origin_is_absent(client):
    token = _unlocked(client)
    response = client.get(
        "/entries",
        headers={"X-Auth-Token": token, "Referer": "https://evil.example/post"},
    )
    assert response.status_code == 403


def test_localhost_and_127_are_the_same_machine():
    """Which one appears depends on what the user typed into the bar."""
    assert security._is_same_site("http://localhost:8000", "127.0.0.1:8000", "http")
    assert security._is_same_site("http://127.0.0.1:8000", "localhost:8000", "http")


def test_a_different_port_on_loopback_is_still_another_origin():
    """Another server on this machine is not this app."""
    assert not security._is_same_site("http://localhost:3000", "localhost:8000", "http")


def test_a_hostname_that_merely_starts_with_localhost_is_not_loopback():
    assert not security._is_same_site(
        "http://localhost.evil.example", "localhost:8000", "http"
    )


def test_the_null_origin_of_a_sandboxed_frame_is_not_trusted(client):
    """A sandboxed iframe and a file:// page both send "null"; neither is us."""
    assert not security._is_same_site("null", "localhost:8000", "http")


# --- the content security policy --------------------------------------------


def test_every_response_carries_the_policy(client):
    assert "Content-Security-Policy" in client.get("/health").headers


def test_the_policy_names_no_remote_host():
    """Affordable only because nothing here comes from a CDN, d3 and p5 are
    vendored. A policy this tight is normally the expensive part of adding one.
    """
    policy = security.build_csp([])
    assert "http://" not in policy and "https://" not in policy
    assert "*" not in policy


def test_the_policy_refuses_inline_script_and_style():
    policy = security.build_csp([])
    assert "'unsafe-inline'" not in policy
    assert "'unsafe-eval'" not in policy


def test_the_policy_closes_the_usual_bypasses():
    policy = security.build_csp([])
    for directive in ("object-src 'none'", "base-uri 'self'", "frame-ancestors 'none'"):
        assert directive in policy


def test_custom_css_does_not_inject_a_style_tag():
    """The one feature the strict policy broke, and the only thing that found
    it was a browser, 757 green tests said nothing.

    Settings → Appearance lets the user write their own CSS. It was applied by
    creating a <style> element, which is exactly what style-src 'self' refuses,
    so the feature silently stopped working while every test stayed green. It
    now adopts a constructed stylesheet, which CSP does not treat as inline
    content. This asserts the shape of the fix so a later edit cannot quietly
    put the <style> tag back on the main path.
    """
    from memorymap.api.app import FRONTEND_DIR

    # applyCustomCss/applyCustomCssLegacy moved to settings.js with the rest
    # of appearance (§88.3 item 4, the app.js split's fourth and last file).
    source = (FRONTEND_DIR / "settings.js").read_text(encoding="utf-8")
    start = source.index("function applyCustomCss(")
    end = source.index("function applyCustomCssLegacy(")
    main_path = source[start:end]
    assert "adoptedStyleSheets" in main_path
    assert "createElement" not in main_path, (
        "custom CSS is back to injecting a <style> tag, which the CSP blocks"
    )


def test_the_real_page_needs_no_hash_at_all():
    """**This assertion is the reverse of what it used to be, on purpose.**

    index.html carried exactly one inline script, the pre-paint theme block
    - allowed by a hash computed from the file. It was believed to have to
    stay inline, because app.js loads at the end of the body, far too late to
    stop the flash. That was true of app.js and false of the requirement: a
    plain `<script src>` in the head runs before first paint just as well,
    which is what `theme-boot.js` now is.

    The move was made because the hash kept costing more than it was worth. A
    hash is a second copy of the script, held in a header, and the report

        [browser/csp] blocked script-src-elem: inline

    is what a browser says when the two copies disagree, which lands on the
    user as the app opening in its default look with their saved theme never
    applied. `CspForPage` already closed the stale-server cause of that
    disagreement; this closes the rest of them, because `script-src 'self'`
    covers a same-origin file with nothing to disagree with.

    So the page yielding *no* hashes is now the healthy state, and a hash
    reappearing means an inline block has come back.
    """
    from memorymap.api.app import FRONTEND_DIR

    assert security.inline_script_hashes(FRONTEND_DIR / "index.html") == []


def test_the_hash_tracks_the_file_rather_than_a_written_down_value(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<script>console.log(1)</script>")
    before = security.inline_script_hashes(page)
    page.write_text("<script>console.log(2)</script>")
    assert security.inline_script_hashes(page) != before


def test_a_script_with_a_src_needs_no_hash(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<script src="/app.js"></script>')
    assert security.inline_script_hashes(page) == []


def test_the_frontend_has_no_inline_style_attributes():
    """style-src 'self' is only honest while this holds. The eight attributes
    that used to be here moved into style.css.

    **app.js is checked too, and that is the half this test used to miss.**
    A `style="…"` inside a template literal that app.js hands to `innerHTML`
    is refused by the CSP exactly as one written into index.html is, the
    browser does not care which file the markup came from. Only index.html was
    read here, so five of them sat in app.js unnoticed and their elements
    rendered unstyled: most visibly the agent's edit preview, which lost the
    red/green that is the entire point of showing a diff.

    Setting `el.style.someProperty` from JS is fine and is not what this
    matches: the CSP blocks the *attribute*, not the CSSOM.
    """
    from memorymap.api.app import FRONTEND_DIR

    # whiteboard.js carries the board/card CRUD, sketch drawing, export and
    # move/resize code that used to be the back half of app.js (ROADMAP.md
    # Priority 0 item 2), and graph.js carries the force-directed map, its
    # layouts, tracing and node popup (frontend refactor path, the step
    # after whiteboard): the same innerHTML-template-literal risk applies
    # there as anywhere else in the frontend, so both are checked too.
    for name in ("index.html", "app.js", "whiteboard.js", "graph.js"):
        source = (FRONTEND_DIR / name).read_text(encoding="utf-8")
        assert 'style="' not in source and "style='" not in source, (
            f"{name} carries an inline style attribute. The CSP refuses it, so it "
            "renders as no styling at all, move it into style.css as a class."
        )


def test_the_other_headers_are_there_too(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def test_the_microphone_is_not_denied(client):
    """Voice capture is a real feature; the policy must not break it while
    turning off the permissions the app genuinely never wants."""
    policy = client.get("/health").headers["Permissions-Policy"]
    assert "microphone" not in policy
    assert "camera=()" in policy


# --- SearXNG's published port -----------------------------------------------


def test_searxng_is_published_to_loopback_only():
    """`-p 8888:8080` publishes on EVERY interface, which is not what the
    plain reading suggests. The source path always bound 127.0.0.1; the docker
    path did not, and docker writes its own firewall rules, so a host firewall
    set to refuse the port never sees the packet.

    An exposed SearXNG is worse than an exposed port: it is an unauthenticated
    proxy to the internet, and a log of everything the owner has searched.
    """
    from memorymap.search import searxng_manager

    spec = searxng_manager._publish_spec()
    assert spec.startswith("127.0.0.1:")
    assert spec.endswith(":8080")


def test_a_container_from_an_older_version_is_replaced(monkeypatch):
    """Publishing is fixed when a container is CREATED, so changing the run
    command only protects people who never started SearXNG. Anyone who ran an
    earlier version has one published on 0.0.0.0 that `docker start` would
    keep that way forever."""
    from memorymap.search import searxng_manager

    class _Result:
        returncode = 0
        stdout = "0.0.0.0\n"
        stderr = ""

    monkeypatch.setattr(searxng_manager, "_run", lambda *a, **k: _Result())
    assert searxng_manager._docker_publishes_beyond_localhost() is True


def test_a_loopback_container_is_left_alone(monkeypatch):
    from memorymap.search import searxng_manager

    class _Result:
        returncode = 0
        stdout = "127.0.0.1\n"
        stderr = ""

    monkeypatch.setattr(searxng_manager, "_run", lambda *a, **k: _Result())
    assert searxng_manager._docker_publishes_beyond_localhost() is False


def test_an_unreadable_container_is_not_destroyed_on_a_guess(monkeypatch):
    """Failing to inspect is not evidence of exposure, and removing a
    container on a guess costs the user their working search."""
    from memorymap.search import searxng_manager

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "no such object"

    monkeypatch.setattr(searxng_manager, "_run", lambda *a, **k: _Result())
    assert searxng_manager._docker_publishes_beyond_localhost() is False


def test_a_container_with_no_recorded_host_ip_counts_as_exposed(monkeypatch):
    """An empty HostIp is how docker records "all interfaces", the same thing
    the bare `-p 8888:8080` form produces."""
    from memorymap.search import searxng_manager

    class _Result:
        returncode = 0
        stdout = "\n"
        stderr = ""

    monkeypatch.setattr(searxng_manager, "_run", lambda *a, **k: _Result())
    assert searxng_manager._docker_publishes_beyond_localhost() is True


# --- the two items that were already built ----------------------------------
#
# Pinned here rather than taken on trust: the roadmap listed both as
# outstanding, and an audit found them done. A test is what stops the next
# audit having to rediscover that, and what would notice a silent regression.


def test_sqlite_runs_in_wal_mode(app_state):
    """Without it, one background write blocks every read, and FastAPI serves
    from a threadpool, so the janitor filing a note during a page load is
    routine rather than rare."""
    from memorymap.core import deps

    with deps.get_db().engine.connect() as connection:
        mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert str(mode).lower() == "wal"


def test_the_private_note_key_uses_a_slow_kdf():
    """The difference only matters if the database file is ever copied off the
    machine: which is exactly the scenario private notes exist for."""
    from memorymap.core import crypto

    assert crypto.SCRYPT_N >= 2**14
    assert crypto.KEY_BYTES == 32


def test_wrong_passwords_earn_a_growing_wait(client):
    """bcrypt makes one guess slow; nothing made many guesses slow, and the
    password floor is four characters."""
    _unlocked(client)
    routes_auth._active_tokens.clear()
    codes = [
        client.post("/auth/unlock", json={"password": "wrong pass"}).status_code
        for _ in range(routes_auth._FAILURE_ALLOWANCE + 2)
    ]
    assert 429 in codes, "a run of wrong passwords should start earning waits"


# --- the inline-script reader (CodeQL py/bad-tag-filter) ---------------------
#
# CodeQL flagged this pattern as a "bad HTML filtering regexp". The reported
# risk, an attacker crafting markup that slips past a sanitiser, does not
# apply: this reads `frontend/index.html`, a file shipped with the app, to hash
# its own pre-paint theme script. Nothing user-supplied reaches it.
#
# The bug it pointed at was real, though, and its failure mode is the app
# opening as a blank unstyled page: a script the pattern misses gets no hash in
# the CSP, so the browser refuses to run it.


def _hashes_of(tmp_path, markup: bytes):
    page = tmp_path / "page.html"
    page.write_bytes(markup)
    return security.inline_script_hashes(page)


def test_whitespace_before_the_closing_bracket_still_matches(tmp_path):
    """HTML permits `</script >`. The old pattern required them adjacent, so
    the match failed outright and the script silently lost its hash."""
    assert _hashes_of(tmp_path, b"<script>go()</script >")
    assert _hashes_of(tmp_path, b"<script>go()</script\n>")


def test_the_same_script_hashes_the_same_however_the_tag_is_spelled(tmp_path):
    """The hash is of the *body*, so tag whitespace must not change it."""
    tight = _hashes_of(tmp_path, b"<script>go()</script>")
    loose = _hashes_of(tmp_path, b"<script>go()</script >")
    assert tight == loose


def test_an_external_script_is_never_hashed(tmp_path):
    """It has no inline body to hash, and `src` with spaces around the `=` used
    to slip past the exclusion and contribute a hash of the empty string."""
    assert _hashes_of(tmp_path, b'<script src="/app.js"></script>') == []
    assert _hashes_of(tmp_path, b'<script src = "/app.js"></script>') == []
    assert _hashes_of(tmp_path, b'<script SRC="/app.js"></script>') == []


def test_an_inline_script_with_attributes_is_still_hashed(tmp_path):
    assert _hashes_of(tmp_path, b'<script type="module">go()</script>')


def test_several_inline_scripts_each_get_their_own_hash(tmp_path):
    hashes = _hashes_of(tmp_path, b"<script>a()</script><script>b()</script>")
    assert len(hashes) == 2
    assert len(set(hashes)) == 2


def test_a_comment_mentioning_a_script_tag_yields_nothing(tmp_path):
    """Found live, and it hid a real tag while it did it.

    `_INLINE_SCRIPT` is a regex, so a comment that merely *writes out* a
    script tag opens a match, and the pattern then runs to the next
    `</script`, swallowing whatever real tags lie between. index.html's own
    comment explaining why the theme bootstrap is a file did exactly that: it
    produced a phantom hash and consumed the `<script src>` it was written
    about. A phantom hash is harmless; a real inline script hidden behind one
    would be served with no hash and refused by the browser, which is the
    failure this whole module exists to prevent."""
    page = tmp_path / "index.html"
    page.write_text(
        "<!-- explains why `<script src>` is used here -->\n"
        '<script src="/theme-boot.js"></script>\n'
    )
    assert security.inline_script_hashes(page) == []


def test_csp_follows_the_page_when_it_changes_under_a_running_server(tmp_path):
    """A frontend update must not leave the policy naming the old script.

    The bug this pins down was reported from real use, more than once, as

        [browser/csp] blocked script-src-elem: inline

    and the cause was structural rather than a bad hash: the policy was built
    once at startup while `index.html` is read from disk on every request, so
    any edit to the page under a running server served a new inline script
    against the *previous* script's hash. The browser blocks it, and what is
    lost is the anti-flash theme bootstrap in the page head, the app paints
    its default look instead of the user's. Restarting fixed it, which is why
    it kept coming back.
    """
    page = tmp_path / "index.html"
    page.write_text("<script>window.A = 1;</script>", encoding="utf-8")
    provider = security.CspForPage(page)

    first = provider.value()
    assert security.inline_script_hashes(page)[0] in first

    # Same content, no re-read needed: the policy must stay valid.
    assert provider.value() == first

    # Now the page changes under the running process, exactly as a frontend
    # update does. os.utime keeps the test independent of filesystem mtime
    # granularity, which is coarse enough on some platforms to hide this.
    page.write_text("<script>window.A = 2;</script>", encoding="utf-8")
    import os

    st = page.stat()
    os.utime(page, (st.st_atime, st.st_mtime + 10))

    second = provider.value()
    assert second != first, "policy still names the old script after an edit"
    assert security.inline_script_hashes(page)[0] in second


def test_csp_keeps_the_last_good_policy_if_the_page_goes_missing(tmp_path):
    """Never silently widen to a policy with no hashes at all."""
    page = tmp_path / "index.html"
    page.write_text("<script>window.A = 1;</script>", encoding="utf-8")
    provider = security.CspForPage(page)
    good = provider.value()

    page.unlink()

    assert provider.value() == good
