"""The link-type vocabulary is written down twice, so this stops it drifting.

`LINK_TYPES` lives in `core/database.py` because the column, the traversal and
the AI pass all read it there. The graph's drag-to-link dialog needs the same
list *before* any request has been made, a picker that waits on the network to
learn what it can offer opens empty, so `frontend/graph.js` carries its own
copy as `GRAPH_LINK_TYPES`.

Two copies of one vocabulary is exactly the shape that rots: someone adds a
kind to the backend, the dialog never offers it, and nothing anywhere fails.
This is the failure that would otherwise be silent.
"""

from __future__ import annotations

import re
from pathlib import Path

from memorymap.core.database import LINK_TYPES

GRAPH = Path(__file__).resolve().parents[1] / "frontend" / "graph.js"


def _frontend_types() -> list[str]:
    source = GRAPH.read_text(encoding="utf-8")
    block = re.search(r"const GRAPH_LINK_TYPES = \[(.*?)\];", source, re.S)
    assert block, "GRAPH_LINK_TYPES not found in graph.js"
    return re.findall(r'\[\s*"([a-z_]+)"', block.group(1))


def test_the_two_vocabularies_match():
    assert _frontend_types() == list(LINK_TYPES), (
        "The graph's link-type picker and core.database.LINK_TYPES disagree.\n"
        f"  backend:  {list(LINK_TYPES)}\n"
        f"  graph.js: {_frontend_types()}\n"
        "Add the kind to both, in the same order, the dialog lists them in "
        "the order it finds them, and 'related' is deliberately first because "
        "it is the default selection."
    )


def test_related_is_first_so_it_can_be_the_default():
    """The dialog preselects the first option. If that stopped being the
    neutral one, every drag-to-link would default to a claim about meaning."""
    assert list(LINK_TYPES)[0] == "related"


def test_every_kind_has_a_human_description():
    for key, description in LINK_TYPES.items():
        assert description.strip(), f"{key} has no description"
        assert ": " in description, (
            f"{key}'s description should read 'Name: what it means'; the UI "
            "splits on that dash to show the label and the hint separately."
        )


# --- the column, end to end ---------------------------------------------------


def _note(client, text: str) -> int:
    return client.post("/entries", json={"content": text}).json()["id"]


def test_a_link_stores_and_returns_its_kind(client):
    """Asserted on a follow-up GET, never on the POST response.

    CLAUDE.md trap 3: SQLAlchemy hands back the in-memory object, so a create
    response can happily report a value that was never written.
    """
    a = _note(client, "The deadline is the 14th")
    b = _note(client, "Actually the deadline moved to the 21st")
    made = client.post(
        f"/entries/{a}/links",
        json={"target_id": b, "link_type": "contradicts", "reason": "dates disagree"},
    )
    assert made.status_code == 200, made.text

    graph = client.get("/graph").json()
    edge = next(
        e
        for e in graph["edges"]
        if e.get("kind") == "link" and {e["source"], e["target"]} == {a, b}
    )
    assert edge["link_type"] == "contradicts"
    assert edge["reason"] == "dates disagree"


def test_an_unknown_kind_is_stored_as_null_not_refused(client):
    """A typo should cost you the label, not the link, see manager.create_link."""
    a = _note(client, "Gym on Tuesday")
    b = _note(client, "Gym on Thursday")
    made = client.post(
        f"/entries/{a}/links", json={"target_id": b, "link_type": "not-a-real-kind"}
    )
    assert made.status_code == 200, made.text

    graph = client.get("/graph").json()
    edge = next(
        e
        for e in graph["edges"]
        if e.get("kind") == "link" and {e["source"], e["target"]} == {a, b}
    )
    assert edge["link_type"] is None


def test_a_link_made_without_a_kind_is_null(client):
    """Every link that existed before this column does exactly this, and must
    keep meaning what it always meant: 'these are related'."""
    a = _note(client, "Booked the flights")
    b = _note(client, "Booked the hotel")
    client.post(f"/entries/{a}/links", json={"target_id": b})
    graph = client.get("/graph").json()
    edge = next(
        e
        for e in graph["edges"]
        if e.get("kind") == "link" and {e["source"], e["target"]} == {a, b}
    )
    assert edge["link_type"] is None
