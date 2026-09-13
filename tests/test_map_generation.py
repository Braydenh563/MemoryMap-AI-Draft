"""Make a map of these notes (MINDMAP_PLAN.md section 5 item 15).

Two endpoints and one rule between them: `POST /whiteboard/boards/propose`
writes nothing and returns an outline, `POST /whiteboard/boards/generate`
creates the map from the outline the user actually saw. That is
`generate_diagram`'s own preview-before-commit convention, and the reason for
it is that a generator which writes straight to a new board makes "undo" mean
"go and find the board it made".

The standing caveat in CLAUDE.md applies to every test here: the model is a
fake transport (`tests/fakes.FakeOllama`), so what is asserted is the shape of
the prompt, the parsing of the reply, and both fallbacks. No real model has
answered this prompt.
"""

from __future__ import annotations


def _notes(client, *contents):
    return [client.post("/entries", json={"content": text}).json() for text in contents]


def _tree(client, board_id):
    return client.get(f"/whiteboard/boards/{board_id}/tree").json()


def _flat(nodes, out=None):
    out = [] if out is None else out
    for node in nodes:
        out.append(node)
        _flat(node["children"], out)
    return out


# --- the proposal -----------------------------------------------------------


def test_a_proposal_writes_nothing(client):
    """Preview before commit, asserted the only way it can be: the notebook
    has no new board afterwards."""
    notes = _notes(client, "# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits")
    before = len(client.get("/whiteboard/boards").json())

    proposed = client.post(
        "/whiteboard/boards/propose", json={"note_ids": [n["id"] for n in notes]}
    )
    assert proposed.status_code == 200, proposed.text
    assert len(client.get("/whiteboard/boards").json()) == before


def test_with_no_model_the_notebooks_own_filing_is_the_proposal(client):
    """`client` has the AI switched off entirely, which is the state a first
    run of this app is in. The action still has to produce a map: a feature
    that only works when a local model is up is a feature most people meet
    broken."""
    notes = _notes(client, "# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits")
    proposed = client.post(
        "/whiteboard/boards/propose",
        json={"note_ids": [n["id"] for n in notes], "name": "Information"},
    ).json()

    assert proposed["source"] == "notebook"
    # The three fallbacks are three different sentences in the dialog, so the
    # server has to say which one this is rather than only that it fell back.
    assert proposed["reason"] == "offline"
    assert proposed["name"] == "Information"
    assert "- Information" in proposed["outline"]
    assert "Kolmogorov complexity" in proposed["outline"]
    assert "Entropy" in proposed["outline"]


def test_the_models_outline_is_used_when_it_answers_with_one(ai_client, fake_ollama):
    fake_ollama.librarian_reply = (
        "- Information theory\n"
        "  - Foundations\n"
        "    - Kolmogorov complexity\n"
        "  - Measures\n"
        "    - Entropy\n"
    )
    notes = _notes(ai_client, "# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits")
    proposed = ai_client.post(
        "/whiteboard/boards/propose", json={"note_ids": [n["id"] for n in notes]}
    ).json()

    assert proposed["source"] == "model"
    assert "Foundations" in proposed["outline"]


def test_a_model_that_answers_with_prose_falls_back_rather_than_failing(ai_client, fake_ollama):
    """The 4B case this was designed around. `librarian_reply`'s default is a
    sentence, which is exactly what a small model hands back when asked for an
    outline."""
    notes = _notes(ai_client, "# Kolmogorov complexity\n\nstrings")
    proposed = ai_client.post(
        "/whiteboard/boards/propose", json={"note_ids": [n["id"] for n in notes]}
    ).json()

    assert proposed["source"] == "notebook"
    assert proposed["reason"] == "unusable"
    assert "Kolmogorov complexity" in proposed["outline"]


def test_a_note_the_model_left_out_is_added_back(ai_client, fake_ollama):
    """The failure worth guarding: a proposal for thirty notes that quietly
    holds eleven looks like a map and reads like an answer, and the nineteen
    that are gone are invisible unless you count them."""
    fake_ollama.librarian_reply = "- Information theory\n  - Kolmogorov complexity\n"
    notes = _notes(ai_client, "# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits")
    proposed = ai_client.post(
        "/whiteboard/boards/propose", json={"note_ids": [n["id"] for n in notes]}
    ).json()

    assert proposed["source"] == "model"
    assert "Other notes" in proposed["outline"]
    assert "Entropy" in proposed["outline"]
    assert len(notes) == 2


def test_a_private_note_is_dropped_from_the_proposal_not_sent_to_the_model(
    ai_client, fake_ollama, session
):
    """The boundary every AI-facing read path in this codebase holds. Dropped
    rather than refused: this is a list someone assembled by ticking boxes,
    and failing all of it over one private note is a dead end."""
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    notes = _notes(ai_client, "# Public thing\n\nfine", "# Secret thing\n\nhidden")
    made_private = ai_client.post(f"/entries/{notes[1]['id']}/privacy", json={"private": True})
    assert made_private.status_code == 200, made_private.text

    # From here on, not from the start of the test: the note was public when
    # it was captured, so the janitor filed it through the model then, which
    # is a different question from what this proposal sends.
    already = len(fake_ollama.chat_calls)
    proposed = ai_client.post(
        "/whiteboard/boards/propose", json={"note_ids": [n["id"] for n in notes]}
    ).json()
    assert proposed["notes"] == 1
    assert "Secret thing" not in proposed["outline"]
    sent = "\n".join(
        message["content"]
        for call in fake_ollama.chat_calls[already:]
        for message in call
    )
    assert sent
    assert "Secret thing" not in sent
    vault.close()


def test_a_proposal_of_nothing_mappable_is_a_404(client):
    refused = client.post("/whiteboard/boards/propose", json={"note_ids": [9999]})
    assert refused.status_code == 404


# --- the commit -------------------------------------------------------------


def test_the_accepted_outline_becomes_a_map_of_the_real_notes(client):
    """The differentiator the plan names: the nodes are the user's own notes,
    not invented text that happens to look like them. A `note` node carries
    the note's id, so editing it edits the note and deleting the map leaves
    the note alone."""
    notes = _notes(client, "# Kolmogorov complexity\n\nstrings", "# Entropy\n\nbits")
    proposed = client.post(
        "/whiteboard/boards/propose",
        json={"note_ids": [n["id"] for n in notes], "name": "Information"},
    ).json()

    made = client.post(
        "/whiteboard/boards/generate",
        json={
            "name": proposed["name"],
            "outline": proposed["outline"],
            "note_ids": proposed["note_ids"],
        },
    )
    assert made.status_code == 201, made.text
    board = made.json()
    assert board["type"] == "map"

    nodes = _flat(_tree(client, board["id"])["roots"])
    by_text = {node["text"]: node for node in nodes}
    assert by_text["Kolmogorov complexity"]["kind"] == "note"
    assert by_text["Kolmogorov complexity"]["ref_id"] == notes[0]["id"]
    assert by_text["Entropy"]["ref_id"] == notes[1]["id"]
    # The headings the proposal wrote are topics: they stand for nothing.
    assert by_text["Information"]["kind"] == "topic"


def test_a_title_repeated_in_the_outline_places_the_note_once(client):
    """A model that cannot decide where a note belongs writes it twice, and
    two nodes editing one note is a confusion that only surfaces later."""
    notes = _notes(client, "# Entropy\n\nbits")
    outline = "- Root\n  - Entropy\n  - Entropy\n"
    board = client.post(
        "/whiteboard/boards/generate",
        json={"name": "Twice", "outline": outline, "note_ids": [notes[0]["id"]]},
    ).json()

    nodes = _flat(_tree(client, board["id"])["roots"])
    references = [node for node in nodes if node["kind"] == "note"]
    assert len(references) == 1
    assert len(nodes) == 3


def test_case_alone_does_not_break_the_match(client):
    """The one thing a person editing the outline is most likely to change."""
    notes = _notes(client, "# Entropy\n\nbits")
    board = client.post(
        "/whiteboard/boards/generate",
        json={"name": "Case", "outline": "- Root\n  - entropy\n", "note_ids": [notes[0]["id"]]},
    ).json()

    nodes = _flat(_tree(client, board["id"])["roots"])
    assert [node["kind"] for node in nodes] == ["topic", "note"]


def test_an_edited_outline_is_what_gets_built(client):
    """The point of preview-before-commit: what the user saw and changed is
    what lands, not what the proposal said."""
    notes = _notes(client, "# Entropy\n\nbits")
    board = client.post(
        "/whiteboard/boards/generate",
        json={
            "name": "Mine",
            "outline": "- My own root\n  - A topic I typed\n    - Entropy\n",
            "note_ids": [notes[0]["id"]],
        },
    ).json()

    nodes = _flat(_tree(client, board["id"])["roots"])
    assert [node["text"] for node in nodes] == ["My own root", "A topic I typed", "Entropy"]


def test_an_outline_with_no_nodes_is_a_422(client):
    refused = client.post(
        "/whiteboard/boards/generate",
        json={"name": "Empty", "outline": "just a sentence", "note_ids": []},
    )
    assert refused.status_code == 422


def test_deleting_a_generated_map_leaves_its_notes(client):
    """Section 5 item 4's containment rule, on the map this feature makes: a
    generated map is full of pointers, and the notes behind them belong to the
    library, not to the board."""
    notes = _notes(client, "# Entropy\n\nbits")
    board = client.post(
        "/whiteboard/boards/generate",
        json={"name": "Doomed", "outline": "- Root\n  - Entropy\n", "note_ids": [notes[0]["id"]]},
    ).json()

    deleted = client.delete(f"/entries/{board['id']}")
    assert deleted.status_code == 200
    purged = client.delete(f"/entries/{board['id']}/purge")
    assert purged.status_code == 200
    still_there = client.get(f"/entries/{notes[0]['id']}")
    assert still_there.status_code == 200
