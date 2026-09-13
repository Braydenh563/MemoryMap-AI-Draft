"""ROADMAP.md item 34: a lightweight entity/concept layer above notes.

Fakes the model layer (a plain object with a `.chat()`/`.utility_model()`
shape, same convention `test_model_specs.py`'s own `ollama` fixture uses)
rather than needing a real Ollama, this suite runs fully offline.
"""

from __future__ import annotations

from memorymap.ai.entities import extract_entities_pass, suggest_entities
from memorymap.core.database import Entity, EntityMention, Entry


class _FakeModelManager:
    def utility_model(self) -> str:
        return "fake-utility-model"


class _FakeOllama:
    """Replies with whatever `next_reply` is currently set to, good enough
    for one note at a time, which is all `extract_entities_pass` ever asks
    of it per call."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)

    def chat(self, model, messages, mode=None):  # noqa: ANN001, ARG002
        content = self._replies.pop(0) if self._replies else "NONE"
        return {"content": content}


def test_suggest_entities_parses_a_comma_list():
    ollama = _FakeOllama(["Sarah, the Riverside project, Tokyo"])
    names = suggest_entities("text", _FakeModelManager(), ollama)
    assert names == ["Sarah", "the Riverside project", "Tokyo"]


def test_suggest_entities_none_means_no_entities():
    ollama = _FakeOllama(["NONE"])
    assert suggest_entities("text", _FakeModelManager(), ollama) == []


def test_extraction_pass_creates_entities_and_mentions(session):
    entry = Entry(content="Had lunch with Sarah to discuss the Riverside project.", ai_confidence=0)
    session.add(entry)
    session.commit()

    ollama = _FakeOllama(["Sarah, the Riverside project"])
    processed = extract_entities_pass(session, _FakeModelManager(), ollama, limit=5)

    assert processed == 1
    entities = {e.name for e in session.query(Entity).all()}
    assert entities == {"Sarah", "the Riverside project"}
    assert session.query(EntityMention).count() == 2

    session.refresh(entry)
    assert entry.entities_extracted_at is not None


def test_extraction_pass_skips_already_scanned_notes(session):
    from memorymap.core.database import utcnow

    entry = Entry(content="Already scanned before.", ai_confidence=0, entities_extracted_at=utcnow())
    session.add(entry)
    session.commit()

    ollama = _FakeOllama(["Someone"])
    processed = extract_entities_pass(session, _FakeModelManager(), ollama, limit=5)

    assert processed == 0
    assert session.query(EntityMention).count() == 0


def test_extraction_pass_merges_same_name_across_notes(session):
    session.add_all(
        [
            Entry(content="Sarah asked about the deadline for the report.", ai_confidence=0),
            Entry(content="Caught up with Sarah again about the same report.", ai_confidence=0),
        ]
    )
    session.commit()

    ollama = _FakeOllama(["Sarah", "Sarah"])
    processed = extract_entities_pass(session, _FakeModelManager(), ollama, limit=5)

    assert processed == 2
    sarahs = session.query(Entity).filter(Entity.name.ilike("Sarah")).all()
    assert len(sarahs) == 1
    assert session.query(EntityMention).filter(EntityMention.entity_id == sarahs[0].id).count() == 2


def test_a_short_note_is_skipped_without_a_model_call(session):
    entry = Entry(content="ok", ai_confidence=0)
    session.add(entry)
    session.commit()

    ollama = _FakeOllama(["should never be read"])
    processed = extract_entities_pass(session, _FakeModelManager(), ollama, limit=5)

    assert processed == 1  # still marked scanned
    assert session.query(EntityMention).count() == 0
    assert len(ollama._replies) == 1  # the model was never actually asked


def test_graph_endpoint_includes_entities_only_when_asked(client):
    entry_resp = client.post("/entries", json={"content": "Sarah's note about the Riverside project."})
    entry_id = entry_resp.json()["id"]

    from memorymap.core import deps

    with deps.get_db().session() as session:
        entity = Entity(name="Sarah")
        session.add(entity)
        session.flush()
        session.add(EntityMention(entity_id=entity.id, entry_id=entry_id))
        session.commit()

    plain = client.get("/graph").json()
    assert all(n.get("type") != "entity" for n in plain["nodes"])

    with_entities = client.get("/graph?include_entities=true").json()
    entity_nodes = [n for n in with_entities["nodes"] if n.get("type") == "entity"]
    assert len(entity_nodes) == 1
    assert entity_nodes[0]["preview"] == "Sarah"
    assert any(
        e["kind"] == "entity" and e["source"] == entity_nodes[0]["id"] and e["target"] == entry_id
        for e in with_entities["edges"]
    )
