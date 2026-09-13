"""Category management as agent tools (§14).

Asked for indirectly: "more tools for managing… creating, editing, deleting,
and applying categories". Renaming and deleting already existed as UI actions,
but not as tools, so the agent could file a note into a category it had no
way to create, which is the wrong half of the job.

The interesting cases here are the ones where doing the obvious thing would be
wrong: an "undo" that invents a history, a delete that takes notes with it, and
a create that fails because the job is already done.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from memorymap.ai import tools
from memorymap.core.database import Category, Entry
from memorymap.entry import manager


def _names(session) -> list[str]:
    return sorted(c.name for c in session.scalars(select(Category)))


def _category_of(session, entry_id: int) -> str:
    return manager.category_name_for(session, session.get(Entry, entry_id))


# --- create -----------------------------------------------------------------


def test_the_agent_can_create_a_category(session, app_state):
    result = tools.execute_tool(session, "create_category", {"name": "Recipes"})
    assert result["created"] is True
    assert "Recipes" in _names(session)


def test_creating_one_that_exists_is_not_an_error(session, app_state):
    """The model asked for a category to exist, and it does. Failing here
    would send it round a retry loop over a job that is already done."""
    tools.execute_tool(session, "create_category", {"name": "Recipes"})
    again = tools.execute_tool(session, "create_category", {"name": "recipes"})
    assert "error" not in again
    assert again["created"] is False
    assert _names(session).count("Recipes") == 1


def test_a_nameless_category_is_refused(session, app_state):
    assert "error" in tools.execute_tool(session, "create_category", {"name": "  "})


def test_creating_a_category_can_be_undone(session, app_state):
    """Safe to reverse: one made a moment ago holds nothing, so removing it
    cannot strand a note."""
    result = tools.execute_tool(session, "create_category", {"name": "Temporary"})
    undo = result["undo"]
    tools.execute_tool(session, undo["tool"], undo["arguments"])
    assert "Temporary" not in _names(session)


# --- rename -----------------------------------------------------------------


def test_renaming_moves_the_notes_with_it(session, app_state):
    entry = manager.create_entry(session, "a note about dinner", "Recipes")

    tools.execute_tool(session, "rename_category", {"old": "Recipes", "new": "Cooking"})
    assert _category_of(session, entry.id) == "Cooking"


def test_renaming_is_undoable_when_it_was_only_a_rename(session, app_state):
    tools.execute_tool(session, "create_category", {"name": "Recipes"})
    result = tools.execute_tool(
        session, "rename_category", {"old": "Recipes", "new": "Cooking"}
    )
    assert result["merged"] is False
    undo = result["undo"]
    tools.execute_tool(session, undo["tool"], undo["arguments"])
    assert "Recipes" in _names(session)


def test_a_rename_that_merged_offers_no_undo(session, app_state):
    """Renaming onto a name already in use merges the two, and once both sets
    of notes sit in one category nothing records which came from where. An
    "undo" would move all of them back, inventing a history that never
    happened, which is worse than having no undo at all."""
    tools.execute_tool(session, "create_category", {"name": "Work"})
    tools.execute_tool(session, "create_category", {"name": "Job"})
    result = tools.execute_tool(
        session, "rename_category", {"old": "Job", "new": "Work"}
    )
    assert result["merged"] is True
    assert "undo" not in result


def test_renaming_something_that_is_not_there_says_what_is(session, app_state):
    """The model picked the name out of a conversation. "No such category"
    with nothing after it invites it to guess again rather than look."""
    tools.execute_tool(session, "create_category", {"name": "Recipes"})
    result = tools.execute_tool(
        session, "rename_category", {"old": "Recipies", "new": "Cooking"}
    )
    assert "error" in result
    assert "Recipes" in result["error"], "the error should list what does exist"


# --- merge ------------------------------------------------------------------


def test_merging_moves_every_note_and_drops_the_empty_category(session, app_state):
    first = manager.create_entry(session, "a work note", "Work")
    second = manager.create_entry(session, "another work note", "work")

    result = tools.execute_tool(
        session, "merge_categories", {"from": "work", "into": "Work"}
    )
    assert result["notes_moved"] == 1
    assert _category_of(session, first.id) == "Work"
    assert _category_of(session, second.id) == "Work"
    assert _names(session).count("work") == 0


def test_merging_a_category_into_itself_is_refused(session, app_state):
    tools.execute_tool(session, "create_category", {"name": "Work"})
    result = tools.execute_tool(
        session, "merge_categories", {"from": "Work", "into": "work"}
    )
    assert "error" in result


def test_merge_is_its_own_tool_rather_than_a_side_effect_of_rename():
    """rename_category merges when the new name is taken, which is right for a
    rename and a terrible way to *ask* for a merge, the model would have to
    know a name was already used to predict what its call did."""
    assert "merge_categories" in tools.TOOLS


# --- delete -----------------------------------------------------------------


def test_deleting_a_category_keeps_its_notes(session, app_state):
    """An organising action that could destroy writing is not what anyone
    means by "delete category"."""
    entry = manager.create_entry(session, "a note that must survive", "Scratch")

    result = tools.execute_tool(session, "delete_category", {"name": "Scratch"})
    assert result["notes_moved"] == 1
    assert session.get(Entry, entry.id) is not None
    assert _category_of(session, entry.id) == manager.UNCATEGORISED
    assert "Scratch" not in _names(session)


def test_uncategorised_itself_cannot_be_deleted(session, app_state):
    entry = manager.create_entry(session, "a note with no home")
    result = tools.execute_tool(
        session, "delete_category", {"name": manager.UNCATEGORISED}
    )
    assert "error" in result
    assert session.get(Entry, entry.id) is not None


def test_deleting_something_that_is_not_there_is_an_error_not_a_crash(session, app_state):
    assert "error" in tools.execute_tool(session, "delete_category", {"name": "Nope"})


# --- safety and cost --------------------------------------------------------


@pytest.mark.parametrize("name", ["merge_categories", "delete_category"])
def test_the_irreversible_ones_need_the_user_to_approve_them(name):
    """Neither can be undone from here, nothing records which notes moved , 
    so the agent loop parks them for the user instead of running them."""
    assert tools.TOOLS[name].destructive is True


@pytest.mark.parametrize("name", ["create_category", "rename_category"])
def test_the_reversible_ones_do_not_interrupt(name):
    assert tools.TOOLS[name].destructive is False


def test_the_category_tools_are_not_sent_with_every_question():
    """Four more schemas on every round is exactly the per-round cost §11a
    went to some trouble to cut, and most questions have nothing to do with
    reorganising the category tree."""
    quiet = tools.focus_for("what did I say about the beans?")
    assert quiet is not None
    assert "create_category" not in quiet


@pytest.mark.parametrize(
    "question",
    [
        "make a category called Recipes",
        "file this under Work",
        "merge my duplicate categories",
        "rename the Work category",
    ],
)
def test_they_are_sent_when_the_question_is_about_categories(question):
    wanted = tools.focus_for(question)
    assert wanted is None or "create_category" in wanted


def test_the_schemas_stay_terse():
    """They were rewritten without per-parameter descriptions because the
    registry was already within ~100 characters of what a 4096-token window
    holds. This is what would notice them growing back."""
    import json

    schemas = json.dumps(
        [
            {"name": name, "parameters": tools.TOOLS[name].parameters,
             "description": tools.TOOLS[name].description}
            for name in (
                "create_category",
                "rename_category",
                "merge_categories",
                "delete_category",
            )
        ]
    )
    assert len(schemas) < 1400, "the category schemas have grown; check the budget"
