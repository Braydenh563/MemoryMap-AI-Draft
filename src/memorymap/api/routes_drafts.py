"""Thoughts → note drafts (the writing room).

Write loose thoughts, get a draft, edit it, add more thoughts, repeat until
it's right: then save it as a note like any other.

There's no draft table: the draft lives in the browser until you save it. A
half-finished draft isn't a note, and quietly filling the notebook with them
would be worse than losing one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from memorymap.ai import drafter
from memorymap.core import deps

router = APIRouter(prefix="/drafts", tags=["drafts"])


class ComposeBody(BaseModel):
    # What the user has just typed. Empty is allowed when they only want the
    # model to act on a one-off instruction against the existing draft.
    thoughts: str = Field(default="", max_length=8000)
    # The draft as it stands, including any edits the user made by hand.
    draft: str = Field(default="", max_length=20000)
    # An optional steer for this pass only ("make it shorter").
    instruction: str = Field(default="", max_length=300)


class TitleBody(BaseModel):
    draft: str = Field(min_length=1, max_length=20000)


@router.post("/compose")
def compose_draft(body: ComposeBody) -> dict:
    """Write or revise a draft from thoughts."""
    if not body.thoughts.strip() and not body.draft.strip():
        raise HTTPException(status_code=400, detail="Write a thought first")

    text, note = drafter.compose(
        body.thoughts,
        body.draft,
        deps.get_model_manager(),
        deps.get_ollama(),
        instruction=body.instruction,
    )
    offline = note == drafter.OFFLINE_MESSAGE
    return {
        "draft": text,
        # Distinguishes "the model reasoned" from "the model wasn't there".
        "thinking": None if offline else note,
        "message": drafter.OFFLINE_MESSAGE if offline else "",
        "ollama_running": not offline,
    }


@router.post("/title")
def draft_title(body: TitleBody) -> dict:
    """A suggested title for a finished draft ("" when unavailable)."""
    return {
        "title": drafter.suggest_title(
            body.draft, deps.get_model_manager(), deps.get_ollama()
        )
    }
