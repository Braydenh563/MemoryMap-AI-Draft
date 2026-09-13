"""`_keyword_context`: the text around a search hit, not the start of the
document: the "or something simpler" asked for directly: *"if the ai is
searching for something, might keywords be flagged in certain pages of a
file document in the actual document and/or extracted text, then it can use
a tool or smth simpler to get the full text from those areas??"*

`get_document`'s existing `query` argument already does this well when
embeddings are available (ranks paragraphs by cosine similarity); this is
the plain-substring fallback for the common case this project runs in on
purpose, no torch, no sentence-transformers (CLAUDE.md), and the one
`search_files`/`read_file` never had at all.
"""

from __future__ import annotations

from memorymap.ai.tools._common import _keyword_context


def test_no_needle_falls_back_to_a_head_of_text_clip():
    text = "a" * 500
    assert _keyword_context(text, "", length=50) == "a" * 49 + "…"


def test_no_match_falls_back_to_a_head_of_text_clip():
    text = "the quick brown fox " * 30
    out = _keyword_context(text, "xylophone", length=50)
    assert out == text[:49] + "…"


def test_the_match_is_actually_in_the_result():
    filler = "padding " * 200
    text = f"{filler}the password is hunter2{filler}"
    out = _keyword_context(text, "password", radius=50)
    assert "password is hunter2" in out
    # And it is not the whole 3,600-character document, the point of this
    # over a plain head clip is that it is short and centred.
    assert len(out) < 300


def test_case_insensitive():
    text = "some text before " + "PASSWORD: hunter2" + " some text after"
    out = _keyword_context(text, "password", radius=20)
    assert "PASSWORD: hunter2" in out


def test_ellipses_mark_what_was_cut_only_where_something_was_cut():
    text = "short text with keyword in the middle, nothing before or after cut off"
    out = _keyword_context(text, "keyword", radius=1000)
    # The whole text fits inside one radius-wide window, so nothing before
    # the match or after it was actually trimmed.
    assert not out.startswith("…")
    assert not out.endswith("…")


def test_multiple_hits_are_merged_when_their_windows_overlap():
    text = "start " + "keyword one " + ("filler " * 3) + "keyword two " + " end"
    out = _keyword_context(text, "keyword", radius=60, max_hits=3)
    # Close together: one continuous passage, not two near-duplicate snippets.
    assert out.count("\n\n") == 0
    assert "keyword one" in out and "keyword two" in out


def test_distant_hits_stay_as_separate_snippets():
    text = "keyword here" + (" filler" * 400) + "keyword there"
    out = _keyword_context(text, "keyword", radius=30, max_hits=3)
    assert "\n\n" in out
    assert "keyword here" in out
    assert "keyword there" in out


def test_a_hit_limit_of_zero_hits_is_never_produced():
    """max_hits caps how many locations are found, not how many survive
    merging: this just pins that a sane max_hits always returns something
    when there is a match."""
    text = "keyword " * 10
    out = _keyword_context(text, "keyword", radius=5, max_hits=2)
    assert "keyword" in out
