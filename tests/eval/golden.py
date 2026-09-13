"""Thirty golden asks over the fixture notebook (PLAN.md §4, item A6).

Each row is one thing a person would type, the tool that answers it, the
arguments that tool should be called with, and **what the answer has to cite**
- the notes, documents, files, boards and reminders the chat would show as
cards for that call (`ai/cards.py`).

Two rules kept this honest while it was written:

- **The ask is the person's words, not the tool's.** "what did I write about
  squats?" is what gets typed; `search_notes` is what answers it. Rewording an
  ask until the router happens to offer the right tool would be scoring the
  set against itself.
- **Nothing here names an id.** Every expectation is a lambda over the
  `Notebook` the fixture returns, so adding a note to the fixture cannot
  silently re-point twenty rows.

Read-only throughout. A golden set that writes would need a fresh notebook per
case, which is the difference between a one-second CI run and a minute of
them: and the two properties being scored, tool choice and citation, are both
observable without changing anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tests.eval.fixture import Notebook


@dataclass(frozen=True)
class Ask:
    """One golden case."""

    id: str
    #: What a person types.
    ask: str
    #: The tool that answers it.
    tool: str
    #: The arguments it should be called with, as a function of the notebook.
    arguments: Callable[[Notebook], dict] = lambda book: {}
    #: `(kind, id)` pairs the tool's cards must name. Empty when the answer is
    #: a number or a list of names rather than things, those use `check`.
    cites: Callable[[Notebook], list[tuple[str, object]]] = lambda book: []
    #: For a tool whose result names nothing openable: is the answer right?
    check: Callable[[dict, Notebook], bool] | None = None
    #: Tools that must **not** be offered for this ask. A read must never put
    #: a delete on the wire, that is the failure mode a keyword router has.
    forbid: tuple[str, ...] = field(default=())


#: Every read-only ask should keep the destructive tools off the wire.
NO_DESTRUCTION = ("delete_note", "delete_category", "delete_document", "merge_categories")


GOLDEN: list[Ask] = [
    # --- finding a note ------------------------------------------------------
    Ask(
        "search-squats",
        "what did I write about squats?",
        "search_notes",
        lambda book: {"query": "squats"},
        lambda book: [("note", book.notes["gym"])],
        forbid=NO_DESTRUCTION,
    ),
    Ask(
        "search-thesis",
        "find my notes about the thesis",
        "search_notes",
        lambda book: {"query": "thesis"},
        lambda book: [("note", book.notes["thesis"])],
        forbid=NO_DESTRUCTION,
    ),
    Ask(
        "search-rent",
        "do I have anything about rent going up?",
        "search_notes",
        lambda book: {"query": "rent"},
        lambda book: [("note", book.notes["rent"])],
    ),
    Ask(
        "search-shopping",
        "what do I need to buy on the way home?",
        "search_notes",
        lambda book: {"query": "buy on the way home"},
        lambda book: [("note", book.notes["groceries"])],
    ),
    Ask(
        "search-money",
        "which notes are about money?",
        "search_notes",
        lambda book: {"query": "money"},
        lambda book: [("note", book.notes["budget"])],
    ),
    Ask(
        "search-migration",
        "what is blocking the migration?",
        "search_notes",
        lambda book: {"query": "migration blocked"},
        lambda book: [("note", book.notes["standup"])],
    ),
    # --- walking the notebook ------------------------------------------------
    Ask(
        "list-untagged",
        "which of my notes have no tags at all?",
        "list_notes",
        lambda book: {"untagged": True},
        lambda book: [("note", book.notes["loose"])],
    ),
    Ask(
        "list-category",
        "show me my Health notes",
        "list_notes",
        lambda book: {"category": "Health"},
        lambda book: [("note", book.notes["gym"]), ("note", book.notes["race"])],
    ),
    Ask(
        "list-tag-exact",
        "list the notes tagged work",
        "list_notes",
        lambda book: {"tag": "work"},
        #: The prefix trap, as a scored case: `homework` contains `work`, and
        #: the SQL pre-filter matches it. Only the exact-tag pass removes it.
        check=lambda result, book: (
            book.notes["homework"] not in [n["id"] for n in result.get("notes", [])]
            and book.notes["standup"] in [n["id"] for n in result.get("notes", [])]
        ),
    ),
    Ask(
        "list-recent",
        "what have I written in the last week?",
        "list_notes",
        lambda book: {"since": "week"},
        check=lambda result, book: result.get("returned", 0) > 0,
    ),
    Ask(
        "count-notes",
        "how many notes do I have?",
        "count_notes",
        check=lambda result, book: result.get("total", 0) >= len(book.notes),
    ),
    Ask(
        "count-in-category",
        "how many notes are in Uni?",
        "count_notes",
        lambda book: {"category": "Uni"},
        check=lambda result, book: result.get("count", 0) == 3,
    ),
    Ask(
        "list-tags",
        "what tags am I using?",
        "list_tags",
        check=lambda result, book: "running" in [t["name"] for t in result.get("tags", [])],
    ),
    Ask(
        "list-categories",
        "what categories have I got?",
        "list_categories",
        check=lambda result, book: "Uni" in [c["name"] for c in result.get("categories", [])],
    ),
    Ask(
        "overview",
        "give me an overview of my notebook",
        "notebook_overview",
        check=lambda result, book: bool(result.get("categories")) and bool(result.get("tags")),
    ),
    # --- one note, and what surrounds it -------------------------------------
    Ask(
        "get-note",
        "read the note about the schema change in full",
        "get_note",
        lambda book: {"note_id": book.notes["schema"]},
        lambda book: [("note", book.notes["schema"])],
    ),
    Ask(
        "related",
        "what is connected to my standup note?",
        "related_notes",
        lambda book: {"note_id": book.notes["standup"]},
        lambda book: [("note", book.notes["schema"])],
    ),
    Ask(
        "path-between",
        "how are the standup note and the schema note connected?",
        "path_between",
        lambda book: {"note_id": book.notes["standup"], "other_note_id": book.notes["schema"]},
        lambda book: [("note", book.notes["standup"]), ("note", book.notes["schema"])],
    ),
    Ask(
        "structure-orphans",
        "which notes aren't connected to anything?",
        "notebook_structure",
        cites=lambda book: [("note", book.notes["orphan"])],
    ),
    Ask(
        "similar",
        "what reads like my thesis note?",
        "find_similar_notes",
        lambda book: {"note_id": book.notes["thesis"]},
        check=lambda result, book: "similar" in result,
    ),
    Ask(
        "summarise-week",
        "summarise what I wrote this week",
        "summarize_notes",
        lambda book: {"period": "week"},
        check=lambda result, book: result.get("count", 0) > 0,
    ),
    # --- documents -----------------------------------------------------------
    Ask(
        "docs-list",
        "what documents do I have?",
        "list_documents",
        cites=lambda book: [("document", book.documents["essay"]), ("document", book.documents["recipe"])],
    ),
    Ask(
        "docs-search",
        "find the document about attention",
        "list_documents",
        lambda book: {"query": "attention"},
        lambda book: [("document", book.documents["essay"])],
    ),
    Ask(
        "docs-sourdough",
        "is there a document about sourdough?",
        "list_documents",
        lambda book: {"query": "sourdough"},
        lambda book: [("document", book.documents["recipe"])],
    ),
    Ask(
        "docs-read",
        "read the attention document",
        "get_document",
        lambda book: {"document_id": book.documents["essay"]},
        lambda book: [("document", book.documents["essay"])],
    ),
    Ask(
        "docs-read-passage",
        "what does the attention document say about long documents?",
        "get_document",
        lambda book: {"document_id": book.documents["essay"], "query": "long documents"},
        #: The passage, not the head of the document, the keyword-context path
        #: `get_document` falls back to when there is no embedding backend,
        #: which is every install that followed CLAUDE.md.
        check=lambda result, book: "long document" in (result.get("content") or "").lower(),
    ),
    # --- files ---------------------------------------------------------------
    Ask(
        "files-photo",
        "find the photo of the whiteboard",
        "search_files",
        lambda book: {"query": "whiteboard"},
        lambda book: [("file", book.files["whiteboard-photo"][1])],
    ),
    Ask(
        "files-ocr",
        "which file mentions the retention plan?",
        "search_files",
        lambda book: {"query": "retention"},
        #: Nothing but the OCR text contains this word, so a hit can only have
        #: come from the reading, which is the whole point of the tool.
        lambda book: [("file", book.files["whiteboard-photo"][1])],
    ),
    Ask(
        "files-read",
        "read the whiteboard photo for me",
        "read_file",
        lambda book: {"kind": "upload", "file_id": book.files["whiteboard-photo"][1]},
        lambda book: [("file", book.files["whiteboard-photo"][1])],
    ),
    # --- boards and reminders ------------------------------------------------
    Ask(
        "board-read",
        "what is on my project planning board?",
        "read_whiteboard",
        lambda book: {"board_id": book.boards["planning"]},
        lambda book: [("board", book.boards["planning"]), ("note", book.notes["schema"])],
    ),
    Ask(
        "board-search",
        "which board did I put the schema note on?",
        "search_whiteboard",
        lambda book: {"query": "schema"},
        lambda book: [("board", book.boards["planning"])],
    ),
    Ask(
        "reminders",
        "what reminders have I got coming up?",
        "list_reminders",
        cites=lambda book: [("reminder", book.reminders["draft"])],
    ),
    Ask(
        "time",
        "what is today's date?",
        "get_current_time",
        check=lambda result, book: bool(result.get("iso")),
    ),
]
