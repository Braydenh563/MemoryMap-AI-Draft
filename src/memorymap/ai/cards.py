"""Tool results as **typed cards**, not as prose (PLAN.md §4, item A1).

## The gap this closes

A tool result reaches the chat three ways today, and only one of them is a
thing the reader can act on:

1. `label`, one sentence of prose ("Searched files for “budget”").
2. `result_summary`, the raw JSON, in a disclosure that has to be opened.
3. `touched` (`agent._touched_items`), **notes and documents only**, as chips
   that open the thing.

So a `search_files` result rendered as a JSON blob with nothing to click, a
`read_whiteboard` named a board the reader could not open, and every reminder
the agent set or listed was a line of text. Two of the five kinds PLAN.md
names had cards; three had none.

## The shape

`result_cards(name, result)` returns a list of envelopes::

    [{"kind": "note", "items": [{"id": 3, "label": "…", "snippet": "…"}, …]},
     {"kind": "file", "items": [{"id": 7, "file_kind": "upload", …}]}]

One envelope per kind, in `KINDS` order, capped at `CARD_ITEM_LIMIT` items
each. The front end has one renderer per kind and reads nothing else.

## Why a projection table rather than a field on every tool

The obvious reading of "every tool returns `{kind, items}`" is to rewrite
fifty-eight executors. That was rejected, for three reasons that are all
measurable:

- **The model's copy is the same object.** A tool result is fed back to the
  model as JSON under a real budget (`agent.TOOL_RESULT_BUDGET_CHARS` and
  `context.plan(...).tool_result_chars`). Wrapping every result in a second
  envelope with duplicated labels and snippets spends that budget on
  presentation the model has no use for.
- **`_result_summary` and every existing test read the current shape.**
  Rewriting the results would rewrite the prose the transcript shows and the
  assertions that pin it, for no gain to either.
- **A card is a *view*, and views belong on the boundary.** This module runs
  once per tool call, at the point where the event is built, the same place
  `_tool_sources` and `_touched_items` already run.

What "every tool" does buy is coverage, and that is enforced rather than
hoped for: `PROJECTIONS` has an entry for every registered tool name, empty
tuple included, and `tests/test_tool_cards.py` fails when a new tool is added
without a decision being made about it. An empty tuple is a decision, a
count, a rename or a tag list names nothing you can open.
"""

from __future__ import annotations

#: The kinds the chat can draw, in the order the cards appear under a tool
#: call. PLAN.md §4 A1 names exactly these five ("note, document, file, board,
#: reminder"); anything else a tool returns is a number or a name, not a thing
#: with a page to open.
KINDS = ("note", "document", "file", "board", "reminder")

#: How many cards of one kind a single tool call may contribute. The same
#: reasoning as `agent.TOUCHED_LIMIT`, which this sits beside: a `list_notes`
#: over a big notebook would otherwise put fifty cards under one row and bury
#: the answer beneath its own evidence. The tool's own result still says how
#: many there really were, the card strip is a way in, not an inventory.
CARD_ITEM_LIMIT = 6

#: How much of a thing's own text rides along as its one-line preview. Long
#: enough to recognise the note, short enough that six of them are not a
#: second answer under the answer. Matches `agent.SOURCE_SNIPPET_CHARS`.
SNIPPET_CHARS = 180

#: How long a card's title may be. `agent._touched_items` uses 60 for the same
#: job and the two strips sit next to each other.
LABEL_CHARS = 60


def _flat(value: object) -> str:
    return " ".join(str(value or "").split())


def _clip(value: object, chars: int) -> str:
    text = _flat(value)
    return text[:chars]


def _first_text(row: dict, *keys: str) -> str:
    for key in keys:
        text = _flat(row.get(key))
        if text:
            return text
    return ""


def _note_item(row: dict) -> dict | None:
    """A note card.

    A note has no title, so its opening words are its name, the same thing
    `noteLabel` shows in every list in the app. `preview` and `text` are the
    names the graph tools and the whiteboard tools give the same field.
    """
    note_id = row.get("id")
    if not isinstance(note_id, int):
        return None
    body = _first_text(row, "content", "preview", "text", "excerpt")
    return {
        "id": note_id,
        "label": _clip(body, LABEL_CHARS) or f"Note #{note_id}",
        "snippet": _clip(body, SNIPPET_CHARS),
    }


def _document_item(row: dict) -> dict | None:
    """A document card. Its title is its name, which is what makes it a
    document rather than a note, see `agent._touched_kind` for why the two
    must never be confused: id 12 is a different object in each table."""
    doc_id = row.get("id")
    if not isinstance(doc_id, int):
        return None
    title = _flat(row.get("title"))
    return {
        "id": doc_id,
        "label": _clip(title, LABEL_CHARS) or f"Document #{doc_id}",
        "snippet": _clip(_first_text(row, "preview", "content"), SNIPPET_CHARS),
    }


def _file_item(row: dict) -> dict | None:
    """An uploaded file or a note attachment.

    `file_kind` is not decoration: a `MediaUpload` and an `Attachment` are two
    tables with separate id spaces (see `ai/tools/files.py`), so id 12 is two
    different files and a card that lost the kind would open the wrong one.
    Renamed from the result's own `kind` because `kind` on a card already
    means which of `KINDS` it is.
    """
    file_id = row.get("id")
    file_kind = str(row.get("kind") or "").strip().lower()
    if not isinstance(file_id, int) or file_kind not in ("upload", "attachment"):
        return None
    name = _first_text(row, "name", "original_name", "filename")
    item = {
        "id": file_id,
        "file_kind": file_kind,
        "label": _clip(name, LABEL_CHARS) or f"File #{file_id}",
        "snippet": _clip(_first_text(row, "caption", "text"), SNIPPET_CHARS),
        "url": str(row.get("url") or ""),
    }
    if isinstance(row.get("attached_to_note"), int):
        item["note_id"] = row["attached_to_note"]
    return item


def _board_item(row: dict) -> dict | None:
    """A whiteboard or mindmap board.

    **`None` is a real board id**, the default board, which is what every
    whiteboard tool means when `board_id` is absent (`_whiteboard_board_filter`
    exists because `== None` renders as SQL `= NULL` and matches nothing). So
    this cannot use "no id" as its rejection test the way the others do; it
    accepts a missing id and lets the front end open the default board.
    """
    board_id = row.get("board_id", ...)
    if board_id is ...:
        return None
    if board_id is not None and not isinstance(board_id, int):
        return None
    title = _first_text(row, "board_title", "title")
    return {
        "id": board_id,
        "label": _clip(title, LABEL_CHARS) or ("Default board" if board_id is None else f"Board #{board_id}"),
        "snippet": _clip(_first_text(row, "preview", "text", "next"), SNIPPET_CHARS),
    }


def _reminder_item(row: dict) -> dict | None:
    reminder_id = row.get("id")
    if not isinstance(reminder_id, int):
        return None
    text = _flat(row.get("text"))
    item = {
        "id": reminder_id,
        "label": _clip(text, LABEL_CHARS) or f"Reminder #{reminder_id}",
        "snippet": "",
        "due_at": str(row.get("due_at") or ""),
        "done": bool(row.get("done")),
    }
    if isinstance(row.get("note_id"), int):
        item["note_id"] = row["note_id"]
    return item


_BUILDERS = {
    "note": _note_item,
    "document": _document_item,
    "file": _file_item,
    "board": _board_item,
    "reminder": _reminder_item,
}


class _Where:
    """Where in one tool's result a kind of thing is found.

    `key` is the list to walk; `None` means the result object itself is the
    single row. `id_field` renames the id for results that carry two of them
    (a contradiction names `earlier_note_id` and `later_note_id`, and both are
    notes worth opening).
    """

    __slots__ = ("kind", "key", "id_field")

    def __init__(self, kind: str, key: str | None = None, id_field: str | None = None) -> None:
        self.kind = kind
        self.key = key
        self.id_field = id_field


def _N(key: str | None = None, id_field: str | None = None) -> _Where:
    return _Where("note", key, id_field)


def _D(key: str | None = None) -> _Where:
    return _Where("document", key)


def _F(key: str | None = None) -> _Where:
    return _Where("file", key)


def _B(key: str | None = None) -> _Where:
    return _Where("board", key)


def _R(key: str | None = None) -> _Where:
    return _Where("reminder", key)


#: **Every registered tool, with what its result names.**
#:
#: An empty tuple is as much a decision as a projection is, and the test that
#: walks `tools.TOOLS` against this table is what makes it one: a tool added
#: later cannot quietly render as a JSON blob because somebody forgot this
#: file. The comment beside each empty entry says what it returns instead.
PROJECTIONS: dict[str, tuple[_Where, ...]] = {
    # --- notes ------------------------------------------------------------
    "search_notes": (_N("notes"),),
    "list_notes": (_N("notes"),),
    "get_note": (_N(),),
    "summarize_notes": (_N("notes"),),
    "related_notes": (_N("related"), _N("might_connect")),
    "find_similar_notes": (_N("similar"),),
    "path_between": (_N("path"),),
    # A structure report names its hubs, its orphans and each cluster's
    # centre. The clusters themselves are counts, not things, their `centre`
    # is nested one level deeper than this table walks, and hubs/orphans
    # already give the reader a way in.
    #
    # **Orphans first, and the order is load-bearing** because the per-kind
    # cap is six: a well-connected notebook has more hubs than that, so with
    # hubs first the orphans were squeezed out entirely, measured by the eval
    # harness, whose "which notes aren't connected to anything?" case cited
    # six hubs and not the orphan it asked for. Orphans are also the
    # actionable half: a hub is a note you already know about, and an orphan
    # is one you have lost.
    "notebook_structure": (_N("orphans"), _N("hubs")),
    "find_contradictions": (_N("tensions", "earlier_note_id"), _N("tensions", "later_note_id")),
    "create_note": (_N(),),
    "edit_note": (_N(),),
    "restore_note": (_N(),),
    # `tag_note`/`pin_note`/`link_notes`/`unlink_notes`/`delete_note` report
    # ids under their own names (`tagged`, `linked`, `deleted`) with no text
    # beside them, so a card built from one would be "Note #12" and nothing
    # else. The change list already shows those with View and Undo, which is
    # strictly more than a bare chip.
    "tag_note": (),
    "pin_note": (),
    "link_notes": (),
    "unlink_notes": (),
    "delete_note": (),
    # --- documents --------------------------------------------------------
    "list_documents": (_D("documents"),),
    "get_document": (_D(),),
    "create_document": (_D(),),
    # Deleted: the id is gone and there is nothing left to open.
    "delete_document": (),
    # --- files ------------------------------------------------------------
    "search_files": (_F("files"),),
    "read_file": (_F(),),
    # --- boards -----------------------------------------------------------
    # A whiteboard card is a *note* placed on a board, and its row names the
    # note under `note_id`, `id` there would be the card's own row id, which
    # opens nothing. Hence `id_field` on every note projection here.
    "read_whiteboard": (_B(), _N("cards", "note_id")),
    "search_whiteboard": (_B("matches"), _N("matches", "note_id")),
    "add_whiteboard_card": (_B(), _N(None, "note_id")),
    "add_whiteboard_link": (),  # two card ids, no board and no note text
    "generate_diagram": (_B(), _N("cards", "note_id")),
    "read_mindmap": (_B(),),
    "create_mindmap": (_B(),),
    "add_map_node": (_B(),),
    "link_map_nodes": (_B(),),
    # --- reminders --------------------------------------------------------
    "set_reminder": (_R(),),
    "list_reminders": (_R("reminders"),),
    "complete_reminder": (_R(),),
    # --- everything else: numbers, names and prose ------------------------
    # Each of these returns counts, names or text with nothing behind it that
    # has a page in this app. Listing them here rather than leaving them out
    # is the point of the table: the coverage test reads it.
    "count_notes": (),  # numbers
    "list_tags": (),  # tag names and counts
    "list_categories": (),  # category names and counts
    "notebook_overview": (),  # both of the above
    "create_category": (),
    "rename_category": (),
    "merge_categories": (),
    "delete_category": (),
    "rename_tag": (),
    "delete_tag": (),
    "audit_link_reasons": (),  # a count of reasons written
    "search_chat_history": (),  # conversations, which the Library lists
    "list_skills": (),  # skills, which Settings lists
    "save_skill": (),
    "delete_skill": (),
    "get_current_time": (),
    "save_user_preference": (),  # carries its own accept/decline card
    "web_search": (),  # the Sources panel draws these, see `_tool_sources`
    "read_url": (),  # ditto
    "ask_user": (),  # ends the turn with a question card
    "run_skill": (),  # ends the turn and hands over to the runner
    "make_plan": (),  # ditto, and the plan card is the checklist
    "compress_chat": (),  # ends the turn with the summary editor
}


def _rows(result: dict, where: _Where) -> list[dict]:
    if where.key is None:
        return [result]
    value = result.get(where.key)
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def result_cards(name: str, result: object) -> list[dict]:
    """The typed cards one tool call earns, as ``[{kind, items}]``.

    Never raises and never guesses: a result that does not match the shape
    this tool is declared to have contributes nothing, which renders as the
    strip simply not appearing. A failed call contributes nothing either, an
    error result has no things in it, and a card promising one would be the
    transcript inventing a note.
    """
    if not isinstance(result, dict) or "error" in result:
        return []
    wheres = PROJECTIONS.get(name)
    if not wheres:
        return []
    by_kind: dict[str, list[dict]] = {}
    seen: set[tuple[str, object]] = set()
    for where in wheres:
        build = _BUILDERS[where.kind]
        items = by_kind.setdefault(where.kind, [])
        for row in _rows(result, where):
            if len(items) >= CARD_ITEM_LIMIT:
                break
            source = row if where.id_field is None else {**row, "id": row.get(where.id_field)}
            item = build(source)
            if item is None:
                continue
            # A file's id is only unique within its own table, so the key has
            # to carry `file_kind` too: the same trap `_file_item` guards.
            key = (where.kind, item.get("file_kind", ""), item["id"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return [
        {"kind": kind, "items": by_kind[kind]}
        for kind in KINDS
        if by_kind.get(kind)
    ]
