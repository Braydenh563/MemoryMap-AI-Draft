"""Find notes that say the same thing twice.

A notebook you actually use accumulates near-duplicates: the same thought
captured on two days, a note re-typed because the first one was hard to find,
a shopping list rewritten rather than edited.

Detection here is deliberately arithmetic rather than AI, normalise the text
and compare word overlap. That means it works with nothing running, it's
instant, and it's explainable: the score is a percentage of shared words, not
a black box. The AI's job comes later and is optional, at merge time, where
judgement genuinely helps.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import Entry

# Below this, two notes are merely on the same topic rather than duplicates.
# Chosen high on purpose: a false positive invites someone to merge two notes
# that only looked alike, and that loses writing.
DEFAULT_THRESHOLD = 0.72

# Comparing more than this many notes pairwise gets slow, and a notebook that
# large wants a different approach than a scan anyway.
MAX_SCAN = 500


def normalise(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _word_set(text: str) -> set[str]:
    return {word for word in normalise(text).split() if len(word) > 1}


def similarity(a: str, b: str) -> float:
    """0..1 overlap between two notes, by shared words (Jaccard).

    Identical text scores 1.0. Word order is ignored on purpose: "milk and
    eggs" and "eggs and milk" are the same shopping list.
    """
    if normalise(a) == normalise(b):
        return 1.0
    left, right = _word_set(a), _word_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def find_duplicates(
    session: Session, threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    """Groups of notes that look like the same note, most similar first.

    Private notes are excluded: reporting one as a duplicate would reveal both
    that it exists and roughly what it says.
    """
    entries = list(
        session.scalars(
            select(Entry)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
            )
            .order_by(Entry.id)
            .limit(MAX_SCAN)
        )
    )

    # Union-find, so three notes that each match the others become one group of
    # three rather than three overlapping pairs the user has to reconcile.
    parent = {entry.id: entry.id for entry in entries}

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    best: dict[tuple[int, int], float] = {}
    for i, first in enumerate(entries):
        for second in entries[i + 1 :]:
            score = similarity(first.content, second.content)
            if score >= threshold:
                best[(first.id, second.id)] = score
                parent[root(first.id)] = root(second.id)

    grouped: dict[int, list[Entry]] = {}
    for entry in entries:
        grouped.setdefault(root(entry.id), []).append(entry)

    groups = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        ids = {m.id for m in members}
        scores = [s for (a, b), s in best.items() if a in ids and b in ids]
        groups.append(
            {
                "similarity": round(max(scores), 3) if scores else threshold,
                "entries": [
                    {
                        "id": m.id,
                        "content": m.content,
                        "created_at": m.created_at.isoformat(),
                        "tags": m.tags,
                    }
                    for m in sorted(members, key=lambda m: m.id)
                ],
            }
        )
    groups.sort(key=lambda g: -g["similarity"])
    return groups
