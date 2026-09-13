"""What the notebook learned, over HTTP (WORLD_CLASS_PLAN 15, I7).

One writer and one reader over `ai/learning.py`. The write exists because
three of the four correction kinds happen in the browser and nowhere else: a
dismissed link suggestion, a result opened after a question, a resurfacing
card sent away. The fourth, a re-file, is already recorded server-side by
`entry/manager.update_entry_with_correction`, which is why there is no
"refile" caller here.

I9, the Settings section that lists, edits, deletes and switches these off,
is not this module: it needs a view of derived facts rather than of the
corrections themselves, and it is the next step of Brief 23.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from memorymap.ai import learning
from memorymap.core.deps import get_session

router = APIRouter(prefix="/learned", tags=["learned"])


class CorrectionBody(BaseModel):
    #: One of `learning.KINDS`. Validated in the route rather than as an enum
    #: here so the error names the kinds that do exist, which is the thing a
    #: caller with a typo needs to read.
    kind: str
    #: What the correction is about: `{"entry_id": 1}` for a resurfacing
    #: dismissal, `{"a": 1, "b": 2}` for a link pair, `{"question": "...",
    #: "entry_id": 1}` for a result opened after a question. Free-form
    #: because the four kinds genuinely point at different things, and a
    #: column per kind would be four columns three of which are always null.
    subject: dict = Field(default_factory=dict)
    from_value: str | None = None
    to_value: str | None = None
    #: The subject's own words, so a filing prompt can say what kind of note a
    #: rule is about. Clipped by `learning.record`.
    excerpt: str = ""


@router.post("/corrections", status_code=201)
def add_correction(body: CorrectionBody, session: Session = Depends(get_session)) -> dict:
    """Record one correction."""
    try:
        item = learning.record(
            session,
            kind=body.kind,
            subject=body.subject,
            from_value=body.from_value,
            to_value=body.to_value,
            excerpt=body.excerpt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"id": item.id, "kind": item.kind, "subject": item.subject}


#: One page of corrections. This table only ever grows: every refile, every
#: dismissed suggestion and every card sent away adds a row, for the life of
#: the notebook, so "every correction" is the one answer this route must not
#: keep giving.
CORRECTIONS_PAGE_SIZE = 200


@router.get("/corrections")
def list_corrections(
    response: Response,
    kind: str | None = None,
    limit: int = Query(default=CORRECTIONS_PAGE_SIZE, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    """One page of corrections, oldest first, optionally of one kind."""
    rows = learning.corrections(session, kind=kind)
    response.headers["X-Total-Count"] = str(len(rows))
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "subject": item.subject,
            "from": item.from_value,
            "to": item.to_value,
            "excerpt": item.excerpt,
        }
        for item in rows[offset : offset + limit]
    ]
