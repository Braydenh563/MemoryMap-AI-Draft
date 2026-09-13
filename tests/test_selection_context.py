"""Selecting text and asking about it: what must stay true.

REDESIGN.md §R7.1 item 1, quoted from the request behind it: *"able to
highlight text and say something in the chat and the agent gets the context of
what is highlighted and cursor position."* It is ranked the highest ratio of
"feels capable" to work in that whole section.

Source lints, because the behaviour is JavaScript and this suite cannot run a
browser. Each one stands for something that was measured against a running
Chromium when it was built, and would go silently wrong if the code moved:
the live view is the *default* document view, so a regression here is not a
corner case.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_the_selection_bar_offers_asking_about_the_selection():
    editor = _read("editor.js")
    assert "ask: true" in editor, (
        "the ask action lives in SELECTION_BAR_ACTIONS so it is offered "
        "wherever a selection already raises the bar"
    )
    assert "selection-bar-rule" in editor, (
        "it is not a ninth way to change the text, the hairline is what says "
        "so, and a wider gap alone did not read as a boundary"
    )


def test_the_ask_action_never_formats_and_the_format_actions_never_ask():
    """One handler, two jobs, and the wrong branch would either mangle the
    note or send nothing."""
    editor = _read("editor.js")
    start = editor.index("button.addEventListener(\"mousedown\"")
    handler = editor[start : start + 700]
    assert "if (action.ask)" in handler
    ask_at = handler.index("if (action.ask)")
    apply_at = handler.index("applyMarkdown(action.md")
    assert ask_at < apply_at, "the ask branch has to return before applyMarkdown"


def test_offsets_are_revalidated_at_send_not_trusted_from_attach_time():
    """The part of odysseus's `getSelectionContext()` worth porting exactly.
    Between selecting a passage and pressing send the user can type above it,
    undo, or rewrite the note, stored offsets then point at different words,
    and sending those hands the model text from a region the user is no longer
    looking at, under a line number that now belongs to someone else."""
    app = _read("app.js")
    assert "function revalidateSelection(context)" in app
    send = app[app.index("const sentSelection = ") : app.index("const sentSelection = ") + 400]
    assert "revalidateSelection(attachedSelection)" in send, (
        "sendChat must re-check, not read attachedSelection's stored offsets"
    )
    guard = app[app.index("function revalidateSelection(context)") :][:1800]
    for outcome in ('"exact"', '"moved"', '"gone"', '"unknown"'):
        assert outcome in guard, (
            f"{outcome} is one of the four things that can be true of a stored "
            "selection by send time, and each is said plainly rather than "
            "papered over"
        )


def test_a_position_that_cannot_be_confirmed_is_not_claimed():
    app = _read("app.js")
    block = app[app.index("function selectionContextBlock(context)") :][:900]
    assert '"gone"' in block and '"unknown"' in block, (
        "the block the model reads has to stop claiming a line and column once "
        "the passage can no longer be found"
    )


def test_a_selection_is_already_in_the_documents_coordinates():
    """**What this used to check, and why it now checks the opposite.**

    The live view was one `<textarea>` per paragraph, each starting at offset
    zero, so a selection in the last paragraph of a long document reported
    itself as line 2 unless `selectionContextFrom` translated it through
    `docLiveBlockOffset`. This pinned that translation.

    DOCUMENTS_PLAN Phase 2 made Live and Source one CodeMirror view, so there
    are no paragraph-local offsets left to translate and the translation was
    deleted. The invariant the old test was really protecting is unchanged and
    is what is pinned here: what reaches the model is the *document's* line
    and column. Keeping the old assertions would have pinned the workaround
    rather than the thing it worked around.

    Measured on the engine by `scratchpad/ui-sweeps/cm-editor.js`: a selection
    made in the editor reports `surfaceId: "doc-content"`, `kind: "document"`
    and the line it is actually on.
    """
    editor = _read("editor.js")
    assert "docLiveBlockOffset" not in editor, (
        "the per-paragraph translation is gone with the per-paragraph boxes"
    )
    start = editor.index("function selectionContextFrom(")
    body = editor[start : editor.index("function selectionOffsets(")]
    assert (
        "return selectionOffsets(textarea, textarea.selectionStart, textarea.selectionEnd);"
        in body
    ), "a selection is reported straight, in the surface's own coordinates"
    documents = _read("documents.js")
    assert "function docLiveBlockOffset" not in documents


def test_formatting_addresses_the_surface_and_is_not_a_silent_no_op():
    """`applyMarkdown(kind, boxId)` resolves the box it acts on by id, and a
    box it cannot resolve makes every formatting button a no-op that still
    draws: this repo's "a policy silently refusing the work" shape, found live
    the day the selection bar started appearing over live-view paragraphs.

    The id it resolves used to be a generated `doc-live-block-N` on whichever
    paragraph textarea existed at that moment. There is one editor now, and it
    reports `doc-content` in every view, so what has to hold is that the
    lookup goes through the adapter rather than through `$(id)`: with
    CodeMirror mounted `$("doc-content")` is a hidden fallback holding stale
    text, and formatting it would draw nothing and change nothing.
    """
    documents = _read("documents.js")
    assert "function docSurfaceById(id)" in documents
    start = documents.index("function applyMarkdown(")
    body = documents[start : start + 400]
    assert "docSurfaceById(boxId)" in body, (
        "applyMarkdown resolves its box through the adapter, so `doc-content` "
        "reaches the engine rather than the fallback element"
    )
    start = documents.index("function wrapDocSelection(")
    assert "docSurfaceById(boxId)" in documents[start : start + 600]


def test_applying_a_marker_tells_the_box_it_changed():
    """The two toggle-*off* branches of `wrapDocSelection` ended with
    `finishMarkdownEdit`; the branch that applies formatting, the one that
    runs almost every time, did the doc-content half inline instead. Measured
    on a live-view paragraph: the block showed `**bold**` and the document
    underneath never received it, `input` fired 0 times."""
    documents = _read("documents.js")
    start = documents.index("function wrapDocSelection(")
    end = documents.index("async function exportDocumentMarkdown()")
    body = documents[start:end]
    assert body.count("finishMarkdownEdit(box, boxId)") == 3, (
        "all three exits of wrapDocSelection, both toggle-offs and the apply "
        ", have to end the same way, or the box's own listeners never hear it"
    )
    assert "markDocDirty();\n  renderDocPreview();\n}" not in body, (
        "the inline doc-content-only ending is what caused the bug; it must "
        "not come back"
    )
