"""The notebook every golden ask is scored against.

**Built through the app's own managers**, not by inserting rows: `create_entry`
files a note, records its dates and writes an audit row, and a fixture that
skipped all three would be scoring the agent against a notebook this app could
never have produced. The two exceptions are a media upload and a whiteboard
card, which have no manager, those are the ORM objects the routes themselves
create, with the same fields filled in.

Small on purpose. Thirty asks over fifteen notes runs in under a second and
still has every shape the tools have to tell apart: two categories, a tag that
is a prefix of another tag (`work`/`homework`, the over-match `_list_notes`
guards against), an untagged note, an orphan with no links, a linked pair, a
document whose subject appears nowhere in a note, a file whose only text came
out of OCR, a board with a card on it, and a reminder.

Ids are not hard-coded anywhere: `build()` returns a `Notebook` naming each
thing it made, and `golden.py` refers to them by name. A fixture that changed
by one row would otherwise silently re-point every expectation in the set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from memorymap.entry import manager


@dataclass
class Notebook:
    """What `build` made, by name, so an expectation can say `notes["gym"]`."""

    notes: dict[str, int] = field(default_factory=dict)
    documents: dict[str, int] = field(default_factory=dict)
    files: dict[str, tuple[str, int]] = field(default_factory=dict)
    boards: dict[str, int] = field(default_factory=dict)
    reminders: dict[str, int] = field(default_factory=dict)


NOTES: list[tuple[str, str, str, list[str]]] = [
    # key, category, content, tags
    ("gym", "Health", "Went to the gym before work and did squats and deadlifts.", ["gym", "routine"]),
    ("sleep", "Health", "Sleeping badly again: no screens after ten seems to help.", ["routine"]),
    ("thesis", "Uni", "Thesis chapter two is about attention and why it beats recurrence.", ["thesis", "work"]),
    ("supervisor", "Uni", "Supervisor meeting: bring the chapter two draft and the results table.", ["thesis"]),
    ("homework", "Uni", "Homework for the stats unit is due on the fourteenth.", ["homework"]),
    ("groceries", "Life", "Buy milk, eggs and coffee on the way home.", ["shopping"]),
    ("rent", "Life", "Rent goes up in March, check the lease before signing anything.", ["money"]),
    ("budget", "Life", "Monthly budget: rent, food, transport, and put the rest into savings.", ["money"]),
    ("race", "Health", "Race day is the fourteenth, carnival starts at eight in the morning.", ["running"]),
    ("shoes", "Health", "New running shoes are worn out already; the last pair lasted longer.", ["running"]),
    ("standup", "Work", "Standup notes: the migration is blocked on the schema change.", ["work"]),
    ("schema", "Work", "The schema change needs a backfill before the migration can run.", ["work"]),
    ("idea", "Work", "Idea: a local-first notebook that files itself and answers questions.", ["work", "idea"]),
    # No tags at all, `list_notes(untagged=True)` has to find exactly this one.
    ("loose", "Life", "A stray thought about nothing in particular that never got filed.", []),
    # No links, no shared tag with anything: the orphan `notebook_structure`
    # has to report.
    ("orphan", "Life", "Chess openings I keep losing to, especially the London.", ["chess"]),
]

#: Which notes are linked to which. `standup`↔`schema` is the pair
#: `related_notes` and `path_between` are scored on.
LINKS = [("standup", "schema"), ("thesis", "supervisor")]

DOCUMENTS = [
    (
        "essay",
        "Attention and recurrence",
        "# Attention and recurrence\n\n"
        "Recurrent models carry state forward one step at a time, which is what makes "
        "them slow to train. Attention reads the whole sequence at once.\n\n"
        "## Why it matters for long documents\n\n"
        "A long document is exactly where the difference shows up: the last paragraph "
        "can attend to the first without paying for every step in between.\n",
    ),
    (
        "recipe",
        "Sourdough notes",
        "# Sourdough notes\n\nStarter doubles in about six hours at twenty-four degrees. "
        "Autolyse for an hour before adding salt.\n",
    ),
]


def build(session: Session) -> Notebook:
    """Fill an empty notebook and return what is in it."""
    from memorymap.core.database import Document, MediaUpload, Reminder, WhiteboardNode, utcnow

    book = Notebook()

    for key, category, content, tags in NOTES:
        entry = manager.create_entry(session, content, category_name=category, tags=tags)
        book.notes[key] = entry.id

    for left, right in LINKS:
        manager.create_link(
            session,
            manager.get_entry(session, book.notes[left]),
            manager.get_entry(session, book.notes[right]),
            reason="same piece of work",
        )

    for key, title, content in DOCUMENTS:
        document = Document(title=title, content=content)
        session.add(document)
        session.flush()
        book.documents[key] = document.id

    #: A photograph whose *only* searchable text came out of OCR, the case
    #: `search_files` exists for, and one no note in this notebook mentions,
    #: so a hit on it cannot come from anywhere else.
    upload = MediaUpload(
        filename="scan-01.png",
        original_name="whiteboard-march.png",
        caption="A photo of a whiteboard covered in boxes and arrows",
        ocr_text="RETENTION PLAN, cohort by week, churn spikes at week six",
    )
    session.add(upload)
    session.flush()
    book.files["whiteboard-photo"] = ("upload", upload.id)

    #: A board is itself an `Entry` with `is_board` set (see MINDMAP_PLAN.md's
    #: own finding), so it is made the same way and then flagged.
    board = manager.create_entry(session, "Project planning", category_name="Work")
    board.is_board = True
    session.flush()
    book.boards["planning"] = board.id
    session.add(
        WhiteboardNode(board_id=board.id, entry_id=book.notes["schema"], x=100.0, y=100.0)
    )

    reminder = Reminder(
        text="Send the chapter two draft to my supervisor",
        due_at=utcnow() + timedelta(days=3),
        entry_id=book.notes["supervisor"],
    )
    session.add(reminder)
    session.flush()
    book.reminders["draft"] = reminder.id

    session.commit()
    return book
