"""What a read-only tool call contributes to the answer's Sources panel.

Reported twice: *"improve the ui of the sources as well in the chat"*, then
*"what is shown about the sources, dropdown previews, hyperlinks etc."*, and
the front end could show none of it because none of it was ever sent: a tool
event carried a prose label and a bounded `result_summary` blob, so the panel
had a sentence where it needed a title, an address and a line of the page.

`_tool_sources` is that missing payload. These tests pin the three shapes it
has to read (a search's list of hits, one fetched page, a file read) and the
two rules that keep the panel honest: a write tool contributes nothing (a
change is not a source), and neither does a call that failed.
"""

from __future__ import annotations

from memorymap.ai.agent import SOURCE_SNIPPET_CHARS, _tool_sources


def test_a_web_search_yields_one_row_per_hit():
    rows = _tool_sources(
        "web_search",
        {
            "results": [
                {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762",
                 "snippet": "We propose a new simple network architecture."},
                {"title": "The Illustrated Transformer", "url": "https://jalammar.github.io/x/",
                 "snippet": "A visual walkthrough."},
            ]
        },
    )
    assert [r["title"] for r in rows] == ["Attention Is All You Need", "The Illustrated Transformer"]
    assert rows[0]["url"] == "https://arxiv.org/abs/1706.03762"
    assert rows[0]["snippet"].startswith("We propose")


def test_a_page_read_yields_the_page_itself():
    rows = _tool_sources(
        "read_url",
        {"title": "A page", "url": "https://example.com/a", "text": "Body text here."},
    )
    assert rows == [{"title": "A page", "url": "https://example.com/a", "snippet": "Body text here."}]


def test_a_url_with_no_title_still_becomes_a_row():
    """A card needs something to name it, and the address is the honest
    fallback: dropping the source entirely would under-report what the
    answer actually read."""
    rows = _tool_sources("read_url", {"url": "https://example.com/a", "text": "x"})
    assert rows[0]["title"] == "https://example.com/a"


def test_a_file_read_names_the_path():
    rows = _tool_sources("read_file", {"path": "vault/notes.md", "text": "Positional encoding."})
    assert rows == [{"title": "vault/notes.md", "url": "", "snippet": "Positional encoding."}]


def test_a_file_search_yields_one_row_per_match():
    rows = _tool_sources(
        "search_files",
        {"matches": [{"path": "a.md", "snippet": "one"}, {"path": "b.md", "snippet": "two"}]},
    )
    assert [r["title"] for r in rows] == ["a.md", "b.md"]


def test_snippets_are_clipped_and_flattened():
    """Eight of these ride on one SSE event, and a card shows two lines. A
    whole page in each would make the event large and the card useless."""
    rows = _tool_sources("read_url", {"url": "https://e.com", "text": "word " * 500})
    assert len(rows[0]["snippet"]) <= SOURCE_SNIPPET_CHARS
    assert "\n" not in rows[0]["snippet"]


def test_a_write_tool_contributes_nothing():
    """A change is not a source. `create_note`'s result names a note the answer
    *made*, and listing it under "what this answer drew on" would be a claim
    about provenance that is simply false."""
    assert _tool_sources("create_note", {"id": 3, "content": "hello"}) == []


def test_a_failed_call_contributes_nothing():
    assert _tool_sources("web_search", {"error": "Web search is disabled"}) == []


def test_a_result_that_is_not_a_dict_is_survivable():
    assert _tool_sources("read_url", None) == []
