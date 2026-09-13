"""What the notebook learned from being corrected (WORLD_CLASS_PLAN 15, I7).

A correction is the record of the app getting something wrong and the person
putting it right: a note re-filed out of the category the AI chose, a
suggested link dismissed, a search result opened after a question the ranking
answered badly, a resurfacing card sent away for good. Each one is a fact
about this notebook that no model was trained on and no amount of prompting
will rediscover, so each one is written down and read back by the thing that
is about to make the same decision again.

**Where corrections are stored, and why there is no new table.** The spec
(`tests/test_learned_spec.py`) names a `corrections` table; this module keeps
them in `AuditLog`, as `action="correction"` rows, and is the layer over that.
The reason, recorded because standing order 3 says a decision is not remade:

- There is already exactly one store, and it already works. A filing
  correction has been written by `entry/manager.update_entry_with_correction`
  and read by `ai/librarian.filing_corrections` since Brief 13. A second
  table beside it would mean two places a correction can live, which is the
  shape that ends with one of them quietly going stale.
- `AuditLog` is the event log Brief 7 built up: it has the
  `ix_audit_log_entity` index, a retention rule, compaction, and a feed that
  renders it. A corrections table would need all four again.
- The spec's own header allows it: "Module and function names below are the
  contract; a session that needs a different shape changes the test in the
  same commit, with the reason." This is that reason. The *functions* are
  exactly as specified; only the storage differs.

**What a boost is.** Corrections are facts; a boost is what a pile of the
same fact adds up to. `boosts()` folds the rows into a weight per subject,
bounded at `MAX_BOOST` so fifty corrections cannot drown the signal the
ranking is supposed to be using, and `decayed()` halves a weight every
`HALF_LIFE_DAYS`, so a rule the person has stopped reasserting fades instead
of becoming permanent. Both are deliberately arithmetic rather than learned:
there is no training here, and nothing to go wrong that a person cannot see
and undo.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import LIKE_ESCAPE, AuditLog, like_escape

#: The most any pile of corrections is allowed to be worth. A boost is a nudge
#: to a ranking that already works, not a replacement for it: without a
#: ceiling, a question asked fifty times would pin one note to the top of
#: every search that shared a word with it.
MAX_BOOST = 1.0

#: How long a correction stays worth half of what it was. Thirty days is the
#: span over which "I always file these under Projects" stops being true
#: without anyone saying so, and it is the number the spec measures against.
HALF_LIFE_DAYS = 30.0

#: What one correction is worth before the ceiling and the decay. Small on
#: purpose: two of the same correction is the point at which a preference is
#: worth acting on, which is also what `centroid_excluded` reads.
PER_CORRECTION = 0.25

#: How many corrections away from a category make it wrong for notes like
#: these. Two, matching the spec, and matching the intuition: once is a
#: mistake, twice is a rule.
EXCLUDE_AFTER = 2

#: The kinds this module knows. Kept as a set so a typo in a `kind=` argument
#: is an error at the call rather than a row nothing will ever read back.
KINDS = frozenset({"refile", "open_after_ask", "dismiss_link", "dismiss_resurface"})

#: Which family of boost each kind feeds. `boosts(kind="filing")` and
#: `boosts(kind="search")` are what the spec asks for, and they are groups of
#: correction kinds rather than kinds themselves: filing learns from re-files,
#: search learns from what got opened after a question.
FAMILIES: dict[str, tuple[str, ...]] = {
    "filing": ("refile",),
    "search": ("open_after_ask",),
    "links": ("dismiss_link",),
    "resurface": ("dismiss_resurface",),
}


@dataclass(frozen=True)
class Correction:
    """One recorded correction, in the shape the spec reads it back in.

    `from_value`/`to_value` rather than `from`/`to` because `from` is a Python
    keyword; the stored payload keeps the short names, which is what
    `librarian.filing_corrections` has always read.
    """

    id: int
    kind: str
    subject: dict[str, Any]
    from_value: str | None
    to_value: str | None
    excerpt: str
    at: Any


def _payload(row: AuditLog) -> dict:
    raw = row.payload
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_correction(row: AuditLog) -> Correction:
    payload = _payload(row)
    subject = payload.get("subject")
    if not isinstance(subject, dict):
        # A row written before this module existed: `update_entry_with_correction`
        # stored the entry id on the row itself and nothing else, so the subject
        # is reconstructed rather than treated as missing. This is the whole
        # point of keeping one store: yesterday's corrections still count.
        subject = {"entry_id": row.entity_id} if row.entity_id else {}
    return Correction(
        id=row.id,
        kind=str(payload.get("kind") or "refile"),
        subject=subject,
        from_value=(payload.get("from") or None),
        to_value=(payload.get("to") or None),
        excerpt=str(payload.get("excerpt") or ""),
        at=row.created_at,
    )


def record(
    session: Session,
    *,
    kind: str,
    subject: dict[str, Any],
    from_value: str | None = None,
    to_value: str | None = None,
    excerpt: str = "",
) -> Correction:
    """Write one correction. The only writer.

    Not routed through `events.record`: a correction must never be folded into
    the write that provoked it. `entry/manager.update_entry_with_correction`
    already says why at length, and the short version is that a correction is
    a second, separately readable fact about the same moment, and folded into
    the edit it is invisible to the query that looks for it.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown correction kind {kind!r}; known: {sorted(KINDS)}")
    payload: dict[str, Any] = {"kind": kind, "subject": dict(subject)}
    if from_value is not None:
        payload["from"] = from_value
    if to_value is not None:
        payload["to"] = to_value
    if excerpt:
        payload["excerpt"] = " ".join(excerpt.split())[:200]
    row = AuditLog(
        action="correction",
        entity_type="entry",
        entity_id=subject.get("entry_id"),
        detail=f"{kind}: {from_value or ''} -> {to_value or ''}".strip(),
        payload=payload,
        actor="user",
    )
    session.add(row)
    session.flush()
    return _as_correction(row)


def corrections(session: Session, kind: str | None = None, limit: int = 500) -> list[Correction]:
    """Corrections, oldest first, optionally of one kind.

    Oldest first because every reader of these is building a history ("you
    have moved three of these"), and a history reads forwards.

    **The kind narrows the query, not the page.** It used to filter in Python
    after taking the newest `limit` rows of *every* kind, which quietly broke
    the promise this whole module exists to keep: measured, one
    `dismiss_resurface` followed by 600 refiles, and asking for the
    dismissals returned none, so a card told "never again" came back the
    moment the notebook had been filed in enough times. This table only ever
    grows, so that was a matter of time rather than of scale.

    `detail` carries the kind as its own prefix (`record` writes
    `f"{kind}: ..."`), which is what makes the narrowing possible without a
    column: SQLite has no JSON operator here. The payload stays the
    authority, so the Python check below still runs; SQL only decides which
    rows are worth reading.
    """
    query = select(AuditLog).where(AuditLog.action == "correction")
    if kind is not None:
        query = query.where(
            AuditLog.detail.like(f"{like_escape(kind)}:%", escape=LIKE_ESCAPE)
        )
    rows = session.scalars(query.order_by(AuditLog.id.desc()).limit(limit)).all()
    found = [_as_correction(row) for row in rows]
    if kind is not None:
        found = [item for item in found if item.kind == kind]
    return list(reversed(found))


def decayed(weight: float, days: float) -> float:
    """What a weight is worth `days` later. Halves every `HALF_LIFE_DAYS`."""
    return weight * math.pow(0.5, days / HALF_LIFE_DAYS)


def boosts(session: Session, kind: str) -> dict[tuple, float]:
    """The weight each subject has earned, keyed by what the reader looks up.

    `kind` here names a *family* (`filing`, `search`, `links`, `resurface`),
    because that is how a reader asks: the ranking wants "what has search
    learned", not "how many open_after_ask rows are there".

    The key shape is the family's own: filing is keyed `(from, to)` because
    the lesson is a move between two categories; search is keyed
    `(question, entry_id)` because the lesson is that one note answered one
    question; links and resurfacing are keyed by the pair or the note.
    """
    kinds = FAMILIES.get(kind)
    if not kinds:
        raise ValueError(f"unknown boost family {kind!r}; known: {sorted(FAMILIES)}")
    out: dict[tuple, float] = {}
    # **Read per kind, not once over everything.** `corrections()` takes the
    # newest 500 rows, and this used to ask for all kinds at once and then
    # keep the family's: with one dismissal followed by six hundred re-files,
    # the dismissal was outside the window and "never again" quietly expired.
    # This table only ever grows, so that was a matter of time rather than of
    # scale. Asking per kind gives each its own window, and the SQL narrows
    # before the limit rather than after it.
    items = [item for correction_kind in kinds for item in corrections(session, kind=correction_kind)]
    for item in sorted(items, key=lambda row: row.id):
        key: tuple | None = None
        if item.kind == "refile":
            key = (item.from_value or "", item.to_value or "")
        elif item.kind == "open_after_ask":
            question = str(item.subject.get("question") or "")
            entry_id = item.subject.get("entry_id")
            if question and entry_id is not None:
                key = (question, entry_id)
        elif item.kind == "dismiss_link":
            a, b = item.subject.get("a"), item.subject.get("b")
            if a is not None and b is not None:
                key = (min(a, b), max(a, b))
        elif item.kind == "dismiss_resurface":
            entry_id = item.subject.get("entry_id")
            if entry_id is not None:
                key = (entry_id,)
        if key is None:
            continue
        out[key] = min(MAX_BOOST, out.get(key, 0.0) + PER_CORRECTION)
    return out


def centroid_excluded(session: Session, category: str, text: str) -> bool:
    """Has this category been corrected away from, for notes like this one?

    The filing centroid is a similarity score and has no memory; this is the
    memory. Two moves out of a category (`EXCLUDE_AFTER`) mean the centroid
    may not choose it again for a note that reads like the ones that were
    moved, which is the specific failure the owner reported: "the model files
    work notes about a side project under Work, the user moves them to Side
    project every single time, and the next note goes back under Work".

    "Reads like" is word overlap against the corrected notes' own excerpts,
    not an embedding: the excerpts are short, the comparison has to be exact
    and explainable, and a cosine here would make a rule the person can see
    into a rule they cannot.
    """
    wanted = _words(text)
    if not wanted:
        return False
    moved_away = 0
    for item in corrections(session, kind="refile"):
        if (item.from_value or "").strip().lower() != category.strip().lower():
            continue
        excerpt = _words(item.excerpt)
        # An excerpt-less correction still counts: the older rows carry one,
        # and a correction with no words to compare is still a move out of
        # this category.
        if not excerpt or excerpt & wanted:
            moved_away += 1
    return moved_away >= EXCLUDE_AFTER


def filing_evidence(session: Session, text: str, limit: int = 5) -> list[dict]:
    """What the next filing decision about `text` should see.

    Two kinds of row, deliberately in one list: the corrections that moved
    notes like this one, and the notes already filed that read like it. A
    prompt built from only the first has rules with no examples; from only the
    second, examples with no rules.
    """
    from memorymap.entry import manager

    wanted = _words(text)
    out: list[dict] = []
    for item in corrections(session, kind="refile"):
        excerpt = _words(item.excerpt)
        if wanted and excerpt and not (excerpt & wanted):
            continue
        out.append(
            {
                "kind": "correction",
                "from": item.from_value or "",
                "to": item.to_value or "",
                "excerpt": item.excerpt,
            }
        )
        if len(out) >= limit:
            break

    from memorymap.core.database import Entry

    rows = session.scalars(
        select(Entry)
        .where(Entry.is_deleted.is_(False), Entry.is_board.is_(False))
        .order_by(Entry.id.desc())
        .limit(200)
    ).all()
    scored: list[tuple[int, Entry]] = []
    for entry in rows:
        overlap = len(_words(manager.readable_content(entry)) & wanted)
        if overlap:
            scored.append((overlap, entry))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    for _overlap, entry in scored[:limit]:
        out.append(
            {
                "kind": "neighbour",
                "entry_id": entry.id,
                "category": manager.category_name_for(session, entry),
            }
        )
    return out


#: Words too common to say two notes are about the same thing. Deliberately
#: tiny: a stop list that grows becomes a second, invisible ranking.
_STOP = frozenset(
    "the a an and or but of in on at to for with from is are was were be been "
    "it its this that these those my your our their about into over under".split()
)


def _words(text: str) -> set[str]:
    return {
        word
        for word in "".join(c.lower() if c.isalnum() else " " for c in (text or "")).split()
        if len(word) > 2 and word not in _STOP
    }
