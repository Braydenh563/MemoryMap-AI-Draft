"""The live log console and the support bundle (§1).

Asked for directly: the Logs screen should read "like the terminal running in
the background, with key errors flagged", not a list you refresh by hand.

The stream's contract is the interesting part here, a log console that
silently skips records, or replays them, is worse than one you refresh
yourself, because you would not know to distrust it.
"""

from __future__ import annotations

import re

import io
import json
import logging
import zipfile

import pytest

from memorymap.api import routes_settings
from memorymap.core import deps, logbuffer


@pytest.fixture(autouse=True)
def _empty_buffer():
    # install() is what attaches the handler, and it normally runs from
    # create_app(). The buffer tests below have no app, so without this they
    # would assert against a buffer nothing ever writes to, and pass for the
    # wrong reason the moment an assertion was weakened.
    logbuffer.install()
    logbuffer.clear()
    yield
    logbuffer.clear()


def _log(count: int, level: int = logging.INFO, name: str = "memorymap.test") -> None:
    logger = logging.getLogger(name)
    for index in range(count):
        logger.log(level, "record %d", index)


# --- sequence numbers, which the stream is built on -------------------------


def test_every_record_gets_an_increasing_id():
    _log(3)
    seqs = [record["seq"] for record in logbuffer.recent()]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_ids_are_not_reused_after_the_ring_wraps():
    """Position in the deque cannot do this job, the deque shifts every time
    it is full, so "the 400th record" means something different one message
    later. A reader resuming at 8,317 has to get exactly what follows it."""
    _log(logbuffer.MAX_RECORDS + 20)
    seqs = [record["seq"] for record in logbuffer.recent(logbuffer.MAX_RECORDS)]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert min(seqs) > 1, "the earliest ids should have been pushed out"


def test_since_returns_only_what_the_reader_has_not_seen():
    _log(3)
    cursor = logbuffer.latest_seq()
    _log(2)
    fresh = logbuffer.since(cursor)
    assert len(fresh) == 2
    assert all(record["seq"] > cursor for record in fresh)


def test_since_zero_is_everything_held():
    _log(4)
    assert len(logbuffer.since(0)) == 4


def test_a_reader_further_ahead_than_the_log_gets_nothing_rather_than_everything():
    """Guards the inverted-comparison bug, where a stale cursor would replay
    the whole buffer on every poll."""
    _log(3)
    assert logbuffer.since(logbuffer.latest_seq()) == []
    assert logbuffer.since(10**9) == []


def test_latest_seq_is_zero_on_an_empty_log():
    assert logbuffer.latest_seq() == 0


def test_clearing_does_not_restart_the_numbering():
    """Restarting at 1 would break every stream already open: a reader holding
    "I have seen up to 400" would treat the next 400 records as older than
    what it had and show none of them, a console that goes silent the moment
    you press Clear."""
    _log(5)
    before = logbuffer.latest_seq()
    logbuffer.clear()
    _log(1)
    assert logbuffer.latest_seq() > before


# --- the stream endpoint ----------------------------------------------------


@pytest.fixture()
def _brief_stream(monkeypatch):
    """Make the stream hand back on its first pass.

    TestClient reads a response to completion, so an open-ended generator
    would hang the suite rather than fail it. Zeroing the lifetime exercises
    the real code path, including the handover the client relies on, and
    lets the response finish. The live behaviour that this cannot show was
    driven in a browser instead.
    """
    monkeypatch.setattr(routes_settings, "LOG_STREAM_SECONDS", 0)


def _stream_events(client, url: str = "/logs/stream?after=999999999") -> list[dict]:
    response = client.get(url)
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_the_stream_is_ndjson_not_server_sent_events(client, _brief_stream):
    """EventSource cannot set request headers and this app authenticates with
    X-Auth-Token, so an EventSource here would simply 401. The usual fix is to
    put the token in the query string, which on the endpoint that serves the
    log would write the token into the records it protects."""
    response = client.get("/logs/stream?after=999999999")
    assert response.status_code == 200
    assert "ndjson" in response.headers["content-type"]


def test_the_stream_opens_immediately_rather_than_waiting_for_a_record(
    client, _brief_stream
):
    """A stream that says nothing until something is logged is
    indistinguishable from one that failed to connect."""
    events = _stream_events(client)
    assert events[0]["type"] == "open"
    assert "cursor" in events[0] and "latest" in events[0]


def test_the_stream_hands_back_instead_of_dying_quietly(client, _brief_stream):
    """The client reconnects from its cursor, so the handover costs no
    records: but only if it is told the connection ended on purpose."""
    events = _stream_events(client)
    assert events[-1]["type"] == "reconnect"
    assert "cursor" in events[-1]


def test_the_stream_carries_records_the_reader_has_not_seen(client, _brief_stream):
    _log(3)
    events = _stream_events(client, "/logs/stream?after=0")
    records = [event["record"] for event in events if event["type"] == "record"]
    assert len(records) >= 3
    assert [r["seq"] for r in records] == sorted(r["seq"] for r in records)


def test_the_stream_skips_what_the_reader_already_has(client, _brief_stream):
    _log(3)
    cursor = logbuffer.latest_seq()
    _log(2)
    events = _stream_events(client, f"/logs/stream?after={cursor}")
    records = [event["record"] for event in events if event["type"] == "record"]
    assert all(record["seq"] > cursor for record in records)


def test_the_stream_tells_a_proxy_not_to_buffer_it(client, _brief_stream):
    """A stream whose whole value is arriving promptly, sat in nginx's buffer,
    is just a slower version of the list this replaces."""
    response = client.get("/logs/stream?after=999999999")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"


def test_the_stream_is_behind_the_unlock_gate(client):
    """It carries every message the app has logged."""
    client.post("/auth/setup", json={"password": "a password"})
    from memorymap.api import routes_auth

    routes_auth._active_tokens.clear()
    # 401s before any streaming begins, so this needs no shortened lifetime.
    assert client.get("/logs/stream").status_code == 401


def test_the_stream_hands_back_rather_than_living_forever():
    """A connection held open for a tab left open all week is a resource
    nothing ever reclaims; the client reconnects with its cursor, so the
    handover costs no records."""
    assert routes_settings.LOG_STREAM_SECONDS <= 30 * 60
    assert routes_settings.LOG_STREAM_HEARTBEAT < routes_settings.LOG_STREAM_SECONDS


# --- the support bundle -----------------------------------------------------


def _bundle(client) -> zipfile.ZipFile:
    response = client.get("/support-bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_the_bundle_contains_what_a_bug_report_needs(client):
    names = _bundle(client).namelist()
    for member in ("README.txt", "logs.json", "preferences.json", "status.json"):
        assert member in names


def test_the_bundle_explains_itself(client):
    """It is a file the user is being asked to send to a stranger, so it says
    what is in it, what is not, and that nothing was transmitted."""
    readme = _bundle(client).read("README.txt").decode()
    assert "Nothing was sent anywhere" in readme
    assert "No note, document, chat or reminder content" in readme


def test_free_text_settings_are_described_rather_than_disclosed(client):
    """An allowlist, not a denylist. A denylist has to predict every sensitive
    key anyone will ever add; this only has to name the ones that help."""
    config = deps.get_config()
    secret = "MY-PRIVATE-NICKNAME"
    config.set_preference("display_name", secret)
    config.set_preference("user_profile", f"I work at {secret}")
    config.set_preference("personas", [{"name": "p", "prompt": secret}])

    response = client.get("/support-bundle")
    assert secret.encode() not in response.content, "the secret reached the bundle"

    prefs = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read("preferences.json"))
    assert "display_name" not in prefs["included"]
    # Still useful: you can tell a setting is populated without seeing it.
    assert "chars" in prefs["withheld"]["display_name"]


def test_diagnostic_settings_are_included_verbatim(client):
    """Withholding everything would make the bundle useless, the point is to
    diagnose a bug, and these are the settings that cause them."""
    deps.get_config().set_preference("search_provider", "duckduckgo")
    prefs = json.loads(_bundle(client).read("preferences.json"))
    assert prefs["included"]["search_provider"] == "duckduckgo"


def test_the_bundle_carries_counts_but_never_content(client):
    client.post("/entries", json={"content": "a very private thought indeed"})
    response = client.get("/support-bundle")
    assert b"a very private thought indeed" not in response.content
    counts = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read("counts.json"))
    assert counts["entries"] == 1


def test_the_bundle_still_builds_when_a_probe_fails(client, monkeypatch):
    """The moment this is most needed is when something is already broken, so
    one failing probe must not take the whole file with it."""
    monkeypatch.setattr(
        routes_settings, "_models_status_snapshot", lambda: 1 / 0
    )
    status = json.loads(_bundle(client).read("status.json"))
    assert "error" in status["models"]
    assert status["app_version"]


def test_the_bundle_is_behind_the_unlock_gate(client):
    client.post("/auth/setup", json={"password": "a password"})
    from memorymap.api import routes_auth

    routes_auth._active_tokens.clear()
    assert client.get("/support-bundle").status_code == 401


def test_building_a_bundle_is_recorded_in_the_activity_log(client):
    """It collects settings and logs; that is worth a line in the audit trail
    even though it never leaves the machine."""
    client.get("/support-bundle")
    actions = [row["action"] for row in client.get("/audit?limit=20").json()]
    assert "exported" in actions


# --- the console's own rules, asserted against the frontend -----------------


# The logs console itself (this whole section's own functions) moved to
# settings.js in the app.js split's fourth and last file (§88.3 item 4);
# copyToClipboard/showCopyFallback/copyViaTextarea are general clipboard
# helpers used well beyond the logs screen and stayed in app.js. Each test
# below reads whichever file its own function actually lives in now.


def test_the_console_does_not_authenticate_through_the_query_string():
    """The reason NDJSON was chosen over EventSource. Putting the token in the
    URL would write it into the very log being streamed."""
    source = _settings_js()
    body = _function_body(source, "startLogStream")
    assert "X-Auth-Token" in body
    assert "token=" not in body


def test_leaving_the_screen_closes_the_stream():
    """A stream held open by a tab nobody is looking at is invisible until it
    is a hundred of them."""
    source = _settings_js()
    assert 'if (name !== "logs") closeLogs();' in source


def _app_js() -> str:
    from memorymap.api.app import FRONTEND_DIR

    return (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")


def _settings_js() -> str:
    from memorymap.api.app import FRONTEND_DIR

    return (FRONTEND_DIR / "settings.js").read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """The whole of a top-level function, brace-matched.

    Every assertion below used to slice a fixed number of characters from the
    function's opening line: 400, 500, 600, 900, 1200, 1800, each one a guess
    at how long that function would stay. `renderCopyLogsLabel` grew a comment
    explaining a bug it had just been fixed for, the string the test looks for
    moved past character 600, and the suite reported a broken Copy button on a
    Copy button that was fine.

    A test that fails when a comment is added is a test nobody trusts the
    second time. This reads what the assertions have always meant: the body of
    that function, however long it is.
    """
    match = re.search(rf"(?:async )?function {re.escape(name)}\s*\(", source)
    assert match, f"{name} is gone or has been renamed"
    start = match.start()
    brace = source.index("{", match.end())
    depth, index = 0, brace
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"{name} is not brace-balanced")


# --- getting an error OUT of the log ----------------------------------------
#
# "Copy all" plus a filter can technically reach one error, but that is a
# three-step answer to "send me that error", and hand-selecting a row whose
# traceback sits in its own scrolling box is worse than it sounds.


def test_every_record_has_its_own_copy_button():
    source = _settings_js()
    start = source.index("function logRow(record) {")
    body = source[start : source.index("function logRecordText(")]
    assert "log-copy" in body
    assert "copyToClipboard(logRecordText(record)" in body


def test_copying_a_record_takes_its_traceback_with_it():
    """The traceback is the half worth having, and it lives in a separate
    element: copying the row without it would be the useless half."""
    source = _settings_js()
    body = _function_body(source, "logRecordText")
    assert "record.trace" in body


def test_a_records_copy_button_does_not_toggle_the_fold_it_sits_beside():
    source = _settings_js()
    start = source.index("function logRow(record) {")
    body = source[start : source.index("function logRecordText(")]
    assert "stopPropagation" in body


def test_copy_falls_back_when_the_clipboard_api_is_missing():
    """`navigator.clipboard` only exists in a SECURE CONTEXT. On
    http://localhost that holds, which is why this looked fine, but reach the
    app at http://192.168.1.20:8000 or through a tunnel and the whole API is
    `undefined`, so every copy button in the app becomes a no-op that says
    "couldn't copy". Worst on this screen, where the thing being copied is the
    error you are trying to report."""
    source = _app_js()
    body = _function_body(source, "copyToClipboard")
    assert "window.isSecureContext" in body
    assert "copyViaTextarea" in body
    assert "showCopyFallback" in body


def test_the_last_resort_shows_the_text_already_selected():
    """If both copy mechanisms are refused, the answer to "how do I get this
    error out" still must not be "you can't"."""
    source = _app_js()
    body = _function_body(source, "showCopyFallback")
    assert ".select()" in body
    assert "Ctrl+C" in body


def test_every_copy_path_goes_through_the_fallback():
    """A helper that only some callers use leaves the others quietly lying.
    No raw navigator.clipboard writes should remain outside the helper.

    Scans settings.js too now (§88.3 item 4 moved the logs console's own
    copy buttons there): a raw write introduced in either file should still
    be caught, not just one this split happened to touch.
    """
    app_source = _app_js()
    helper = app_source.index("async function copyToClipboard(")
    writes = [
        index
        for index in range(len(app_source))
        if app_source.startswith("navigator.clipboard.writeText", index)
    ]
    outside = [index for index in writes if not (helper < index < helper + 900)]
    assert not outside, "a copy path is still calling the clipboard API directly"
    assert "navigator.clipboard.writeText" not in _settings_js(), (
        "settings.js is calling the clipboard API directly instead of "
        "going through app.js's copyToClipboard()"
    )


def test_the_copy_button_says_what_it_will_copy():
    """"Copy all" while a filter hides 400 records is a promise it does not
    keep, and the reader would not find out until they pasted it."""
    source = _settings_js()
    body = _function_body(source, "renderCopyLogsLabel")
    assert "Copy all" in body and "shown" in body


def test_the_error_badge_leads_to_the_errors():
    """The badge is the only place a failure announces itself, so it should
    also be the shortest way to reach one."""
    source = _settings_js()
    body = _function_body(source, "renderLogErrorBadge")
    assert 'log-level").value = "error"' in body


def test_the_live_pill_is_not_left_claiming_to_be_live():
    """A deliberate abort returns early from the stream's own exit path, so the
    pill would still read "live" with nothing behind it. Found in a browser,
    not by a test, this is the test that would notice it coming back."""
    source = _settings_js()
    body = _function_body(source, "closeLogs")
    assert "setLogLive" in body


# --- the log buffer's dropped records -----------------------------------------


def test_nothing_is_reported_dropped_before_the_buffer_fills(client):
    _log(10)
    assert client.get("/logs/stats").json()["dropped"] == 0


def test_records_pushed_out_of_the_ring_are_counted(client):
    """A deque with a maxlen discards silently, so a busy hour and a quiet one
    look identical: the same 500 rows, and no way to tell whether the top row
    is the start of the story or the middle of it."""
    _log(logbuffer.MAX_RECORDS + 25)
    stats = client.get("/logs/stats").json()
    assert stats["dropped"] >= 25
    assert stats["held"] == logbuffer.MAX_RECORDS
    assert stats["capacity"] == logbuffer.MAX_RECORDS


def test_the_gap_says_how_far_back_the_log_still_reaches(client):
    _log(logbuffer.MAX_RECORDS + 5)
    assert client.get("/logs/stats").json()["dropped_since"]


def test_clearing_the_log_clears_the_gap_with_it(client):
    """Otherwise the viewer reports a hole in a log it just emptied itself."""
    _log(logbuffer.MAX_RECORDS + 5)
    client.delete("/logs")
    assert client.get("/logs/stats").json()["dropped"] == 0


def test_truncated_and_dropped_are_different_numbers(client):
    """One is gone for good; the other is one bigger `limit` away. Reporting
    them as the same thing sends a reader looking in the wrong place."""
    _log(50)
    stats = logbuffer.stats(limit=10)
    assert stats["dropped"] == 0
    assert stats["truncated"] >= 40


def test_the_records_endpoint_is_still_a_plain_list(client):
    """The stats live at their own path precisely so this shape never moved."""
    assert isinstance(client.get("/logs").json(), list)


# --- the buffer itself, and the /logs endpoints on top of it -------------------


def test_buffer_captures_and_caps(client):
    logging.getLogger("memorymap.test").info("hello from the test")

    records = client.get("/logs").json()
    assert any("hello from the test" in r["message"] for r in records)
    record = next(r for r in records if "hello from the test" in r["message"])
    assert record["level"] == "INFO"
    assert record["logger"] == "memorymap.test"


def test_ai_decisions_are_logged(client):
    client.post("/entries", json={"content": "a note to file"})

    messages = [r["message"] for r in client.get("/logs").json()]
    assert any("janitor: filed by" in m for m in messages)


def test_clear_endpoint(client):
    logging.getLogger("memorymap.test").info("about to vanish")
    # Not inside the assert: `python -O` removes assert statements, taking the
    # clear with them and leaving a test that proves nothing.
    cleared = client.delete("/logs")
    assert cleared.json() == {"cleared": True}
    # New records may arrive after the clear (request plumbing logs);
    # what matters is that the old ones are gone.
    messages = [r["message"] for r in client.get("/logs").json()]
    assert not any("about to vanish" in m for m in messages)


def test_install_is_idempotent():
    logbuffer.install()
    logbuffer.install()
    root = logging.getLogger()
    buffers = [h for h in root.handlers if isinstance(h, logbuffer.BufferHandler)]
    assert len(buffers) == 1


def test_log_noise_filter_drops_windows_proactor_chatter():
    """The Windows asyncio Proactor error is benign and must not reach the
    log viewer, but real errors still must."""
    noise = logging.LogRecord(
        "asyncio", logging.ERROR, __file__, 1,
        "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        None, None,
    )
    real = logging.LogRecord(
        "memorymap", logging.ERROR, __file__, 1, "Something actually broke", None, None
    )
    log_filter = logbuffer.NoiseFilter()
    assert log_filter.filter(noise) is False
    assert log_filter.filter(real) is True
