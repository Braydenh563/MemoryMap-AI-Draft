"""How two notes relate, and what shape the notebook is (§9).

`related_notes` (see `test_related_notes.py`) answers "what is near this note".
These two answer the questions that needed a *traversal* rather than a walk:

- **"How are these two related?"**, the chain between them, which is the one
  question a graph answers better than a list, and the one the view could not
  answer at all.
- **"What does my notebook look like?"**, clusters, hubs and notes joined to
  nothing. The model could always count notes and list categories, both of
  which describe the *filing*; nothing described the **structure**, so "tidy
  up my notebook" was answered by reading category names.

The properties worth pinning are the ones that make an answer trustworthy
rather than merely present:

1. **A weak connection must not beat a strong one.** An unweighted search
   returns the fewest hops, so one shared `#misc` beats a three-step chain of
   deliberate links: technically a path, actually noise.
2. **A tag on half the notebook is filing, not connection.** Otherwise
   everything is two hops from everything and the feature answers "related" to
   every pair it is given.
3. **"No path" says why.** A bare no invites the model to invent a reason.
4. **Private notes are not in the graph the AI searches.** It may not read one,
   so routing through one would put a preview it is barred from into an answer.
"""

from __future__ import annotations

import json

from memorymap.ai import tools
from memorymap.core.database import Entry, EntryLink, link_strength
from memorymap.entry import paths


def _note(session, content, tags=None, parent_id=None, private=False):
    entry = Entry(
        content=content,
        tags=json.dumps(tags or []),
        parent_id=parent_id,
        is_private=private,
    )
    session.add(entry)
    session.commit()
    return entry


def _link(session, a, b):
    session.add(EntryLink(source_entry_id=a.id, target_entry_id=b.id))
    session.commit()


def _chain(session, source, target):
    return paths.find(paths.build(session), source.id, target.id)


# --- link_strength, the pure function §87.5's weighting is built on -----------


def test_link_strength_is_one_for_a_bare_link():
    """The baseline, no type, no deduced-reason confidence, is exactly
    what every link created before either column existed still is, so this
    has to be neutral or every old link would silently get weaker."""
    assert link_strength(None, None) == 1.0


def test_link_strength_favours_a_named_type():
    assert link_strength("supports", None) > link_strength(None, None)


def test_every_named_type_gets_the_same_boost():
    """The distinction is "somebody decided this" vs. "nobody said", not a
    ranking between e.g. "supports" and "contradicts", which are equally
    deliberate choices."""
    boosted = {link_strength(kind, None) for kind in ("related", "continues", "context", "supports", "contradicts", "example_of")}
    assert len(boosted) == 1


def test_link_strength_discounts_a_low_confidence_deduction():
    assert 0 < link_strength(None, 0.15) < link_strength(None, None)


def test_link_strength_has_a_floor_so_a_low_confidence_guess_is_still_a_real_signal():
    assert link_strength(None, 0.01) == link_strength(None, 0.4)  # both hit the floor


def test_link_strength_combines_type_and_confidence():
    """A typed link with a confidently deduced reason (unusual: `create_link`
    only deduces when no reason was given at all) still stacks both signals
    rather than one silently overriding the other."""
    assert link_strength("supports", 0.9) < link_strength("supports", None)
    assert link_strength("supports", 0.9) > link_strength(None, 0.9)


# --- the path itself ----------------------------------------------------------


def test_a_direct_link_is_one_step(session):
    a = _note(session, "sourdough starter needs feeding")
    b = _note(session, "the oven runs hot")
    _link(session, a, b)

    chain = _chain(session, a, b)
    assert [step.target for step in chain] == [b.id]
    assert chain[0].kind == "link"


def test_a_links_reason_shows_up_in_how_it_connects(session):
    """Trace's readout reads `step.how` directly: this is the reason a
    user-given explanation ("both about scheduling") reaches the person
    asking how two notes relate, not just the model."""
    a = _note(session, "assignment due next week")
    b = _note(session, "gym session tuesday")
    session.add(
        EntryLink(source_entry_id=a.id, target_entry_id=b.id, reason="both about scheduling")
    )
    session.commit()

    chain = _chain(session, a, b)
    assert chain[0].how == "linked to (both about scheduling)"


def test_a_deduced_reasons_confidence_shows_up_in_how_it_connects(session):
    """A reason nobody actually said carries its score, so Trace and the
    story prompt don't read a guess with the same certainty as a person's or
    the AI's own words (see `EntryLink.reason_confidence`)."""
    a = _note(session, "assignment due next week")
    b = _note(session, "gym session tuesday")
    session.add(
        EntryLink(
            source_entry_id=a.id,
            target_entry_id=b.id,
            reason="similar in meaning",
            reason_confidence=0.83,
        )
    )
    session.commit()

    chain = _chain(session, a, b)
    assert chain[0].how == "linked to (similar in meaning, 83% confidence, deduced)"


def test_a_path_runs_through_the_notes_between(session):
    a = _note(session, "beans need netting")
    b = _note(session, "the netting is in the shed")
    c = _note(session, "shed door hinge is rusted")
    _link(session, a, b)
    _link(session, b, c)

    chain = _chain(session, a, c)
    assert [step.source for step in chain] == [a.id, b.id]
    assert [step.target for step in chain] == [b.id, c.id]


def test_a_reply_thread_is_a_path(session):
    a = _note(session, "trying a new proving schedule")
    b = _note(session, "day two: better crumb", parent_id=a.id)

    chain = _chain(session, a, b)
    assert len(chain) == 1
    assert chain[0].kind == "thread"
    # Written from source to target, so a chain of these reads in order.
    assert chain[0].how == "was replied to by"


def test_a_shared_tag_is_a_path_when_nothing_stronger_exists(session):
    a = _note(session, "risotto method", tags=["cooking"])
    b = _note(session, "stock from the freezer", tags=["cooking"])

    chain = _chain(session, a, b)
    assert len(chain) == 1
    assert chain[0].kind == "tag"
    assert chain[0].how == "shares #cooking with"


def test_deliberate_links_beat_a_tag_shortcut(session):
    """Property 1, and the reason the search is weighted at all.

    Both routes exist: three links, or one shared tag. An unweighted search
    returns the tag, one hop, and the answer is "these are related because
    they are both tagged #idea", which is true and worthless. The chain of
    links is what somebody actually decided.
    """
    a = _note(session, "the argument for local-first", tags=["idea"])
    b = _note(session, "sync is the hard part")
    c = _note(session, "CRDTs, in principle")
    d = _note(session, "what I would build instead", tags=["idea"])
    _link(session, a, b)
    _link(session, b, c)
    _link(session, c, d)

    chain = _chain(session, a, d)
    assert [step.kind for step in chain] == ["link", "link", "link"]


def test_typed_links_beat_bare_links_at_equal_hop_count(session):
    """§87.5's first slice: a link somebody deliberately typed ("supports",
    "contradicts", ...) is a stronger signal than a bare one, so a
    shortest-path search should prefer it when two routes tie on hop count."""
    a = _note(session, "the trip plan")
    bare_mid = _note(session, "a note with no real bearing on it")
    typed_mid = _note(session, "the note that actually explains it")
    d = _note(session, "the outcome")
    _link(session, a, bare_mid)
    _link(session, bare_mid, d)
    session.add(EntryLink(source_entry_id=a.id, target_entry_id=typed_mid.id, link_type="supports"))
    session.add(EntryLink(source_entry_id=typed_mid.id, target_entry_id=d.id, link_type="supports"))
    session.commit()

    chain = _chain(session, a, d)
    assert [step.target for step in chain] == [typed_mid.id, d.id]


def test_a_low_confidence_deduced_link_loses_to_a_plain_one_at_equal_hop_count(session):
    """The other half: a deduced reason is a guess, and a low-confidence
    guess should weigh less than a link somebody just made with no
    explanation at all."""
    a = _note(session, "the trip plan")
    guessed_mid = _note(session, "loosely similar, low confidence")
    solid_mid = _note(session, "a plain deliberate link")
    d = _note(session, "the outcome")
    session.add(
        EntryLink(
            source_entry_id=a.id,
            target_entry_id=guessed_mid.id,
            reason="maybe related",
            reason_confidence=0.15,
        )
    )
    session.add(
        EntryLink(
            source_entry_id=guessed_mid.id,
            target_entry_id=d.id,
            reason="maybe related",
            reason_confidence=0.15,
        )
    )
    _link(session, a, solid_mid)
    _link(session, solid_mid, d)
    session.commit()

    chain = _chain(session, a, d)
    assert [step.target for step in chain] == [solid_mid.id, d.id]


def test_a_tag_route_is_still_found_when_it_is_the_only_one(session):
    """The counterpart. Weighting a tag down must not mean discarding it, 
    a tag hop is a real connection and often the only one there is."""
    a = _note(session, "the pond is silting up", tags=["garden"])
    b = _note(session, "order more gravel", tags=["garden"])

    chain = _chain(session, a, b)
    assert [step.kind for step in chain] == ["tag"]


def test_a_tag_on_most_of_the_notebook_connects_nothing(session):
    """Property 2. A tag past `HUB_TAG_NOTES` is filing, not connection.

    Without this, one heavily-used tag makes every note two hops from every
    other, and the feature reports a relationship between any two notes it is
    handed: which is the same as reporting nothing at all.
    """
    everything = [
        _note(session, f"note number {n}", tags=["notes"])
        for n in range(paths.HUB_TAG_NOTES + 2)
    ]
    index = paths.build(session)

    assert "notes" in index.hub_tags
    assert paths.find(index, everything[0].id, everything[-1].id) is None


def test_a_path_longer_than_the_cap_is_not_a_relationship(session):
    """Property: six intermediaries is not a relationship, and reporting one
    as though it were is the hub-tag failure arriving from the other end."""
    chain_of_notes = [_note(session, f"link in the chain {n}") for n in range(9)]
    for first, second in zip(chain_of_notes, chain_of_notes[1:]):
        _link(session, first, second)

    index = paths.build(session)
    assert paths.find(index, chain_of_notes[0].id, chain_of_notes[6].id) is not None
    assert paths.find(index, chain_of_notes[0].id, chain_of_notes[8].id) is None


def test_unconnected_notes_have_no_path(session):
    a = _note(session, "a thought about nothing in particular")
    b = _note(session, "an unrelated thought")
    assert _chain(session, a, b) is None


def test_a_deleted_note_is_not_a_stepping_stone(session):
    """A binned note is out of the notebook, so a route through it is a route
    through something the user cannot see."""
    a = _note(session, "one end")
    middle = _note(session, "the note in between")
    b = _note(session, "the other end")
    _link(session, a, middle)
    _link(session, middle, b)
    middle.is_deleted = True
    session.commit()

    assert _chain(session, a, b) is None


# --- the structural view ------------------------------------------------------


def test_clusters_are_groups_that_can_reach_each_other(session):
    first = [_note(session, f"island one, note {n}") for n in range(3)]
    second = [_note(session, f"island two, note {n}") for n in range(2)]
    for group in (first, second):
        for a, b in zip(group, group[1:]):
            _link(session, a, b)
    _note(session, "adrift, connected to nothing")

    found = paths.clusters(paths.build(session))
    assert [len(cluster.ids) for cluster in found] == [3, 2]
    # A note connected to nothing is an orphan, not a cluster of one.
    assert all(len(cluster.ids) >= 2 for cluster in found)


def test_the_cluster_core_is_its_best_connected_note(session):
    """What a cluster gets *called*. A cluster the model can only refer to as
    "cluster 2" is one the user cannot picture."""
    centre = _note(session, "the idea everything hangs off")
    spokes = [_note(session, f"a consequence, {n}") for n in range(3)]
    for spoke in spokes:
        _link(session, centre, spoke)

    cluster = paths.clusters(paths.build(session))[0]
    assert cluster.core_id == centre.id


def test_orphans_are_notes_joined_to_nothing(session):
    joined_a = _note(session, "one half of a pair")
    joined_b = _note(session, "the other half")
    _link(session, joined_a, joined_b)
    alone = _note(session, "never linked, never tagged, never replied to")

    assert paths.orphans(paths.build(session)) == [alone.id]


def test_hubs_are_the_notes_several_things_meet_at(session):
    hub = _note(session, "the note everything points at")
    for n in range(4):
        _link(session, hub, _note(session, f"a note pointing at it, {n}"))

    found = paths.hubs(paths.build(session))
    assert found[0] == (hub.id, 4)
    # The threshold matches the graph view's own `.graph-hub` class on purpose:
    # two definitions of "hub" that disagree is how the picture and the answer
    # start contradicting each other.
    assert all(count >= paths.HUB_DEGREE for _id, count in found)


# --- the AI's view ------------------------------------------------------------


def test_the_tool_names_how_each_step_connects(session):
    a = _note(session, "the compost bin is full")
    b = _note(session, "turn it next weekend")
    c = _note(session, "borrow the fork", tags=["borrowing"])
    d = _note(session, "return the ladder", tags=["borrowing"])
    _link(session, a, b)
    _link(session, b, c)

    result = tools.TOOLS["path_between"].handler(
        session, {"note_id": a.id, "other_note_id": d.id}
    )
    assert result["found"] is True
    assert [step["kind"] for step in result["steps"]] == ["link", "link", "tag"]
    # Every note on the path comes back with its own words, so the answer can
    # name notes rather than numbering them (§35K).
    assert all(row["preview"] for row in result["path"])


def test_the_tool_says_why_there_is_no_path(session):
    """Property 3. A bare "no" invites the model to explain it away."""
    a = _note(session, "one thing")
    b = _note(session, "another thing")

    result = tools.TOOLS["path_between"].handler(
        session, {"note_id": a.id, "other_note_id": b.id}
    )
    assert result["found"] is False
    assert "connected to nothing at all" in result["note"]


def test_the_tool_will_not_route_through_a_private_note(session):
    """Property 4. The model may not read a private note, so a chain that
    passes through one hands it a preview it is barred from."""
    a = _note(session, "one end")
    secret = _note(session, "something I would rather keep to myself", private=True)
    b = _note(session, "the other end")
    _link(session, a, secret)
    _link(session, secret, b)

    result = tools.TOOLS["path_between"].handler(
        session, {"note_id": a.id, "other_note_id": b.id}
    )
    assert result["found"] is False


def test_structure_separates_what_is_connected_from_what_is_filed(session):
    """The gap the tool exists to close: `list_categories` describes filing,
    and a notebook can be perfectly filed and entirely unconnected."""
    a = _note(session, "one of a pair")
    b = _note(session, "the other of the pair")
    _link(session, a, b)
    for n in range(3):
        _note(session, f"filed, but joined to nothing, {n}")

    result = tools.TOOLS["notebook_structure"].handler(session, {})
    assert result["notes"] == 5
    assert result["connected"] == 2
    assert result["orphan_count"] == 3
    assert len(result["orphans"]) == 3


def test_structure_explains_a_tag_it_declined_to_count(session):
    """Otherwise this reads as a wrong answer: two notes plainly share a tag
    and the tool says they are unconnected."""
    for n in range(paths.HUB_TAG_NOTES + 2):
        _note(session, f"note {n}", tags=["notes"])

    result = tools.TOOLS["notebook_structure"].handler(session, {})
    assert result["ignored_tags"] == ["notes"]
    assert "filing rather than as connections" in result["about_ignored_tags"]


# --- the HTTP surface ---------------------------------------------------------


def test_the_path_route_returns_the_chain_in_order(client, session):
    a = _note(session, "start here")
    b = _note(session, "then this")
    c = _note(session, "and finally this")
    _link(session, a, b)
    _link(session, b, c)

    body = client.get(f"/graph/path?source={a.id}&target={c.id}").json()
    assert body["found"] is True
    assert [node["id"] for node in body["nodes"]] == [a.id, b.id, c.id]
    assert body["hops"] == 2


def test_the_path_route_explains_a_missing_route(client, session):
    a = _note(session, "one thing")
    b = _note(session, "another thing")
    body = client.get(f"/graph/path?source={a.id}&target={b.id}").json()
    assert body["found"] is False
    assert "connected to anything yet" in body["reason"]


def test_the_structure_route_maps_every_note_to_its_cluster(client, session):
    """`cluster_of` is what makes colouring the graph a lookup rather than a
    second traversal in JavaScript, and its keys are strings, because that is
    what JSON object keys are whatever they started as."""
    group = [_note(session, f"in the cluster {n}") for n in range(3)]
    for a, b in zip(group, group[1:]):
        _link(session, a, b)
    alone = _note(session, "not in any cluster")

    body = client.get("/graph/structure").json()
    assert body["clusters"][0]["size"] == 3
    assert {body["cluster_of"][str(note.id)] for note in group} == {0}
    assert str(alone.id) not in body["cluster_of"]
    assert body["orphan_count"] == 1


def test_the_graph_never_labels_a_note_with_its_ciphertext(client, session, monkeypatch):
    """A private note's `content` is encrypted at rest, and the graph route
    read the column directly, so a private note appeared on the map labelled
    with a base64 blob. `readable_content` names the graph in its own docstring
    as a place that must not break on one."""
    from memorymap.core import crypto
    from memorymap.entry import manager

    note = _note(session, "the plain words of a private note")
    key = b"k" * 32
    monkeypatch.setattr("memorymap.core.vault.key", lambda: key)
    assert manager.set_private(session, note, True)
    session.commit()
    assert crypto.is_encrypted(note.content)

    body = client.get("/graph").json()
    label = next(n["preview"] for n in body["nodes"] if n["id"] == note.id)
    assert label.startswith("the plain words")
