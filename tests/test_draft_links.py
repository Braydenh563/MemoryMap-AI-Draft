"""Drafts are separate from the notebook, links included.

Asked for directly: *"draft notes shouldnt be able to connect with actual
notes, they need to be separate."*

Drafts are already kept out of every other view, sidebar counts, category
lists, retrieval: because an unfinished note is not part of the notebook yet.
A link was the one thing still crossing that line, and it crossed it in the
worst direction: a link outlives the draft's own invisibility, so a committed
note grew an edge to something a reader cannot reach from anywhere else.
"""

from __future__ import annotations

from memorymap.entry import manager


def _draft(session, text):
    entry = manager.create_entry(session, text)
    entry.is_draft = True
    session.commit()
    return entry


def test_a_draft_cannot_be_linked_to_a_saved_note(session):
    draft = _draft(session, "half an idea about beans")
    note = manager.create_entry(session, "the beans need netting next week")
    session.commit()

    assert manager.create_link(session, draft, note) is None


def test_the_refusal_holds_in_both_directions(session):
    """The guard is on the pair, not on which side the caller passed first."""
    draft = _draft(session, "half an idea about beans")
    note = manager.create_entry(session, "the beans need netting next week")
    session.commit()

    assert manager.create_link(session, note, draft) is None


def test_two_drafts_can_still_be_linked(session):
    """The literal reading of the request: drafts are separate from *real
    notes*, not from each other. Two drafts of one idea are exactly the pair
    worth connecting before either is saved."""
    first = _draft(session, "half an idea about beans")
    second = _draft(session, "the other half of the bean idea")

    assert manager.create_link(session, first, second) is not None


def test_two_saved_notes_are_unaffected(session):
    one = manager.create_entry(session, "the beans need netting next week")
    two = manager.create_entry(session, "netting arrived today")
    session.commit()

    assert manager.create_link(session, one, two) is not None


def test_saving_the_draft_makes_the_link_allowed(session):
    """The rule is about what a note *is* right now, not a permanent mark on
    it: so the fix the error message suggests actually works."""
    draft = _draft(session, "half an idea about beans")
    note = manager.create_entry(session, "the beans need netting next week")
    session.commit()
    assert manager.create_link(session, draft, note) is None

    draft.is_draft = False
    session.commit()
    assert manager.create_link(session, draft, note) is not None


def test_the_api_says_which_refusal_it_was(ai_client, session):
    """Three refusals share one return value, so the message has to name the
    one that applies: "already linked" would send someone hunting for a link
    that was never allowed to exist."""
    draft = _draft(session, "half an idea about beans")
    note = manager.create_entry(session, "the beans need netting next week")
    session.commit()

    response = ai_client.post(f"/entries/{draft.id}/links", json={"target_id": note.id})
    assert response.status_code == 400
    assert "draft" in response.json()["detail"].lower()
