"""AI tool handlers for category CRUD: find/create/rename/merge/delete.

Split out of `ai/tools.py` (ROADMAP.md §0/§4): small and self-contained
apart from the shared helpers in `_common.py`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core.database import Category
from memorymap.entry import manager

from ._common import ToolError

# --- categories -----------------------------------------------------------------
#
# Asked for indirectly: "more tools for managing… creating, editing, deleting,
# and applying categories". Renaming and deleting already existed as UI actions
# in routes_categories, but not as tools, so the agent could file a note into
# a category it had no way to create, which is the wrong half of the job.
#
# These take NAMES, not ids. The model has never seen an id and would have to
# guess one; every other categorising tool here already speaks in names.


def _find_category(session: Session, name: str) -> Category:
    """Resolve a category by name, or explain what exists.

    Exact match FIRST, then case-insensitively. That order is not fussiness:
    the case this tool exists for is a notebook that has grown both "Work" and
    "work", and a purely case-insensitive lookup resolves both spellings to
    whichever row comes back first, so `merge_categories(from="work",
    into="Work")` found the same category twice and refused itself. The
    duplicate is precisely what the user is trying to clear up.

    Naming the alternatives on a miss matters more here than usual: the model
    picked the name out of a conversation, and "no category called Work" with
    nothing after it invites it to guess again rather than look.
    """
    wanted = (name or "").strip()
    if not wanted:
        raise ToolError("No category name was given")
    found = session.scalar(select(Category).where(Category.name == wanted))
    if found is None:
        found = session.scalar(
            select(Category).where(func.lower(Category.name) == wanted.lower())
        )
    if found is None:
        existing = [c["name"] for c in manager.all_categories(session)]
        known = ", ".join(f"“{n}”" for n in existing[:12]) or "none yet"
        raise ToolError(f"There is no category called “{wanted}”. There is: {known}")
    return found


def _create_category(session: Session, args: dict) -> dict:
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError("A category needs a name")
    if len(name) > 100:
        raise ToolError("That category name is too long (100 characters max)")
    existing = session.scalar(
        select(Category).where(func.lower(Category.name) == name.lower())
    )
    if existing is not None:
        # Not an error: the model asked for a category to exist, and it does.
        # Failing here would send it round a retry loop over a done job.
        return {
            "name": existing.name,
            "created": False,
            "label": f"ph:folder “{existing.name}” already exists",
        }
    category = manager.get_or_create_category(session, name)
    description = str(args.get("description") or "").strip()
    if description:
        category.description = description[:500]
    manager.log_action(session, "created", "category", category.id, name)
    session.commit()
    return {
        "name": category.name,
        "created": True,
        "label": f"ph:folder Created the category “{category.name}”",
        # Safe to reverse: a category made a moment ago holds nothing, so
        # removing it cannot strand any notes.
        "undo": {"tool": "delete_category", "arguments": {"name": category.name}},
    }


def _rename_category(session: Session, args: dict) -> dict:
    category = _find_category(session, str(args.get("old") or ""))
    new_name = str(args.get("new") or "").strip()
    if not new_name:
        raise ToolError("A category needs a name")
    old_name = category.name
    try:
        result = manager.rename_category(session, category.id, new_name)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    if result["merged"]:
        # An undo is deliberately NOT offered here. Renaming onto an existing
        # name merges the two, and once both sets of notes sit in one category
        # nothing records which came from where, "undo" would move all of them
        # back, inventing a history that never happened.
        return {
            "name": new_name,
            "merged": True,
            "notes_moved": result["moved"],
            "label": (
                f"ph:folder Merged “{old_name}” into “{new_name}” "
                f"({result['moved']} notes moved)"
            ),
        }
    return {
        "name": new_name,
        "merged": False,
        "notes_moved": 0,
        "label": f"ph:folder Renamed “{old_name}” → “{new_name}”",
        "undo": {
            "tool": "rename_category",
            "arguments": {"old": new_name, "new": old_name},
        },
    }


def _merge_categories(session: Session, args: dict) -> dict:
    """Fold one category into another. Separate from rename on purpose.

    `rename_category` merges as a side effect when the new name is taken, which
    is the right behaviour for a rename and a terrible way to *ask* for a merge
    - the model would have to know a name was already used to predict what its
    call did. Saying "merge" says what is meant.
    """
    source = _find_category(session, str(args.get("from") or ""))
    target = _find_category(session, str(args.get("into") or ""))
    if source.id == target.id:
        raise ToolError(f"“{source.name}” and “{target.name}” are the same category")
    source_name, target_name = source.name, target.name
    try:
        result = manager.rename_category(session, source.id, target_name)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "from": source_name,
        "into": target_name,
        "notes_moved": result["moved"],
        "label": (
            f"ph:folder Merged “{source_name}” into “{target_name}” "
            f"({result['moved']} notes moved)"
        ),
    }


def _delete_category(session: Session, args: dict) -> dict:
    """Remove a category. Its notes survive as Uncategorised.

    Deleting a category never deletes notes, an organising action that could
    destroy writing is not what anyone means by "delete category". Still marked
    destructive, so the user approves it before it runs: it is not reversible
    from here, because nothing records which notes were moved out.
    """
    category = _find_category(session, str(args.get("name") or ""))
    name = category.name
    try:
        result = manager.delete_category(session, category.id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "name": name,
        "notes_moved": result["moved"],
        "label": (
            f"ph:folder Deleted the category “{name}”: {result['moved']} "
            f"note{'' if result['moved'] == 1 else 's'} kept, now Uncategorised"
        ),
    }


