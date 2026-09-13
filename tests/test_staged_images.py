"""A staged image URL must never reach the database.

REDESIGN.md §R7.2 deliberately held the note-composer's inline images back
for a session over one failure mode, and its wording is the specification
this file enforces:

> Every path that can save the composer has to rewrite the staged markers
> first; one that does not leaves `staged:`/`blob:` URLs inside saved note
> content: **corrupted notes, which is worse than the recoverable orphan it
> replaces** (orphans already have a collector: Library → orphan cleanup,
> `media_gc.find_orphaned_media`). Do it with a test per save path, not as a
> drive-by.

"A test per save path" is the weaker version of what is built, and the
difference matters: a list of save paths is an enumeration a *new* save path
joins by being forgotten, this repo's own recurring defect shape. Every
request in the frontend goes through `api()`, so the check sits there and a
save path written next year is covered by existing.

These are source lints because the invariant lives in JavaScript and this
suite cannot run a browser. They fail loudly if the guard is moved or
weakened, which is the whole point: nothing else in the test suite would
notice a corrupted note until a user reported a picture that never loads.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_every_request_passes_through_the_guard():
    source = _source()
    start = source.index("async function api(path, options = {})")
    body = source[start : start + 2000]
    guard = body.index("refuseStagedUrls(fetchOptions.body)")
    fetch = body.index("await fetch(path")
    assert guard < fetch, (
        "the staged-URL guard has to run before the request leaves, after it, "
        "the corrupted note is already saved"
    )


def test_the_guard_covers_both_schemes_and_only_the_embed_shape():
    source = _source()
    line = re.search(r"const STAGED_IN_BODY = /(.+?)/;", source)
    assert line, "STAGED_IN_BODY is what defines the shape being refused"
    pattern = line.group(1)
    assert "staged" in pattern and "blob" in pattern, (
        "a note can hold either: `staged:` is this app's placeholder, `blob:` "
        "is the object URL a preview renders from"
    )
    assert pattern.startswith(r"]\("), (
        "match the markdown embed shape, not the bare scheme, a note that "
        "mentions the word 'staged:' in prose must still save"
    )


def test_the_guard_throws_rather_than_repairing():
    source = _source()
    start = source.index("function refuseStagedUrls(body)")
    body = source[start : start + 400]
    assert "throw new Error" in body, (
        "a silent repair would ship a note missing its picture; a throw leaves "
        "the note unsaved in the box where nothing is lost"
    )


def test_committing_staged_images_is_always_followed_by_the_rewrite():
    """`commitCaptureImages()` returns the map from staged key to real URL.
    A call site that uploads but never rewrites has done the expensive half
    and none of the useful half, the note still points at dead keys."""
    source = _source()
    for match in re.finditer(r"await commitCaptureImages\(\)", source):
        window = source[match.end() : match.end() + 400]
        assert "rewriteStagedUrls" in window, (
            "every commitCaptureImages() call has to rewrite the note body "
            f"with what it returned (call site near offset {match.start()})"
        )
