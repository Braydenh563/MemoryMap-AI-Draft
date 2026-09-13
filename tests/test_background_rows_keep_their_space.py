"""A row the night shift makes belongs to the space its note is in.

A new row takes its space from `session.info["workspace_id"]`, which
`core/deps.get_session` sets from the request's `X-Workspace-ID` header and
the before-flush hook in `core/database.py` applies. A background pass has no
request and no header: `ai/autonomous.py` opens a plain session, so every row
it created was written with the column default, "default".

Measured before the fix: two notes in `space-b`, a link made the way the
librarian makes one, and the space that owns both notes could see zero links.
The link existed, in a space neither of its notes was in, which is worse than
not being made at all: nothing surfaces it and nothing cleans it up.

The fix is to take the space from the note rather than from the session,
because the note is the fact that is true in both cases: in a request it is
already in the session's space, and in a background pass it is the only thing
that knows.
"""

from __future__ import annotations

from sqlalchemy import select

from memorymap.core import deps
from memorymap.core.database import Entry, EntryLink
from memorymap.entry import manager


def _notes_in(session, space: str) -> tuple[Entry, Entry]:
    session.info["workspace_id"] = space
    first = Entry(content=f"First note in {space}")
    second = Entry(content=f"Second note in {space}")
    session.add_all([first, second])
    session.commit()
    return first, second


def test_a_link_made_without_a_request_lands_in_its_notes_space(app_state):
    db = deps.get_db()
    with db.session() as session:
        first, second = _notes_in(session, "space-b")
        ids = (first.id, second.id)

    # A background pass: a plain session, no workspace in `info`, which is
    # exactly how `ai/autonomous.py` opens one.
    with db.session() as session:
        manager.create_link(
            session, session.get(Entry, ids[0]), session.get(Entry, ids[1]), reason="related"
        )
        session.commit()

    with db.session() as session:
        session.info["workspace_id"] = "all"
        links = session.scalars(select(EntryLink)).all()
        assert [link.workspace_id for link in links] == ["space-b"]

    with db.session() as session:
        session.info["workspace_id"] = "space-b"
        assert len(session.scalars(select(EntryLink)).all()) == 1, (
            "the space that owns both notes cannot see the link between them"
        )


def test_a_link_made_inside_a_request_still_takes_that_space(app_state):
    """The other direction: taking the space from the note must not break the
    ordinary case, where the session already knows which space it is in."""
    db = deps.get_db()
    with db.session() as session:
        first, second = _notes_in(session, "space-c")
        manager.create_link(session, first, second, reason="related")
        session.commit()

    with db.session() as session:
        session.info["workspace_id"] = "all"
        assert [link.workspace_id for link in session.scalars(select(EntryLink)).all()] == [
            "space-c"
        ]


def test_filing_a_note_without_a_request_makes_the_category_in_its_space(app_state):
    """The same fact at the other place a row is made for a note.

    A category created while filing takes its space from the session too, so a
    caller with no request behind it (a background pass, an import off the main
    thread) would file a note in `space-b` into a category in "default": a
    category the note's own space cannot list, which is a note that has quietly
    left the sidebar.
    """
    from memorymap.core.database import Category

    db = deps.get_db()
    with db.session() as session:
        first, _second = _notes_in(session, "space-b")
        note_id = first.id

    with db.session() as session:
        manager.set_category(session, session.get(Entry, note_id), "Research")
        session.commit()

    with db.session() as session:
        session.info["workspace_id"] = "space-b"
        names = [row.name for row in session.scalars(select(Category)).all()]
        assert "Research" in names, "the note's own space cannot see the category it was filed into"
