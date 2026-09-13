"""What the user has taught the AI to remember, folded into its persona.

**This module exists because half the app was ignoring it.** The function
below used to live in `ai/agent.py` as `_persona_with_memory`, private, with
exactly one caller: `run_agent`. So a preference written through
`save_user_preference` or typed into Settings → "What it remembers" reached
the model in Request/agent mode and was silently absent from Ask, which is the
mode most questions are asked in. Nothing in the UI said so, and the setting
looked like it worked.

Prompted by the question "does the ai include those instructions??", which is
the right question and had two different answers depending on which box you
typed into. It has one now: `routes_chat` folds the stream in for the plain
librarian path, and `agent.build_agent_messages` calls the same function.

Its own module rather than `librarian.py` because both `agent` and `librarian`
need it and `agent` already imports `librarian`, putting it there and
importing it back would be the cycle CodeQL has flagged twice in this codebase.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from memorymap.ai import librarian

#: How much of the memory stream may ride along with the persona.
#:
#: `save_user_preference` lets the model write rules it will then be given back
#: on every later turn, which is a genuinely useful feature and also the one
#: shape of prompt text `agent.PROSE_BUDGET_CHARS` cannot see: that constant is
#: asserted against the *static* persona and TOOLS_GUIDE, so anything appended
#: at runtime slips past the very guard that exists to stop the system prompt
#: growing. A notebook that has been used for a year could otherwise hold
#: hundreds of these and quietly push the real question out of a 4k window.
#:
#: Newest wins when the budget is spent, a preference stated last month is
#: likelier to be current than one stated at setup.
MEMORY_STREAM_BUDGET_CHARS = 600


def persona_with_memory(session: Session, persona_prompt: str | None) -> str:
    """The persona, plus the standing preferences the user has taught the AI.

    Bounded on purpose (`MEMORY_STREAM_BUDGET_CHARS`) and newest-first: this
    text is resent on every round of every turn, and nothing downstream trims
    it, so an unbounded version is a slow leak that ends with a small model
    losing the actual question off the front of its window.

    Defensive about the query for a reason beyond tidiness, `run_agent` is
    also driven with lightweight stand-in sessions (the skill runner's, the
    test fakes'), and a notebook that predates the `user_preferences` table
    won't have one until migrations run. Losing the memory stream should cost
    the user their preferences on that turn, never the turn itself.
    """
    base = (persona_prompt or librarian.DEFAULT_PERSONA).strip()
    try:
        from sqlalchemy import select

        from memorymap.core.database import UserPreference

        rows = session.scalars(
            select(UserPreference)
            .where(UserPreference.active == True)  # noqa: E712
            .order_by(UserPreference.created_at.desc())
        ).all()
    except Exception:  # noqa: BLE001  # see the docstring: never fail the turn
        logging.getLogger("memorymap.agent").debug(
            "memory stream unavailable for this turn", exc_info=True
        )
        return base

    kept: list[str] = []
    spent = 0
    for row in rows:
        line = f"USER PREFERENCE: {(row.content or '').strip()}"
        if len(line) <= len("USER PREFERENCE: "):
            continue
        if spent + len(line) > MEMORY_STREAM_BUDGET_CHARS:
            break
        kept.append(line)
        spent += len(line) + 1
    # Oldest-first in the prompt even though newest-first won the budget, so
    # the model reads them in the order they were taught.
    return " ".join([base, *reversed(kept)]).strip()
