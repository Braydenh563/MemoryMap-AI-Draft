"""Reading a PDF by page range, not one page at a time.

Reported directly: *"on files like pdfs, there's a read text on this page
option but not an option to read the text on the whole document or specific
pages."* The OCR workspace could read the page you were looking at and
nothing else, so transcribing a ten-page scan meant ten clicks and ten waits.

The parser is what these cover. The read itself is a loop over the existing
single-page reader: deliberately, so "no rasteriser", "no vision model" and
"nothing legible" keep one definition: and the model half is unverifiable
here for the usual reason (no Ollama in the sandbox).
"""

from __future__ import annotations

import pytest

from memorymap.api.routes_files import MAX_RANGE_PAGES, _parse_page_spec


@pytest.mark.parametrize(
    ("spec", "count", "expected"),
    [
        # "everything", in the two spellings a caller might send.
        ("all", 5, [0, 1, 2, 3, 4]),
        ("*", 3, [0, 1, 2]),
        # Empty means the same as "all": the control defaults to the whole
        # document, so a blank box must not read nothing.
        ("", 3, [0, 1, 2]),
        # One-based on the way in, because that is what the page rail shows.
        ("1", 5, [0]),
        ("2-2", 5, [1]),
        ("1-3", 5, [0, 1, 2]),
        ("1,4", 5, [0, 3]),
        ("1-2,4-5", 5, [0, 1, 3, 4]),
        (" 1 - 2 , 4 ", 5, [0, 1, 3]),  # spaces are how people actually type
    ],
)
def test_a_page_spec_becomes_the_pages_a_person_meant(spec, count, expected):
    assert _parse_page_spec(spec, count) == expected


def test_a_backwards_range_is_read_the_way_it_was_meant():
    """"3-1" is a typo for "1-3", not an empty selection."""
    assert _parse_page_spec("3-1", 5) == [0, 1, 2]


def test_a_range_past_the_end_is_clamped_to_the_document():
    assert _parse_page_spec("1-99", 3) == [0, 1, 2]


def test_page_zero_does_not_exist_because_people_count_from_one():
    assert _parse_page_spec("0", 3) == []


def test_junk_is_skipped_rather_than_refusing_the_whole_range():
    """A stray character should cost you that one part, not the request.

    Refusing everything would mean a mistyped range reads nothing and says
    little; this reads the pages it could understand.
    """
    assert _parse_page_spec("abc", 3) == []
    assert _parse_page_spec("1,abc,3", 5) == [0, 2]


def test_duplicates_and_overlaps_collapse():
    """Asking for a page twice must not read it twice, a vision pass is
    seconds per page, and the overlap in "1-3,2-4" is easy to type."""
    assert _parse_page_spec("1-3,2-4", 10) == [0, 1, 2, 3]
    assert _parse_page_spec("2,2,2", 5) == [1]


def test_there_is_a_ceiling_on_one_request():
    """"All" on a 300-page scan is not a request anyone means synchronously."""
    assert MAX_RANGE_PAGES > 0
    assert len(_parse_page_spec("all", 300)) == 300  # the parser is honest…
    # …and the cap is applied by `_vision_read_range`, which reports how far it
    # got so the reader can ask for the next block.
