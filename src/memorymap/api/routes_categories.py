"""Category management: list, rename (merging on collision), and delete.

Categories are created implicitly by the AI as it files notes, so over time
they drift: near-duplicates, typos, ones that stopped being useful. These
endpoints are how the user tidies that up.

Neither operation ever loses a note: renaming onto an existing category merges
the two, and deleting one moves its notes to Uncategorised.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from memorymap.core.deps import get_session
from memorymap.entry import manager

router = APIRouter(prefix="/categories", tags=["categories"])


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


#: Same reasoning as the tag list: this feeds the sidebar and every filing
#: picker, so it is not a list anyone pages through. The cap exists so one
#: response cannot grow without limit, and `X-Total-Count` says when it bit.
CATEGORIES_PAGE_SIZE = 1000


@router.get("")
def list_categories(
    response: Response,
    limit: int = Query(default=CATEGORIES_PAGE_SIZE, ge=1, le=5000),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Every category with its live note count, biggest first."""
    rows = manager.all_categories(session)
    response.headers["X-Total-Count"] = str(len(rows))
    return rows[:limit]


@router.put("/{category_id}")
def rename_category(
    category_id: int, body: RenameBody, session: Session = Depends(get_session)
) -> dict:
    """Rename a category. Renaming onto an existing one merges them."""
    try:
        return manager.rename_category(session, category_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{category_id}")
def delete_category(category_id: int, session: Session = Depends(get_session)) -> dict:
    """Remove a category; its notes survive as Uncategorised."""
    try:
        return manager.delete_category(session, category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
