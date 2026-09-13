"""Where the notebook disagrees with itself.

**This is the thing `LINK_TYPES` was built for and nobody ever built.** Its
own comment in `core/database.py` says so:

    `contradicts` is the one worth having built this for: a notebook that can
    show you where you disagreed with yourself is not something an embedding
    similarity score can ever produce, however well tuned.

That was true and it stayed unbuilt. `link_type` is writable only through
`POST /entries/{id}/links`, a person, by hand, choosing "Contradicts" from a
dropdown. So the notebook could *record* a disagreement it was told about, and
could never *find* one.

Everything else this app knows about connection answers "these are about the
same thing": embedding similarity, shared words, `[[wiki links]]`, threads.
None of them can tell agreement from disagreement, two notes that flatly
contradict each other are, to a vector, maximally similar. That gap is the
whole point of this module.

**Why this app can do it and a cloud notebook cannot.** Reading every
plausible pair of notes with a language model is an unbounded number of
tokens against a corpus that is entirely the user's private writing. Metered,
that is a bill nobody would pay to be told they changed their mind; sent to a
someone else's server, it is the most sensitive text a person owns. Here
inference is free and stays on the machine, so the notebook can afford to
actually read itself.

## What it looks for, and what it deliberately ignores

A *tension* is two notes that make claims which cannot both be right. Not two
notes on the same topic, not one adding nuance to another, not a plan that
changed because the facts changed.

Two rules keep this from becoming noise, and both matter more than the model
prompt does:

1. **Candidates come from pairs that are already about the same thing.**
   Contradiction is only possible between notes that share a subject, so this
   never scans all pairs, it takes the ones the existing similarity pass
   already produced. That bounds the work and removes the obvious false
   positives before a model is asked anything.
2. **Time is part of the finding, not decoration.** The interesting case is
   almost always a change of mind: written in March, contradicted in
   September. Two notes written the same afternoon that seem to disagree are
   usually one thought being refined. `MIN_GAP_DAYS` is what encodes that.

## Nothing is written without a person saying yes

Same policy as the auto-linker (`routes_entries.link_suggestions`) and for a
stronger reason: telling someone they contradicted themselves when they did
not is worse than telling them nothing. This module only ever *proposes*.
Accepting a tension is what creates the `EntryLink` with
`link_type="contradicts"`, an existing column, so there is no migration
here and the graph, the traversal weighting and Trace all understand the
result the moment it exists.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from memorymap.ai import model_manager as model_manager_module
from memorymap.ai import ollama_client as ollama_client_module
from memorymap.core.database import Entry

logger = logging.getLogger("memorymap.ai.tensions")

#: Two notes written within a few days of each other that appear to disagree
#: are usually one idea being worked out, not a change of position. A week is
#: long enough that the second note is a considered revisit rather than the
#: same sitting, and short enough that a fast-moving project still surfaces.
MIN_GAP_DAYS = 7

#: How much of each note the model is shown. Long enough to carry the claim,
#: short enough that a pair costs one small prompt, this runs over many
#: pairs, and the budget discipline in `ai/agent.py` applies here too.
EXCERPT_CHARS = 700

#: A hard ceiling on model calls per pass, so a large notebook cannot turn one
#: background pass into an hours-long job. The pass is resumable by nature:
#: pairs already judged are skipped by the caller.
MAX_PAIRS_PER_PASS = 40

#: The model must open with this token for a genuine disagreement. Asking for
#: a single leading word rather than JSON is deliberate, the small local
#: models this app targets are markedly better at "say YES or NO first" than
#: at emitting well-formed JSON, and `ai/extractor.py` already carries a
#: `_extract_json_object` helper written because they get that wrong.
_YES = "yes"
_NO = "no"

#: An "explanation" that only restates the verdict. Shown beside the two notes
#: it is accusing, one of these tells the reader nothing they could check, so
#: it is treated as no finding rather than displayed.
#:
#: A pattern rather than a phrase list, because the phrase list this started
#: as missed "basically they just conflict": the subject and the verb are the
#: fixed part and anything can sit between them. The same guard `ai/links.py`
#: needs for link reasons, for the same reason, a small model told to justify
#: itself will sometimes assert the conclusion instead.
VAGUE_EXPLANATION = re.compile(
    r"\b(?:they|these|the(?:\s+two)?\s+notes)\b[^.]{0,24}?"
    r"\b(?:disagree|contradict|conflict|inconsistent|different\s+things)\b",
    re.IGNORECASE,
)


@dataclass
class Tension:
    """One proposed disagreement, before anybody has agreed it is real."""

    earlier_id: int
    later_id: int
    #: One line, in the model's words, naming what the two notes disagree
    #: about. Shown to the person deciding, so it has to say something
    #: specific, and `_clean_explanation` rejects it when it does not.
    explanation: str
    earlier_excerpt: str
    later_excerpt: str
    earlier_at: str | None
    later_at: str | None
    gap_days: int


_SYSTEM = (
    "You compare two notes from one person's private notebook and decide "
    "whether they CONTRADICT each other.\n\n"
    "A contradiction means both notes make claims that cannot both be true, "
    "or state opposite positions, decisions or preferences about the same "
    "thing. The person has changed their mind, or written something "
    "inconsistent, and would want to know.\n\n"
    "These are NOT contradictions, and you must answer NO for them:\n"
    "- two notes about the same topic that simply say different things\n"
    "- one note adding detail, nuance or a later step to the other\n"
    "- a plan that changed because the circumstances changed, where both "
    "notes are true of their own moment\n"
    "- different opinions about different things\n"
    "- one note being vague and the other specific\n\n"
    "Answer NO unless you can name the specific claim each note makes and "
    "say why they cannot both hold. Most pairs are NOT contradictions; NO is "
    "the right answer far more often than YES.\n\n"
    "Reply on ONE line, starting with YES or NO. If YES, follow it with a "
    "dash and one short sentence naming what they disagree about, for "
    "example: 'YES - the first says the launch is in May, the second says "
    "it slipped to August'. If NO, reply with only the word NO."
)


def _excerpt(text: str) -> str:
    """A single-paragraph excerpt of a note, trimmed for the prompt."""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if len(flat) <= EXCERPT_CHARS:
        return flat
    return flat[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"


def _clean_explanation(reply: str) -> str | None:
    """The sentence after YES, or None if the reply was NO or unusable.

    Strict on purpose. A model that answers "YES" with nothing after it has
    not made a case, and a tension with no stated reason is exactly the
    unfalsifiable accusation this feature must never produce, so an empty or
    too-short explanation is treated as a NO rather than shown with a blank
    line where the reasoning should be.
    """
    text = (reply or "").strip()
    if not text:
        return None
    head = text.lower()
    if head.startswith(_NO):
        return None
    if not head.startswith(_YES):
        # Neither word. The instruction was explicit, so a reply that ignores
        # it is not evidence of anything, treated as no finding.
        return None
    rest = text[len(_YES) :].lstrip()
    rest = rest.lstrip("-–, :,. ").strip()
    rest = rest.strip("\"'").strip()
    # "YES" alone, or a stub like "they disagree", says nothing a person can
    # check against the two notes shown beside it. Both shapes are rejected:
    # a length floor for the empty case, and a vague-phrase list for the
    # answer that restates the question instead of answering it.
    #
    # The same guard `ai/links.py` needs for link reasons, for the same
    # reason: a small model told to justify itself will sometimes assert the
    # conclusion instead. Its `VAGUE_PHRASES` covers "related"; these cover
    # the disagreement wording it does not.
    if len(rest) < 12:
        return None
    if VAGUE_EXPLANATION.search(rest):
        return None
    return rest


def _gap_days(earlier: datetime | None, later: datetime | None) -> int | None:
    if earlier is None or later is None:
        return None
    return abs((later - earlier).days)


def compare_pair(
    earlier: Entry,
    later: Entry,
    models: model_manager_module.ModelManager,
    ollama: ollama_client_module.OllamaClient,
) -> Tension | None:
    """Ask the model whether these two notes contradict each other.

    Returns None for "no contradiction", for an unusable reply, and for any
    model failure: a pass over many pairs must not be taken down by one bad
    round trip, and "we could not tell" and "they agree" lead to the same
    place here: nothing is shown.
    """
    earlier_text = _excerpt(earlier.content)
    later_text = _excerpt(later.content)
    if not earlier_text or not later_text:
        return None

    prompt = (
        f"Note A (written {_stamp(earlier.created_at)}):\n{earlier_text}\n\n"
        f"Note B (written later, {_stamp(later.created_at)}):\n{later_text}\n\n"
        "Do these contradict each other?"
    )
    try:
        reply = ollama.chat(
            models.utility_model(),
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception:  # noqa: BLE001  # one pair failing must not end the pass
        logger.debug("tension check failed for %s/%s", earlier.id, later.id, exc_info=True)
        return None

    explanation = _clean_explanation((reply or {}).get("content", ""))
    if explanation is None:
        return None

    return Tension(
        earlier_id=earlier.id,
        later_id=later.id,
        explanation=explanation,
        earlier_excerpt=_excerpt(earlier.content)[:280],
        later_excerpt=_excerpt(later.content)[:280],
        earlier_at=_stamp(earlier.created_at),
        later_at=_stamp(later.created_at),
        gap_days=_gap_days(earlier.created_at, later.created_at) or 0,
    )


def _stamp(when: datetime | None) -> str | None:
    return when.date().isoformat() if when else None


def order_by_time(a: Entry, b: Entry) -> tuple[Entry, Entry] | None:
    """`(earlier, later)`, or None if the pair should not be considered.

    Filters here rather than in the caller because "which is earlier" and
    "is this pair worth a model call" are the same question: a pair with no
    timestamps has no story to tell about a change of mind, and a pair from
    the same few days is one thought being worked out (see `MIN_GAP_DAYS`).
    """
    if a.created_at is None or b.created_at is None:
        return None
    earlier, later = (a, b) if a.created_at <= b.created_at else (b, a)
    gap = _gap_days(earlier.created_at, later.created_at)
    if gap is None or gap < MIN_GAP_DAYS:
        return None
    return earlier, later
