"""The graph endpoint: nodes, link/thread edges, similarity."""

from __future__ import annotations

from datetime import datetime


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_graph_empty_notebook(client):
    body = client.get("/graph").json()
    assert body == {"nodes": [], "edges": [], "categories": []}


def test_graph_nodes_and_manual_link_edges(client):
    a = _save(client, "first note", category="Alpha")
    b = _save(client, "second note", category="Beta")
    linked = client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]}).json()
    link_id = linked["links"][0]["link_id"]

    body = client.get("/graph").json()
    assert {n["id"] for n in body["nodes"]} == {a["id"], b["id"]}
    assert body["categories"] == ["Alpha", "Beta"]
    assert body["edges"] == [
        {
            "source": a["id"],
            "target": b["id"],
            "kind": "link",
            # The link row's own id: asked for directly, so the graph can
            # edit or remove a reason without going through a note card.
            "id": link_id,
            "reason": None,
            "reason_confidence": None,
            # Null on a link made without one, which is every link that
            # existed before link types and still means what it always
            # meant: "these are related". See core.database.LINK_TYPES.
            "link_type": None,
        }
    ]

    node = next(n for n in body["nodes"] if n["id"] == a["id"])
    assert node["category"] == "Alpha"
    assert node["preview"] == "first note"
    assert node["pinned"] is False
    # A note with no pin ever set, see the pin tests below.
    assert node["graph_pin_x"] is None
    assert node["graph_pin_y"] is None


def test_a_node_pin_survives_a_refetch(client):
    """ROADMAP §87.1's own audit: a double-click pin (graph.js) only ever
    lived on the in-memory D3 node object, `PUT /graph/pin/{id}` is the
    persistence half, and this is what makes it survive a reload."""
    a = _save(client, "held in place on purpose")
    resp = client.put(f"/graph/pin/{a['id']}", json={"x": 12.5, "y": -30.0})
    assert resp.status_code == 200
    assert resp.json() == {"id": a["id"], "graph_pin_x": 12.5, "graph_pin_y": -30.0}

    node = next(n for n in client.get("/graph").json()["nodes"] if n["id"] == a["id"])
    assert node["graph_pin_x"] == 12.5
    assert node["graph_pin_y"] == -30.0


def test_a_pin_can_be_released(client):
    a = _save(client, "pinned then released")
    client.put(f"/graph/pin/{a['id']}", json={"x": 1.0, "y": 2.0})

    resp = client.put(f"/graph/pin/{a['id']}", json={"x": None, "y": None})
    assert resp.status_code == 200
    assert resp.json() == {"id": a["id"], "graph_pin_x": None, "graph_pin_y": None}

    node = next(n for n in client.get("/graph").json()["nodes"] if n["id"] == a["id"])
    assert node["graph_pin_x"] is None
    assert node["graph_pin_y"] is None


def test_unpin_all_releases_every_pinned_node(client):
    """Direct instruction: "I want to be able to unroot and reset the graph
    to free float if I want with a button", one call releases every
    pinned note rather than tracking each down to double-click it."""
    a = _save(client, "pinned note one")
    b = _save(client, "pinned note two")
    c = _save(client, "never pinned")
    client.put(f"/graph/pin/{a['id']}", json={"x": 1.0, "y": 2.0})
    client.put(f"/graph/pin/{b['id']}", json={"x": -5.0, "y": 8.0})

    resp = client.post("/graph/unpin-all")
    assert resp.status_code == 200
    assert resp.json() == {"unpinned": 2}

    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    assert nodes[a["id"]]["graph_pin_x"] is None
    assert nodes[a["id"]]["graph_pin_y"] is None
    assert nodes[b["id"]]["graph_pin_x"] is None
    assert nodes[b["id"]]["graph_pin_y"] is None
    assert nodes[c["id"]]["graph_pin_x"] is None  # was never pinned; still fine


def test_unpin_all_is_a_no_op_when_nothing_is_pinned(client):
    _save(client, "an ordinary note")
    resp = client.post("/graph/unpin-all")
    assert resp.status_code == 200
    assert resp.json() == {"unpinned": 0}


def test_a_lone_coordinate_is_refused_not_guessed(client):
    """One axis set and the other null is not a position, refused rather
    than silently coerced into either a pin or a release."""
    a = _save(client, "a note")
    resp = client.put(f"/graph/pin/{a['id']}", json={"x": 5.0, "y": None})
    assert resp.status_code == 400


def test_pinning_an_unknown_note_404s(client):
    resp = client.put("/graph/pin/999999", json={"x": 1.0, "y": 1.0})
    assert resp.status_code == 404


def test_pinning_a_deleted_note_404s(client):
    a = _save(client, "about to be binned")
    client.delete(f"/entries/{a['id']}")
    resp = client.put(f"/graph/pin/{a['id']}", json={"x": 1.0, "y": 1.0})
    assert resp.status_code == 404


def test_a_pin_shows_up_in_focus_mode_too(client):
    """The same persisted pin, read from /graph/local, a user can pin a
    node while already focused on its neighbourhood, not only from the
    top-level map."""
    a = _save(client, "central note")
    client.put(f"/graph/pin/{a['id']}", json={"x": 7.0, "y": 8.0})

    nodes = client.get(f"/graph/local/{a['id']}").json()["nodes"]
    node = next(n for n in nodes if n["id"] == a["id"])
    assert node["graph_pin_x"] == 7.0
    assert node["graph_pin_y"] == 8.0


def test_graph_node_dates_are_valid_iso_not_double_timezoned(client):
    """`created_at` used to be built as `e.created_at.isoformat() + "Z"`, 
    but `core/database.DateTime` already hands back a timezone-AWARE
    datetime, so `.isoformat()` alone ends in `+00:00`, and the extra "Z"
    produced `...+00:00Z`: two timezone markers in one string. Python's own
    `datetime.fromisoformat` rejects that (and so, silently, does
    JavaScript's `Date` constructor, `Invalid Date`, no exception), which
    is why the graph's time-filter slider could never move: every node's
    date failed to parse, so the filter's min/max collapsed to "now" no
    matter what any note's actual date was.
    """
    a = _save(client, "first note", category="Alpha")
    node = next(n for n in client.get("/graph").json()["nodes"] if n["id"] == a["id"])
    parsed = datetime.fromisoformat(node["created_at"])
    assert parsed.tzinfo is not None


def test_graph_local_node_dates_are_valid_iso_too(client):
    """The focus-mode graph (`/graph/local/{id}`) builds its node list from
    a different loop over the same data and had the identical bug."""
    a = _save(client, "first note", category="Alpha")
    b = _save(client, "second note", category="Beta")
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})

    body = client.get(f"/graph/local/{a['id']}").json()
    for node in body["nodes"]:
        parsed = datetime.fromisoformat(node["created_at"])
        assert parsed.tzinfo is not None


def test_graph_link_edge_carries_its_reason(client):
    a = _save(client, "assignment due next week", category="Uni")
    b = _save(client, "gym session tuesday", category="Fitness")
    linked = client.post(
        f"/entries/{a['id']}/links",
        json={"target_id": b["id"], "reason": "both about scheduling"},
    ).json()
    link_id = linked["links"][0]["link_id"]

    edges = client.get("/graph").json()["edges"]
    assert edges == [
        {
            "source": a["id"],
            "target": b["id"],
            "kind": "link",
            "id": link_id,
            "reason": "both about scheduling",
            # A reason someone typed, not one deduced, no score attached.
            "reason_confidence": None,
            # Null on a link made without one, which is every link that
            # existed before link types and still means what it always
            # meant: "these are related". See core.database.LINK_TYPES.
            "link_type": None,
        }
    ]


def test_graph_link_edge_without_a_reason_is_none(client):
    a = _save(client, "first note", category="Alpha")
    b = _save(client, "second note", category="Beta")
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})

    edges = client.get("/graph").json()["edges"]
    assert edges[0]["reason"] is None


def test_graph_link_edge_carries_a_deduced_reasons_confidence(ai_client):
    a = _save(ai_client, "a funny scarecrow joke", category="Alpha")
    b = _save(ai_client, "another funny pun", category="Beta")
    ai_client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})

    edges = ai_client.get("/graph").json()["edges"]
    assert edges[0]["reason"] == "similar in meaning"
    assert edges[0]["reason_confidence"] == 1.0


def test_graph_omits_documents_by_default(client):
    a = _save(client, "first note", category="Alpha")
    document = client.post("/documents", json={"title": "Plan", "content": ""}).json()
    client.post(f"/documents/{document['id']}/notes", json={"entry_id": a["id"]})

    body = client.get("/graph").json()
    assert {n["id"] for n in body["nodes"]} == {a["id"]}
    assert body["edges"] == []


def test_graph_include_documents_adds_a_prefixed_node_and_edge(client):
    a = _save(client, "first note", category="Alpha")
    document = client.post("/documents", json={"title": "Plan", "content": ""}).json()
    client.post(f"/documents/{document['id']}/notes", json={"entry_id": a["id"]})

    body = client.get("/graph?include_documents=true").json()
    doc_node_id = f"document:{document['id']}"
    node = next(n for n in body["nodes"] if n["id"] == doc_node_id)
    assert node["type"] == "document"
    assert node["preview"] == "Plan"
    assert node["category"] == "Document"
    assert {n["id"] for n in body["nodes"]} == {a["id"], doc_node_id}
    assert body["edges"] == [{"source": doc_node_id, "target": a["id"], "kind": "document"}]
    # Document nodes aren't in the stable category list, same treatment as
    # entities, so the legend doesn't grow a filter for a node kind that's
    # off by default.
    assert "Document" not in body["categories"]


def test_graph_include_documents_ignores_a_document_with_no_linked_notes(client):
    _save(client, "first note", category="Alpha")
    client.post("/documents", json={"title": "Untouched", "content": ""})

    body = client.get("/graph?include_documents=true").json()
    assert all(n.get("type") != "document" for n in body["nodes"])


def test_graph_thread_edges(client):
    parent = _save(client, "the start of a thought", category="Ideas")
    child = _save(client, "…and where it went", parent_id=parent["id"])

    edges = client.get("/graph").json()["edges"]
    assert edges == [
        {"source": parent["id"], "target": child["id"], "kind": "thread"}
    ]


def test_graph_excludes_deleted_notes(client):
    a = _save(client, "keeper", category="Stuff")
    b = _save(client, "goner", category="Stuff")
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})
    client.delete(f"/entries/{b['id']}")

    body = client.get("/graph").json()
    assert [n["id"] for n in body["nodes"]] == [a["id"]]
    assert body["edges"] == []  # its only edge pointed at the deleted note


def test_graph_excludes_drafts(client):
    """A draft is unfinished by definition, reported directly ("drafts
    appear... in the graph"). The Notes tab already keeps drafts out of
    every list it draws; `/graph` didn't."""
    keeper = _save(client, "a finished thought", category="Stuff")
    _save(client, "half a thought", is_draft=True)

    body = client.get("/graph").json()
    assert [n["id"] for n in body["nodes"]] == [keeper["id"]]


def test_graph_similarity_edges_opt_in(ai_client):
    # The fake embedder puts both "joke" notes on the same axis → cosine 1.
    a = _save(ai_client, "a funny scarecrow joke")
    b = _save(ai_client, "another funny pun")
    _save(ai_client, "buy milk and eggs")  # different topic: no edge to jokes

    # Off by default.
    assert client_edges(ai_client, similarity=False) == []

    edges = client_edges(ai_client, similarity=True)
    similar = [e for e in edges if e["kind"] == "similar"]
    assert {frozenset((e["source"], e["target"])) for e in similar} == {
        frozenset((a["id"], b["id"]))
    }
    assert all(e["score"] >= 0.55 for e in similar)


def test_graph_similarity_skips_already_linked_pairs(ai_client):
    a = _save(ai_client, "a funny scarecrow joke")
    b = _save(ai_client, "another funny pun")
    ai_client.post(f"/entries/{a['id']}/links", json={"target_id": b['id']})

    edges = client_edges(ai_client, similarity=True)
    # The manual link wins; no duplicate dotted edge for the same pair.
    assert [e["kind"] for e in edges] == ["link"]


def client_edges(client, similarity: bool) -> list[dict]:
    url = "/graph?similarity=true" if similarity else "/graph"
    return client.get(url).json()["edges"]


def test_graph_previews_show_words_not_markdown_markers(client):
    """Reported: "**note" showing in graph titles when a note starts with a
    header or bolded word. Labels clip at ~40 characters, so markers are
    stripped rather than rendered, a clip mid-`**` is scaffolding."""
    client.post("/entries", json={"content": "## **Seraphine build** for _mid_ lane"})
    nodes = client.get("/graph").json()["nodes"]
    assert nodes[0]["preview"] == "Seraphine build for mid lane"


# --- the physics sliders, checked against the frontend source directly -------
#
# Not an API test, Gravity/Spread only make sense under the force layout, and
# the only way to check the toggle actually disables them under the others is
# to read graph.js, the same way test_frontend_ids.py/test_style_scale.py do
# for their own DOM-invisible-to-pytest checks.


def test_the_physics_sliders_are_disabled_under_tree_layouts():
    """Gravity and Spread scale the force simulation, and the tree layouts do
    not run one. Left enabled they are two controls that move, save, and change
    nothing: which reads as a broken app rather than a setting that does not
    apply here."""
    from memorymap.api.app import FRONTEND_DIR

    # setGraphPhysicsEnabled's *definition* moved out of app.js into
    # frontend/graph.js in the frontend refactor path's graph-view extraction
    # (the step after whiteboard.js), see index.html and graph.js's own
    # header for why that file has to load *before* app.js, unlike
    # whiteboard.js. Its call sites did not move with it: `switchTab`'s
    # "arrival" call and the layout-<select> "change" listener both stayed in
    # app.js, so the count below needs both files' text, the same way
    # test_frontend_ids.py/test_frontend_handlers.py read app.js +
    # whiteboard.js + graph.js together rather than any one file alone.
    graph_source = (FRONTEND_DIR / "graph.js").read_text(encoding="utf-8")
    app_source = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    start = graph_source.index("function setGraphPhysicsEnabled(")
    body = graph_source[start : start + 1400]
    assert 'layoutKind === "force"' in body
    assert "disabled" in body
    # Called on arrival as well as on change, or a notebook left on Tree comes
    # back with two live-looking dead sliders.
    combined = graph_source + "\n" + app_source
    assert combined.count("setGraphPhysicsEnabled(") >= 3


# --- the graph's expensive derivations, cached (§40 items 4 and 5) ---------------


def test_the_path_endpoint_stays_cheap_by_default(ai_client, monkeypatch):
    """It began computing similarity edges across the whole notebook on every
    call, while its docstring still promised something cacheable and safe to
    re-issue."""
    from memorymap.api import routes_graph

    calls: list[int] = []
    monkeypatch.setattr(
        routes_graph,
        "_similarity_edges",
        lambda *a, **k: calls.append(1) or [],
    )
    ai_client.get("/graph/path", params={"source": 1, "target": 2})
    assert calls == []

    ai_client.get("/graph/path", params={"source": 1, "target": 2, "similarity": "true"})
    assert calls == [1]


def _count_calls(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def test_pagerank_is_not_recomputed_for_an_unchanged_notebook(ai_client, monkeypatch):
    """Fifteen passes over every node and edge, on every single graph load."""
    from memorymap.api import routes_graph
    from memorymap.entry import paths

    ai_client.post("/entries", json={"content": "one"})
    ai_client.post("/entries", json={"content": "two"})

    calls = _count_calls(monkeypatch, paths, "pagerank")
    for _ in range(3):
        assert ai_client.get("/graph").status_code == 200
    assert len(calls) == 1, "pagerank ran more than once for the same notebook"

    # ...and a new note invalidates it, because a stale graph is worse than a
    # slow one.
    ai_client.post("/entries", json={"content": "three"})
    ai_client.get("/graph")
    assert len(calls) == 2
    routes_graph.reset_graph_cache()


def test_the_cache_is_scoped_to_the_notebook_it_was_built_from(app_state, session):
    """The cache is process-global and the counts in its key are not unique, 
    two notebooks with three notes each collide trivially. Restoring a backup
    must not be served the previous notebook's centrality."""
    from memorymap.api import routes_graph

    first = routes_graph._graph_fingerprint(session)
    assert str(app_state.data_dir) in first


def test_focus_mode_reuses_the_full_graphs_similarity_sweep(ai_client, monkeypatch):
    """`/graph/local` is meant to be the cheap one and was paying the whole
    notebook's cost. It still needs the global sweep, a similarity edge can
    join two notes at opposite ends, but it should not repeat it."""
    from memorymap.api import routes_graph

    made = ai_client.post("/entries", json={"content": "kayak repair"}).json()
    ai_client.post("/entries", json={"content": "kayak paddle"})

    # Patched on `routes_graph`, not on `embeddings`: it was imported by name,
    # so the module attribute is the binding that actually gets called.
    calls = _count_calls(monkeypatch, routes_graph, "similar_pairs")
    ai_client.get("/graph", params={"similarity": "true"})
    ai_client.get(f"/graph/local/{made['id']}", params={"similarity": "true"})
    assert len(calls) == 1
    routes_graph.reset_graph_cache()


def test_switching_embedding_model_invalidates_the_similarity_cache(ai_client, monkeypatch):
    """Vectors from two backends live in different spaces, so a model switch
    has to recompute even though no note changed."""
    from memorymap.api import routes_graph

    ai_client.post("/entries", json={"content": "a note"})
    calls = _count_calls(monkeypatch, routes_graph, "similar_pairs")

    ai_client.get("/graph", params={"similarity": "true"})
    assert len(calls) == 1

    backend = _deps_backend_id_patch(monkeypatch)
    ai_client.get("/graph", params={"similarity": "true"})
    assert len(calls) == 2, f"a switch to {backend} reused the old vectors' edges"
    routes_graph.reset_graph_cache()


def _deps_backend_id_patch(monkeypatch):
    """Pretend the user switched embedding model."""
    from memorymap.core import deps

    service = deps.get_embeddings()
    monkeypatch.setattr(service, "backend_id", lambda: "some-other-model")
    return "some-other-model"
