"""Editing a file in place, where it is honest, and where it is refused.

REDESIGN.md §R7.1 item 2, from the request: *"all the files should be
managable, viewable and editable in the library and document/file/text
editor."*

`core/docview.py` has said since it was written that the viewer is read-only,
and its reason is right: extraction is one-way, and text pulled out of a .docx
is not a .docx. This does not widen that rule, it draws the line where the
rule's own reason stops applying. For a .md, a .txt, a .csv or a source file,
"extraction" is `bytes.decode()`: the text *is* the file.

The refusals matter as much as the saves. §R7.1 asked for the honest reason in
the UI rather than a control that quietly does nothing, so every refusal
carries a message written to be shown.
"""

from __future__ import annotations

import io
from pathlib import Path

from memorymap.core import docview


def _viewed(path: Path):
    return docview.extract(path)


def test_a_text_file_may_be_edited(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("# Heading\n\nSome text.\n", encoding="utf-8")
    editable, message = docview.editability(path, _viewed(path))
    assert editable is True
    assert message == ""


def test_a_code_file_may_be_edited(tmp_path: Path):
    path = tmp_path / "script.py"
    path.write_text("print('hi')\n", encoding="utf-8")
    assert docview.editability(path, _viewed(path))[0] is True


def test_a_converted_document_may_not_and_says_why(tmp_path: Path):
    """The reason is the teaching bit: a .docx is not the text pulled out of
    it. A greyed-out button with no explanation is the dead end §R7.1 named."""
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK\x03\x04 not really a docx")
    editable, message = docview.editability(path, _viewed(path))
    assert editable is False
    assert "formatting" in message and "images" in message
    assert ".docx" in message


def test_an_unknown_type_may_not(tmp_path: Path):
    path = tmp_path / "thing.bin"
    path.write_bytes(b"\x00\x01")
    editable, message = docview.editability(path, _viewed(path))
    assert editable is False
    assert "no editor" in message


def test_a_truncated_file_may_not_because_saving_would_drop_the_rest(tmp_path: Path):
    """The one refusal that protects data rather than honesty: the editor was
    only ever shown the first `MAX_VIEW_CHARS`, so saving what it holds would
    delete everything past that point."""
    path = tmp_path / "huge.txt"
    path.write_text("x" * (docview.MAX_VIEW_CHARS + 100), encoding="utf-8")
    viewed = _viewed(path)
    assert viewed.truncated is True
    editable, message = docview.editability(path, viewed)
    assert editable is False
    assert "drop everything" in message


def test_a_missing_file_may_not(tmp_path: Path):
    path = tmp_path / "gone.txt"
    editable, message = docview.editability(path, _viewed(path))
    assert editable is False
    assert "missing" in message


def test_writing_back_is_lossless_and_does_not_translate_newlines(tmp_path: Path):
    """`newline=""` is not decoration: without it a Windows round trip turns
    every "\\n" into "\\r\\n" on save, so a file grows a byte a line every
    time it is opened and saved."""
    path = tmp_path / "round.txt"
    path.write_text("one\ntwo\n", encoding="utf-8")
    docview.write_text_file(path, "one\ntwo\nthree\n")
    assert path.read_bytes() == b"one\ntwo\nthree\n"
    assert _viewed(path).text == "one\ntwo\nthree\n"


def _attach(client, name: str, data: bytes) -> int:
    entry = client.post("/entries", json={"content": f"A note with {name}"}).json()
    response = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["attachments"][-1]["id"]


def test_the_route_refuses_a_docx_even_when_asked_directly(client):
    """The `editable` flag the GET returned is a hint for drawing the UI, not
    an authority: the file can have changed between the two calls, and a
    client is never the thing that decides what may be overwritten."""
    attachment_id = _attach(client, "report.docx", b"PK\x03\x04 not a real docx")

    read = client.get(f"/files/{attachment_id}/text").json()
    assert read["editable"] is False
    assert read["edit_message"]

    refused = client.put(f"/files/{attachment_id}/text", json={"text": "overwritten"})
    assert refused.status_code == 409
    assert "formatting" in refused.json()["detail"]


def test_the_route_saves_a_text_file_and_reports_it_back(client):
    attachment_id = _attach(client, "notes.md", b"# Before\n")

    read = client.get(f"/files/{attachment_id}/text").json()
    assert read["editable"] is True
    assert read["text"] == "# Before\n"

    saved = client.put(f"/files/{attachment_id}/text", json={"text": "# After\n\nMore.\n"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["text"] == "# After\n\nMore.\n"
    assert client.get(f"/files/{attachment_id}/text").json()["text"] == "# After\n\nMore.\n"


def test_the_reason_is_computed_before_the_empty_body_return():
    """A .docx on an install without markitdown extracts to nothing, so the
    viewer's "no readable text" branch returns early. The read-only reason
    used to be computed past that return and was therefore never shown for
    exactly the files that most needed it, measured live: the note read only
    "Importing documents needs the optional markitdown package"."""
    app = (Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text(
        encoding="utf-8"
    )
    start = app.index("const editNotes = [];")
    empty_return = app.index('if (!body.trim()) {', start - 4000)
    assert start < empty_return, (
        "the editability branch has to run before the empty-body return, or a "
        "file with no extractable text never says why it cannot be edited"
    )


# --- The HTML preview pane (§R7.1 item 4) -----------------------------------


def test_the_preview_serves_the_files_own_html(client):
    attachment_id = _attach(
        client, "page.html", b"<html><head><style>body{background:#eef}</style></head><body><h1>Hi</h1></body></html>"
    )
    response = client.get(f"/files/{attachment_id}/html-preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Hi</h1>" in response.text


def test_the_preview_refuses_anything_that_is_not_html(client):
    """One suffix, checked here rather than through an allowlist that grows.
    `core/docview.py`'s rule is that nothing new is served to the browser
    inline; this is the single, stated exception and it must stay single."""
    attachment_id = _attach(client, "notes.md", b"# Not a page\n")
    assert client.get(f"/files/{attachment_id}/html-preview").status_code == 404


def test_the_preview_response_carries_its_own_policy(client):
    """**The whole reason this is a route rather than a `blob:` in the
    browser.** A `blob:` document inherits its creator's CSP, so the app's
    `style-src 'self'` applied to the framed page and refused the page's own
    `<style>`, measured in Chromium, with `background-color` coming back
    transparent on a page that sets `#eef`. A same-origin response carries its
    own policy, and this asserts every token that policy needs."""
    attachment_id = _attach(client, "page.html", b"<html><body>hi</body></html>")
    policy = client.get(f"/files/{attachment_id}/html-preview").headers[
        "content-security-policy"
    ]
    assert policy.startswith("sandbox;"), (
        "the sandbox is what makes rendering a file this app did not write "
        "safe at all: opaque origin, no scripts, no forms, no navigation"
    )
    assert "script-src 'none'" in policy
    assert "style-src 'unsafe-inline'" in policy, (
        "a preview that strips the file's own styling is not a preview of "
        "that file"
    )
    assert "img-src data:" in policy and "img-src data: 'self'" not in policy, (
        "inline images only: with 'self' a framed page could probe this "
        "app's own endpoints by pointing an <img> at them"
    )
    assert "frame-ancestors 'self'" in policy, (
        "default-src 'none' covers frame-ancestors too, so without this the "
        "response forbids being framed at all and the pane renders "
        "chrome-error://: measured, after exactly that shipped once"
    )


def test_the_preview_is_the_one_response_allowed_to_be_framed(client):
    attachment_id = _attach(client, "page.html", b"<html><body>hi</body></html>")
    preview = client.get(f"/files/{attachment_id}/html-preview")
    assert preview.headers["x-frame-options"] == "SAMEORIGIN"
    assert preview.headers["x-content-type-options"] == "nosniff"
    # Everything else still refuses, including the file's own bytes.
    assert client.get("/health").headers["x-frame-options"] == "DENY"


def test_the_app_may_frame_blobs_and_itself_but_nothing_else():
    from memorymap.core import security

    policy = security.build_csp([])
    assert "frame-src 'self' blob:" in policy
    assert "frame-ancestors 'none'" in policy, (
        "the other direction is unchanged: nothing may frame MemoryMap"
    )


# --- Syntax highlighting and text export (§R7.1 items 3 and 5) --------------


def _editor_js() -> str:
    return (Path(__file__).resolve().parents[1] / "frontend" / "editor.js").read_text(
        encoding="utf-8"
    )


def test_the_highlighter_builds_nodes_and_never_markup():
    """A file's own text is exactly the untrusted input a markup-assembling
    highlighter turns into an injection, and this app's CSP would not stop a
    same-origin one. Driven live with a .js file containing
    `<img src=x onerror=…>` and `<b id="pwned">`: no element appeared, no
    global was set, and the text rendered verbatim."""
    editor = _editor_js()
    body = editor[editor.index("function highlightCodeInto(") :]
    assert "innerHTML" not in body, (
        "spans are built with textContent, an innerHTML here is the bug"
    )
    assert "document.createTextNode" in body and "span.textContent" in body


def test_the_highlighter_cannot_loop_on_a_zero_length_match():
    editor = _editor_js()
    body = editor[editor.index("function highlightCodeInto(") :]
    assert "scanner.lastIndex++" in body, (
        "a zero-length match with a /g regex is an infinite loop; none of the "
        "patterns can produce one and this makes that not matter"
    )


def test_no_syntax_pattern_nests_a_quantifier():
    """CI runs CodeQL, which has caught a real polynomial-ReDoS in code
    written in this repo. The string rules use the `[^"\\\\\\n]|\\\\.` shape,
    whose alternatives are disjoint on their first character."""
    editor = _editor_js()
    body = editor[editor.index("function codeScanner(") : editor.index("function codeFamilyFor(")]
    assert ")+*" not in body and ")**" not in body and ")++" not in body


def test_keywords_do_not_use_the_user_chosen_accent():
    """Settings → Appearance writes any hex onto `--accent`, so a keyword
    painted with it can be set to a colour with no contrast against the code
    behind it. Found on a profile whose accent was #cdd5e0: keywords measured
    `rgb(205, 213, 224)` against near-white text. Strings, numbers and
    comments reuse `--ok`, `--warn` and `--muted`, none of which are settable."""
    css_dir = Path(__file__).resolve().parents[1] / "frontend" / "css"
    misc = (css_dir / "07-whiteboard-misc.css").read_text(encoding="utf-8")
    rule = misc[misc.index(".lightbox-doc-pre .tok-keyword") :][:200]
    assert "var(--syntax-keyword)" in rule
    assert "var(--accent)" not in rule
    tokens = (css_dir / "00-tokens-shell.css").read_text(encoding="utf-8")
    assert tokens.count("--syntax-keyword:") == 3, (
        "light, the manual dark toggle, and the OS-default dark block, CSS "
        "has no variables-for-variables, which is why that file already "
        "carries the dark palette twice"
    )


def test_export_names_the_file_after_what_the_text_is():
    """Save hands back the file as it is on disk; Export text hands back what
    the viewer is showing, which for a scanned PDF is the only readable form
    of it the app has. `report.pdf` exports as `report.md` or `report.txt`
    depending on `kind`, never as something claiming to still be a PDF."""
    app = (Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text(
        encoding="utf-8"
    )
    body = app[app.index("const exportTextBtn = actionBtn(") :][:900]
    assert 'kind === "markdown" ? "md" : "txt"' in body
    assert "replace(" in body, "the source file's own extension is stripped first"
