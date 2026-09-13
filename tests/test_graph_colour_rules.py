"""GRAPH_PLAN Phase 3: every note on the graph carries the fields the colour
rules read (kind, tags, space, has a file), so "colour by" is a rendering of
the payload and never a second request per node."""

from __future__ import annotations


def test_graph_nodes_carry_the_rule_fields(client):
    saved = client.post("/entries", json={"content": "sourdough starter schedule", "tags": ["baking"]}).json()
    nodes = client.get("/graph").json()["nodes"]
    node = next(n for n in nodes if n["id"] == saved["id"])
    assert node["kind"] == "note"
    assert node["tags"] == ["baking"]
    assert isinstance(node["space_id"], str) and node["space_id"]
    assert node["has_file"] is False
    assert "created_at" in node


def test_a_note_with_no_tags_carries_an_empty_list(client):
    saved = client.post("/entries", json={"content": "a plain note"}).json()
    nodes = client.get("/graph").json()["nodes"]
    node = next(n for n in nodes if n["id"] == saved["id"])
    assert node["tags"] == []


def test_graph_match_returns_the_ids_a_groups_words_match(client):
    a = client.post("/entries", json={"content": "thesis outline for the first chapter"}).json()
    client.post("/entries", json={"content": "gym on tuesday"}).json()
    b = client.post("/entries", json={"content": "thesis chapter two draft"}).json()
    ids = client.get("/graph/match", params={"q": "thesis"}).json()["ids"]
    assert set(ids) == {a["id"], b["id"]}
    assert client.get("/graph/match", params={"q": ""}).json() == {"ids": []}


def test_graph_nodes_carry_degree_age_and_map_ids(client):
    a = client.post("/entries", json={"content": "first note of a pair"}).json()
    b = client.post("/entries", json={"content": "second note of a pair"}).json()
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    assert nodes[a["id"]]["degree"] == 1 and nodes[b["id"]]["degree"] == 1
    assert nodes[a["id"]]["age_days"] == 0
    assert nodes[a["id"]]["map_ids"] == []


def test_a_note_on_a_map_lists_the_map(client):
    note = client.post("/entries", json={"content": "a note that goes on a map"}).json()
    board = client.post("/whiteboard/boards", json={"name": "Map for the test", "type": "map"}).json()
    root = client.post(f"/whiteboard/boards/{board['id']}/nodes", json={"kind": "topic", "text": "Root"}).json()
    client.post(
        f"/whiteboard/boards/{board['id']}/nodes",
        json={"kind": "note", "ref_id": note["id"], "parent_id": root["id"], "text": "a note"},
    )
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    assert nodes[note["id"]]["map_ids"] == [board["id"]]


def test_structure_is_served_from_the_cache_until_the_notebook_changes(client, monkeypatch):
    from memorymap.api import routes_graph

    client.post("/entries", json={"content": "one note so the index is not empty"})
    calls = {"n": 0}
    real = routes_graph._build_structure

    def counting(session):
        calls["n"] += 1
        return real(session)

    monkeypatch.setattr(routes_graph, "_build_structure", counting)
    routes_graph.reset_graph_cache()
    client.get("/graph/structure")
    client.get("/graph/structure")
    assert calls["n"] == 1
    client.post("/entries", json={"content": "a second note changes the version"})
    client.get("/graph/structure")
    assert calls["n"] == 2


def test_the_payload_stays_small_at_scale(client):
    """The plan's gate is 600 KB gzipped for 5,000 notes; 2,000 here, in
    proportion, so the suite stays fast."""
    import gzip
    import json as _json

    from memorymap.core import deps
    from memorymap.entry import manager

    with deps.get_db().session() as session:
        for i in range(2000):
            manager.create_entry(session, f"note {i} about topic{i % 40} and thing{i % 7}", tags=[f"t{i % 9}"])
        session.commit()
    body = client.get("/graph").content
    assert len(_json.loads(body)["nodes"]) >= 2000
    assert len(gzip.compress(body)) < 240 * 1024
