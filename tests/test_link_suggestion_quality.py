"""What `GET /entries/link-suggestions` is allowed to offer.

The auto-linker was working exactly as written and surfacing nothing worth
acting on. Measured against a real 116-note notebook through a browser: **all
twelve suggestions were pairs of notes with identical text**, scoring 1.00,
six of them one stub note paired with six copies of itself. That is the
measured reason a notebook can sit at 16 linked notes out of 116 with the
auto-linker switched on the whole time, the twelve slots were full before a
single real connection could reach them.

Two rules came out of it, and these tests hold them:

  1. A near-identical pair is a **duplicate**, not a connection. This app has
     a separate feature for that case (`entry/duplicates.py`), and recording
     that a note resembles itself is not a link anyone wants.
  2. **One note may anchor at most `MAX_SUGGESTIONS_PER_NOTE` suggestions.**
     Otherwise the most connectable note in a notebook takes every slot and
     the list stops being a survey of the notebook.

The fake embedding service gives same-topic text the same direction, so two
notes sharing a topic word score 1.0, which is precisely the shape that
exposed the bug.
"""

from __future__ import annotations

from memorymap.api.routes_entries import MAX_SUGGESTIONS_PER_NOTE


def _suggest(client):
    response = client.get("/entries/link-suggestions")
    assert response.status_code == 200
    return response.json()


def _pairs(suggestions):
    return {frozenset((s["source_id"], s["target_id"])) for s in suggestions}


def test_two_notes_with_the_same_text_are_not_offered_as_a_link(client, fake_embeddings):
    """The exact case that filled every slot: a note and a copy of itself."""
    text = "Buy milk and eggs on the way home"
    a = client.post("/entries", json={"content": text}).json()
    b = client.post("/entries", json={"content": text}).json()

    assert frozenset((a["id"], b["id"])) not in _pairs(_suggest(client))


def test_notes_on_one_topic_in_different_words_are_still_offered(client, fake_embeddings):
    """The filter must not swallow the feature it is protecting.

    Both notes are about shopping, the same direction to the embedding
    service: but share almost no words, so `duplicates.similarity` scores
    them far below its threshold and they remain a real suggestion.
    """
    a = client.post("/entries", json={"content": "Remember to buy oat milk"}).json()
    b = client.post(
        "/entries", json={"content": "Ordered groceries for collection on Thursday"}
    ).json()

    assert frozenset((a["id"], b["id"])) in _pairs(_suggest(client))


def test_no_single_note_takes_more_than_its_share_of_the_slots(client, fake_embeddings):
    """One note plus many same-topic neighbours must not monopolise the list.

    Every note here scores 1.0 against every other (same topic word, different
    wording), so without the cap the first note would pair with all of the
    rest and fill the list on its own.
    """
    phrases = [
        "Buy oat milk today",
        "Shopping trip for the weekend",
        "Groceries: bread, rice, coffee",
        "Buy tickets before they sell out",
        "Milk delivery moved to Friday",
        "Shopping list for the party",
        "Groceries are cheaper at the market",
        "Buy a new kettle",
    ]
    for phrase in phrases:
        client.post("/entries", json={"content": phrase})

    suggestions = _suggest(client)
    assert suggestions, "the cap must not empty the list"

    appearances: dict[int, int] = {}
    for suggestion in suggestions:
        for note_id in (suggestion["source_id"], suggestion["target_id"]):
            appearances[note_id] = appearances.get(note_id, 0) + 1

    worst = max(appearances.values())
    assert worst <= MAX_SUGGESTIONS_PER_NOTE, (
        f"one note anchors {worst} suggestions, over the "
        f"{MAX_SUGGESTIONS_PER_NOTE} cap: {appearances}"
    )
