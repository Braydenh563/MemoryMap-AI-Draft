"""Alternative wordings for a passage the app's own checks cannot fix.

Asked for directly: *"the listed errors in suggestions have no way to have the
ai write a suggested replacement or multiple for the user to choose."* The
built-in checks catch spelling, spacing and sentence length and can offer a fix
for the first two; for "this sentence is hard to follow" there is no mechanical
answer, and the suggestion menu could only say so.

Nothing is saved: the alternatives come back for the writer to pick from, the
same rule `ai_edit` follows. These tests are about the parsing, because that is
where a small local model's reply actually goes wrong: numbering that varies,
quotes half the time, and a fondness for handing back the original.
"""

from __future__ import annotations

from memorymap.ai.drafter import _parse_rephrasings


def test_numbered_lines_become_options():
    reply = "1. The first way\n2. A second way\n3. Or this way"
    assert _parse_rephrasings(reply, "original", 3) == [
        "The first way",
        "A second way",
        "Or this way",
    ]


def test_other_numbering_styles_are_accepted():
    """Small models number with whatever they feel like."""
    assert _parse_rephrasings("1) One\n- Two\n* Three\n• Four", "x", 4) == [
        "One",
        "Two",
        "Three",
        "Four",
    ]


def test_surrounding_quotes_are_dropped():
    """A quoted answer pasted into a document brings its quotes with it."""
    assert _parse_rephrasings('1. "Quoted answer"', "x", 3) == ["Quoted answer"]


def test_the_original_is_never_offered_back():
    """An option that changes nothing costs a click and does nothing."""
    reply = "1. the same words\n2. genuinely different"
    assert _parse_rephrasings(reply, "the same words", 3) == ["genuinely different"]


def test_duplicates_are_dropped():
    reply = "1. One way\n2. one way\n3. Another way"
    assert _parse_rephrasings(reply, "x", 3) == ["One way", "Another way"]


def test_the_count_is_a_ceiling():
    reply = "\n".join(f"{i}. Option {i}" for i in range(1, 9))
    assert len(_parse_rephrasings(reply, "x", 3)) == 3


def test_an_empty_or_unusable_reply_is_no_options():
    assert _parse_rephrasings("", "x", 3) == []
    assert _parse_rephrasings("\n\n  \n", "x", 3) == []


def test_the_endpoint_answers_with_no_model_running(client):
    """Offline is "no suggestions", not an error the writer caused."""
    doc = client.post("/documents", json={"title": "T", "content": "Some words."}).json()
    body = client.post(
        f"/documents/{doc['id']}/rephrase",
        json={"passage": "Some words.", "note": "This sentence runs long"},
    )
    assert body.status_code == 200, body.text
    assert body.json()["options"] == []


def test_a_missing_document_is_a_404(client):
    assert client.post("/documents/999999/rephrase", json={"passage": "x"}).status_code == 404
