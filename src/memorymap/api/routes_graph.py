"""The graph view's data: every note and its connections in
one call, so the frontend can draw an Obsidian-style map.

Nodes are non-deleted entries; edges come from three places:
- manual links (the link button / link_notes tool),
- train-of-thought threads (parent_id),
- optionally, semantic similarity between stored vectors (?similarity=true)
  - computed on demand from the embeddings we already have, never stored.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.ai.embeddings import bytes_to_vector, similar_pairs
from memorymap.core import deps
from memorymap.core.database import Attachment, EmbeddingRecord, Entry, EntryLink
from memorymap.core.deps import get_session
from memorymap.entry import manager, paths
from memorymap.search import search_manager

router = APIRouter(tags=["graph"])



def _age_days(created_at, now) -> int:  # noqa: ANN001  # datetime, kept off the signature for the import
    """Whole days since the note was written, never negative."""
    if created_at is None:
        return 0
    stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return max(0, int((now - stamp).total_seconds() // 86400))


def _tags_of(entry: Entry) -> list[str]:
    """The note's tags as a list, whatever shape the column holds."""
    try:
        tags = json.loads(entry.tags or "[]")
    except (TypeError, ValueError):
        return []
    return [str(t) for t in tags if isinstance(t, (str, int))]

# Below this cosine similarity two notes aren't "about the same thing"
# enough to draw a line between them.
SIMILARITY_EDGE_THRESHOLD = 0.55
# A hard cap keeps a dense notebook from becoming a hairball (and the
# O(n²) comparison from mattering, it's personal-notebook scale).
MAX_SIMILARITY_EDGES = 200


# --- caching the two expensive derivations (ROADMAP §40, items 4 and 5) ----------
#
# Similarity edges are an all-pairs vector comparison and PageRank is fifteen
# passes over every node and edge. Both were recomputed from scratch on every
# request, which made `/graph` the most expensive endpoint in the app and made
# `/graph/local`, "focus mode", which is supposed to be the *cheap* one, pay
# the full notebook cost to draw a neighbourhood.
#
# Neither can be made local. Centrality is a global property by definition, and
# a similarity edge can join two notes at opposite ends of the notebook, so
# restricting either to the visited set would return different, wrong numbers.
# What they can be is computed once per version of the notebook.
#
# The version is a fingerprint of cheap aggregates rather than a counter
# someone has to remember to bump, a counter is a thing to forget, and a
# forgotten one serves a stale graph indefinitely. `updated_at` moves on any
# note edit, and the two counts move on anything created or destroyed.
#
# The known gap, stated rather than papered over: adding and removing one link
# between two requests leaves the counts identical, so that single case serves
# one stale render. The alternative is a `max(updated_at)` on links too, and a
# stale centrality value for one frame is not worth another aggregate on every
# graph load.
_cache_lock = threading.Lock()
_cache: dict[str, tuple] = {}


def _graph_fingerprint(session: Session) -> tuple:
    live = Entry.is_deleted == False  # noqa: E712
    return (
        # Which notebook. The cache is process-global while the counts below
        # are emphatically not unique, two notebooks holding three notes each
        # collide trivially, and so do two tests. Without this, restoring a
        # backup or pointing MEMORYMAP_DATA_DIR somewhere else could be served
        # the previous notebook's centrality.
        str(deps.get_config().data_dir),
        session.scalar(select(func.count(Entry.id)).where(live)) or 0,
        session.scalar(select(func.max(Entry.updated_at)).where(live)),
        session.scalar(select(func.count(EntryLink.id))) or 0,
    )


def _cached(name: str, fingerprint: tuple, build):  # noqa: ANN001
    """`build()`'s result for this version of the notebook, computed once.

    One slot per name, not an LRU: only the current version is ever asked for,
    and keeping the previous one alive holds a whole graph's worth of floats
    for nobody.
    """
    with _cache_lock:
        hit = _cache.get(name)
        if hit is not None and hit[0] == fingerprint:
            return hit[1]
    value = build()
    with _cache_lock:
        _cache[name] = (fingerprint, value)
    return value


def reset_graph_cache() -> None:
    """Drop everything. For the tests, and for a data restore."""
    with _cache_lock:
        _cache.clear()


# Registered rather than imported by the container. `deps.reset_app_state`
# used to reach up into this module to call the line above, which is the wrong
# direction: `core/` is the bottom layer. This says "empty me when the
# singletons go" without `core` needing to know this file exists.
deps.register_cache_reset(reset_graph_cache)


_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
# A callout's own opening line, `> [!tip] Remember`, is a blockquote marker
# plus the `[!kind]` tag (editor.js's mdCalloutElement parses the same shape).
# Left unstripped, a note that opens with a callout showed as a graph node
# label reading literally "Review > [!tip] Remem…", reported directly, and
# the fix is the callout equivalent of what _HEADING_MD already does for `#`.
_CALLOUT_MD = re.compile(r"^\s{0,3}>\s*\[!\w+\]\s*", re.M)


def _preview(text: str, length: int = 40) -> str:
    """One line of a note as plain words, markers stripped, not rendered.

    Mirrors the frontend's notePreviewText: these labels are clipped to ~40
    characters, and a clip that lands mid-`**` shows scaffolding
    ("**Seraphine…") instead of the note. Inline marker stripping is
    `manager.strip_inline_markdown`, heading/wiki-link handling stays here
    since those are specific to what a graph label is for.
    """
    text = _HEADING_MD.sub("", text)
    text = _CALLOUT_MD.sub("", text)
    text = re.sub(r"\[\[([^\[\]]{1,120})\]\]", r"\1", text)
    text = manager.strip_inline_markdown(text)
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1] + "…"


def _similarity_edges(
    session: Session, node_ids: set[int], taken: set[frozenset[int]]
) -> list[dict]:
    """Pairwise cosine over stored vectors of the current backend.

    Pairs already joined by a real link/thread edge are skipped, the stronger
    relationship wins.

    The comparison itself is cached per version of the notebook; only the
    `taken` filter and the cap are re-applied, because `taken` differs between
    callers (the full graph has already claimed its link and thread pairs;
    focus mode has not). The backend id is part of the key: vectors from two
    embedding models live in different spaces, so a model switch has to
    invalidate this even when no note changed.
    """
    backend = deps.get_embeddings().backend_id()
    fingerprint = (*_graph_fingerprint(session), backend)

    def build() -> list[tuple[int, int, float]]:
        records = session.scalars(
            select(EmbeddingRecord).where(EmbeddingRecord.model_version == backend)
        )
        vectors = {
            r.entry_id: bytes_to_vector(r.embedding)
            for r in records
            if r.entry_id in node_ids
        }
        return similar_pairs(vectors, SIMILARITY_EDGE_THRESHOLD)

    # Already sorted best-first, so the cap below keeps the strongest edges.
    scored = [
        {"source": a, "target": b, "kind": "similar", "score": round(score, 2)}
        for a, b, score in _cached("similarity", fingerprint, build)
        if frozenset((a, b)) not in taken
    ]
    return scored[:MAX_SIMILARITY_EDGES]


def _centrality(session: Session, index: paths.Connections, similarity: bool) -> dict:
    """PageRank over the whole graph, once per version of the notebook.

    `similarity` is in the key because similarity edges change the graph, so
    they change every node's rank: the same notebook scores differently with
    the edges on and off, and both answers are correct for their own picture.
    """
    fingerprint = (*_graph_fingerprint(session), similarity)
    return _cached("centrality", fingerprint, lambda: paths.pagerank(index))




@router.get("/graph/match")
def graph_match(q: str = Query(default="", max_length=200), session: Session = Depends(get_session)) -> dict:
    """The note ids a group's words match (GRAPH_PLAN Phase 3).

    A group is a saved search painted one colour, resolved on every render
    so a note written tomorrow joins it by itself. `/entries?q=` only filters
    when `semantic=true` (the list is filtered client-side by keyword), so a
    group needs the keyword engine directly: the same `keyword_search` the
    Notes tab uses, ids only, capped so a one-word group over a big notebook
    is one small reply rather than five thousand previews.
    """
    words = q.strip()
    if not words:
        return {"ids": []}
    hits = search_manager.keyword_search(session, words, limit=5000)
    return {"ids": [entry.id for entry in hits]}

@router.get("/graph")
def graph(
    similarity: bool = False,
    include_entities: bool = False,
    include_documents: bool = False,
    include_maps: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    # A draft is unfinished by definition, and the Notes tab already keeps
    # every draft out of the notebook it draws from, the graph is a map of
    # your notes and their connections, not a staging area, and a half-typed
    # draft has nothing worth connecting yet. Reported directly alongside the
    # same gap in Library (routes_library.py's `_notes()`).
    entries = list(
        session.scalars(
            select(Entry).where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_draft == False,  # noqa: E712
            )
        )
    )
    node_ids = {e.id for e in entries}
    category_names = manager.bulk_category_names(session, entries)
    # GRAPH_PLAN Phase 3: "colour by" is a rule picker (category, cluster,
    # kind, age, space, tag, has a file), so every note carries the fields
    # each rule reads. One query for the file rule rather than a join per
    # node; tags are the column's JSON list, never the raw string.
    with_files = set(session.scalars(select(Attachment.entry_id).distinct()))
    # GRAPH_PLAN Phase 5: which mind maps a note is on, from the map nodes'
    # own data (a note node stores `ref_id`), one query for the whole
    # payload. `map_ids` is what "has a map" colours by and what the local
    # pane will list; it is here whether or not maps are drawn as nodes.
    maps_of: dict[int, list[int]] = {}
    from memorymap.core.database import WhiteboardObject

    for board_id, raw in session.execute(
        select(WhiteboardObject.board_id, WhiteboardObject.data).where(
            WhiteboardObject.kind == "note", WhiteboardObject.board_id.is_not(None)
        )
    ):
        try:
            ref_id = (json.loads(raw or "{}") or {}).get("ref_id")
        except (TypeError, ValueError):
            continue
        if isinstance(ref_id, int) and board_id is not None:
            maps_of.setdefault(ref_id, []).append(board_id)
    now = datetime.now(timezone.utc)
    nodes = [
        {
            "id": e.id,
            "kind": "note",
            "tags": _tags_of(e),
            "space_id": e.workspace_id,
            "has_file": e.id in with_files,
            "map_ids": sorted(set(maps_of.get(e.id, []))),
            "age_days": _age_days(e.created_at, now),
            # Through the manager, never off the column: a private note's
            # `content` is ciphertext at rest, so `_preview(e.content)` labelled
            # it with a base64 blob. `readable_content` names the graph in its
            # own docstring as one of the places that must not break on a
            # private note: it decrypts while the vault is open and hands back
            # "Private note: unlock to read it." while it is locked.
            "preview": _preview(manager.readable_content(e)),
            "category": category_names.get(e.category_id, manager.UNCATEGORISED),
            "access_count": e.access_count,
            "pinned": e.pinned,
            # Where a double-click hold (graph.js) left this node, if it was
            # ever pinned in place, both null or both set, never one alone.
            # Distinct from `pinned` just above: that means "float to the
            # top of lists", this means "hold still at this point on the
            # map". Read on load so a pin survives a page reload, which is
            # the gap ROADMAP §87.1's own audit named.
            "graph_pin_x": e.graph_pin_x,
            "graph_pin_y": e.graph_pin_y,
            # A note's reply-to, so the tree layouts can nest a train of
            # thought under the note that started it instead of laying every
            # note out as a sibling (§9).
            "parent_id": e.parent_id if e.parent_id in node_ids else None,
            # `+ "Z"` predates `core/database.DateTime`, which now always
            # hands back a timezone-AWARE (UTC) datetime: so `.isoformat()`
            # alone already ends in `+00:00`, and appending "Z" on top
            # produced `...+00:00Z`: two timezone markers in one string,
            # which `new Date(...)` in JavaScript cannot parse at all
            # (silently `Invalid Date`, not an error). Every node's
            # `created_at` on the graph was affected, which is why the time
            # filter slider could never move, the frontend's own bounds
            # calculation filters out unparseable dates, so `min` and `max`
            # always collapsed to `Date.now()` regardless of any note's
            # actual date, on every single note in the notebook, not a rare
            # case. `/entries`, `/timeline` and everywhere else serialise
            # through Pydantic directly and were never affected, this was
            # the graph's own two hand-built dicts.
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]

    edges: list[dict] = []
    taken: set[frozenset[int]] = set()  # pairs already connected

    for link in session.scalars(select(EntryLink)):
        if link.source_entry_id in node_ids and link.target_entry_id in node_ids:
            pair = frozenset((link.source_entry_id, link.target_entry_id))
            if pair not in taken:
                taken.add(pair)
                edges.append(
                    {
                        "source": link.source_entry_id,
                        "target": link.target_entry_id,
                        "kind": "link",
                        # The link row's own id: asked for directly (a way
                        # to manage a reason from the graph itself, not only
                        # a note card's link chip). Without it, editing or
                        # removing a link from here had no id to act on.
                        "id": link.id,
                        "reason": link.reason,
                        # Set only when `reason` was deduced from embedding
                        # similarity rather than said in words, see
                        # EntryLink.reason_confidence.
                        "reason_confidence": link.reason_confidence,
                        # What kind of connection, when one was chosen. Fed
                        # through the same channel the render-time `kind`
                        # above already uses rather than a second one: the
                        # graph has always invented a kind per edge, and a
                        # real stored type belongs beside it, not parallel
                        # to it. Null on every link made before link types
                        # existed, which reads as the flat "related" the
                        # graph has always shown.
                        "link_type": link.link_type,
                    }
                )

    for e in entries:
        if e.parent_id is not None and e.parent_id in node_ids:
            pair = frozenset((e.parent_id, e.id))
            if pair not in taken:
                taken.add(pair)
                edges.append({"source": e.parent_id, "target": e.id, "kind": "thread"})

    config = deps.get_config()
    with_similarity = similarity and not config.get_preference("battery_efficient_mode")
    if with_similarity:
        edges.extend(_similarity_edges(session, node_ids, taken))

    index = paths.build(session, extra_edges=edges, entries=entries)
    centrality_scores = _centrality(session, index, with_similarity)

    # Stable category order so the frontend assigns stable colours.
    # Phase 5: degree per node, from the edges this payload carries, so a
    # client never has to count them itself (the colour rule, the label
    # priority and the local pane all read it).
    degree: dict[int, int] = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)
    categories = sorted({n["category"] for n in nodes})
    
    # Attach PageRank centrality to nodes for dynamic sizing
    for n in nodes:
        n["centrality"] = centrality_scores.get(n["id"], 0)

    # ROADMAP.md item 34: off by default (the frontend has to ask for it),
    # since every existing consumer of this endpoint assumes every node id
    # is an Entry id. An entity node's id is prefixed ("entity:5") so it can
    # never collide with one; the frontend's own node-shape code is what
    # tells the two apart, not a numeric range.
    if include_entities:
        from memorymap.core.database import Entity, EntityMention

        mentions = list(
            session.execute(
                select(EntityMention.entity_id, EntityMention.entry_id).where(
                    EntityMention.entry_id.in_(node_ids)
                )
            )
        )
        entity_ids = {m.entity_id for m in mentions}
        if entity_ids:
            entities = {
                e.id: e for e in session.scalars(select(Entity).where(Entity.id.in_(entity_ids)))
            }
            for entity_id, entity in entities.items():
                nodes.append(
                    {
                        "id": f"entity:{entity_id}",
                        "type": "entity",
                        "preview": entity.name,
                        "category": "Entity",
                        "created_at": entity.created_at.isoformat(),
                    }
                )
            for mention in mentions:
                if mention.entity_id in entities:
                    edges.append(
                        {
                            "source": f"entity:{mention.entity_id}",
                            "target": mention.entry_id,
                            "kind": "entity",
                        }
                    )

    # Tier 2 item 16: "documents in the graph", off by default, same reason
    # and same shape as include_entities just above (a document id is
    # prefixed so it can never collide with an Entry id, and every existing
    # consumer of this endpoint that assumes every node id is an Entry id
    # keeps working unasked). Edges come from DocumentLink, the many-to-many
    # note-document attachment table (§43/routes_documents.py): a document
    # already has a real connection to the notes it draws on; this is that
    # relationship rendered, not a new one invented for the graph.
    #
    # Deliberately not wired into centrality, similarity, or the trace-path
    # BFS (paths.build/_centrality) this pass: both are built entirely
    # around Entry, and extending either to a second node type is a
    # materially bigger, separate change from making a document visible and
    # connected in the first place.
    if include_documents:
        from memorymap.core.database import Document, DocumentLink

        doc_links = list(
            session.execute(
                select(DocumentLink.document_id, DocumentLink.entry_id).where(
                    DocumentLink.entry_id.in_(node_ids)
                )
            )
        )
        document_ids = {link.document_id for link in doc_links}
        if document_ids:
            documents = {
                d.id: d
                for d in session.scalars(
                    select(Document).where(Document.id.in_(document_ids))
                )
            }
            for document_id, document in documents.items():
                nodes.append(
                    {
                        "id": f"document:{document_id}",
                        "type": "document",
                        "preview": document.title,
                        "category": "Document",
                        "created_at": document.created_at.isoformat(),
                    }
                )
            for link in doc_links:
                if link.document_id in documents:
                    edges.append(
                        {
                            "source": f"document:{link.document_id}",
                            "target": link.entry_id,
                            "kind": "document",
                        }
                    )

    #: **A mind map, and the notes it is made of** (MINDMAP_PLAN.md §5 item
    #: 13). This is the "decide once" call §3.3 makes and §5 item 13 restates:
    #: *a map's membership is a link; a node's position is not.* So the only
    #: thing added here is one edge per `note`-kind object on a map, never an
    #: x, never a y, never a parent-child edge between two topics (a topic is
    #: not a note and has no place in a graph of notes).
    #:
    #: **No new node is created**, and that is the difference between this and
    #: `include_entities` / `include_documents` just above. A board *is* an
    #: `Entry` (§2), so it is already in `nodes`, it has been on the graph
    #: since maps existed, drawn as an ordinary note whose text is `# My map`
    #: and connected to nothing. Adding a second `map:<id>` node would put the
    #: same object on the map twice. What was missing was that the node never
    #: said it was a map and its membership was invisible, so this marks the
    #: node and adds the edges.
    #:
    #: Opt-in for the reason the two above are: an existing consumer that
    #: assumes every edge joins two notes it retrieved is not wrong, and a map
    #: with forty notes on it would add forty edges to a picture nobody asked
    #: to change.
    if include_maps:
        from memorymap.api.routes_whiteboard import _board_settings
        from memorymap.core.database import WhiteboardObject

        board_ids = {e.id for e in entries if getattr(e, "is_board", False)}
        if board_ids:
            by_id = {n["id"]: n for n in nodes}
            maps: set[int] = set()
            for entry in entries:
                if entry.id not in board_ids:
                    continue
                board_type, _layout = _board_settings(entry)
                node = by_id.get(entry.id)
                if node is None:
                    continue
                # `board` and `map` both, because the graph's own reason for
                # marking these is that a board of any kind is not a note the
                # way every other node here is, and a whiteboard that says so
                # is more honest than one drawn as a note with a heading.
                node["type"] = board_type
                if board_type == "map":
                    maps.add(entry.id)
            if maps:
                #: **`kind == "note"` only, and this is not a tidiness
                #: preference.** The first version queried every
                #: `MAP_REFERENCE_KINDS` row and filtered on `ref_id in
                #: node_ids` afterwards, reasoning that a document/file/
                #: bookmark id simply would not be an entry id. It is: these
                #: are four independent autoincrement sequences, so document 1
                #: and note 1 both exist in any notebook with one of each.
                #: `tests/test_mindmap.py` caught it emitting `{source: 1,
                #: target: 1}`, a map joined to *itself* through a document
                #: node: on the second row it was ever given. An id is only
                #: meaningful with its table, and the kind is the table.
                rows = session.execute(
                    select(WhiteboardObject.board_id, WhiteboardObject.data).where(
                        WhiteboardObject.board_id.in_(maps),
                        WhiteboardObject.kind == "note",
                    )
                )
                for board_id, raw in rows:
                    try:
                        ref_id = (json.loads(raw or "{}") or {}).get("ref_id")
                    except (TypeError, ValueError):
                        # A row edited by hand, or written before `data` was
                        # JSON. A map node nobody can read points at nothing.
                        continue
                    # A note that has since been deleted, or a private one the
                    # caller's `entries` query never returned: an edge naming a
                    # node the client did not receive is silently dropped by
                    # d3, which is an invisible failure rather than a visible
                    # one.
                    if not isinstance(ref_id, int) or ref_id not in node_ids:
                        continue
                    # A map that somehow points at itself is not a connection.
                    if ref_id == board_id:
                        continue
                    pair = frozenset((board_id, ref_id))
                    if pair in taken:
                        continue
                    taken.add(pair)
                    edges.append({"source": board_id, "target": ref_id, "kind": "map"})

    return {"nodes": nodes, "edges": edges, "categories": categories}

@router.get("/graph/local/{entry_id}")
def graph_local(
    entry_id: int,
    # Unbounded before this: `?depth=999999999` ran the BFS loop below that
    # many times on a bare Python range(), no per-note work once the
    # frontier empties, but the loop itself still costs real wall-clock time
    # per iteration, and this server is single-worker (deps.py), so it stalls
    # every other request for however long that takes. 6 hops covers any
    # notebook a "local neighbourhood" view is meant for; Focus Mode never
    # asks for more than 2-3 today.
    depth: int = Query(default=2, ge=1, le=6),
    similarity: bool = False,
    session: Session = Depends(get_session)
) -> dict:
    """Focus Mode API: Gets the local neighborhood up to N degrees."""
    config = deps.get_config()
    extra_edges = []

    if similarity and not config.get_preference("battery_efficient_mode"):
        node_ids = set(
            session.scalars(
                select(Entry.id).where(Entry.is_deleted == False)  # noqa: E712
            )
        )
        extra_edges = _similarity_edges(session, node_ids, set())

    index = paths.build(session, extra_edges=extra_edges)

    if entry_id not in index.entries:
        return {"nodes": [], "edges": [], "categories": []}
        
    # BFS up to `depth`
    visited = {entry_id}
    queue = [entry_id]
    edges = []
    taken = set()
    
    for _ in range(depth):
        next_queue = []
        for n in queue:
            for neighbor, step in index.neighbours(n).items():
                pair = frozenset((n, neighbor))
                if pair not in taken:
                    taken.add(pair)
                    edges.append({
                        "source": n,
                        "target": neighbor,
                        "kind": step.kind
                    })
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_queue.append(neighbor)
        queue = next_queue
        if not queue:
            break  # nothing left to expand, further iterations would be no-ops

    category_names = manager.bulk_category_names(session, [index.entries[n] for n in visited])
    nodes = [
        {
            "id": e_id,
            "preview": _preview(manager.readable_content(index.entries[e_id])),
            "category": category_names.get(index.entries[e_id].category_id, manager.UNCATEGORISED),
            "access_count": index.entries[e_id].access_count,
            "pinned": index.entries[e_id].pinned,
            # Same pin-restore field as the top-level /graph, see that
            # endpoint's own comment. Focus Mode is the other real place a
            # double-click pin can be made or seen, so it needs the same
            # persistence, not just the top-level map.
            "graph_pin_x": index.entries[e_id].graph_pin_x,
            "graph_pin_y": index.entries[e_id].graph_pin_y,
            "parent_id": index.entries[e_id].parent_id if index.entries[e_id].parent_id in visited else None,
            # See the other node-list above: `created_at` is already
            # timezone-aware (`core/database.DateTime` guarantees it), so
            # `+ "Z"` on top of `.isoformat()`'s own `+00:00` produced an
            # unparseable double-suffixed string in JavaScript.
            "created_at": index.entries[e_id].created_at.isoformat(),
        }
        for e_id in visited
    ]
    
    centrality_scores = _centrality(session, index, bool(extra_edges))
    for n in nodes:
        n["centrality"] = centrality_scores.get(n["id"], 0)
        
    categories = sorted({n["category"] for n in nodes})
    return {"nodes": nodes, "edges": edges, "categories": categories}


def _path_node(entry: Entry, category_names: dict[int | None, str]) -> dict:
    """One note on a path or in a structural list. The same shape the graph's
    nodes use, so the view can highlight by id without a second lookup, plus
    enough text to read a chain as a sentence when the graph is not on screen."""
    return {
        "id": entry.id,
        "preview": _preview(manager.readable_content(entry), 60),
        "category": category_names.get(entry.category_id, manager.UNCATEGORISED),
    }


@router.get("/graph/structure")
def graph_structure(session: Session = Depends(get_session)) -> dict:
    """The shape of the notebook: clusters, hubs and orphans (§9).

    One call, because all three come off the same index and the view wants them
    together: colouring by cluster and listing the orphans are the same
    question asked twice. `cluster_of` is what makes the colouring a lookup
    rather than a second traversal in JavaScript.
    """
    # GRAPH_PLAN Phase 5: computed once per version of the notebook. The
    # colour rule "cluster" asks for this on every render, and community
    # detection over a big notebook is the slowest thing the graph does.
    return _cached("structure", _graph_fingerprint(session), lambda: _build_structure(session))


def _build_structure(session: Session) -> dict:
    index = paths.build(session)
    category_names = manager.bulk_category_names(session, list(index.entries.values()))

    def category_of(entry: Entry) -> str:
        return category_names.get(entry.category_id, manager.UNCATEGORISED)

    groups = paths.clusters(index, category_of)
    cluster_of: dict[str, int] = {}
    for position, cluster in enumerate(groups):
        for note_id in cluster.ids:
            # String keys: this is JSON, where an object's keys are strings
            # whatever they started as, and a client reading `cluster_of[id]`
            # with a numeric id gets undefined. Being explicit here beats
            # discovering it in the browser.
            cluster_of[str(note_id)] = position

    loose = paths.orphans(index)
    return {
        "notes": len(index.entries),
        "connected": len(index.entries) - len(loose),
        "clusters": [
            {
                "size": len(cluster.ids),
                "core": _path_node(index.entries[cluster.core_id], category_names),
                "categories": cluster.categories[:3],
                "ids": cluster.ids,
            }
            for cluster in groups
            if len(cluster.ids) >= paths.MIN_CLUSTER_NOTES
        ],
        # Counted separately rather than listed: a notebook with thirty pairs
        # is a different shape from one with two big clusters, and that fact is
        # worth a number even though the pairs are not worth thirty rows.
        "small_clusters": sum(
            1 for cluster in groups if len(cluster.ids) < paths.MIN_CLUSTER_NOTES
        ),
        "cluster_of": cluster_of,
        "hubs": [
            {**_path_node(index.entries[note_id], category_names), "links": count}
            for note_id, count in paths.hubs(index)
        ],
        "orphans": [_path_node(index.entries[note_id], category_names) for note_id in loose[:20]],
        "orphan_count": len(loose),
        "hub_tags": index.hub_tags,
    }


@router.get("/graph/path")
def graph_path(
    source: int,
    target: int,
    similarity: bool = False,
    routes: int = paths.MAX_ALTERNATE_PATHS,
    session: Session = Depends(get_session),
) -> dict:
    """The chain of connections between two notes (§9).

    The one question a graph answers better than a list, and the one the view
    could not answer: *how are these two related?* Returns the notes in order
    with the reason for each step, or `found: false` and: this is the part
    that makes it usable, **why** there is no path, since "no" is only a
    useful answer when it says what to do about it.

    Deliberately a GET with two ids: it reads nothing but the notebook's own
    structure, so it is cacheable, linkable and safe to re-issue.

    `similarity=true` additionally lets the chain hop along "these read alike"
    edges, which finds a route between notes nothing actually connects. It is
    opt-in and off by default for two reasons: it costs a full vector sweep of
    the notebook, which is not what "cacheable and safe to re-issue" above
    describes; and a path made of similarity edges answers a weaker question
    than the one asked, `SIMILAR_WEIGHT` makes them the last resort within a
    route, but a route made only of them is "these are both about cooking"
    dressed up as a connection the user made.
    """
    extra_edges = []
    if similarity and not deps.get_config().get_preference("battery_efficient_mode"):
        node_ids = set(
            session.scalars(
                select(Entry.id).where(Entry.is_deleted == False)  # noqa: E712
            )
        )
        extra_edges = _similarity_edges(session, node_ids, set())

    index = paths.build(session, extra_edges=extra_edges)
    missing = [
        note_id for note_id in (source, target) if note_id not in index.entries
    ]
    if missing:
        return {
            "found": False,
            "source": source,
            "target": target,
            "reason": (
                "That note isn't in the map, it may have been deleted."
                if len(missing) == 1
                else "Neither note is in the map."
            ),
        }
    if source == target:
        return {
            "found": False,
            "source": source,
            "target": target,
            "reason": "Those are the same note.",
        }

    #: Asked for directly: "allow for multiple paths to be displayed if they
    #: exist." `find_many`'s first entry *is* `find`'s answer: they share one
    #: Dijkstra: so the single-path shape below is unchanged and the extras
    #: ride alongside it. `routes=1` gets the old behaviour exactly, for a
    #: caller that does not want to pay for the alternatives.
    wanted = max(1, min(int(routes or 1), paths.MAX_ALTERNATE_PATHS))
    chains = paths.find_many(index, source, target, limit=wanted)
    chain = chains[0] if chains else None
    if chain is None:
        ends = [
            (note_id, paths.degree(index, note_id)) for note_id in (source, target)
        ]
        lonely = [note_id for note_id, count in ends if count == 0]
        if lonely:
            reason = (
                "Neither note is connected to anything yet."
                if len(lonely) == 2
                else "One of these notes isn't connected to anything yet."
            )
        else:
            reason = (
                "They're both connected to other notes, but there's no route "
                f"between them within {paths.MAX_PATH_HOPS} steps."
            )
        if index.hub_tags:
            # Said plainly, because otherwise this reads as a wrong answer: the
            # two notes may well share a tag and still get "no path" back.
            listed = ", ".join("#" + tag for tag in index.hub_tags[:3])
            reason += (
                f" Tags on more than {paths.HUB_TAG_NOTES} notes ({listed}) are "
                "treated as filing rather than as a connection."
            )
        return {
            "found": False,
            "source": source,
            "target": target,
            "reason": reason,
        }

    #: Every note on *any* of the routes, named once. `bulk_category_names` is
    #: a query, so calling it per route would issue three where one does.
    everywhere: list[int] = []
    for one in chains:
        for note_id in [source] + [step.target for step in one]:
            if note_id not in everywhere:
                everywhere.append(note_id)
    category_names = manager.bulk_category_names(
        session, [index.entries[note_id] for note_id in everywhere]
    )

    def rendered(one: list) -> dict:
        order = [source] + [step.target for step in one]
        return {
            "hops": len(one),
            "cost": sum(step.weight for step in one),
            "nodes": [
                _path_node(index.entries[note_id], category_names) for note_id in order
            ],
            "steps": [
                {
                    "source": step.source,
                    "target": step.target,
                    "kind": step.kind,
                    "how": step.how,
                }
                for step in one
            ],
        }

    routes_out = [rendered(one) for one in chains]
    best = routes_out[0]
    return {
        "found": True,
        "source": source,
        "target": target,
        #: The best route, spelled at the top level exactly as it always was, 
        #: every existing caller and test reads `nodes`/`steps`/`hops` from
        #: here, and moving them into `routes[0]` would be a breaking change
        #: for no gain.
        "hops": best["hops"],
        "nodes": best["nodes"],
        "steps": best["steps"],
        #: …and all of them, best first. Always at least one element when
        #: `found` is true, so the UI has one shape to render rather than two.
        "routes": routes_out,
    }


class PinBody(BaseModel):
    # Both set or both null, never one alone. `x`/`y` rather than reusing
    # `graph_pin_x`/`graph_pin_y` verbatim: the column names carry "graph_"
    # because they live on the shared `Entry` table, but this endpoint is
    # already scoped to the graph by its own path.
    x: float | None = None
    y: float | None = None


@router.put("/graph/pin/{entry_id}")
def pin_node(
    entry_id: int, body: PinBody, session: Session = Depends(get_session)
) -> dict:
    """Hold a node in place, or release it, the persistence half of the
    Graph tab's double-click pin (graph.js), which used to live only on the
    in-memory D3 node object and vanish the moment `/graph` was refetched
    (ROADMAP §87.1's own audit named this gap directly).

    `x`/`y` both null clears the pin; both set pins it there. One set and
    one null is refused rather than silently coerced, a lone coordinate is
    not a position, and guessing which axis was meant would be worse than
    asking again.
    """
    entry = session.get(Entry, entry_id)
    if entry is None or entry.is_deleted:
        raise HTTPException(status_code=404, detail="No such note.")
    if (body.x is None) != (body.y is None):
        raise HTTPException(
            status_code=400, detail="A pin needs both x and y, or neither."
        )
    entry.graph_pin_x = body.x
    entry.graph_pin_y = body.y
    session.commit()
    return {"id": entry.id, "graph_pin_x": entry.graph_pin_x, "graph_pin_y": entry.graph_pin_y}


@router.post("/graph/unpin-all")
def unpin_all_nodes(session: Session = Depends(get_session)) -> dict:
    """Release every pinned node at once, direct instruction: "I want to be
    able to unroot and reset the graph to free float if I want with a
    button." `pin_node` above only ever clears one note at a time, which is
    fine for the drag-to-place gesture it serves but not for "start over,"
    which would otherwise mean tracking down and double-clicking every
    pinned node individually.

    Scoped by the ordinary session (the same `WorkspaceMixin` scoping every
    other query in this app already gets) rather than an explicit
    workspace filter here: this route has no more reason to reach across
    spaces than `pin_node` above does.
    """
    pinned = (
        session.query(Entry)
        .filter(Entry.is_deleted == False, Entry.graph_pin_x.is_not(None))  # noqa: E712
        .all()
    )
    for entry in pinned:
        entry.graph_pin_x = None
        entry.graph_pin_y = None
    session.commit()
    return {"unpinned": len(pinned)}
