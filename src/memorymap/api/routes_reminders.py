"""Reminders: create, list, tick off, delete.

Local-only: the browser fires the notification while the app is open;
nothing runs in the cloud.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typing import Literal

from memorymap.core import deps
from memorymap.core.database import Entry, Reminder, utcnow
from memorymap.core.deps import get_session
from memorymap.entry.manager import log_action, readable_content

router = APIRouter(prefix="/reminders", tags=["reminders"])

Priority = Literal["low", "normal", "high"]
Recurring = Literal["none", "daily", "weekly", "monthly"]


class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime
    entry_id: int | None = None
    priority: Priority = "normal"
    recurring: Recurring = "none"


class MagicAddBody(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    # Minutes east of UTC, as the browser reports it. "Tomorrow evening" has to
    # be resolved against the user's clock, not the server's: without this the
    # model was told the time in UTC and every relative time landed hours out.
    tz_offset_minutes: int | None = Field(default=None, ge=-840, le=840)


class ReminderUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    due_at: datetime | None = None
    done: bool | None = None
    priority: Priority | None = None
    recurring: Recurring | None = None


def _reject_if_in_the_past(due_at: datetime) -> None:
    """A reminder due before now will never usefully fire, it's either an
    accidental past date (a slipped year, an AM/PM mix-up in the picker) or
    a "reminder" that isn't reminding of anything upcoming. A minute of
    slack covers submit latency and clock skew, not a real mistake.
    """
    now = datetime.now(timezone.utc)
    compare_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
    if compare_at < now - timedelta(minutes=1):
        raise HTTPException(
            status_code=422,
            detail="That reminder's due time is in the past, pick a time that hasn't happened yet.",
        )


def _to_out(session: Session, reminder: Reminder) -> dict:
    entry_preview = None
    if reminder.entry_id is not None:
        entry = session.get(Entry, reminder.entry_id)
        if entry is not None and not entry.is_deleted:
            # `readable_content`, not the raw column: a private note's
            # `content` is ciphertext at rest, and this preview showed that
            # ciphertext blob (or, once unlocked, otherwise skipped the
            # locked-vault placeholder every other preview surface uses), 
            # the same class of bug as the digest's, just local to this UI
            # rather than sent to a model.
            content = readable_content(entry)
            entry_preview = content if len(content) <= 60 else content[:59] + "…"
    return {
        "id": reminder.id,
        "text": reminder.text,
        "due_at": reminder.due_at.isoformat(),
        "done": reminder.done,
        "entry_id": reminder.entry_id,
        "entry_preview": entry_preview,
        "priority": reminder.priority,
        "recurring": reminder.recurring,
    }


def _existing(session: Session, reminder_id: int) -> Reminder:
    return deps.get_or_404(session, Reminder, reminder_id, "Reminder not found")


#: A page of the reminder list, not a ceiling on how many reminders may
#: exist: `X-Total-Count` says the real size and `offset` reaches the rest,
#: the same shape `GET /entries` uses. 200 because the Reminders tab groups
#: what it gets by due date and a person with more than two hundred live
#: reminders is not reading past the first screen of them; at the measured
#: row cost (about 180 bytes) a page is about 35 KB rather than a response
#: that grows with the table forever (300 rows measured at 52.5 KB).
REMINDERS_PAGE_SIZE = 200
REMINDERS_PAGE_SIZE_MAX = 1000


@router.get("")
def list_reminders(
    response: Response,
    limit: int = Query(default=REMINDERS_PAGE_SIZE, ge=1, le=REMINDERS_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    """A page of reminders, soonest first; the frontend groups them.

    `limit`/`offset` page the list and `X-Total-Count` gives the real size
    regardless of the page, so a caller knows when it has everything. The id
    is the tiebreaker on `due_at` so two reminders due at the same minute
    cannot swap places between one page and the next, which is how a paged
    list silently drops a row.
    """
    total = session.scalar(select(func.count(Reminder.id))) or 0
    rows = session.scalars(
        select(Reminder).order_by(Reminder.due_at, Reminder.id).limit(limit).offset(offset)
    )
    response.headers["X-Total-Count"] = str(total)
    return [_to_out(session, r) for r in rows]


@router.post("", status_code=201)
def create_reminder(body: ReminderCreate, session: Session = Depends(get_session)) -> dict:
    _reject_if_in_the_past(body.due_at)
    if body.entry_id is not None:
        deps.get_or_404(session, Entry, body.entry_id, "Entry not found")
    reminder = Reminder(
        text=body.text,
        due_at=body.due_at,
        entry_id=body.entry_id,
        priority=body.priority,
        recurring=body.recurring,
    )
    session.add(reminder)
    session.flush()
    log_action(session, "created", "reminder", reminder.id, body.text[:80])
    session.commit()
    return _to_out(session, reminder)


@router.post("/parse", status_code=201)
def magic_add_reminder(body: MagicAddBody, session: Session = Depends(get_session)) -> dict:
    """Magic Add: parse natural language into a reminder and create it.

    Needs the local model running; returns 503 otherwise so the UI can point
    the user at the manual form.
    """
    from memorymap.ai import reminder_parser

    offset = timedelta(minutes=body.tz_offset_minutes or 0)
    # The user's clock, labelled with the offset it actually has.
    #
    # This line is the bug behind "play league of legends in half an hour" being
    # scheduled for 10am the next day. It used to be `utcnow() + offset`, which
    # produces an aware datetime TAGGED UTC that really holds local wall-clock, 
    # so the model was told "now is 2026-08-01T23:30:00+00:00" when the +00:00
    # was a fiction. A model that then answered with an offset of its own (the
    # natural thing to do, having been given one) landed in the `else` branch
    # below, was trusted, and skipped the correction, putting the reminder out
    # by exactly the user's UTC offset. For the reporter, ten hours: half an
    # hour away became 10am tomorrow.
    #
    # A real tzinfo makes the frame true, so both branches below are now
    # answering the same question.
    user_zone = timezone(offset)
    local_now = utcnow().astimezone(user_zone)

    ollama = deps.get_ollama()
    # A phrase the rules can read needs no model at all, and refusing to add
    # "remind me in 20 minutes" because Ollama is off would break design
    # principle 2 for a request that needs nothing but arithmetic.
    parsed = reminder_parser.parse_relative(body.text, local_now)
    if parsed is None:
        if not ollama.is_running():
            raise HTTPException(
                status_code=503,
                detail=(
                    "The local AI isn't running, and I couldn't read a time from "
                    "that. Try “in 20 minutes”, or use the form."
                ),
            )
        parsed = reminder_parser.parse_reminder(
            body.text, ollama, deps.get_model_manager(), local_now
        )

    due_at = parsed["due_at"]
    if due_at.tzinfo is None:
        # Answered in the user's wall-clock time, as asked.
        due_at = due_at.replace(tzinfo=user_zone)
    due_at = due_at.astimezone(timezone.utc)
    reminder = Reminder(
        text=parsed["text"], due_at=due_at, priority=parsed["priority"]
    )
    session.add(reminder)
    session.flush()
    log_action(session, "created", "reminder", reminder.id, parsed["text"][:80])
    session.commit()
    return _to_out(session, reminder)


@router.put("/{reminder_id}")
def update_reminder(
    reminder_id: int, body: ReminderUpdate, session: Session = Depends(get_session)
) -> dict:
    reminder = _existing(session, reminder_id)
    if body.text is not None:
        reminder.text = body.text
    if body.due_at is not None:
        _reject_if_in_the_past(body.due_at)
        reminder.due_at = body.due_at
    if body.priority is not None:
        reminder.priority = body.priority
    if body.recurring is not None:
        reminder.recurring = body.recurring
    if body.done is not None and body.done != reminder.done:
        reminder.done = body.done
        log_action(
            session,
            "edited",
            "reminder",
            reminder.id,
            "done" if body.done else "reopened",
        )
    session.commit()
    return _to_out(session, reminder)


@router.delete("/{reminder_id}")
def delete_reminder(reminder_id: int, session: Session = Depends(get_session)) -> dict:
    reminder = _existing(session, reminder_id)
    log_action(session, "deleted", "reminder", reminder.id)
    session.delete(reminder)
    session.commit()
    return {"deleted": True}
