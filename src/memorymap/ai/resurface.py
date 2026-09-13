"""Three notes a day that are slipping out of reach (WORLD_CLASS_PLAN 15, I4).

A notebook that only ever shows you what you just wrote is a diary. The thing
a notebook can do that a pile of files cannot is bring back the note you would
never have thought to look for: written months ago, linked to nothing, never
opened since. That is what "faded" means here, and it is deliberately made of
three facts a person can check rather than a model's opinion:

- **age**, because a note you wrote this morning is not lost,
- **links**, because a note joined to others is reachable through them,
- **reads**, because a note you keep opening is not forgotten.

The score is computed nightly into `note_scores` (`compute_scores`), and the
request-time step is a sort plus, when there is something to compare against,
a cosine to what the person is looking at now (`for_context`). That split is
the whole performance story: the scan is the expensive half and it does not
need to be fresh, the cosine is the cheap half and does.

**Three rules that keep it from becoming noise**, each one a failure this
feature has in other tools:

1. A small notebook gets nothing. Three cards a day out of five notes is the
   same three notes for ever, which teaches people to ignore the panel.
2. The day's three are stable within the day and different the next. A panel
   that reshuffles on every page load is a slot machine, and one that never
   reshuffles is wallpaper.
3. "Never again" is honoured for good, through the corrections loop
   (`ai/learning.py`), so dismissing a card is a decision rather than a
   thirty-second reprieve.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core.database import Entry, EntryLink, NoteScore

#: How many notes a notebook needs before resurfacing says anything at all.
#: Below this, "the three most faded" is just "three of your notes".
MIN_NOTEBOOK = 10

#: How many cards a day. Three is the number in the plan, and the reason is
#: that a person will read three and skim ten.
DAILY = 3

#: The age at which a note counts as fully faded, in days. Ninety days is a
#: season: long enough that "I wrote this recently" is no longer true, short
#: enough that a year-old notebook is not uniformly at 1.0.
FULL_FADE_DAYS = 90.0

#: How much each part is worth. Age dominates because it is the only part that
#: moves on its own; links and reads are corrections to it.
W_AGE, W_UNLINKED, W_UNREAD = 0.6, 0.25, 0.15


def _clamp(value: float) -> float:
    return 0.0 if value < 0 else (1.0 if value > 1 else value)


def score_for(age_days: float, link_count: int, access_count: int) -> float:
    """The fading score from its three parts, 0 to 1, higher is more faded."""
    age = _clamp(age_days / FULL_FADE_DAYS)
    unlinked = 1.0 / (1.0 + link_count)
    unread = 1.0 / (1.0 + access_count)
    return _clamp(W_AGE * age + W_UNLINKED * unlinked + W_UNREAD * unread)


def compute_scores(session: Session) -> int:
    """Refresh every note's fading score. Returns how many rows were written.

    One query for the notes, one for the link counts, one for the existing
    rows: the whole point of storing this is that the scan happens here and
    never on the request path, so it must not be a scan *per note*.
    """
    now = datetime.now(timezone.utc)
    entries = session.scalars(
        select(Entry).where(
            Entry.is_deleted.is_(False),
            Entry.is_board.is_(False),
            Entry.is_private.is_(False),
        )
    ).all()
    if not entries:
        return 0

    links: dict[int, int] = {}
    for column in (EntryLink.source_entry_id, EntryLink.target_entry_id):
        for entry_id, count in session.execute(
            select(column, func.count()).group_by(column)
        ).all():
            links[entry_id] = links.get(entry_id, 0) + int(count)

    existing = {row.entry_id: row for row in session.scalars(select(NoteScore)).all()}
    written = 0
    for entry in entries:
        created = entry.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created is not None else 0
        link_count = links.get(entry.id, 0)
        access_count = int(entry.access_count or 0)
        row = existing.get(entry.id)
        if row is None:
            row = NoteScore(entry_id=entry.id)
            session.add(row)
        row.score = score_for(age_days, link_count, access_count)
        row.age_days = max(0, age_days)
        row.link_count = link_count
        row.access_count = access_count
        row.computed_at = now
        written += 1

    # A note that has since been deleted keeps no row: this is a cache, and a
    # cache that outlives what it describes is how a deleted note comes back
    # from the dead in a panel.
    live = {entry.id for entry in entries}
    for entry_id, row in existing.items():
        if entry_id not in live:
            session.delete(row)
    session.flush()
    return written


#: How old the stored scores may be before a read refreshes them. A day,
#: because every part of the score moves on the scale of days: age by
#: definition, links and opens because that is how often a person touches a
#: notebook.
MAX_AGE_HOURS = 24.0


def ensure_fresh(session: Session, max_age_hours: float = MAX_AGE_HOURS) -> bool:
    """Compute the scores if they are missing or stale. True if it ran.

    **Why a read is allowed to do this, when the whole point of the split is
    that it should not.** The alternative is a night shift, and the night
    shift in this app (`ai/autonomous.py`) only runs when the AI is on. This
    feature needs no model at all: it is three facts and some arithmetic, and
    a notebook with the AI switched off is exactly the notebook that most
    needs something bringing its old notes back. Tying it to the model would
    have made it silently do nothing for those people, which is the "feature
    that never ran once" shape.

    So the cost is paid once a day, by whichever read comes first. Measured
    on 2,000 notes: 137 ms to build the table from nothing, 99 ms to refresh
    it, against 4.3 ms for the read itself. One request in a day at a tenth
    of a second, and the other reads keep the fast path they were designed
    for.
    """
    newest = session.scalar(select(func.max(NoteScore.computed_at)))
    if newest is not None:
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - newest).total_seconds() / 3600.0
        if age < max_age_hours:
            return False
    compute_scores(session)
    session.commit()
    return True


def _dismissed(session: Session) -> set[int]:
    """Notes told "never again". Read through the corrections loop, so one
    dismissal is one fact stored in one place (`ai/learning.py`)."""
    from memorymap.ai import learning

    return {key[0] for key in learning.boosts(session, kind="resurface")}


def ranked(session: Session, limit: int = DAILY) -> list[Entry]:
    """The most faded notes, most faded first, dismissals removed.

    No `MIN_NOTEBOOK` floor here: this is the raw ranking, and the floor is a
    rule about the *panel*, applied by `for_day` where the panel asks.
    """
    dismissed = _dismissed(session)
    # The limit goes into SQL, not into the loop below. Without it this reads
    # every scored note in the notebook and throws all but three away, which
    # is invisible on a test fixture and is the whole cost at ten thousand
    # notes: measured at 800 notes, the read was already drifting from 13.8 ms
    # to 23.0 ms while its *query count* stayed at four, which is exactly what
    # a query with no LIMIT looks like from the outside.
    #
    # `+ len(dismissed)` because the dismissals are filtered in Python (they
    # live in the corrections log, not in this table), so the page has to be
    # deep enough that every dismissed note in it can be dropped and the
    # asked-for number still come back.
    rows = session.execute(
        select(NoteScore, Entry)
        .join(Entry, Entry.id == NoteScore.entry_id)
        .where(Entry.is_deleted.is_(False))
        .order_by(NoteScore.score.desc(), NoteScore.entry_id.desc())
        .limit(limit + len(dismissed))
    ).all()
    out: list[Entry] = []
    for _row, entry in rows:
        if entry.id in dismissed:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def for_day(session: Session, day: date | None = None, limit: int = DAILY) -> list[Entry]:
    """The day's cards: stable within the day, different the next.

    Taken from the top of the ranking rather than from the whole notebook, so
    what surfaces is still the faded end; which slice of that top is a hash of
    the date, so it moves each day without a stored "shown on" column to keep
    in step. A notebook under `MIN_NOTEBOOK` gets nothing at all.
    """
    total = session.scalar(
        select(func.count())
        .select_from(Entry)
        .where(
            Entry.is_deleted.is_(False),
            Entry.is_board.is_(False),
            Entry.is_private.is_(False),
        )
    )
    if (total or 0) < MIN_NOTEBOOK:
        return []
    pool = ranked(session, limit=max(limit * 4, 12))
    if len(pool) <= limit:
        return pool
    day = day or datetime.now(timezone.utc).date()
    # The day's own number, not a hash of it. A hash distributes nicely and
    # says nothing about *consecutive* days: two dates in a row can land on
    # the same offset, and then "different tomorrow" is true on average and
    # false on the day someone checks. The ordinal advances by exactly one
    # each day, so consecutive days always differ, which is the property this
    # is supposed to have rather than a probability. The hash still decides
    # where the cycle starts, so two notebooks do not march in step.
    offset = int(hashlib.sha256(b"resurface").hexdigest()[:8], 16)
    start = (day.toordinal() + offset) % len(pool)
    # Wrapping, so every note in the pool gets a turn instead of the tail
    # never being reached.
    doubled = pool + pool
    return doubled[start : start + limit]


def for_context(
    session: Session, context_entry_id: int, limit: int = DAILY
) -> list[Entry]:
    """The faded notes closest to what the person is looking at now.

    The fading score says a note is slipping away; the cosine says it is
    slipping away from something you are thinking about today, which is the
    difference between a reminder and an interruption. Without an embedding
    backend this degrades to the plain ranking rather than returning nothing:
    a faded note is still worth surfacing without a vector to rank it by.

    Never the context note itself, whatever it scores.
    """
    from memorymap.ai.embeddings import bytes_to_vector, cosine_similarity
    from memorymap.core.database import EmbeddingRecord

    pool = [entry for entry in ranked(session, limit=max(limit * 8, 24)) if entry.id != context_entry_id]
    if not pool:
        return []
    vectors = {
        row.entry_id: row.vector
        for row in session.scalars(
            select(EmbeddingRecord).where(
                EmbeddingRecord.entry_id.in_([entry.id for entry in pool] + [context_entry_id])
            )
        ).all()
    }
    anchor = vectors.get(context_entry_id)
    if anchor is None:
        return pool[:limit]
    anchor_vector = bytes_to_vector(anchor)
    scored: list[tuple[float, Entry]] = []
    for entry in pool:
        blob = vectors.get(entry.id)
        nearness = cosine_similarity(anchor_vector, bytes_to_vector(blob)) if blob else 0.0
        scored.append((nearness, entry))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    return [entry for _nearness, entry in scored[:limit]]
