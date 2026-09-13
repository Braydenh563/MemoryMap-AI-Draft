"""What kind of file a document is.

`normalise` is the whole surface worth testing: everything else in the module
is data, and the one thing that can go wrong at runtime is a value arriving in
a spelling nobody anticipated. Its contract is deliberately forgiving, it
never raises, and it falls back rather than refusing, because the field only
describes how to *display* a document, and failing a save over it would refuse
someone's writing on account of its label.
"""

from __future__ import annotations

import pytest

from memorymap.core import filetypes


@pytest.mark.parametrize(
    "sent",
    ["py", ".py", "PY", " .Py ", "script.py", "/tmp/some/script.py"],
)
def test_every_spelling_of_a_type_normalises_to_the_same_one(sent):
    assert filetypes.normalise(sent) == "py"


@pytest.mark.parametrize("sent", [None, "", "   ", "wat", ".exe", "no-dot-here"])
def test_anything_unknown_falls_back_to_markdown(sent):
    assert filetypes.normalise(sent) == filetypes.DEFAULT_FILE_TYPE


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("yml", "yaml"), ("markdown", "md"), ("tsx", "ts"), ("sh", "bash"), ("htm", "html")],
)
def test_aliases_collapse_onto_one_entry(alias, canonical):
    """The picker offers one entry per language, not five spellings of it."""
    assert filetypes.normalise(alias) == canonical


def test_no_alias_shadows_a_real_type():
    """An alias for something that is also in the table would make the
    picker's own value normalise to a different one."""
    real = {ft.ext for ft in filetypes.FILE_TYPES}
    assert not (set(filetypes.ALIASES) & real)


def test_every_alias_points_at_a_type_that_exists():
    real = {ft.ext for ft in filetypes.FILE_TYPES}
    assert set(filetypes.ALIASES.values()) <= real


def test_get_never_returns_none():
    assert filetypes.get("nonsense").ext == filetypes.DEFAULT_FILE_TYPE


def test_only_markdown_is_previewable():
    """A Preview button that renders a .py file as a wall of escaped source
    is a control that lies about what it does."""
    previewable = [ft.ext for ft in filetypes.FILE_TYPES if ft.previewable]
    assert previewable == ["md"]


def test_every_type_can_be_commented_somehow():
    """Ctrl+/ has to do something on every type the picker offers. A type
    with neither form would be a keystroke that silently does nothing."""
    for ft in filetypes.FILE_TYPES:
        if ft.ext in {"txt"}:
            continue  # plain text genuinely has no comment syntax
        assert ft.line_comment or ft.block_comment, ft.ext


def test_the_served_table_keeps_the_pickers_order():
    """The order is a decision, "the ones you will actually pick" is not
    alphabetical: and sorting it client-side would quietly undo it."""
    served = [t["ext"] for t in filetypes.as_dicts()]
    assert served == [ft.ext for ft in filetypes.FILE_TYPES]
    assert served[0] == "md"


def test_the_served_table_is_json_safe():
    """`block_comment` is a tuple in Python and has to cross the wire as a
    list; a tuple serialises fine and comes back as one, but the shape the
    frontend indexes into should be stated here rather than assumed."""
    by_ext = {t["ext"]: t for t in filetypes.as_dicts()}
    assert by_ext["html"]["block_comment"] == ["<!-- ", " -->"]
    assert by_ext["py"]["block_comment"] is None
