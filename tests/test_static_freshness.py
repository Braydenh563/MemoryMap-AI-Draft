"""The frontend is served so a cache cannot hand back yesterday's build.

**A desktop-app bug hiding in a header.** `StaticFiles` sends `last-modified`
and an `etag` but no `Cache-Control`, and a response with neither
`Cache-Control` nor `Expires` is one an HTTP cache may reuse *without asking*, 
for a heuristic fraction of its age (RFC 9111 §4.2.2). In a browser you press
reload and never notice. The desktop shell has no reload, is a WebView2/WebKit
instance with its own on-disk cache, and restarts the *process* without
invalidating any of it, so after an update it can go on running the previous
`app.js` indefinitely.

This is the standing explanation for a class of report this project keeps
getting: "that button is still broken" for a button whose fix is in the file.
The recycle bin's *Empty now* is the case that prompted this: §35F replaced the
`window.confirm` that pywebview does not implement, the flow was then driven
end to end in a real browser against this server (dialog opens, notes go, the
server reports an empty bin), and it was still reported broken afterwards.

`no-cache` is not `no-store`. The file is still cached and the conditional
request still answers 304 from the etag, all that is removed is the guessing.
"""

from __future__ import annotations

import re

import pytest

# style.css split into multiple linked files (ROADMAP.md Priority 0 item 2);
# one representative path under /css/ stands in for what "/style.css" used to
# check here: this test is about RevalidatedStatic's header behaviour for
# any static path, not about that one file's content, and test_api_entries.py
# separately confirms every split file individually resolves to 200.
@pytest.mark.parametrize(
    "path",
    ["/", "/app.js", "/whiteboard.js", "/graph.js", "/css/00-tokens-shell.css", "/index.html"],
)
def test_the_frontend_must_be_revalidated(ai_client, path):
    response = ai_client.get(path)
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "")


def test_it_is_no_cache_and_not_no_store(ai_client):
    """The difference matters: `no-store` would re-download 650KB of app.js on
    every navigation of a local-first app that is meant to be instant."""
    header = ai_client.get("/app.js").headers.get("cache-control", "")
    assert "no-store" not in header


def test_the_validators_are_still_there(ai_client):
    """`no-cache` means "ask first", and asking is only cheap if there is
    something to ask with. Without a validator every check would be a full
    re-download."""
    headers = ai_client.get("/app.js").headers
    assert headers.get("etag") or headers.get("last-modified")


def test_the_page_has_no_inline_script_left():
    """The other half of the same class of report, and the reason the
    anti-flash theme bootstrap now lives in `theme-boot.js`.

    The CSP carries no `'unsafe-inline'`, so an inline `<script>` has to be
    named in the header by sha256 hash, and a hash is a second copy of the
    file that can disagree with the first. `CspForPage` recomputes it when
    index.html changes, which closed the stale-server case, but the report
    came back anyway:

        [browser/csp] blocked script-src-elem: inline

    and when it does, the block that is refused is the one that applies the
    saved theme before first paint, so the app renders in its default look
    with the resolved light/dark mode never applied. Any path that pairs one
    version of the page with the other version's header brings it straight
    back, and a browser cache is very good at finding such paths.

    A same-origin file is covered by `script-src 'self'` unconditionally,
    with no second copy of anything to fall out of step. So the rule is not
    "get the hash right", it is **no inline scripts in this page at all**, 
    which is a thing a test can actually hold.
    """
    from pathlib import Path

    index = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    # Comments stripped first: this file's comments explain the rule and
    # quote the very markup being searched for, so scanning them finds the
    # explanation and calls it the offence.
    html = re.sub(r"<!--.*?-->", "", index.read_text(encoding="utf-8"), flags=re.DOTALL)
    # `<script>` or `<script type=…>` with no `src`, the opening tag of an
    # inline block. A `<script src=…>` always carries src before the ">".
    #
    # `re.IGNORECASE`: CodeQL flagged the bare version (py/bad-tag-filter,
    # "does not match upper case <SCRIPT> tags"), and it was right to. HTML
    # tag and attribute names are case-insensitive, so a bare regex here
    # would wave `<SCRIPT>` or `<Script Src=…>` straight through: the
    # opposite of what a lint guarding "no inline scripts" is for.
    # index.html is a file this app ships, not user input, so there is no
    # attacker crafting a case trick past this specific check today, but a
    # regex that silently mismatches on case is exactly the "zero-match
    # regex reports the page clean while an inline script sits right there"
    # failure this file's own docstring already warns about, one line up
    # from this one.
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html, flags=re.IGNORECASE)
    assert not inline, f"index.html has inline script blocks again: {inline}"


def test_the_inline_scanner_catches_upper_case_script_tags():
    """CodeQL's actual finding (py/bad-tag-filter), pinned down so the fix
    above cannot regress silently: HTML tag names are case-insensitive, and
    `<SCRIPT>`/`<Script Src=…>` are exactly as inline (or exactly as
    external) as their lower-case spellings. A scanner that only recognises
    one case is a scanner an inline script can walk straight past."""
    pattern = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", flags=re.IGNORECASE)
    assert pattern.findall("<SCRIPT>alert(1)</SCRIPT>")
    assert pattern.findall("<Script>alert(1)</Script>")
    # And the external form, in any case, still counts as external, this
    # must not start flagging every ordinary <script src> in the page.
    assert not pattern.findall('<SCRIPT SRC="/app.js"></SCRIPT>')
