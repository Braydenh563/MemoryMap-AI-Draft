"""ROADMAP.md item 34: a lightweight entity/concept layer above notes.

Every edge in the graph before this connected two whole notes; there was no
node for "this person" or "this project" independent of any one note
mentioning them. Deliberately smaller than a full ontology (see ANALYSIS.md
§59's read of a sibling project's LLM-entity-extraction, which this borrows
the *idea* of, not the code): no entity-to-entity graph, no type system, a
single free-text name per entity, and membership (`EntityMention`) as the
only edge kind. Extraction is one `suggest_tags`-shaped completion call per
note, on the utility model, run a few notes at a time by the autonomous
background pass (`ai/autonomous.py`) when `auto_entities_enabled` is on.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient
from memorymap.core.database import (
    LIKE_ESCAPE,
    Entity,
    EntityMention,
    Entry,
    like_escape,
    utcnow,
)

# A note this short rarely names anything worth its own node, cheaper to
# skip than to spend a model call finding nothing, the same reasoning
# `suggest_tags`' caller already applies before asking for tags.
MIN_CONTENT_LENGTH = 20

# Per note, per pass, a name-dropping note ("thanks Sam, Priya and Jo for
# the trip") shouldn't flood the entity table any more than five topic tags
# would.
MAX_ENTITIES_PER_NOTE = 5


def suggest_entities(
    text: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
    limit: int = MAX_ENTITIES_PER_NOTE,
) -> list[str]:
    """Named people/projects/things this note actually mentions, model's
    own words. Raises OllamaError if the model is unavailable, the caller
    decides what to do, same contract as `suggest_tags`.
    """
    system = (
        "You extract named entities from a note, real people, projects, "
        "places or things it names, not generic topics (a topic is a tag, "
        "not an entity: 'baking' is a topic, 'the sourdough starter' is a "
        "thing). Reply with ONLY a comma-separated list of "
        f"{limit} or fewer entity names, each as short as it's naturally "
        "called (a first name is fine), no explanation. If the note names "
        "nothing worth tracking as its own thing, reply with NONE."
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    raw = reply["content"].strip()
    if not raw or raw.upper().startswith("NONE"):
        return []
    seen: set[str] = set()
    names: list[str] = []
    for piece in raw.replace("\n", ",").split(","):
        name = piece.strip().strip("\"'").lstrip("-•").strip()
        key = name.lower()
        if name and key not in seen and len(name) <= 200:
            seen.add(key)
            names.append(name)
    return names[:limit]


def _find_or_create_entity(session: Session, name: str, cache: dict[str, Entity]) -> Entity:
    """Case-folded exact match within this pass's own cache first (so the
    same note's five names don't each hit the database), then the table
    itself, then a new row. Two different real-world Sarahs proposed as
    "Sarah" across two notes are merged into one entity, a real ambiguity
    this MVP accepts rather than solves (ROADMAP.md item 34's own scope
    cut); a later pass can add disambiguation without changing this shape.
    """
    key = name.lower()
    if key in cache:
        return cache[key]
    existing = session.scalars(
        select(Entity).where(Entity.name.ilike(like_escape(name), escape=LIKE_ESCAPE))
    ).first()
    entity = existing or Entity(name=name)
    if not existing:
        session.add(entity)
        session.flush()  # need entity.id for the EntityMention below
    cache[key] = entity
    return entity


def extract_entities_pass(
    session: Session,
    model_manager: ModelManager,
    ollama: OllamaClient,
    limit: int = 5,
) -> int:
    """Entity-extract up to `limit` not-yet-scanned notes. Returns how many
    were processed (successfully or not: a note that fails still gets
    marked scanned, the same "don't retry forever" reasoning
    `entities_extracted_at` exists for at all).

    Never raises: called from the autonomous pass's own worker thread,
    which the rest of that module's docstrings already establish must not
    propagate an exception past its own top level.
    """
    candidates = list(
        session.scalars(
            select(Entry)
            .where(
                Entry.entities_extracted_at.is_(None),
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
            )
            .order_by(Entry.id.desc())
            .limit(limit)
        )
    )
    if not candidates:
        return 0

    cache: dict[str, Entity] = {}
    processed = 0
    for entry in candidates:
        content = (entry.content or "").strip()
        try:
            if len(content) >= MIN_CONTENT_LENGTH:
                names = suggest_entities(content, model_manager, ollama)
                for name in names:
                    entity = _find_or_create_entity(session, name, cache)
                    already = session.scalars(
                        select(EntityMention).where(
                            EntityMention.entity_id == entity.id,
                            EntityMention.entry_id == entry.id,
                        )
                    ).first()
                    if not already:
                        session.add(EntityMention(entity_id=entity.id, entry_id=entry.id))
        except Exception:  # noqa: BLE001  # one bad note must not stop the pass
            pass
        finally:
            entry.entities_extracted_at = utcnow()
            processed += 1
    session.commit()
    return processed
