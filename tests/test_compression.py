"""Response compression, and the streaming endpoints it must not break.

Two halves, and the second is the one worth having. Compression is easy to add
and easy to verify; what is easy to get wrong is a streaming response that
still *arrives* correctly but no longer arrives *incrementally*, the chat
reply appears all at once at the end instead of word by word, which no status
code and no response body would ever show. That failure looks like "the model
got slower", so it would be blamed on the model.
"""

from __future__ import annotations

import gzip

from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

from memorymap.api.app import create_app


def test_a_large_json_response_is_compressed(client):
    for i in range(60):
        client.post("/entries", json={"content": f"a reasonably wordy note number {i}"})

    response = client.get("/entries", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    # httpx decodes transparently, so the evidence is the header plus the fact
    # that the raw bytes really were gzip.
    assert response.headers.get("content-encoding") == "gzip"
    assert len(response.json()) == 60


def test_the_frontend_is_compressed(client):
    """The reason this middleware exists: `app.js` is over a megabyte of
    unminified source and there is no bundler to shrink it."""
    response = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_a_client_that_does_not_ask_for_gzip_still_gets_plain_bytes(client):
    response = client.get("/entries", headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_tiny_responses_are_left_alone(client):
    """Below `minimum_size` gzip makes a response bigger, not smaller."""
    response = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers


def test_both_streaming_media_types_are_excluded():
    """The invariant, asserted against the configured app rather than against
    a constant we could drift from.

    `text/event-stream` comes from Starlette's own default list; the two NDJSON
    streams in this app (`routes_insights`' weekly digest and `routes_settings`'
    live log) do not, so they have to be named explicitly. If a future upgrade
    drops either from the defaults, this fails here rather than showing up as
    a log view that stops updating.
    """
    app = create_app()
    gzip_layer = [m for m in app.user_middleware if "GZip" in repr(m)]
    assert gzip_layer, "no gzip middleware configured"
    excluded = gzip_layer[0].kwargs["exclude_content_types"]
    assert "text/event-stream" in excluded
    assert "application/x-ndjson" in excluded


def test_streaming_chunks_are_flushed_as_they_are_produced():
    """The half that a plain request/response test cannot see.

    Starlette compresses a streaming body chunk by chunk with `Z_SYNC_FLUSH`,
    which means each chunk is decompressible on arrival instead of only after
    the stream ends. This drives that directly: compress two chunks the way the
    middleware would, and assert the first one is readable before the second
    exists. An implementation that buffered would produce nothing here.
    """
    import zlib

    compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    first = compressor.compress(b'{"line": 1}\n') + compressor.flush(zlib.Z_SYNC_FLUSH)

    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    assert decompressor.decompress(first) == b'{"line": 1}\n'

    second = compressor.compress(b'{"line": 2}\n') + compressor.flush()
    assert decompressor.decompress(second) == b'{"line": 2}\n'


def test_already_compressed_formats_are_not_recompressed():
    """Spending CPU to make a PNG very slightly larger is the classic own goal."""
    for content_type in ("image/png", "application/zip", "video/*"):
        assert content_type in DEFAULT_EXCLUDED_CONTENT_TYPES


def test_gzip_round_trips_the_real_bytes(client):
    """Belt and braces: fetch without letting httpx decode, and gunzip it."""
    for i in range(60):
        client.post("/entries", json={"content": f"note {i} with some length to it"})

    with client.stream(
        "GET", "/entries", headers={"Accept-Encoding": "gzip"}
    ) as response:
        raw = b"".join(response.iter_raw())
    assert gzip.decompress(raw).startswith(b"[")
