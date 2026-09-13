"""The documents editor talks to one adapter, not to a textarea.

DOCUMENTS_PLAN Phase 2 step 2 makes `docSurface()` the only thing that knows
what the document's editing surface actually *is*: a `<textarea>` before the
CodeMirror bundle has loaded, a CodeMirror 6 `EditorView` afterwards. The
value of that arrangement is entirely in the "only": a second place that
reads `$("doc-content").value` is a second place that keeps working against
the fallback while the real editor holds different text, and the failure is
silent, the document simply stops saving what you typed.

Python cannot see the DOM, so this is a lint in the same family as
test_frontend_ids.py and test_frontend_handlers.py: it reads the source and
fails the build when a call site goes round the adapter. The markers
`DOC-SURFACE-BEGIN` / `DOC-SURFACE-END` in documents.js bracket the adapter's
own bodies, which is the one region allowed to touch the element directly.

Deliberately not a regex over "every mention of doc-content": the id is still
in the markup, the fallback textarea still needs its placeholder set and its
class toggled, and a lint that forbade the string outright would be widened
the first time someone needed one of those. What it forbids is the two shapes
that actually cause the bug: reading or writing the box's *text and
selection* through `$("doc-content")`, and stashing the element in a local so
the same reads can happen a line later under another name.
"""

from __future__ import annotations

import re
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
DOCUMENTS_JS = FRONTEND / "documents.js"
EDITOR_JS = FRONTEND / "editor.js"
INDEX = FRONTEND / "index.html"
CSS_DIR = FRONTEND / "css"

BEGIN = "DOC-SURFACE-BEGIN"
END = "DOC-SURFACE-END"

#: The properties that carry the document's text and the caret in it. Every
#: one of these on the fallback element is a read that CodeMirror would have
#: answered differently.
SURFACE_PROPS = (
    "value",
    "selectionStart",
    "selectionEnd",
    "setSelectionRange",
    "setRangeText",
    "scrollTop",
    "scrollLeft",
)

DIRECT_ACCESS = re.compile(
    r'\$\("doc-content"\)\s*(?:\?\.)?\.(' + "|".join(SURFACE_PROPS) + r")\b"
)

#: `const box = $("doc-content")` and friends: the element in a local is the
#: same access one line later, and it is how the direct check above gets
#: quietly defeated.
ELEMENT_BINDING = re.compile(r'(?:const|let|var)\s+\w+\s*=\s*\$\("doc-content"\)')


def _adapter_span(body: str) -> tuple[int, int]:
    start = body.find(BEGIN)
    end = body.find(END)
    assert start != -1, f"{BEGIN} marker is missing from documents.js"
    assert end > start, f"{END} marker is missing or before {BEGIN}"
    return start, end


def _offences(body: str, pattern: re.Pattern[str], span: tuple[int, int] | None) -> list[str]:
    out = []
    for match in pattern.finditer(body):
        if span and span[0] <= match.start() < span[1]:
            continue
        line = body.count("\n", 0, match.start()) + 1
        out.append(f"line {line}: {match.group(0)}")
    return out


def test_documents_js_reads_the_surface_only_through_the_adapter():
    body = DOCUMENTS_JS.read_text(encoding="utf-8")
    span = _adapter_span(body)
    bad = _offences(body, DIRECT_ACCESS, span)
    assert not bad, (
        "documents.js reads the document's text or caret straight off the "
        "fallback textarea:\n  " + "\n  ".join(bad) + "\nUse docSurface() "
        "instead: with CodeMirror mounted the textarea holds stale text."
    )


def test_documents_js_does_not_stash_the_element_outside_the_adapter():
    body = DOCUMENTS_JS.read_text(encoding="utf-8")
    span = _adapter_span(body)
    bad = _offences(body, ELEMENT_BINDING, span)
    assert not bad, (
        "documents.js binds the fallback textarea to a local outside the "
        "adapter:\n  " + "\n  ".join(bad) + "\nThe adapter is the only code "
        "that may hold the element."
    )


def test_editor_js_never_touches_the_document_textarea():
    body = EDITOR_JS.read_text(encoding="utf-8")
    bad = _offences(body, DIRECT_ACCESS, None) + _offences(body, ELEMENT_BINDING, None)
    assert not bad, (
        "editor.js reaches into the document's textarea:\n  "
        + "\n  ".join(bad)
        + "\nIt has docSurface() for this."
    )


def test_index_html_has_the_codemirror_host_and_the_editor_stylesheet():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="doc-editor"' in html, (
        "the CodeMirror view mounts into #doc-editor inside #doc-source-wrap; "
        "the id has to exist in the markup or tests/test_frontend_ids.py "
        "cannot check it and $(\"doc-editor\") finds nothing"
    )
    assert '/css/09-editor.css' in html, "09-editor.css is not linked"
    # After 08-consistency.css: the editor's own layout rules are the last
    # word on the panes they lay out.
    assert html.index("/css/08-consistency.css") < html.index("/css/09-editor.css")
    assert (CSS_DIR / "09-editor.css").exists(), "frontend/css/09-editor.css is missing"


def test_the_bundle_is_loaded_on_demand_and_not_at_boot():
    html = INDEX.read_text(encoding="utf-8")
    body = DOCUMENTS_JS.read_text(encoding="utf-8")
    assert "<script src=\"/vendor/codemirror" not in html, (
        "the CodeMirror bundle is 772 KB and most sessions never open a "
        "document; documents.js injects it the first time one is opened"
    )
    assert "function loadCodeMirror" in body, "loadCodeMirror() is missing"
    assert "/vendor/codemirror/codemirror.min.js" in body


def test_the_block_live_renderer_is_gone():
    """`renderDocLive` and its `.lp-*` rows, retired once Live is decorations.

    Live and Source are one CodeMirror view with a decorations compartment
    now (DOCUMENTS_PLAN Phase 2 decision 3), so the per-paragraph renderer
    and its rules are deleted rather than left dead. The CSS check strips
    comments first: the rules are gone, and the note that says where they
    went names them, which is the whole point of leaving a note.
    """
    body = DOCUMENTS_JS.read_text(encoding="utf-8")
    assert "function renderDocLive" not in body
    assert "lp-src" not in body
    css = "".join(p.read_text(encoding="utf-8") for p in sorted(CSS_DIR.glob("*.css")))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert ".lp-" not in css
    assert "doc-live" not in css
