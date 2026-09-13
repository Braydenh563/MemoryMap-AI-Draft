"""Reading a question before searching for it, and searching both ways at once.

Three changes, all asked for directly, all in the same path:

1. *"Take into account the time of notes as well. So if I ask 'what notes have
   I saved in the last week', it will return the right ones."*, a time phrase
   is a **filter**, not search terms. Before this it was neither: it diluted
   the embedding, dragged the keyword search off course, and the range it meant
   was never applied.
2. *"Use the embedding model to improve the semantic search… streamline the
   user's query into something that returns better results."*, the question's
   scaffolding comes off before anything is embedded. For a three-word subject
   "what did I write about" is most of the sentence, so the vector describes
   the phrasing rather than the subject.
3. Both searches now run and their rankings are **fused**, where before
   semantic won outright and keyword was only consulted when semantic came
   back empty. A note containing the query verbatim used to lose to three notes
   that were vaguely on topic.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from memorymap.core.database import Entry, EntryLink
from memorymap.search import query, search_manager

TODAY = date(2026, 8, 2)


@pytest.fixture(autouse=True)
def _today_is_fixed(monkeypatch):
    """Pin the notebook's "today" to `TODAY` for every test in this file.

    The date tests build notes at `TODAY - N days` and then ask questions like
    "in the last week", but `search_manager.retrieve` reads the *real* clock
    through `_user_today`. So these passed only while the wall clock happened
    to sit within a week of `TODAY`, and started failing on their own six days
    after they were written, with a diff that pointed at the search code and
    an empty result set that looked exactly like a retrieval bug. A dated test
    has to own its own date.
    """
    monkeypatch.setattr(search_manager, "_user_today", lambda _session: TODAY)


def _note(session, content, tags=None, days_ago=0, parent_id=None):
    entry = Entry(
        content=content,
        tags=json.dumps(tags or []),
        parent_id=parent_id,
        created_at=datetime(2026, 8, 2, 12, 0) - timedelta(days=days_ago),
    )
    session.add(entry)
    session.commit()
    return entry


# --- what the question was asking ----------------------------------------------


@pytest.mark.parametrize(
    "question,since,until",
    [
        ("what notes have I saved in the last week", date(2026, 7, 26), TODAY),
        ("what did I write yesterday", date(2026, 8, 1), date(2026, 8, 1)),
        ("anything from this month", date(2026, 8, 1), TODAY),
        ("notes from the last 3 days", date(2026, 7, 30), TODAY),
        ("what have I saved recently", date(2026, 7, 19), TODAY),
        ("what did I save today", TODAY, TODAY),
    ],
)
def test_a_time_phrase_becomes_a_date_range(question, since, until):
    asked = query.understand(question, TODAY)
    assert (asked.since, asked.until) == (since, until)


def test_a_question_only_about_time_has_no_subject_left():
    """"What did I write last week" has nothing to be similar *to*. Saying so
    is what lets retrieval list the range instead of ranking noise."""
    asked = query.understand("what notes have I saved in the last week", TODAY)
    assert asked.time_only is True
    assert asked.subject == ""


def test_a_subject_survives_the_time_phrase_being_lifted_out():
    asked = query.understand("what did I write about the allotment last week", TODAY)
    assert asked.subject == "allotment"
    assert asked.since == date(2026, 7, 26)
    assert asked.time_only is False


def test_scaffolding_comes_off_the_subject():
    """The embedding half. "show me my notes about bread" and "bread" should
    reach the model as the same search."""
    assert query.understand("show me my notes about bread", TODAY).subject == "bread"
    assert query.understand("find my notes on the shed", TODAY).subject == "shed"


def test_a_question_word_inside_the_subject_is_kept():
    """Only the *front* is stripped. "how" is scaffolding at the start of
    "how many notes" and the subject itself in "how do I prove bread"."""
    asked = query.understand("how do I prove bread", TODAY)
    assert "prove bread" in asked.subject


def test_a_question_with_no_time_and_no_scaffolding_is_left_alone():
    asked = query.understand("beans", TODAY)
    assert asked.subject == "beans"
    assert asked.has_range is False


def test_an_empty_question_is_not_an_error():
    asked = query.understand("", TODAY)
    assert asked.subject == "" and asked.has_range is False


# --- what retrieval does with it ------------------------------------------------


def test_a_time_only_question_returns_the_notes_from_that_range(session, fake_embeddings):
    _note(session, "bread proving notes from ages ago", days_ago=60)
    recent_one = _note(session, "the beans need netting", days_ago=2)
    recent_two = _note(session, "shed door hinge", days_ago=5)

    found, mode = search_manager.retrieve(
        session, "what notes have I saved in the last week", fake_embeddings
    )
    assert mode == "dated"
    assert {e.id for e in found} == {recent_one.id, recent_two.id}


def test_a_range_narrows_a_subject_search(session, fake_embeddings):
    """The failure this prevents: a better-matching note from March answering
    a question that said "last week"."""
    _note(session, "the allotment, everything about it", days_ago=90)
    recent = _note(session, "allotment: netting the beans", days_ago=1)

    found, _mode = search_manager.retrieve(
        session, "what did I write about the allotment last week", fake_embeddings
    )
    assert [e.id for e in found] == [recent.id]


def test_an_exact_phrase_is_not_lost_to_vaguely_related_notes(session, fake_embeddings):
    """Reciprocal rank fusion, as a property. The note containing the words
    must not be beaten by notes that merely score higher by cosine."""
    exact = _note(session, "sourdough starter feeding schedule")
    for n in range(4):
        _note(session, f"a note about baking in general, number {n}")

    found, mode = search_manager.retrieve(
        session, "sourdough starter feeding schedule", fake_embeddings, limit=3
    )
    assert exact.id in {e.id for e in found}
    assert mode in {"hybrid", "semantic", "keyword"}


# --- the graph in every answer --------------------------------------------------


def test_a_linked_note_is_pulled_in_beside_the_match(session, fake_embeddings):
    """What makes this a memory *map* rather than a search box: you wrote the
    question's subject in one note and the thing you need in the note you
    linked from it."""
    match = _note(session, "the beans need netting before the pigeons find them")
    linked = _note(session, "netting is in the shed behind the mower")
    session.add(EntryLink(source_entry_id=match.id, target_entry_id=linked.id))
    session.commit()

    found, _mode = search_manager.retrieve(session, "beans netting", fake_embeddings, limit=1)
    ids = [e.id for e in found]
    assert match.id in ids
    assert linked.id in ids, "the note the match links to should come with it"
    # Context, not a match: it comes after everything that actually matched, so
    # a budgeted prompt drops it first.
    assert ids.index(linked.id) > ids.index(match.id)


def test_a_reply_is_pulled_in_with_the_note_it_answers(session, fake_embeddings):
    root = _note(session, "trying a new proving schedule")
    reply = _note(session, "day two: better crumb", parent_id=root.id)

    found, _mode = search_manager.retrieve(session, "proving schedule", fake_embeddings, limit=1)
    assert reply.id in {e.id for e in found}


def test_expansion_can_be_switched_off(session, fake_embeddings):
    """Callers that want the matches alone, a duplicate check, where a linked
    note is not a candidate for anything."""
    match = _note(session, "the beans need netting")
    linked = _note(session, "netting is in the shed")
    session.add(EntryLink(source_entry_id=match.id, target_entry_id=linked.id))
    session.commit()

    found, _mode = search_manager.retrieve(
        session, "beans netting", fake_embeddings, limit=1, expand_graph=False
    )
    assert [e.id for e in found] == [match.id]


def test_expansion_never_reaches_a_private_note(session, fake_embeddings):
    """Retrieval feeds the model. A private note must not arrive by the back
    door of being linked to something public."""
    match = _note(session, "the beans need netting")
    secret = _note(session, "something I would rather keep to myself")
    secret.is_private = True
    session.add(EntryLink(source_entry_id=match.id, target_entry_id=secret.id))
    session.commit()

    found, _mode = search_manager.retrieve(session, "beans netting", fake_embeddings, limit=2)
    assert secret.id not in {e.id for e in found}


def test_a_dated_question_that_finds_nothing_answers_nothing(session, fake_embeddings):
    """The "never look empty" fallback must not quietly drop *either* of the
    constraints the person stated.

    This test asserted the opposite until a user hit the case it was protecting.
    The original half still holds and is still tested: asking about the allotment
    *last week*, with nothing about the allotment that week, must not fall back
    to notes from any time at all labelled `recent`. What was wrong was the
    remedy: it fell back to *everything in the window*, which drops the subject
    instead of the date and is the same mistake facing the other way.

    Reported, in the shape that makes it obvious:

        *"I have a note with a joke in it … when I go into the ask section and
        say 'jokes I have saved recently', it doesn't show."*

    It did not show. A note about a **gym routine** showed, because it was the
    only thing inside the fortnight. From the outside that is indistinguishable
    from the notebook claiming that gym routine is a joke it has on file.

    Two constraints, and the answer to satisfying neither is not to satisfy the
    less specific one: it is to say so. `dated` with nothing in it is a true
    answer the caller renders as "nothing matching 'last week'", naming the
    phrase so the next thing to try is obvious.
    """
    _note(session, "the allotment, everything about it", days_ago=90)
    this_week = _note(session, "unrelated, but from this week", days_ago=2)

    found, mode = search_manager.retrieve(
        session, "what did I write about the allotment last week", fake_embeddings
    )
    assert mode == "dated"
    # Not the out-of-window match, the date was a real constraint.
    assert all(e.id != 90 for e in found)
    # And not the in-window non-match either, so was the subject.
    assert this_week.id not in {e.id for e in found}
    assert found == []


def test_a_question_only_about_time_still_lists_its_window(session, fake_embeddings):
    """The fallback above is narrowed, not removed.

    With no subject there is only one constraint, so listing the window is not
    dropping anything: it is the whole question, answered.
    """
    _note(session, "the allotment, everything about it", days_ago=90)
    this_week = _note(session, "written this week", days_ago=2)

    found, mode = search_manager.retrieve(
        session, "what did I write last week", fake_embeddings
    )
    assert mode == "dated"
    assert this_week.id in {e.id for e in found}


def test_recently_is_a_lean_not_a_boundary(session, fake_embeddings):
    """"Recently" must not exclude, only prefer.

    The reported case, reduced: two notes tagged as jokes, both older than the
    fortnight that "recently" resolves to, and a recent note about something
    else. Filtering on the vague word answered a question about jokes with the
    gym routine. Nobody who says "recently" has a boundary in mind, and any
    number this codebase picks for it is wrong for somebody by a day, so it
    orders the matches and does not remove them.

    "Last week" is a different kind of word and keeps its teeth: see
    `test_a_dated_question_that_finds_nothing_answers_nothing` above.
    """
    # Tagged rather than worded, which is the reported case exactly: the note
    # is a joke and never uses the word.
    old_joke = _note(
        session, "why did the student eat his homework", tags=["joke", "jokes"], days_ago=16
    )
    older_joke = _note(
        session, "the one about a chicken crossing a road", tags=["joke", "jokes"], days_ago=30
    )
    _note(session, "gym routine: push, pull, legs", tags=["gym"], days_ago=2)

    found, mode = search_manager.retrieve(
        session, "jokes I have saved recently", fake_embeddings
    )
    ids = [e.id for e in found]
    assert mode != "dated", "a subject question must not be answered by date alone"
    assert old_joke.id in ids and older_joke.id in ids
    # Newest first: that is what the word was actually asking for.
    assert ids.index(old_joke.id) < ids.index(older_joke.id)


def test_the_subject_survives_a_time_phrase_in_the_middle(session, fake_embeddings):
    """Scaffolding is peeled off both ends, not only the front.

    "jokes I have saved recently" left `jokes I have saved` once the time phrase
    was lifted out, and "jokes from the last month" left a dangling `jokes from`
    - both then reached the keyword search as several required terms and the
    embedder as a sentence about saving rather than about jokes.
    """
    from memorymap.search import query as query_understanding

    assert query_understanding.understand("jokes I have saved recently").subject == "jokes"
    assert query_understanding.understand("jokes from the last month").subject == "jokes"
    # And a real subject word that merely looks like filler is never eaten.
    assert query_understanding.understand("notes about my day").subject == "day"


def test_an_empty_window_returns_nothing_rather_than_something_else(session, fake_embeddings):
    """A true empty answer the caller can render as "nothing that week" beats a
    list of notes from three months ago."""
    _note(session, "the allotment, everything about it", days_ago=90)

    found, mode = search_manager.retrieve(
        session, "what did I write about the allotment last week", fake_embeddings
    )
    assert mode == "dated"
    assert found == []


def test_an_undated_question_still_falls_back_to_recent(session, fake_embeddings):
    """The original behaviour, unchanged where it was right: a notebook must
    never look empty when it isn't."""
    _note(session, "a note about something else entirely")
    found, mode = search_manager.retrieve(
        session, "zzz nothing matches this zzz", fake_embeddings
    )
    assert mode == "recent"
    assert found
