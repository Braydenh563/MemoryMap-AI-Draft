"""What a note means includes how it is filed and what is attached to it.

**Reported directly:** "I have a whole category called hobbies but basically
none came up in the semantic search." Nothing was broken: the word
"hobbies" lives in the *category*, and `embedding_text` had never included
one. A note about bouldering, filed under Hobbies, contained no more
relation to the query "hobbies" than to any other word it does not happen to
contain, so the vectors could not answer the one question the category
exists to answer.

The same gap swallowed attachments. A scanned lecture PDF hanging off a
two-word note was, to the vectors, a two-word note, even now that the
attachment carries a caption and extracted text of its own
(`Attachment.caption`/`ocr_text`, added alongside these tests).

The trap this file exists to hold: this app's models declare foreign keys
and **no ORM `relationship()` anywhere**, so `entry.category` and
`entry.attachments` are not attributes that exist. The first version of the
fix read them with `getattr(entry, "category", None)` and would have indexed
nothing at all, forever, without ever raising, exactly the "features that
never ran once" shape CLAUDE.md warns about. These tests fail if that
regresses, because they assert on the text rather than on the code path.
"""

from __future__ import annotations

from memorymap.ai.embeddings import embedding_text
from memorymap.core.database import Attachment, Category, Entry


def _entry(session, **kwargs) -> Entry:
    entry = Entry(workspace_id="default", **kwargs)
    session.add(entry)
    session.flush()
    return entry


def test_the_category_name_is_part_of_what_gets_embedded(session):
    category = Category(name="Hobbies", workspace_id="default")
    session.add(category)
    session.flush()
    entry = _entry(session, content="Went bouldering after work", category_id=category.id)

    text = embedding_text(session, entry)

    assert "Went bouldering after work" in text
    assert "Hobbies" in text, "a note's category is how the user themselves files it"


def test_tags_come_along_too(session):
    entry = _entry(session, content="Route grades to work on", tags='["climbing", "gym"]')

    text = embedding_text(session, entry)

    assert "climbing" in text
    assert "gym" in text


def test_uncategorised_is_not_worth_embedding(session):
    """It is the *absence* of filing, so putting the word in every unfiled
    note's vector would only pull them all toward each other."""
    category = Category(name="Uncategorised", workspace_id="default")
    session.add(category)
    session.flush()
    entry = _entry(session, content="A stray thought", category_id=category.id)

    assert "Uncategorised" not in embedding_text(session, entry)


def test_an_attachments_own_text_is_searchable_with_its_note(session):
    entry = _entry(session, content="Lecture 4")
    session.add(
        Attachment(
            entry_id=entry.id,
            filename="lecture4.pdf",
            stored_name="stored.pdf",
            mime="application/pdf",
            ocr_text="Dijkstra's algorithm and priority queues",
            workspace_id="default",
        )
    )
    session.flush()

    text = embedding_text(session, entry)

    assert "Dijkstra" in text, "a scanned PDF's text must reach the note's own vector"
    assert "lecture4.pdf" in text


def test_a_plain_note_still_embeds_as_just_itself(session):
    """The floor this must not cross: nothing extra is invented for a note
    with no category, no tags and no files."""
    entry = _entry(session, content="Just a line of text")

    assert embedding_text(session, entry).strip() == "Just a line of text"
