"""Tag manager endpoints: see, rename/merge, delete tags."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from memorymap.core.deps import get_session
from memorymap.entry import manager

router = APIRouter(prefix="/tags", tags=["tags"])


class RenameBody(BaseModel):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1, max_length=60)


class DeleteBody(BaseModel):
    name: str = Field(min_length=1)


#: How many tags one response carries. Higher than the other page sizes on
#: purpose: this list feeds a tag cloud and a filter picker, and a picker
#: showing the first page of your tags is a picker that has lost some, so the
#: cap is a guard against a pathological notebook rather than a page anyone
#: is expected to walk. `X-Total-Count` is what says it was reached.
TAGS_PAGE_SIZE = 1000


@router.get("")
def list_tags(
    response: Response,
    limit: int = Query(default=TAGS_PAGE_SIZE, ge=1, le=5000),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Every tag in use → how many entries carry it (most used first)."""
    counts = manager.all_tags(session)
    response.headers["X-Total-Count"] = str(len(counts))
    if len(counts) <= limit:
        return counts
    #: Already ordered most-used first, so the cut keeps the tags that matter
    #: most and drops the long tail, which is the right end to lose.
    return dict(list(counts.items())[:limit])


@router.post("/rename")
def rename_tag(body: RenameBody, session: Session = Depends(get_session)) -> dict:
    """Rename a tag everywhere; renaming onto an existing tag merges them."""
    return {"changed": manager.rename_tag(session, body.old, body.new.strip())}


@router.post("/delete")
def delete_tag(body: DeleteBody, session: Session = Depends(get_session)) -> dict:
    return {"changed": manager.delete_tag(session, body.name)}
