"""Bookmarks: saved links to somewhere outside the notebook, create, list,
update, delete. Same shape as reminders.py; nothing here needs the AI.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core import deps
from memorymap.core.database import Bookmark, DocumentBookmark, EntryBookmark
from memorymap.core.deps import get_session
from memorymap.entry.manager import log_action

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


class BookmarkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)
    group_name: str = Field(default="", max_length=120)


class BookmarkUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    pinned: bool | None = None
    group_name: str | None = Field(default=None, max_length=120)


def _normalise_url(raw: str) -> str:
    """"google.com" is what most people actually type into a bookmark box, 
    requiring a scheme up front would reject the common case for no benefit,
    since a bare host is unambiguous: it's never meant as a relative path."""
    url = raw.strip()
    if not url:
        raise HTTPException(status_code=422, detail="A bookmark needs a URL")
    if not urlparse(url).scheme:
        url = f"https://{url}"
    return url


def _to_out(bookmark: Bookmark, duplicate_of: int | None = None) -> dict:
    out = {
        "id": bookmark.id,
        "url": bookmark.url,
        "title": bookmark.title,
        "note": bookmark.note,
        "pinned": bookmark.pinned,
        "group_name": bookmark.group_name,
        "created_at": bookmark.created_at.isoformat(),
    }
    if duplicate_of is not None:
        # Warn, don't block (asked for directly): re-saving a link you
        # already have is a normal thing to do by accident, not a mistake
        # worth refusing outright: so this still creates the row and just
        # tells the frontend which earlier bookmark shares its URL, for a
        # toast rather than a hard stop.
        out["duplicate_of"] = duplicate_of
    return out


def _existing(session: Session, bookmark_id: int) -> Bookmark:
    return deps.get_or_404(session, Bookmark, bookmark_id, "Bookmark not found")


#: One page of saved links. A notebook's bookmarks grow with use and nothing
#: ever trimmed this list, so the response grew with the table for ever.
BOOKMARKS_PAGE_SIZE = 200


@router.get("")
def list_bookmarks(
    response: Response,
    limit: int = Query(default=BOOKMARKS_PAGE_SIZE, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Pinned first, then newest first within each group, one page at a time.

    The id is a tiebreaker in the ordering, not decoration: two links saved in
    the same second could otherwise swap places between two pages and hide one
    of them, which is the bug a paged list without a stable sort always has.
    """
    total = session.scalar(select(func.count(Bookmark.id))) or 0
    rows = session.scalars(
        select(Bookmark)
        .order_by(Bookmark.pinned.desc(), Bookmark.created_at.desc(), Bookmark.id.desc())
        .limit(limit)
        .offset(offset)
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_out(b) for b in rows]


@router.post("", status_code=201)
def create_bookmark(body: BookmarkCreate, session: Session = Depends(get_session)) -> dict:
    url = _normalise_url(body.url)
    existing = session.scalar(select(Bookmark).where(Bookmark.url == url))
    bookmark = Bookmark(
        url=url,
        title=body.title.strip(),
        note=body.note.strip(),
        group_name=body.group_name.strip(),
    )
    session.add(bookmark)
    session.flush()
    log_action(session, "created", "bookmark", bookmark.id, bookmark.title or bookmark.url)
    session.commit()
    return _to_out(bookmark, duplicate_of=existing.id if existing else None)


@router.put("/{bookmark_id}")
def update_bookmark(
    bookmark_id: int, body: BookmarkUpdate, session: Session = Depends(get_session)
) -> dict:
    bookmark = _existing(session, bookmark_id)
    if body.url is not None:
        bookmark.url = _normalise_url(body.url)
    if body.title is not None:
        bookmark.title = body.title.strip()
    if body.note is not None:
        bookmark.note = body.note.strip()
    if body.pinned is not None:
        bookmark.pinned = body.pinned
    if body.group_name is not None:
        bookmark.group_name = body.group_name.strip()
    session.commit()
    return _to_out(bookmark)


@router.delete("/{bookmark_id}")
def delete_bookmark(bookmark_id: int, session: Session = Depends(get_session)) -> dict:
    """Delete a saved link, and the two join tables that attach it.

    `EntryBookmark` and `DocumentBookmark` hold real foreign keys with no
    cascade, and `PRAGMA foreign_keys=ON` is set, so a bookmark attached to a
    note or a document could not be deleted at all: the delete raised
    `FOREIGN KEY constraint failed`, answered 500, and the link stayed in the
    list. Attaching it is what made it permanent, which is the same shape
    that made a document with a note on it undeletable, one table over.

    The join row goes, not the thing at the other end of it: a note does not
    disappear because a link saved on it did.
    """
    bookmark = _existing(session, bookmark_id)
    log_action(session, "deleted", "bookmark", bookmark.id)
    session.execute(sa_delete(EntryBookmark).where(EntryBookmark.bookmark_id == bookmark.id))
    session.execute(sa_delete(DocumentBookmark).where(DocumentBookmark.bookmark_id == bookmark.id))
    session.delete(bookmark)
    session.commit()
    return {"deleted": True}
