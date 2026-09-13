"""Browsing back through the Ask box (Notes tab): every notes-only question
it has answered, not just the last five as a chip row.

Turns are written by routes_chat.py's `chat_stream` (the only caller of the
Ask box) once a real answer has landed; nothing here writes a turn. This
file is read, search, pin and delete only.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core import deps
from memorymap.core.database import LIKE_ESCAPE, AskTurn, Entry, like_escape
from memorymap.core.deps import get_session

router = APIRouter(prefix="/ask-history", tags=["ask-history"])

#: A row's answer, cut to a preview length for the list view, the full text
#: is only fetched when a turn is actually opened (GET /{turn_id}).
PREVIEW_CHARS = 220


def _summary(turn: AskTurn) -> dict:
    answer = turn.answer or ""
    return {
        "id": turn.id,
        "question": turn.question,
        "answer_preview": answer[:PREVIEW_CHARS] + ("…" if len(answer) > PREVIEW_CHARS else ""),
        "search_mode": turn.search_mode,
        "when_phrase": turn.when_phrase,
        "result_count": len(json.loads(turn.raw_result_ids or "[]")),
        "pinned": bool(turn.pinned),
        "created_at": turn.created_at.isoformat(),
    }


@router.get("")
def list_ask_history(
    q: str = "",
    pinned_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    """Newest first, pinned first among ties, same ordering Conversation
    uses for the Chat tab's own saved list, for the same reason: the thread
    you keep coming back to shouldn't sink under a week of one-offs."""
    query = select(AskTurn)
    if pinned_only:
        query = query.where(AskTurn.pinned == True)  # noqa: E712
    term = q.strip()
    if term:
        like = f"%{like_escape(term)}%"
        query = query.where(
            AskTurn.question.ilike(like, escape=LIKE_ESCAPE)
            | AskTurn.answer.ilike(like, escape=LIKE_ESCAPE)
        )
    ordered = query.order_by(AskTurn.pinned.desc(), AskTurn.created_at.desc())
    total = session.scalar(select(func.count()).select_from(ordered.subquery()))
    rows = session.scalars(ordered.limit(limit).offset(offset)).all()
    return {
        "turns": [_summary(t) for t in rows],
        "total": total or 0,
        "offset": offset,
        "limit": limit,
    }


@router.get("/stats")
def ask_history_stats(session: Session = Depends(get_session)) -> dict:
    """A one-line header for the panel: how much is here to browse."""
    total = session.scalar(select(func.count(AskTurn.id))) or 0
    pinned = session.scalar(select(func.count(AskTurn.id)).where(AskTurn.pinned == True)) or 0  # noqa: E712
    return {"total": total, "pinned": pinned}


@router.get("/{turn_id}")
def get_ask_turn(turn_id: int, session: Session = Depends(get_session)) -> dict:
    """The full turn, with its notes hydrated to their current state.

    A note deleted or made private since this question was asked is dropped
    rather than shown: same rule `_attached_notes` (routes_chat.py) applies
    when a note is attached live, kept here for the same reason: a browsed-
    back turn should not resurrect binned content or leak a note that has
    since been marked private.
    """
    from memorymap.api.routes_entries import _to_out_bulk  # avoids a route-module cycle

    turn = deps.get_or_404(session, AskTurn, turn_id, "No such question in your history")
    ids = json.loads(turn.raw_result_ids or "[]")
    entries = []
    if ids:
        found = {
            e.id: e
            for e in session.scalars(select(Entry).where(Entry.id.in_(ids)))
            if not e.is_deleted and not e.is_private
        }
        # Preserve the order the answer originally showed them in.
        entries = [found[i] for i in ids if i in found]
    return {
        **_summary(turn),
        "answer": turn.answer,
        "raw_results": [r.model_dump(mode="json") for r in _to_out_bulk(session, entries)],
        "omitted_results": len(ids) - len(entries),
        # Same badge data the live answer had, older rows saved before this
        # field existed fall back to "no explanation" rather than an error.
        "match_info": json.loads(turn.match_info or "{}"),
        "connected_ids": json.loads(turn.connected_ids or "[]"),
    }


@router.put("/{turn_id}/pin")
def pin_ask_turn(turn_id: int, pinned: bool, session: Session = Depends(get_session)) -> dict:
    turn = deps.get_or_404(session, AskTurn, turn_id, "No such question in your history")
    turn.pinned = pinned
    session.commit()
    return _summary(turn)


@router.delete("/{turn_id}")
def delete_ask_turn(turn_id: int, session: Session = Depends(get_session)) -> dict:
    turn = deps.get_or_404(session, AskTurn, turn_id, "No such question in your history")
    session.delete(turn)
    session.commit()
    return {"deleted": True}


@router.delete("")
def clear_ask_history(
    keep_pinned: bool = True, session: Session = Depends(get_session)
) -> dict:
    """Wipe the browsable history. Pinned turns survive by default, the
    same asymmetry a "clear all" next to a pin button always needs, or
    pinning something means nothing the next time this button is pressed."""
    query = select(AskTurn)
    if keep_pinned:
        query = query.where(AskTurn.pinned == False)  # noqa: E712
    rows = session.scalars(query).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return {"deleted": len(rows)}
