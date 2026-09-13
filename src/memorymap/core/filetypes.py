"""What kind of file a document is, and what that changes.

A document used to be markdown and only markdown. Asked for directly: the
editor should handle code as well, with "code lines as well as language
detection and ctrl + / commenting or equivalent as well as indenting and
dedenting", the type should be changeable, and a new document should be
creatable "of any filetype though it should default to md".

So a document now carries a `file_type`, a bare extension without the dot
("md", "py", "sql"), and this module is the one place that says what each one
means. It is deliberately small data rather than a class hierarchy: everything
that varies by type is a label, a comment token, an indent width and whether
the preview button does anything.

**The frontend needs this same table**, because indenting and comment-toggling
happen on keystrokes and cannot wait for a round trip. It is served by
`GET /documents/file-types` rather than duplicated into `app.js`, a second
copy is a second thing to update, and the failure mode of them disagreeing is
Ctrl+/ inserting the wrong comment marker into someone's file.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What a document is when nobody has said otherwise. Markdown, by direct
#: instruction: this app is a notebook first, and every document that existed
#: before file types did is one of these.
DEFAULT_FILE_TYPE = "md"


@dataclass(frozen=True)
class FileType:
    """One selectable document type.

    `line_comment` is what Ctrl+/ inserts. `block_comment` is the fallback for
    the handful of types that have no line-comment form at all, HTML, XML,
    CSS: where toggling a line means wrapping it rather than prefixing it,
    and a prefix would produce a file that no longer parses.

    `indent` is a string, not a width: a tab-indented language wants a real
    tab, and storing "how many spaces" makes that unrepresentable.
    """

    ext: str
    label: str
    line_comment: str = ""
    block_comment: tuple[str, str] | None = None
    indent: str = "  "
    #: Whether the rendered-preview pane means anything for this type. Only
    #: markdown renders; showing a Preview button that produces a wall of
    #: escaped source for a .py file is a control that lies about what it does.
    previewable: bool = False


#: Ordered as it is offered in the picker: the notebook's own formats first,
#: then prose, then the code types alphabetically by label. Not sorted
#: programmatically: "the ones you will actually pick" is not alphabetical,
#: and a picker whose first entry is ".c" for a note-taking app is wrong.
FILE_TYPES: tuple[FileType, ...] = (
    FileType("md", "Markdown", line_comment="", block_comment=("<!-- ", " -->"), previewable=True),
    FileType("txt", "Plain text"),
    FileType("csv", "CSV", line_comment="#"),
    FileType("json", "JSON", line_comment="//"),
    FileType("yaml", "YAML", line_comment="#"),
    FileType("toml", "TOML", line_comment="#"),
    FileType("ini", "INI", line_comment=";"),
    FileType("bash", "Bash", line_comment="#"),
    FileType("c", "C", line_comment="//", block_comment=("/* ", " */"), indent="    "),
    FileType("cpp", "C++", line_comment="//", block_comment=("/* ", " */"), indent="    "),
    FileType("cs", "C#", line_comment="//", block_comment=("/* ", " */"), indent="    "),
    FileType("css", "CSS", line_comment="", block_comment=("/* ", " */")),
    FileType("go", "Go", line_comment="//", indent="\t"),
    FileType("html", "HTML", line_comment="", block_comment=("<!-- ", " -->")),
    FileType("java", "Java", line_comment="//", indent="    "),
    FileType("js", "JavaScript", line_comment="//", block_comment=("/* ", " */")),
    FileType("kt", "Kotlin", line_comment="//", indent="    "),
    FileType("php", "PHP", line_comment="//", indent="    "),
    FileType("py", "Python", line_comment="#", indent="    "),
    FileType("r", "R", line_comment="#"),
    FileType("rb", "Ruby", line_comment="#"),
    FileType("rs", "Rust", line_comment="//", indent="    "),
    FileType("sql", "SQL", line_comment="--", block_comment=("/* ", " */"), indent="    "),
    FileType("swift", "Swift", line_comment="//", indent="    "),
    FileType("ts", "TypeScript", line_comment="//", block_comment=("/* ", " */")),
    FileType("xml", "XML", line_comment="", block_comment=("<!-- ", " -->")),
)

_BY_EXT = {ft.ext: ft for ft in FILE_TYPES}

#: Extensions that are really another type's file. Kept apart from FILE_TYPES
#: so the picker offers one entry per language rather than five spellings of
#: the same one, while `normalise` still accepts whatever a filename carried.
ALIASES = {
    "markdown": "md",
    "text": "txt",
    "log": "txt",
    "tsv": "csv",
    "yml": "yaml",
    "cfg": "ini",
    "sh": "bash",
    "zsh": "bash",
    "h": "c",
    "hpp": "cpp",
    "cc": "cpp",
    "mjs": "js",
    "cjs": "js",
    "jsx": "js",
    "tsx": "ts",
    "htm": "html",
    "scss": "css",
    "sass": "css",
}


def normalise(value: str | None) -> str:
    """Any spelling of a type into a known one, or the default.

    Accepts a bare extension, one with a leading dot, or a whole filename, 
    all three turn up: the picker sends "py", an import sends ".py", and a
    filename is what a drag-and-drop has. Unknown types fall back to the
    default rather than raising, because the alternative is a document that
    cannot be opened because of a field describing how to open it.
    """
    text = (value or "").strip().lower()
    if not text:
        return DEFAULT_FILE_TYPE
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = ALIASES.get(text, text)
    return text if text in _BY_EXT else DEFAULT_FILE_TYPE


def get(value: str | None) -> FileType:
    """The FileType for any spelling, never None."""
    return _BY_EXT[normalise(value)]


def as_dicts() -> list[dict]:
    """The whole table, for the frontend. Order preserved: the picker's
    order is a decision (see FILE_TYPES) and sorting it client-side would
    quietly undo it."""
    return [
        {
            "ext": ft.ext,
            "label": ft.label,
            "line_comment": ft.line_comment,
            "block_comment": list(ft.block_comment) if ft.block_comment else None,
            "indent": ft.indent,
            "previewable": ft.previewable,
        }
        for ft in FILE_TYPES
    ]
