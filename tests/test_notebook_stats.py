"""Questions about the shape of the notebook, answered by counting.

Asked for directly: *"enhance the semantic search so it can pick up stuff like
if I ask 'what are my most common tags', or maybe 'categories with the most
notes'."*

Retrieval cannot answer these and that is not a tuning problem: semantic search
finds the notes most *like* a question, and "what are my most common tags" is
not like any note. Before this, such a question retrieved five arbitrary notes
and the model was told to answer from those alone, so it either declined or
invented a ranking from a five-note sample.

These tests are exact on purpose. The whole argument for computing rather than
retrieving is that the answer is a fact, so a test that accepted "roughly the
right tags" would be testing the thing this replaced.
"""

from __future__ import annotations

import json
from pathlib import Path

from memorymap.ai import notebook_stats
from memorymap.core import deps
from memorymap.core.database import Category, Entry, EntryLink


def _note(session, content, tags=(), category=None):
    entry = Entry(content=content, tags=json.dumps(list(tags)))
    if category is not None:
        entry.category_id = category
    session.add(entry)
    session.flush()
    return entry


def _session():
    return deps.get_db().session()


def test_most_common_tags_are_ranked(client):
    with _session() as session:
        _note(session, "a", ["work", "urgent"])
        _note(session, "b", ["work"])
        _note(session, "c", ["work", "idea"])
        _note(session, "d", ["idea"])
        session.commit()
        result = notebook_stats.answer("what are my most common tags", session)
    assert result is not None
    assert result.kind == "tags"
    assert [fact["label"] for fact in result.facts][:2] == ["work", "idea"]
    assert result.facts[0]["count"] == 3
    assert "work (3)" in result.text


def test_the_question_can_be_phrased_several_ways(client):
    with _session() as session:
        _note(session, "a", ["work"])
        session.commit()
        for phrasing in (
            "what are my most common tags",
            "which tags do I use most",
            "top tags",
            "my most popular tags?",
        ):
            assert notebook_stats.answer(phrasing, session) is not None, phrasing


def test_categories_with_the_most_notes(client):
    with _session() as session:
        big = Category(name="Work")
        small = Category(name="Cooking")
        session.add_all([big, small])
        session.flush()
        _note(session, "a", category=big.id)
        _note(session, "b", category=big.id)
        _note(session, "c", category=small.id)
        session.commit()
        result = notebook_stats.answer("which categories have the most notes", session)
    assert result is not None
    assert result.facts[0] == {"label": "Work", "count": 2}


def test_binned_and_private_notes_are_nobody_s_statistics(client):
    """A count that changes when a note is made private leaks what is in it."""
    with _session() as session:
        _note(session, "counted", ["shown"])
        hidden = _note(session, "private", ["secret"])
        hidden.is_private = True
        binned = _note(session, "binned", ["gone"])
        binned.deleted_at = notebook_stats.utcnow()
        session.commit()
        result = notebook_stats.answer("how many notes do I have", session)
        tags = notebook_stats.answer("my most common tags", session)
    assert result.facts[0]["count"] == 1
    assert [fact["label"] for fact in tags.facts] == ["shown"]


def test_untagged_notes_are_countable(client):
    with _session() as session:
        _note(session, "tagged", ["x"])
        _note(session, "bare")
        _note(session, "also bare")
        session.commit()
        result = notebook_stats.answer("how many notes have no tags", session)
    assert result.facts[0] == {"label": "untagged", "count": 2}


def test_most_connected_notes_count_both_directions(client):
    """A note everything points at is as central as one that points at everything."""
    with _session() as session:
        hub = _note(session, "the hub")
        a = _note(session, "a")
        b = _note(session, "b")
        session.add_all(
            [
                EntryLink(source_entry_id=a.id, target_entry_id=hub.id),
                EntryLink(source_entry_id=b.id, target_entry_id=hub.id),
            ]
        )
        session.commit()
        result = notebook_stats.answer("which are my most linked notes", session)
    assert result.facts[0]["label"] == "the hub"
    assert result.facts[0]["count"] == 2


def test_an_empty_notebook_answers_plainly(client):
    with _session() as session:
        result = notebook_stats.answer("what are my most common tags", session)
    assert result is not None
    assert "not tagged any notes" in result.text


def test_an_ordinary_question_falls_through_to_search(client):
    """Anything not recognised must behave exactly as it did before."""
    with _session() as session:
        for question in (
            "what did I write about pasta",
            "summarise my week",
            "hello",
            "what does the note about tags say",
        ):
            assert notebook_stats.answer(question, session) is None, question


def test_a_singular_count_reads_as_english(client):
    with _session() as session:
        _note(session, "only one")
        session.commit()
        assert "1 note." in notebook_stats.answer("how many notes do I have", session).text


def test_categories_pluralise_correctly(client):
    with _session() as session:
        session.add(Category(name="Only"))
        session.commit()
        text = notebook_stats.answer("how many categories do I have", session).text
    assert "1 category." in text


def test_the_chat_route_answers_with_the_count_and_no_model(client):
    """End to end, and with nothing running: the point of computing these.

    A local model may be stopped, slow to load, or absent entirely. A question
    about the notebook's own shape has an exact answer that needs none of it,
    and this is the test that says so.
    """
    with _session() as session:
        _note(session, "a", ["work", "urgent"])
        _note(session, "b", ["work"])
        session.commit()
    reply = client.post("/chat", json={"question": "what are my most common tags"})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert "work (2)" in body["ai_response"]
    assert body["answered_by"] is None, (
        "no model wrote this sentence, so none may be named under it"
    )


def test_an_ordinary_question_still_goes_through_search(client):
    """The fall-through must be the behaviour that was there before."""
    with _session() as session:
        _note(session, "the pasta recipe uses fresh basil", ["cooking"])
        session.commit()
    body = client.post("/chat", json={"question": "what did I write about pasta"}).json()
    assert "work (" not in body["ai_response"]


# --- spelling, and the questions added with it -------------------------------
#
# Reported: "the stats semantic search needs to be improved and also it doesnt
# account for spelling mistakes." Every matcher in this module is a regex over
# literal words, so a typo did not degrade the answer, it produced the *worst*
# available one, falling through to the retrieval path this module exists
# because retrieval answers badly.


def test_a_misspelt_question_still_gets_the_computed_answer(session) -> None:
    _note(session, "one", tags=["work"])
    _note(session, "two", tags=["work"])
    session.commit()
    for asked in (
        "what are my most common tags",
        "what are my most common tgas",
        "my most comon tags",
        "which catagories have the most notes",
    ):
        assert notebook_stats.answer(asked, session) is not None, asked


def test_it_does_not_correct_a_real_word_into_a_different_one(session) -> None:
    """The failure mode worth guarding: "notepad" is 0.67 similar to
    "notebook", and turning one into the other would answer a question the
    user did not ask. A missed correction costs a fallthrough; a wrong one
    costs a wrong answer."""
    assert notebook_stats._despell("open my notepad") == "open my notepad"
    assert notebook_stats._despell("count the docuemnts") == "count the documents"


def test_short_words_are_left_alone(session) -> None:
    # "tp" is as close to "to", "up" and "top"; correcting it guesses at
    # meaning rather than fixing spelling.
    assert notebook_stats._despell("tp tag") == "tp tag"


def test_every_vocabulary_word_is_one_the_matchers_look_for() -> None:
    """`_VOCABULARY` is written out by hand, so it can drift from the patterns.

    Scraping the regexes for their literals would mean parsing regex syntax and
    would quietly lose a word written inside a group the scraper did not
    understand. This checks the cheap direction instead: every vocabulary word
    appears somewhere in this module's source, so a word added to the list
    without a matcher, or left behind when a matcher is rewritten, shows up
    here rather than as a silently useless correction target.
    """
    import re

    source = Path(notebook_stats.__file__).read_text(encoding="utf-8")
    # The declaration itself does not count as a use.
    body = source.split("_VOCABULARY = (", 1)[1].split(").split()", 1)[1]
    # Every raw-string regex literal in the rest of the module. A word is
    # "looked for" if one of them matches it, `folders?` covers both "folder"
    # and "folders", and `most|top|common|commonest|…` covers five of the list
    # in one pattern, so a plain substring check would report those as unused.
    patterns = re.findall(r'r"([^"]+)"', body)
    missing = [
        word
        for word in notebook_stats._VOCABULARY
        if not any(re.fullmatch(f"(?:{p})", word) or re.search(p, word) for p in patterns)
    ]
    assert not missing, f"in _VOCABULARY but nothing looks for it: {missing}"


def test_word_count_counts_words_not_spaces(session) -> None:
    _note(session, "one  two   three")
    _note(session, "four")
    session.commit()
    answer = notebook_stats.answer("how many words have I written", session)
    assert answer is not None
    assert answer.kind == "word-count"
    # Four, not seven: the run of spaces must not each count as a word, which
    # is exactly what the SQL `length - length(replace(...))` trick would do.
    assert {fact["label"]: fact["count"] for fact in answer.facts}["words"] == 4


def test_longest_notes_ranks_and_skips_fragments(session) -> None:
    _note(session, "short")
    _note(session, "a much longer note " * 6)
    _note(session, "the very longest note in the whole notebook " * 8)
    session.commit()
    answer = notebook_stats.answer("what are my longest notes", session)
    assert answer is not None
    assert answer.kind == "longest-notes"
    counts = [fact["count"] for fact in answer.facts]
    assert counts == sorted(counts, reverse=True)
    # "short" is under the fragment floor, so it is not in the ranking.
    assert all("short" != fact["label"] for fact in answer.facts)


def test_tag_pairs_counts_each_pair_once(session) -> None:
    for _ in range(3):
        _note(session, "note", tags=["a", "b"])
    session.commit()
    answer = notebook_stats.answer("which tags go together", session)
    assert answer is not None
    assert answer.kind == "tag-pairs"
    # Three notes carry the pair; ordering the pair within itself is what stops
    # (a,b) and (b,a) both being counted, which would report six.
    assert answer.facts[0]["count"] == 3
    assert answer.facts[0]["label"] == "#a + #b"


def test_a_pair_seen_once_is_not_a_pattern(session) -> None:
    _note(session, "note", tags=["a", "b"])
    session.commit()
    answer = notebook_stats.answer("which tags appear together", session)
    assert answer is not None
    assert answer.facts == []
