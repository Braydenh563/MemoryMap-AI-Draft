"""ROADMAP.md item 36: per-sentence grounding for a direct Q&A answer.

`match_info` already says which retrieved notes backed the answer as a
whole; `unsupported_claims` already checks the agent's own narrated actions
in full agentic chat; link `reason`/`reason_confidence` already grounds a
connection between two notes. None of the three says which *sentence* in a
direct Q&A answer came from which note, this is that gap, and only that
gap: scoped to the direct Q&A path (`POST /chat`, non-conversational), not
the agentic one, where `unsupported_claims` already does the related job.

Deliberately not a second LLM call (a "lightweight... pass" per the roadmap
text, and every extra model round trip is latency on the one path where the
answer is already sitting in front of someone waiting for it): scored by
shared meaningful words between a sentence and each retrieved note, the same
signal `search_manager._meaningful_terms` already uses to rank keyword
matches. A ranking is either right or a little off; a claim ledger that's
wrong is worse than none, so this only ever attaches a note when the overlap
is real enough to trust, and says nothing rather than guessing at the rest.
"""

from __future__ import annotations

import re
from collections import Counter

from memorymap.search.search_manager import _meaningful_terms

# Below this fraction of a sentence's own meaningful words being found in a
# note, the "match" is coincidence (shared stopword-adjacent filler) rather
# than the note actually backing that sentence, better to say nothing.
MIN_OVERLAP_RATIO = 0.4

# A sentence this short (a "Sure." or a lone connective) is not a claim
# worth grounding, and the odds of it "matching" every note by chance are
# too high to be useful.
MIN_SENTENCE_WORDS = 4

# The second signal, added after the owner reported an answer that named
# three notes and cited one. A model paraphrases: "you planned to carry the
# new boots up Snowdon" shares three words with a twelve-word sentence, well
# under MIN_OVERLAP_RATIO, and yet nobody reading it doubts which note it
# came from, because "boots" and "Snowdon" occur in exactly one candidate.
# So a sentence carrying at least DISTINCTIVE_MIN_TERMS words that only one
# candidate note contains is grounded to that note from DISTINCTIVE_MIN_RATIO
# up. Distinctiveness is measured against the other candidates, so with a
# single candidate every word is "distinctive" and the signal says nothing;
# the rule therefore needs two or more notes to apply at all.
DISTINCTIVE_MIN_RATIO = 0.2
DISTINCTIVE_MIN_TERMS = 2

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\d])")


def split_sentences(text: str) -> list[str]:
    """Plain sentences, code fences and bullet markers stripped least-
    invasively: split on `.!?` followed by whitespace and a capital/digit,
    which misses some abbreviations but never merges two real sentences, 
    the safer direction for a feature that would rather ground too little
    than mis-ground something."""
    if not text:
        return []
    # Skip fenced code blocks entirely, grounding a line of code against
    # note *prose* is a category error, not a claim.
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return [s.strip() for s in _SENTENCE_SPLIT.split(cleaned) if s.strip()]


def _word_set(text: str) -> set[str]:
    return set(_meaningful_terms(text))


def ground_answer_sentences(answer: str, notes: list[dict]) -> list[dict]:
    """One entry per (sentence, supporting note): `{"sentence": str,
    "note_id": int}`. Sentences with no note clearing either threshold, or
    too short to score meaningfully, are omitted: the caller (and the
    frontend badge) treats "not in this list" as "not grounded", never as
    "grounded to nothing", so omission is always safe.

    A sentence usually gets one note, the best overlap. It gets a second
    only when that note is named by its own distinctive words too ("feed the
    starter before you take the boots up Snowdon" is about both notes), never
    by vocabulary the two notes share, which is the case the single-best rule
    exists to keep honest.
    """
    if not answer or not notes:
        return []
    note_words = [(note.get("id"), _word_set(note.get("content") or "")) for note in notes]
    note_words = [(nid, words) for nid, words in note_words if nid is not None and words]
    if not note_words:
        return []
    counts = Counter(word for _, words in note_words for word in words)
    distinctive = (
        [{w for w in words if counts[w] == 1} for _, words in note_words]
        if len(note_words) >= 2
        else [set() for _ in note_words]
    )

    grounded: list[dict] = []
    for sentence in split_sentences(answer):
        sentence_words = _word_set(sentence)
        if len(sentence_words) < MIN_SENTENCE_WORDS:
            continue
        scored: list[tuple[float, int, int]] = []
        for (note_id, words), unique in zip(note_words, distinctive):
            ratio = len(sentence_words & words) / len(sentence_words)
            hits = len(sentence_words & unique)
            if ratio >= MIN_OVERLAP_RATIO or (
                ratio >= DISTINCTIVE_MIN_RATIO and hits >= DISTINCTIVE_MIN_TERMS
            ):
                scored.append((ratio, hits, note_id))
        if not scored:
            continue
        scored.sort(reverse=True)
        grounded.append({"sentence": sentence, "note_id": scored[0][2]})
        for _ratio, hits, note_id in scored[1:]:
            if hits >= DISTINCTIVE_MIN_TERMS:
                grounded.append({"sentence": sentence, "note_id": note_id})
    return grounded
