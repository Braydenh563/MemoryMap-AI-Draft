"""Keyword search: the whole of search when no AI is running.

It used to be a single `LIKE %query%`, so the words had to appear as a
contiguous substring in exactly the order typed. Word order is not something
anyone should have to guess.
"""

from __future__ import annotations

import pytest

from memorymap.core.database import Entry
from memorymap.search import search_manager


@pytest.fixture()
def notes(session):
    rows = [
        ("bread proving times vary by temperature", '["baking"]'),
        ("proving dough overnight in the fridge", '["bread"]'),
        ("sourdough starter needs feeding daily", "[]"),
        ("my bread recipe notes", "[]"),
    ]
    for content, tags in rows:
        session.add(Entry(content=content, tags=tags, ai_confidence=0))
    session.commit()
    return session


def _contents(hits):
    return [h.content for h in hits]


def test_word_order_does_not_matter(notes):
    """The bug: "proving bread" found nothing, "bread proving" found one."""
    forwards = _contents(search_manager.keyword_search(notes, "bread proving"))
    backwards = _contents(search_manager.keyword_search(notes, "proving bread"))
    assert len(forwards) == 2
    assert sorted(forwards) == sorted(backwards)


def test_all_words_must_appear_somewhere(notes):
    hits = _contents(search_manager.keyword_search(notes, "fridge dough"))
    assert hits == ["proving dough overnight in the fridge"]


def test_tags_are_searched_too(notes):
    """A tag is a deliberate choice, so it should be findable."""
    hits = _contents(search_manager.keyword_search(notes, "baking"))
    assert "bread proving times vary by temperature" in hits


def test_an_exact_phrase_ranks_above_scattered_words(notes):
    hits = _contents(search_manager.keyword_search(notes, "bread proving"))
    assert hits[0] == "bread proving times vary by temperature"


def test_partial_matches_beat_an_empty_page(notes):
    """No note has all three words; showing some beats showing nothing."""
    hits = search_manager.keyword_search(notes, "bread sourdough kayaking")
    assert hits, "a partial answer is better than none"


def test_search_is_case_insensitive(notes):
    assert len(search_manager.keyword_search(notes, "BREAD")) == len(
        search_manager.keyword_search(notes, "bread")
    )


def test_punctuation_is_ignored(notes):
    assert _contents(search_manager.keyword_search(notes, "bread, proving!")) == _contents(
        search_manager.keyword_search(notes, "bread proving")
    )


def test_nothing_matching_returns_nothing(notes):
    assert search_manager.keyword_search(notes, "helicopter") == []


def test_an_empty_query_returns_nothing(notes):
    assert search_manager.keyword_search(notes, "   ") == []


def test_private_and_binned_notes_stay_out(notes, session):
    session.add(Entry(content="bread secret", is_private=True, ai_confidence=0))
    session.add(Entry(content="bread binned", is_deleted=True, ai_confidence=0))
    session.commit()
    found = _contents(search_manager.keyword_search(notes, "bread"))
    assert "bread secret" not in found
    assert "bread binned" not in found


def test_the_limit_is_respected(notes):
    assert len(search_manager.keyword_search(notes, "bread", limit=1)) == 1


def test_a_question_made_of_common_words_is_not_a_keyword_search(notes):
    """"what have I saved so far?" has no keywords in it.

    Matching on its words would return the whole notebook, "%a%" appears in
    nearly every note: so it must come back empty and let the caller fall
    through to showing recent notes instead.
    """
    assert search_manager.keyword_search(notes, "what have I saved so far?") == []
    assert search_manager.keyword_search(notes, "how do I") == []


def test_stopwords_are_ignored_but_real_words_still_count(notes):
    """"what about the bread" should search for "bread", not for "the"."""
    hits = _contents(search_manager.keyword_search(notes, "what about the bread"))
    assert hits
    assert all("bread" in h or "proving" in h for h in hits)


def test_short_words_do_not_match_everything(notes):
    assert search_manager.keyword_search(notes, "a") == []


# --- saved filters -------------------------------------------------------------


def test_saved_searches_round_trip(client):
    """A named filter is just a preference, so it survives a restart."""
    saved = [{"name": "Work, untagged", "query": "tag:work is:untagged"}]
    body = client.put("/preferences", json={"saved_searches": saved}).json()
    assert body["saved_searches"] == saved

    # And it comes back on a fresh read, not just in the write response.
    assert client.get("/preferences").json()["saved_searches"] == saved


def test_saved_searches_default_to_empty(client):
    assert client.get("/preferences").json()["saved_searches"] == []


def test_a_saved_search_needs_a_name_and_a_query(client):
    too_short = client.put("/preferences", json={"saved_searches": [{"name": "", "query": "x"}]})
    assert too_short.status_code == 422
    no_query = client.put("/preferences", json={"saved_searches": [{"name": "x", "query": ""}]})
    assert no_query.status_code == 422


def test_a_misspelt_word_still_finds_the_note(notes):
    """"sourdogh" is one letter off a word the notebook holds; the FTS
    vocabulary knows that word, so the search lands on it instead of on an
    empty page."""
    hits = _contents(search_manager.keyword_search(notes, "sourdogh starter"))
    assert hits == ["sourdough starter needs feeding daily"]


def test_a_word_stem_matches_its_longer_forms(notes):
    """"sourdo" matches nothing whole, so it is tried as a prefix."""
    hits = _contents(search_manager.keyword_search(notes, "sourdo"))
    assert hits == ["sourdough starter needs feeding daily"]


def test_a_short_word_is_never_corrected(notes):
    """Three letters are one edit from too many words to guess at."""
    assert search_manager.keyword_search(notes, "zzz") == []


def test_inflections_match_by_stem(notes):
    """"prove" finds "proving": the index stems (porter), so a query in a
    different inflection than the note is not a miss. With no AI running
    this is the whole of search."""
    hits = _contents(search_manager.keyword_search(notes, "prove dough"))
    assert hits == ["proving dough overnight in the fridge"]


def test_an_index_built_without_stemming_is_rebuilt_once(tmp_path):
    """A notebook from before stemming has an FTS table on the default
    tokenizer. A tokenizer is fixed at CREATE time, so startup drops and
    rebuilds that index (never the notes) exactly once."""
    from sqlalchemy import text

    from memorymap.core.database import DatabaseManager

    db_path = tmp_path / "old.db"
    db = DatabaseManager(db_path)
    with db.session() as session:
        session.add(Entry(content="proving dough overnight", tags="[]", ai_confidence=0))
        session.commit()
    # Put the old-shape index back, as an older build would have left it.
    with db.engine.begin() as connection:
        for trigger in ("entries_fts_ai", "entries_fts_ad", "entries_fts_au"):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
        connection.exec_driver_sql("DROP TABLE IF EXISTS entries_fts_vocab")
        connection.exec_driver_sql("DROP TABLE IF EXISTS entries_fts")
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE entries_fts USING fts5("
            "content, tags, content='entries', content_rowid='id')"
        )
        connection.exec_driver_sql(
            "INSERT INTO entries_fts(rowid, content, tags) SELECT id, content, tags FROM entries"
        )
    reopened = DatabaseManager(db_path)
    with reopened.engine.begin() as connection:
        ddl = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='entries_fts'"
        ).scalar()
        assert "porter" in ddl
        assert connection.execute(text("SELECT count(*) FROM entries_fts")).scalar() == 1
    with reopened.session() as session:
        assert _contents(search_manager.keyword_search(session, "prove")) == [
            "proving dough overnight"
        ]
