"""How are these two notes related?, the shortest chain between them (§9).

The graph view could always show you *that* two notes are connected. It could
never answer the question a graph is uniquely good at: **"what is the route
from this note to that one?"**, the chain of links, replies and shared tags
that joins two things you wrote months apart.

`related_notes` walks outward from one note. This walks *between* two, which is
a different search: outward stops when it has enough, between stops when it
arrives, and the interesting result is the sequence rather than the set.

## Why weights, and not a plain breadth-first search

Three kinds of connection exist in this notebook and they are not equally
meaningful:

- **a link**: somebody (or the model, with approval) decided these two belong
  together. The strongest signal there is, because it was a decision;
- **a thread**: a reply. Two notes in one train of thought;
- **a shared tag**: real, but weak. `#idea` on two notes says they are both
  ideas, not that either has anything to do with the other.

An unweighted search returns whichever chain has the fewest hops, so a single
`#misc` bridge beats a three-step chain of deliberate links every time, and
the answer that comes back is *technically* a path and *actually* noise. Tag
steps therefore cost `TAG_WEIGHT` and the search minimises cost, not hops. A
tag shortcut is still found when it is the only route; it just loses to
anything better.

## Hub tags make bridges out of nothing

The same problem, one level up: a tag on forty notes connects all forty to each
other, so in a notebook with one heavily-used tag *everything* is two hops from
everything and the feature answers "related" to every pair it is asked about.
A tag on more than `HUB_TAG_NOTES` notes is treated as filing rather than as a
connection and creates no edges at all. The result says so when it happens,
because "no path" is only honest if the reason is visible.

## And a cap on how far it will look

`MAX_PATH_HOPS` stops the search at six steps. This is not a performance guard
- a personal notebook is small, it is an honesty one. Six intermediaries is
not a relationship, and reporting one as though it were is the same failure as
the hub tag: an answer that is true and useless.
"""

from __future__ import annotations

import heapq
import json
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import Entry, EntryLink, link_strength

#: What each kind of step costs, before `link_strength` (core/database.py)
#: adjusts an individual link up or down. Links and replies are decisions
#: somebody made and cost the same by default; a shared tag is an
#: observation and costs four times as much, so a four-link chain still
#: beats one tag hop. The absolute numbers mean nothing, only the ratio
#: does.
LINK_WEIGHT = 1
THREAD_WEIGHT = 1
TAG_WEIGHT = 4
SIMILAR_WEIGHT = 6

#: Above this many notes, a tag is a filing label rather than a connection.
#: Twelve is the point where "everyone I tagged #recipes" stops being a group
#: and starts being a section of the notebook.
HUB_TAG_NOTES = 12

#: The longest chain worth calling a relationship. See the module docstring.
MAX_PATH_HOPS = 6


@dataclass(frozen=True)
class Step:
    """One hop of a path: which two notes, and what joins them."""

    source: int
    target: int
    #: `link`, `thread` or `tag`, the three the graph view already draws.
    kind: str
    #: A sentence fragment for the UI and for the model: "linked", "a reply to
    #: it", "both tagged #recipes". Written from `source` towards `target`, so
    #: a chain of these reads in order.
    how: str
    weight: float


def _entry_tags(entry: Entry) -> list[str]:
    """Tags off the JSON column, never raising.

    A local copy of `manager.entry_tags` rather than an import: this module is
    imported by the tool layer, the API and the graph route, and `manager`
    pulls in most of the entry stack behind it.
    """
    try:
        loaded = json.loads(entry.tags or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [t for t in loaded if isinstance(t, str)] if isinstance(loaded, list) else []


class Connections:
    """Every connection in the notebook, indexed once.

    Built in three queries rather than per-node, because the search visits many
    nodes and `_graph_neighbours`' tag lookup scans every entry for each one, 
    fine for the twelve results that walk returns, quadratic for a path search.
    """

    def __init__(self, entries: list[Entry]) -> None:
        self.entries: dict[int, Entry] = {e.id: e for e in entries}
        #: node -> neighbour -> the *cheapest* step between them. A pair that is
        #: both linked and tagged reports the link, because that is the
        #: stronger relationship and the one worth telling the user about.
        self.edges: dict[int, dict[int, Step]] = defaultdict(dict)
        #: Tags left out for being filing rather than connection, so the "no
        #: path" answer can say what it declined to count.
        self.hub_tags: list[str] = []

    def _add(self, source: int, target: int, kind: str, how: str, back: str, weight: float) -> None:
        """Record a step and its reverse. Cheaper always wins."""
        for a, b, phrase in ((source, target, how), (target, source, back)):
            existing = self.edges[a].get(b)
            if existing is None or weight < existing.weight:
                self.edges[a][b] = Step(a, b, kind, phrase, weight)

    def neighbours(self, node_id: int) -> dict[int, Step]:
        return self.edges.get(node_id, {})


def build(
    session: Session,
    include_private: bool = True,
    extra_edges: list[dict] = None,
    entries: list[Entry] | None = None,
) -> Connections:
    """Index the notebook's connections.

    `include_private` is False for the AI, which may not read private notes at
    all (`tools._require_note` refuses them). Routing *through* one would leak
    its preview into an answer by the back door, and routing to one would offer
    the model an id it is not allowed to open, so they are not in the graph it
    searches rather than filtered out of the result.

    `entries`, when given, skips this function's own query: for a caller
    (`routes_graph.graph()`) that already fetched the identically-scoped
    `is_deleted == False` set for its own node serialization; without this,
    every `GET /graph` call queried the full `Entry` table twice. Only used
    when `include_private` is left at its default: a caller passing
    `include_private=False` needs the narrower query this function runs
    itself, not the caller's unfiltered list.
    """
    if entries is None or not include_private:
        query = select(Entry).where(Entry.is_deleted == False)  # noqa: E712
        if not include_private:
            query = query.where(Entry.is_private == False)  # noqa: E712
        entries = list(session.scalars(query))
    index = Connections(entries)
    known = index.entries

    for link in session.scalars(select(EntryLink)):
        if link.source_entry_id in known and link.target_entry_id in known:
            # A link's own reason, when someone gave one, is a better answer
            # to "how are these connected?" than the generic "linked to", 
            # same phrase either direction, since "why" doesn't have one.
            # `reason_confidence` only exists on a reason nobody actually
            # said: "deduced" keeps Trace and the story prompt from reading
            # a guess as a fact the way a person's or the AI's own words are.
            phrase = "linked to"
            if link.reason:
                phrase = f"linked to ({link.reason}"
                if link.reason_confidence is not None:
                    phrase += f", {round(link.reason_confidence * 100)}% confidence, deduced"
                phrase += ")"
            # §87.5's first slice: a typed link, or one whose reason came
            # from a confident deduction, costs less than a bare one, see
            # `link_strength`'s own docstring for why this is a divisor.
            index._add(
                link.source_entry_id,
                link.target_entry_id,
                "link",
                phrase,
                phrase,
                LINK_WEIGHT / link_strength(link.link_type, link.reason_confidence),
            )

    for entry in entries:
        if entry.parent_id in known and entry.parent_id != entry.id:
            index._add(
                entry.parent_id,
                entry.id,
                "thread",
                "was replied to by",
                "is a reply to",
                THREAD_WEIGHT,
            )

    by_tag: dict[str, list[int]] = defaultdict(list)
    for entry in entries:
        for tag in _entry_tags(entry):
            by_tag[tag.lower()].append(entry.id)
    for tag, ids in by_tag.items():
        if len(ids) > HUB_TAG_NOTES:
            index.hub_tags.append(tag)
            continue
        phrase = f"shares #{tag} with"
        for position, first in enumerate(ids):
            for second in ids[position + 1 :]:
                index._add(first, second, "tag", phrase, phrase, TAG_WEIGHT)
    index.hub_tags.sort()

    if extra_edges:
        for edge in extra_edges:
            # Treat dynamic extra edges (like similarity) with their appropriate weight
            weight = SIMILAR_WEIGHT if edge.get("kind") == "similar" else LINK_WEIGHT
            index._add(edge["source"], edge["target"], edge.get("kind", "similar"), "is related to", "is related to", weight)

    return index


def find(index: Connections, source_id: int, target_id: int) -> list[Step] | None:
    """The cheapest chain from one note to another, or None.

    Dijkstra rather than breadth-first because the steps are weighted; the
    tie-break is hop count, so two routes of equal cost return the shorter one.
    Nothing here is hot enough to need better, a personal notebook is a few
    thousand nodes at the outside, and this runs once per question.
    """
    return _dijkstra(index, source_id, target_id)


def _dijkstra(
    index: Connections,
    source_id: int,
    target_id: int,
    banned_nodes: frozenset[int] = frozenset(),
    banned_edges: frozenset[tuple[int, int]] = frozenset(),
) -> list[Step] | None:
    """`find`, with two exclusion sets that only `find_many` uses.

    Split out rather than inlined into `find_many` because Yen's algorithm
    below needs *this exact search*, same weights, same hop cap, same
    tie-break: run repeatedly with parts of the graph masked off. A second
    implementation would drift from the one the single-path answer uses, and
    then the "best route" and "route 1 of 3" would disagree about which route
    is best, which is worse than not offering alternatives at all.
    """
    if source_id == target_id or source_id not in index.entries:
        return None
    if target_id not in index.entries:
        return None

    #: (cost, hops, node): the heap orders on cost then hops, which is the
    #: tie-break falling out of the tuple rather than needing its own pass.
    heap: list[tuple[int, int, int]] = [(0, 0, source_id)]
    best: dict[int, tuple[int, int]] = {source_id: (0, 0)}
    came_from: dict[int, Step] = {}
    settled: set[int] = set()

    while heap:
        cost, hops, node = heapq.heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        if node == target_id:
            break
        if hops >= MAX_PATH_HOPS:
            # Far enough. Its neighbours are still reachable by some other
            # route, so this prunes the branch rather than the node.
            continue
        for neighbour, step in index.neighbours(node).items():
            if neighbour in settled:
                continue
            if neighbour in banned_nodes or (node, neighbour) in banned_edges:
                continue
            candidate = (cost + step.weight, hops + 1)
            if candidate < best.get(neighbour, (1 << 30, 1 << 30)):
                best[neighbour] = candidate
                came_from[neighbour] = step
                heapq.heappush(heap, (candidate[0], candidate[1], neighbour))

    if target_id not in came_from:
        return None
    chain: list[Step] = []
    node = target_id
    while node != source_id:
        step = came_from[node]
        chain.append(step)
        node = step.source
    chain.reverse()
    return chain


#: How many routes `find_many` will look for, counting the best one. Three is
#: the number the UI can show as switchable chips without becoming a list you
#: have to read; past that the fourth-best route between two notes in a
#: personal notebook is nearly always a longer version of one of the first
#: three, and each extra one costs a whole Dijkstra per hop of the previous.
MAX_ALTERNATE_PATHS = 3


def find_many(
    index: Connections,
    source_id: int,
    target_id: int,
    limit: int = MAX_ALTERNATE_PATHS,
) -> list[list[Step]]:
    """The best route, then the next-best genuinely different ones.

    Asked for directly: *"allow for multiple paths to be displayed if they
    exist."* One route answers "how are these two related?"; several answer the
    question people actually have next, which is "is that the only way they
    connect?", and in a notebook the difference between one route and three
    is the difference between a fact and a shape.

    Yen's algorithm, which is the standard answer and is built entirely out of
    `_dijkstra`: take the best path; for each node along it, re-run the search
    with that node's outgoing step banned and everything before it pinned, and
    keep whatever comes back. Loopless by construction (the pinned prefix's
    nodes are banned from the suffix), so no route ever revisits a note, which
    matters here beyond correctness, because a path that walked through the
    same note twice would read as nonsense in the readout.

    Returns [] when there is no route at all, so a caller can treat "no path"
    and "one path" the same way it always has.
    """
    best = _dijkstra(index, source_id, target_id)
    if best is None:
        return []
    if limit <= 1:
        return [best]

    found: list[list[Step]] = [best]
    #: Candidates, ordered by (cost, hops) so the cheapest genuinely-different
    #: route is always taken next. A plain list with a scan rather than a heap:
    #: `limit` is 3, so this holds a handful of entries at the outside.
    candidates: list[tuple[float, int, list[Step]]] = []
    #: Route identity is its node sequence. Two routes over the same notes by
    #: different *reasons* are the same route as far as a reader is concerned.
    seen = {_route_key(source_id, best)}

    while len(found) < limit:
        previous = found[-1]
        for i in range(len(previous)):
            spur_node = source_id if i == 0 else previous[i - 1].target
            root = previous[:i]
            # Ban the first step of every known route that shares this prefix,
            # or the search just returns the route we already have.
            banned_edges = {
                (route[i].source, route[i].target)
                for route in found
                if len(route) > i and route[:i] == root
            }
            # And ban the prefix's own nodes, which is what makes the result
            # loopless: the suffix cannot wander back through where it began.
            banned_nodes = frozenset(
                [source_id] + [step.target for step in root[:-1]]
            ) - {spur_node}
            spur = _dijkstra(
                index, spur_node, target_id, banned_nodes, frozenset(banned_edges)
            )
            if spur is None:
                continue
            whole = root + spur
            key = _route_key(source_id, whole)
            if key in seen:
                continue
            seen.add(key)
            cost = sum(step.weight for step in whole)
            candidates.append((cost, len(whole), whole))
        if not candidates:
            break
        candidates.sort(key=lambda item: (item[0], item[1]))
        found.append(candidates.pop(0)[2])

    return found


def _route_key(source_id: int, chain: list[Step]) -> tuple[int, ...]:
    """A route's identity: the notes it visits, in order."""
    return tuple([source_id] + [step.target for step in chain])


def degree(index: Connections, node_id: int) -> int:
    """How many notes this one is connected to. Used to explain a failure:
    "nothing is connected to either of these" is a different answer from "they
    are both well connected, just not to each other", and the first one tells
    you what to do about it."""
    return len(index.neighbours(node_id))


# --- the shape of the whole notebook -----------------------------------------
# The same index, asked a different question. A path answers "how do these two
# relate"; this answers "what does my notebook look like", which is the
# question behind almost every request to tidy it up, and the one thing the
# model had no way to see. It could count notes and list categories, both of
# which describe the *filing*; nothing described the **structure**.

#: A cluster smaller than this is a pair or a triple, which is a fact about two
#: notes rather than a region of the notebook. Reported in the count, not in
#: the list, so "you have 14 little islands" is still sayable.
MIN_CLUSTER_NOTES = 3

#: Connected to this many or more, and a note is doing structural work: it is
#: where several trains of thought meet. Matches the graph view's own `.graph-hub`
#: threshold, deliberately: two definitions of "hub" that disagree is how the
#: picture and the answer start contradicting each other.
HUB_DEGREE = 3

def pagerank(index: Connections, iterations: int = 15, damping: float = 0.85) -> dict[int, float]:
    """Computes PageRank to mathematically identify the true hubs of the notebook."""
    nodes = list(index.entries.keys())
    N = len(nodes)
    if N == 0:
        return {}
    
    ranks = {n: 1.0 / N for n in nodes}
    out_degrees = {n: len(index.neighbours(n)) for n in nodes}
    
    for _ in range(iterations):
        new_ranks = {}
        for n in nodes:
            rank_sum = 0.0
            for neighbor in index.neighbours(n):
                if out_degrees[neighbor] > 0:
                    rank_sum += ranks[neighbor] / out_degrees[neighbor]
            new_ranks[n] = (1.0 - damping) / N + damping * rank_sum
        ranks = new_ranks
        
    return ranks


@dataclass(frozen=True)
class Cluster:
    """A group of notes all reachable from each other."""

    ids: list[int]
    #: The best-connected member, which is the one worth naming the cluster by.
    core_id: int
    #: Categories present, commonest first, a cheap description of what the
    #: cluster is *about* without asking a model anything.
    categories: list[str]


def clusters(index: Connections, category_of=None) -> list[Cluster]:
    """Connected components, largest first.

    Deliberately components rather than a community-detection algorithm
    (Louvain, label propagation and friends). Two reasons, and the second is
    the one that decided it: a component is **exactly true**, every note in it
    really is reachable from every other, where a community is a judgement
    call with a resolution parameter, and an answer the user cannot verify by
    clicking two notes is one they cannot trust. And a personal notebook's
    structure is islands, not a dense web with soft boundaries; the interesting
    fact is usually *how many* islands there are.

    `category_of` is a callable so this module stays free of the entry stack, 
    the caller already has a session and a category lookup.
    """
    seen: set[int] = set()
    found: list[Cluster] = []
    for start in index.entries:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        members: list[int] = []
        while stack:
            node = stack.pop()
            members.append(node)
            for neighbour in index.neighbours(node):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        if len(members) < 2:
            continue  # an island of one is an orphan, and has its own list
        core = max(members, key=lambda note_id: (degree(index, note_id), -note_id))
        names: list[str] = []
        if category_of is not None:
            counts: dict[str, int] = defaultdict(int)
            for note_id in members:
                counts[category_of(index.entries[note_id])] += 1
            names = sorted(counts, key=lambda name: (-counts[name], name))
        found.append(Cluster(ids=sorted(members), core_id=core, categories=names))
    found.sort(key=lambda c: (-len(c.ids), c.core_id))
    return found


def hubs(index: Connections, limit: int = 5) -> list[tuple[int, int]]:
    """The best-connected notes, as (id, connection count).

    Worth surfacing on its own rather than leaving to the picture: a hub is
    where the notebook's ideas actually meet, and it is the note to read first
    when returning to a subject after a month away.
    """
    ranked = sorted(
        ((note_id, degree(index, note_id)) for note_id in index.entries),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [pair for pair in ranked[:limit] if pair[1] >= HUB_DEGREE]


def orphans(index: Connections) -> list[int]:
    """Notes connected to nothing at all, no link, no reply, no shared tag.

    The most actionable thing in this module. An orphan is not a problem in
    itself; a *heap* of them means the notebook is a pile rather than a web,
    and every one is a note the graph view, the related-notes walk and this
    path search are all blind to.
    """
    return sorted(
        note_id for note_id in index.entries if not index.neighbours(note_id)
    )
