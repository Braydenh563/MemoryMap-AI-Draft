"""INBOX 47: the stamped-URL cache policy, and a wire-size check for the
existing compression it rides on.

**What this file is not.** `test_compression.py` (added alongside the gzip
middleware itself, commit 610def1) already proves `/app.js` comes back
`content-encoding: gzip`, that both streaming NDJSON endpoints are excluded,
and that the exclusion is read off the configured app rather than a constant.
Re-deriving that here would be the same "three sessions rebuilt existing
work" mistake CLAUDE.md warns about: curl against a live server on this
branch showed `/app.js`, every root script, `/vendor/d3.v7.min.js` and
`/css/*.css` all already gzip-compressed (515 KB on the wire for a 1.6 MB
`app.js`) before this file existed. INBOX 47's "static assets are not
compressed" did not hold up.

**What was actually missing** is `RevalidatedStatic` in `app.py`: every
static response got `Cache-Control: no-cache` regardless of whether the URL
carried a `?v=<version>` stamp, so a stamped asset (a *different URL* on
every release, per `test_asset_cache_busting.py`) still paid a revalidation
round trip it never needed. That is the actual gap this file closes and
tests.
"""

from __future__ import annotations

import gzip

from memorymap import __version__


def test_a_stamped_asset_is_immutable_and_gzipped(client):
    """`/app.js?v=<version>` is the real request the browser makes."""
    with client.stream(
        "GET", f"/app.js?v={__version__}", headers={"Accept-Encoding": "gzip"}
    ) as response:
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        assert response.headers.get("cache-control") == "public, max-age=31536000, immutable"
        raw = b"".join(response.iter_raw())
    # Belt and braces, same pattern as test_compression.py's round-trip test:
    # fetch without letting httpx decode, then gunzip it by hand.
    body = gzip.decompress(raw)
    assert body.startswith(b"//") or len(body) > 0  # app.js is real JS, not empty
    assert len(raw) < 600_000, f"gzipped app.js is {len(raw)} bytes, expected under 600 KB"


def test_an_unstamped_asset_is_not_immutable(client):
    """No `?v=` means the URL can be reused across a release, so it keeps
    asking the browser to revalidate rather than promising it never will."""
    response = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    cache_control = response.headers.get("cache-control", "")
    assert "immutable" not in cache_control
    assert cache_control == "no-cache"


def test_vendored_assets_stay_revalidated_too(client):
    """Vendored files are deliberately never stamped
    (`test_asset_cache_busting.py::test_vendored_assets_are_left_alone`), so
    they must not accidentally pick up the immutable treatment either."""
    response = client.get("/vendor/d3.v7.min.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache"


def test_a_query_string_that_only_contains_v_as_a_substring_is_not_stamped(client):
    """`?vv=1` or `?rev=1` must not be mistaken for the app's own `?v=` stamp."""
    response = client.get("/app.js?vv=1", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("cache-control") == "no-cache"


def test_chat_stream_never_carries_content_encoding(client):
    """The one response class this change must never touch. Streamed NDJSON
    is excluded from gzip entirely (see test_compression.py); this asserts
    the same invariant holds for the real route, with a real (AI-unavailable)
    request, rather than only against the middleware's configured exclusion
    list."""
    with client.stream(
        "POST", "/chat/stream", headers={"Accept-Encoding": "gzip"}, json={"question": "hey"}
    ) as response:
        assert "content-encoding" not in response.headers
        # Drain the stream so the test client's connection closes cleanly.
        for _ in response.iter_lines():
            pass
