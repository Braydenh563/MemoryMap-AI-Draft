"""A note that came along by connection is never presented as a match.

Retrieval pulls in the notes a match *links to*, that is the app's premise,
and it is what makes this a memory map rather than a search box. It also
introduces a way to mislead that did not exist before: the person asked about
one thing and is shown notes about another, and both the answer and the results
panel would report them as though the search had found them.

So the provenance travels with the note, all the way to both readers:

- the **model** sees "(not a match: linked to one of the above)" in the prompt,
  so an answer can say "you linked this to…" rather than implying a hit;
- the **panel** labels the row, because a note about something else with no
  explanation reads as the search having misfired.
"""

from __future__ import annotations

import json

from memorymap.ai import librarian
from memorymap.core.database import Entry, EntryLink
from memorymap.search import search_manager


def _note(session, content, tags=None):
    entry = Entry(content=content, tags=json.dumps(tags or []))
    session.add(entry)
    session.commit()
    return entry


def test_the_response_names_which_results_arrived_by_connection(ai_client, session):
    match = _note(session, "the beans need netting before the pigeons find them")
    linked = _note(session, "netting is in the shed behind the mower")
    session.add(EntryLink(source_entry_id=match.id, target_entry_id=linked.id))
    session.commit()

    body = ai_client.post("/chat", json={"question": "beans netting"}).json()
    ids = [row["id"] for row in body["raw_results"]]
    assert match.id in ids and linked.id in ids
    assert body["connected_ids"] == [linked.id]


def test_nothing_is_marked_when_nothing_was_pulled_in(ai_client, session):
    """The common case. An empty list rather than a missing key, so the client
    can read it without a guard."""
    _note(session, "a note with no connections at all")
    body = ai_client.post("/chat", json={"question": "connections"}).json()
    assert body["connected_ids"] == []


def test_match_info_names_why_each_result_showed_up(ai_client, session):
    """A keyword match and the note it's connected to should read as two
    different reasons: "why did this appear?" was previously answerable
    only for the connected case, via `connected_ids`, and not at all for an
    ordinary match."""
    match = _note(session, "the beans need netting before the pigeons find them")
    linked = _note(session, "netting is in the shed behind the mower")
    session.add(EntryLink(source_entry_id=match.id, target_entry_id=linked.id))
    session.commit()

    body = ai_client.post("/chat", json={"question": "beans netting"}).json()
    match_info = body["match_info"]

    assert match_info[str(match.id)]["type"] == "keyword"
    assert "beans" in match_info[str(match.id)]["terms"]
    assert match_info[str(linked.id)]["type"] == "connected"


def test_a_connected_note_carries_the_links_own_reason(ai_client, session):
    """Asked for directly: does a link's reason show up in search results
    too, not just on the graph and in Trace. `graph_expansion` has to carry
    it through `_retrieve` for that to reach `/chat`'s `match_info`."""
    match = _note(session, "the beans need netting before the pigeons find them")
    linked = _note(session, "netting is in the shed behind the mower")
    session.add(
        EntryLink(
            source_entry_id=match.id, target_entry_id=linked.id, reason="both about the shed"
        )
    )
    session.commit()

    body = ai_client.post("/chat", json={"question": "beans netting"}).json()
    assert body["match_info"][str(linked.id)]["reason"] == "both about the shed"


def test_a_connected_notes_reason_reaches_both_prompts_not_just_the_api(client):
    """The API carrying `reason` (test above) isn't the same fact as the model
    ever seeing it: `_match_info_hint` had a branch for "semantic"/"keyword"
    match types but none for "connected", so a reason traced all the way to
    the Link row was still dropped right before it reached the prompt text,
    on both the plain librarian path and agent mode."""
    from memorymap.ai import agent, librarian

    note = {
        "id": 1,
        "content": "the shed roof",
        "category": "Home",
        "attached": False,
        "connected": True,
        "match_info": {"type": "connected", "reason": "both about the shed"},
    }

    messages = librarian.build_messages("what about the shed?", [note])
    assert "both about the shed" in messages[-1]["content"]

    agent_messages = agent.build_agent_messages("what about the shed?", [note])
    assert "both about the shed" in agent_messages[-1]["content"]


def test_graph_expansion_keeps_the_strongest_neighbour_when_the_hop_limit_bites(session):
    """§87.5: `GRAPH_EXPANSION_LIMIT` truncates a hop to 3 neighbours, so
    which three survive is a real decision, not an accident of query order.
    A typed link is created *last*, after four bare ones already fill the
    limit: insertion order alone would drop it; strength-ordering must not."""
    match = _note(session, "the source note everything connects to")
    bare = [_note(session, f"a bare neighbour {n}") for n in range(4)]
    for note in bare:
        session.add(EntryLink(source_entry_id=match.id, target_entry_id=note.id))
    typed = _note(session, "the neighbour somebody actually typed a reason for")
    session.add(
        EntryLink(source_entry_id=match.id, target_entry_id=typed.id, link_type="supports")
    )
    session.commit()

    neighbours, _reasons, _hop_of = search_manager.graph_expansion(session, [match])
    assert typed.id in [entry.id for entry in neighbours]


def test_the_prompt_tells_the_model_which_notes_did_not_match():
    notes = [
        {"id": 1, "category": "Garden", "content": "the beans need netting"},
        {
            "id": 2,
            "category": "House",
            "content": "netting is in the shed",
            "connected": True,
        },
    ]
    messages = librarian.build_messages("beans netting", notes)
    prompt = messages[-1]["content"]
    assert "not a match: linked to one of the above" in prompt
    # …and only on the one that needs it.
    assert prompt.count("not a match") == 1


def test_an_attached_note_keeps_its_own_marker():
    """The two markers answer different questions, "I chose this" and "this
    did not match", and a note could carry either."""
    notes = [{"id": 1, "category": "Garden", "content": "beans", "attached": True}]
    prompt = librarian.build_messages("beans", notes)[-1]["content"]
    assert "attached by me" in prompt
    assert "not a match" not in prompt
