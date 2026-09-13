"""The Library's document and board cards carry a preview of the real thing.

Both sub-tabs were reported as "boring and should probably have previews".
Each showed the same three facts for every row, an icon, a name, and a count
or a date: none of which tells four similarly-named drafts apart, or two
boards you drew last week, which is the job a list of them has.
"""

from __future__ import annotations

import pytest

from memorymap.api.routes_documents import PREVIEW_CHARS, _preview
from memorymap.api.routes_whiteboard import PREVIEW_POINTS, _preview_points
from memorymap.core import vault


@pytest.fixture
def open_vault(session):
    """Privacy needs a vault: without one `POST /entries/{id}/privacy`
    answers 409, not 200."""
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    yield
    vault.close()


def test_preview_strips_markdown_structure():
    """A preview that opens with `# ` or `- ` spends its first characters on
    syntax, and a heading is usually a restatement of the title already on the
    card."""
    text = _preview("# Chapter 3\n\n- draft\n\nThe measurement problem is real.")
    assert text.startswith("Chapter 3 draft The measurement")
    assert "#" not in text
    assert "- " not in text


def test_preview_cuts_at_a_word_boundary():
    """A hard slice ended the first rendered preview on "a different kind of
    de", which reads as broken rather than as truncated."""
    text = _preview("word " * 200)
    assert len(text) <= PREVIEW_CHARS + 1  # + the ellipsis
    assert text.endswith("…")
    assert not text.rstrip("…").endswith("wor")


def test_short_document_is_not_ellipsised():
    assert _preview("Just a line.") == "Just a line."


def test_preview_of_an_empty_document_is_empty():
    assert _preview("") == ""
    assert _preview("\n\n   \n") == ""


def test_points_are_normalised_into_the_unit_square():
    points = _preview_points([(100.0, 200.0), (300.0, 600.0), (200.0, 400.0)])
    assert points == [[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]]


def test_a_board_with_no_extent_centres_rather_than_dividing_by_zero():
    """One card, or a perfectly straight row of them, has zero extent on at
    least one axis."""
    assert _preview_points([(5.0, 5.0)]) == [[0.5, 0.5]]
    assert _preview_points([(0.0, 7.0), (10.0, 7.0)]) == [[0.0, 0.5], [1.0, 0.5]]


def test_a_large_board_is_sampled_across_its_whole_width_not_truncated():
    """`rows[:40]` of a 300-card board is whichever 40 cards were inserted
    first, which is not the board's shape."""
    rows = [(float(i), 0.0) for i in range(300)]
    points = _preview_points(rows)
    assert len(points) <= PREVIEW_POINTS
    # The last sampled point must come from near the far end of the board.
    assert points[-1][0] > 0.9


def test_empty_board_has_no_points():
    assert _preview_points([]) == []


# --- what the thumbnail actually says --------------------------------------
#
# Reported a second time, after the first version shipped: "the whiteboard
# preview is poor". Looking at it explained why in one glance, every card
# drew as an identical blank rectangle, so three boards all named "Cloud
# computing" showed three indistinguishable arrangements of grey blobs, and a
# board holding only sketches previewed as an *empty box* beside a line
# reading "2 sketches". A preview that carries only "how many, and roughly
# where" cannot do the job the list needs it for.


def test_a_card_carries_its_own_first_words(client):
    board = client.post("/whiteboard/boards", json={"name": "Reading"}).json()
    entry = client.post("/entries", json={"content": "# Kolmogorov complexity"}).json()
    client.post(
        "/whiteboard/nodes",
        json={"board_id": board["id"], "entry_id": entry["id"], "x": 10.0, "y": 20.0},
    )

    row = next(b for b in client.get("/whiteboard/boards").json() if b["id"] == board["id"])
    assert [i["label"] for i in row["preview_items"]] == ["Kolmogorov complexity"]
    assert [i["kind"] for i in row["preview_items"]] == ["card"]


def test_a_sketch_only_board_still_has_a_picture(client):
    """The case that previewed as nothing at all."""
    board = client.post("/whiteboard/boards", json={"name": "Doodles"}).json()
    client.post(
        "/whiteboard/sketches",
        json={"board_id": board["id"], "data": "[]", "x": 5.0, "y": 5.0},
    )

    row = next(b for b in client.get("/whiteboard/boards").json() if b["id"] == board["id"])
    assert [i["kind"] for i in row["preview_items"]] == ["sketch"]


def test_a_private_card_contributes_its_position_and_not_its_words(client, open_vault):
    """Same rule as the Connections block and the Library's file-usage chips:
    the fact of the thing is not secret, its contents are. A thumbnail is
    rendered on a wall of cards, which is the last place a private note's
    first line should appear."""
    board = client.post("/whiteboard/boards", json={"name": "Private"}).json()
    entry = client.post("/entries", json={"content": "SECRET diary line"}).json()
    client.post(
        "/whiteboard/nodes",
        json={"board_id": board["id"], "entry_id": entry["id"], "x": 1.0, "y": 2.0},
    )
    assert client.post(f"/entries/{entry['id']}/privacy", json={"private": True}).status_code == 200

    row = next(b for b in client.get("/whiteboard/boards").json() if b["id"] == board["id"])
    assert len(row["preview_items"]) == 1
    assert row["preview_items"][0]["label"] == ""
    assert "SECRET" not in str(row["preview_items"])


def test_labels_stay_with_their_own_positions(client):
    """The obvious way to break this while every number still looks
    plausible: sample the positions and the labels separately, and hand back
    a board whose cards all say the wrong thing. One stride, applied once."""
    from memorymap.api.routes_whiteboard import _preview_items

    #: Seven fields per row since the preview started carrying each item's own
    #: size (INBOX 68): x, y, kind, label, colour, width, height. This test
    #: kept passing five and went red the moment a gate ran it, which is the
    #: whole reason a call that unpacks a fixed-width row belongs in a test at
    #: all.
    items = _preview_items(
        [
            (0.0, 0.0, "card", "left", None, 100.0, 60.0),
            (10.0, 0.0, "card", "right", None, 100.0, 60.0),
        ]
    )
    assert items[0]["x"] == 0.0 and items[0]["label"] == "left"
    assert items[1]["x"] == 1.0 and items[1]["label"] == "right"
