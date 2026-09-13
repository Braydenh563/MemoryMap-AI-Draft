"""Finding where the notebook disagrees with itself (`ai.tensions`).

`core/database.py`'s `LINK_TYPES` comment says `contradicts` "is the one
worth having built this for: a notebook that can show you where you disagreed
with yourself is not something an embedding similarity score can ever
produce". It was right, and until now nothing produced one, `link_type` was
writable only by a person choosing it from a dropdown.

**The standing caveat applies and is not papered over here.** There is no
Ollama in this sandbox, so every test below drives `tests/fakes.py`'s fake
transport. What is genuinely exercised is the part that decides things: which
pairs are worth a model call, how a reply is parsed, what is rejected, and
what accepting one writes. What has *never* run is a real local model judging
a real pair: so the prompt's actual hit rate is unmeasured, and that is
stated rather than implied.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from memorymap.ai import tensions
from memorymap.core.database import Entry, EntryLink


# --- Parsing a reply -------------------------------------------------------
#
# This is the guard that keeps the feature from accusing someone of
# contradicting themselves with no case attached.


def test_a_no_reply_is_not_a_tension():
    assert tensions._clean_explanation("NO") is None
    assert tensions._clean_explanation("no, these are about different things") is None


def test_a_yes_reply_keeps_the_sentence_that_justifies_it():
    got = tensions._clean_explanation(
        "YES - the first says the launch is in May, the second says August"
    )
    assert got == "the first says the launch is in May, the second says August"


def test_yes_with_nothing_after_it_is_thrown_away():
    """A verdict with no case is exactly what this feature must never show."""
    assert tensions._clean_explanation("YES") is None
    # Long enough to pass a length check, and still says nothing checkable.
    assert tensions._clean_explanation("YES - they disagree") is None
    assert tensions._clean_explanation("YES - basically they just conflict") is None


def test_a_reply_that_ignores_the_format_is_not_read_as_a_finding():
    """Neither word means the model did not answer the question asked."""
    assert tensions._clean_explanation("These notes both discuss the launch date.") is None
    assert tensions._clean_explanation("") is None


# --- Choosing which pairs are worth asking about ---------------------------


def _note(session, text, days_ago):
    entry = Entry(content=text, created_at=datetime.now() - timedelta(days=days_ago))
    session.add(entry)
    session.commit()
    return entry


def test_two_notes_from_the_same_few_days_are_not_a_change_of_mind(session):
    """One idea being worked out in a sitting is not a contradiction.

    This is the filter that keeps the feature from flagging ordinary drafting,
    and it runs before any model call, so it also bounds the work.
    """
    a = _note(session, "The launch is in May", 2)
    b = _note(session, "Actually the launch is in August", 0)
    assert tensions.order_by_time(a, b) is None


def test_a_gap_of_months_is_a_pair_worth_asking_about(session):
    a = _note(session, "The launch is in May", 120)
    b = _note(session, "The launch slipped to August", 10)
    ordered = tensions.order_by_time(a, b)
    assert ordered is not None
    earlier, later = ordered
    # Order matters to the prompt and to how the finding reads: the story is
    # "you thought this, then you thought that".
    assert (earlier.id, later.id) == (a.id, b.id)


def test_order_is_by_time_not_by_argument_order(session):
    a = _note(session, "later note", 5)
    b = _note(session, "earlier note", 90)
    earlier, later = tensions.order_by_time(a, b)
    assert (earlier.id, later.id) == (b.id, a.id)


def test_an_undated_note_is_skipped_rather_than_guessed_at(session):
    """Defensive, and worth saying why it cannot be tested through the DB.

    `entries.created_at` is NOT NULL, so an undated note cannot be *stored*, 
    trying it raises `IntegrityError`, which is how this test was written the
    first time. The guard in `order_by_time` still earns its place because it
    is handed `Entry` objects, and an unsaved one has no timestamp until the
    database assigns it; without the check that pair would raise inside a
    background pass instead of being skipped.
    """
    a = _note(session, "The launch is in May", 120)
    assert tensions.order_by_time(a, Entry(content="not saved yet")) is None


# --- The endpoint ----------------------------------------------------------


def test_an_empty_result_says_why_it_is_empty(client):
    """"No model running" and "your notebook is consistent" are different
    answers, and a bare `[]` renders them identically: which is how a
    feature that never ran gets reported as one that found nothing."""
    body = client.get("/entries/tensions").json()
    assert body["tensions"] == []
    # No fake AI on the plain `client` fixture, so this is the honest branch.
    assert body["status"] in {"no_model", "no_embeddings", "too_few_notes"}


def test_accepting_a_tension_writes_a_contradicts_link(client, session):
    a = _note(session, "We are going with Postgres", 200)
    b = _note(session, "We settled on SQLite in the end", 10)

    response = client.post(
        "/entries/tensions/accept", json={"earlier_id": a.id, "later_id": b.id}
    )
    assert response.status_code == 200
    assert response.json()["created"] is True

    link = session.scalars(select(EntryLink)).one()
    assert link.link_type == "contradicts"
    assert {link.source_entry_id, link.target_entry_id} == {a.id, b.id}


def test_dismissing_a_pair_is_remembered(client, session):
    a = _note(session, "one", 200)
    b = _note(session, "two", 10)
    response = client.post(
        "/entries/tensions/dismiss", json={"earlier_id": a.id, "later_id": b.id}
    )
    assert response.status_code == 200

    from memorymap.api.routes_entries import TENSION_DISMISSED_KEY, _tension_key
    from memorymap.core import deps

    stored = deps.get_config().get_preference(TENSION_DISMISSED_KEY, [])
    assert _tension_key(a.id, b.id) in stored


def test_the_dismissed_key_does_not_depend_on_which_note_came_first():
    """A pair is one thing however it is named, or dismissing it once would
    leave the mirrored ordering still being offered."""
    from memorymap.api.routes_entries import _tension_key

    assert _tension_key(7, 3) == _tension_key(3, 7)


# --- The agent's way in ----------------------------------------------------


def test_the_agent_has_a_tool_for_this_and_it_never_links_anything(client, session):
    """Reachable by asking, not only by clicking, and read-only.

    The whole feature's rule is that accusing someone of contradicting
    themselves is a claim a person has to agree with first, so the tool
    *reports*. `link_notes` is what writes one, and the user is in that loop.
    """
    from memorymap.ai import tools

    spec = tools.TOOLS["find_contradictions"]
    assert spec.destructive is False
    # Reported, not applied: the handler must not be able to create a link.
    from memorymap.core.database import EntryLink

    result = spec.handler(session, {"limit": 3})
    assert "tensions" in result
    assert session.scalars(select(EntryLink)).all() == []


def test_the_tool_says_why_it_found_nothing(client, session):
    """Same honesty rule as the endpoint: a bare empty list renders "no model
    running" and "your notebook is consistent" identically."""
    from memorymap.ai import tools

    result = tools.TOOLS["find_contradictions"].handler(session, {})
    assert result["tensions"] == []
    assert result["message"], "an empty result must explain itself"
