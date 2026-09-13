"""Find and merge near-duplicate notes.

Finding them needs no AI, it's word overlap on normalised text, so it works
with nothing running and the score is explainable rather than a black box.

Merging is where judgement helps, so it comes two ways. With the AI running it
can write one note that keeps everything the originals said. Without it, the
notes are joined with a separator, which is worse prose but loses nothing, 
and losing nothing is the only property that actually matters here.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from memorymap.ai import drafter
from memorymap.core import deps
from memorymap.core.database import Entry
from memorymap.core.deps import get_session
from memorymap.entry import duplicates, manager

router = APIRouter(prefix="/duplicates", tags=["duplicates"])

MERGE_PROMPT = (
    "These notes say much the same thing. Combine them into ONE note that "
    "keeps every distinct fact from all of them. Don't invent anything, don't "
    "add a preamble, and keep the user's voice. Reply with the note text only."
)


class MergeBody(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=20)
    # When false, or when the AI isn't running, the notes are joined verbatim.
    use_ai: bool = True


class PreviewBody(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=20)
    use_ai: bool = True


def _load(session: Session, ids: list[int]) -> list[Entry]:
    found = []
    for entry_id in dict.fromkeys(ids):
        entry = session.get(Entry, entry_id)
        if entry is None or entry.is_deleted:
            raise HTTPException(status_code=404, detail=f"Note {entry_id} not found")
        if entry.is_private:
            raise HTTPException(
                status_code=400, detail="Private notes can't be merged this way"
            )
        found.append(entry)
    if len(found) < 2:
        raise HTTPException(status_code=400, detail="Pick at least two notes to merge")
    return found


def _joined(entries: list[Entry]) -> str:
    """The no-AI merge: every note, in order, separated. Nothing is lost."""
    return "\n\n---\n\n".join(e.content.strip() for e in entries)


@router.get("")
def list_duplicates(
    threshold: float = duplicates.DEFAULT_THRESHOLD,
    session: Session = Depends(get_session),
) -> dict:
    """Groups of notes that look like the same note."""
    threshold = min(max(threshold, 0.4), 1.0)
    groups = duplicates.find_duplicates(session, threshold)
    return {"threshold": threshold, "groups": groups}


@router.post("/preview")
def preview_merge(body: PreviewBody, session: Session = Depends(get_session)) -> dict:
    """What the merged note would say, shown before anything is changed."""
    entries = _load(session, body.ids)
    fallback = _joined(entries)
    ollama = deps.get_ollama()

    if not body.use_ai or not ollama.is_running():
        return {"merged": fallback, "used_ai": False, "ollama_running": ollama.is_running()}

    # The drafter already knows how to rewrite text to an instruction, and
    # crucially it returns the input unchanged when the model can't help.
    merged, _thinking = drafter.compose(
        "", fallback, deps.get_model_manager(), ollama, instruction=MERGE_PROMPT
    )
    used_ai = merged.strip() != fallback.strip()
    return {"merged": merged or fallback, "used_ai": used_ai, "ollama_running": True}


@router.post("/merge")
def merge_notes(body: MergeBody, session: Session = Depends(get_session)) -> dict:
    """Replace several notes with one.

    The originals go to the recycle bin rather than being destroyed. A merge is
    the one operation here that can silently lose writing, so it has to be
    undoable: the bin is that undo.
    """
    entries = _load(session, body.ids)
    preview = preview_merge(PreviewBody(ids=body.ids, use_ai=body.use_ai), session)

    keeper = entries[0]
    # Keep every tag from every note; a tag is a deliberate choice and dropping
    # one during a tidy-up is exactly the kind of quiet loss to avoid.
    tags: list[str] = []
    for entry in entries:
        for tag in manager.entry_tags(entry):
            if tag not in tags:
                tags.append(tag)

    keeper.content = preview["merged"]
    keeper.tags = json.dumps(tags)
    manager.log_action(
        session, "edited", "entry", keeper.id, f"merged {len(entries)} notes"
    )
    for entry in entries[1:]:
        manager.soft_delete_entry(session, entry)

    session.commit()
    session.refresh(keeper)
    return {
        "id": keeper.id,
        "content": keeper.content,
        "merged_count": len(entries),
        "used_ai": preview["used_ai"],
        "binned_ids": [e.id for e in entries[1:]],
    }
