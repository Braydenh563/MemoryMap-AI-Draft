"""`list_notes(untagged=true)`, one filter instead of a research project.

Reported after watching a skill run fail twice: "skills are too hard for small
ais and things go wrong often", with the model announcing "due to the
conversation context budget, I couldn't access all of them" and tagging
nothing.

That is not a model failing at tagging. It is the app asking a 3B model to
page through the whole notebook, hold every note's tags in mind, subtract one
set from another and only then begin, inside a context budget the app itself
enforces. REDESIGN.md §R5's rule for exactly this: *do not ask a small model to
be careful; make it structurally hard for it to be wrong.*
"""

from __future__ import annotations

import inspect

from memorymap.ai import tools
from memorymap.entry import manager


def _untagged(session):
    return {
        row["id"]
        for row in tools.TOOLS["list_notes"].handler(session, {"untagged": True})["notes"]
    }


def test_only_notes_with_no_tags_come_back(session):
    bare = manager.create_entry(session, "A note with nothing on it", tags=[])
    tagged = manager.create_entry(session, "A note about work", tags=["work"])
    found = _untagged(session)
    assert bare.id in found
    assert tagged.id not in found


def test_every_shape_of_no_tags_counts(session):
    """`tags` is a JSON string, so "no tags" is `"[]"` on a note saved today,
    `NULL` on a row from before that column was always written, and `""` on
    one cleared by hand. A filter that checked only the shape in front of it
    would be right on a fresh notebook and wrong on a restored backup, which
    is exactly what the first version of this did."""
    ids = set()
    #: `NULL` is left out of this loop and asserted separately: the column is
    #: NOT NULL on a database created today, so writing one here fails at the
    #: constraint rather than testing anything. The filter still names it,
    #: because a row restored from an older schema can carry one.
    for value in ("[]", ""):
        entry = manager.create_entry(session, f"Cleared its tags: {value!r}", tags=["temp"])
        entry.tags = value
        ids.add(entry.id)
    session.commit()
    assert ids <= _untagged(session)


def test_the_filter_still_names_null(session):
    from memorymap.ai import tools as tool_module

    source = inspect.getsource(tool_module._list_notes)
    assert "Entry.tags.is_(None)" in source, (
        "a backup restored from an older schema can carry a NULL here, and it "
        "is untagged by every definition a user has"
    )


def test_the_filter_composes_with_the_others(session):
    """`untagged` is one clause among several, not a mode that replaces them, 
    "tag the untagged notes in Recipes" has to be one call."""
    manager.create_entry(session, "Untagged, wrong category", category_name="Other", tags=[])
    wanted = manager.create_entry(session, "Untagged in Recipes", category_name="Recipes", tags=[])
    rows = tools.TOOLS["list_notes"].handler(
        session, {"untagged": True, "category": "Recipes"}
    )["notes"]
    assert [row["id"] for row in rows] == [wanted.id]


def test_the_schema_tells_the_model_when_to_use_it(session):
    """A description says *when* to use a tool, not what it does (§R5 item 2).
    A boolean nobody knows about is a boolean nobody sets."""
    spec = tools.TOOLS["list_notes"]
    assert "untagged" in spec.parameters["properties"]
    assert "untagged" in spec.description
    assert "tag my untagged notes" in spec.description
