"""Which tools a request plausibly needs, decided by reading the words.

The same shape as `entry/timewords.py`, and for the same reasons: regular
expressions and arithmetic, no model call, deterministic, and testable line by
line. A model call to decide what to send a model is a round trip that costs
more than it saves, and a rule you can read is a rule you can argue with.

**This advises; it never decides.** Nothing here can stop the model calling a
tool. `tools.CORE_TOOLS` is always offered whatever this returns, a request
this cannot read gets the whole toolbox rather than a guess, and a tool left
out because no cue fired still runs if the model asks for it. What it changes
is only what is *put in front of* the model, which on a small window is the
difference between the notes fitting and not.

Why it replaced plain substring matching
----------------------------------------
The rule used to be ``cue in text`` over the lowercased message. Measured
against ten ordinary questions, seven picked up tools that had nothing to do
with what was asked:

    "what did I write about my vintage camera?"   -> the tag tools
    "what are the advantages of this approach?"   -> the tag tools
    "notes about blinking lights"                 -> the link/graph tools
    "did I file anything under profile settings?" -> the category tools
    "notes about my drafting table"               -> the document tools

``tag`` inside *vintage* and *advantages*, ``link`` inside *blinking*,
``file `` inside *profile *, ``draft`` inside *drafting*. Each one dragged
three to five schemas, one to two thousand characters, into the prompt of a
model that may only have four thousand tokens in total, and worse, put a
delete_tag in front of a model that was asked about a camera.

Matching on word boundaries removes that entire class. The rest of this module
is the two things that became possible once matching was reliable enough to
build on: scoring, so the *best* groups can be kept when not all of them fit,
and separating a question about a capability from a request to use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: A cue that is a whole phrase ("mind map", "path between") is worth more than
#: a single word: phrases are almost never accidental, where a lone word can be
#: about anything. This is what lets "whiteboard" outrank a bare "board" when
#: both fire and only one group fits.
PHRASE_WEIGHT = 1.0
WORD_WEIGHT = 0.6

#: One cue is enough. The score **ranks**; it does not gate.
#:
#: This started life at 1.0, a threshold a single word could not clear, and
#: that was a straightforward mistake, caught by running it: "tag all my gym
#: notes as fitness" scored 0.6 and was offered no tag tools at all, and "tidy
#: up my notebook" stopped counting as a broad request. Trading a false
#: positive for a false negative is a bad trade here and always will be: an
#: unnecessary schema costs a few hundred characters, while a missing one
#: costs the user the thing they asked for, and looks like the app is broken.
#:
#: The false positives this module exists to remove are removed by matching on
#: word boundaries, which is a correctness fix. Ranking is what the scores are
#: for: when not every group fits the window, take the ones the sentence
#: argued for hardest rather than the ones that sort first in the table.
SCORE_THRESHOLD = WORD_WEIGHT

#: Markers that turn a sentence into a request no matter what verb follows.
#:
#: Deliberately NOT a list of action verbs. That is what this was first, and it
#: was wrong in a way only running it showed: after stripping the question
#: opener from "how do I tag a note?", what is left is "tag a note", so a verb
#: list marked the sentence an instruction on the strength of the very word
#: naming the capability being asked about, and every question about tagging,
#: linking or deleting was read as a request to do it. The verb after "how do
#: I" is always the capability; it can never be the signal.
#:
#: What genuinely distinguishes "what's the best way to do this, please tag
#: them all" from "how do I tag a note?" is the asking, not the verb.
_INSTRUCTION_MARKER = re.compile(
    r"\b(?:please|can you|could you|would you|i want|i'd like|i would like|"
    r"i need you|go ahead|for me|do it|do that)\b",
    re.I,
)

#: "How do I tag a note?", "what does the link tool do?", these name a
#: capability while asking *about* it. Offering the write tools for them is how
#: a small model ends up tagging something in the middle of answering a
#: question about tagging.
_ASKING_ABOUT = re.compile(
    r"^\s*(?:how (?:do|does|can|would|should) (?:i|you|it)\b"
    r"|what (?:is|are|does|do)\b"
    r"|what's\b"
    r"|why (?:do|does|is|are|can)\b"
    r"|can (?:i|you) explain\b"
    r"|explain\b"
    r"|tell me (?:about|how|what|why)\b"
    r"|is (?:there|it) (?:a |any )?(?:way|possible)\b)",
    re.I,
)


@dataclass(frozen=True)
class Focus:
    """What the words said, and why, the whole result of one reading.

    ``tools`` is the answer callers want. Everything else is the reasoning, so
    a log line can say *why* a tool was offered and a test can assert on the
    cue rather than on the outcome.
    """

    #: The tool names worth offering, or None meaning "everything", a request
    #: too broad to narrow safely.
    tools: list[str] | None
    #: (group index, score), best first. Empty when nothing scored.
    ranked: list[tuple[int, float]] = field(default_factory=list)
    #: The cue strings that actually fired, for the log.
    cues: list[str] = field(default_factory=list)
    #: True when the message was a "do something about my notebook" with no
    #: object: the case that genuinely needs the whole toolbox.
    broad: bool = False
    #: True when the message asks *about* a capability rather than for it.
    #: Callers use this to hold back the write tools, not to drop the group.
    asking_about: bool = False
    #: True when the subject had to be taken from the previous exchange.
    followed_through: bool = False

    def explain(self) -> str:
        """One line for the agent log, so "why was delete_tag offered?" is
        answerable from the log rather than by re-deriving it."""
        if self.broad:
            return "focus: broad request, offering everything"
        if self.tools is None:
            return "focus: unreadable, offering everything"
        bits = [f"{len(self.tools)} tools"]
        if self.cues:
            bits.append("cues=" + ",".join(self.cues[:6]))
        if self.asking_about:
            bits.append("asking-about (writes held back)")
        if self.followed_through:
            bits.append("subject from previous turn")
        return "focus: " + " ".join(bits)


#: Endings a cue may carry and still be the same cue. "documents" is the
#: document group; "tagging", "tagged" and "tags" are all the tag group.
#:
#: This is the half of word-boundary matching that is easy to forget, and it
#: was: the first version anchored both ends, so `\bdocument\b` did not match
#: "documents" and the question "what's in my documents about the lease?" was
#: offered no document tools at all. Substring matching got that one right by
#: accident, which is exactly why a change like this has to be run against real
#: sentences rather than reasoned about.
#:
#: Spelled out rather than `\w{0,4}`: a wildcard tail turns the three-letter
#: cues into prefixes, and "doc" would then match "doctor" and "docker". The
#: consonant-doubled forms (ged/ging, ned/ning, ...) are here because "tag",
#: "pin" and "link" all double before an ending, and those three are among the
#: most-used cues in the table.
_INFLECTION = (
    r"(?:s|es|ed|d|ing|ings|ged|ging|ned|ning|red|ring|ped|ping|ked|king)?"
)


def _compile(cues: tuple[str, ...]) -> list[tuple[re.Pattern[str], str, float]]:
    """Cue strings into anchored patterns, once, at import.

    A cue containing a space is matched as a phrase and weighted higher; a
    single word is matched on both boundaries. `re.escape` throughout, because
    these are literals from a table, not patterns, one of them is "draw.io",
    whose dot would otherwise match "drawnio" and anything else.
    """
    out = []
    for cue in cues:
        cue = cue.strip()
        if not cue:
            continue
        weight = PHRASE_WEIGHT if " " in cue else WORD_WEIGHT
        # \b does not fire next to a non-word character, so a cue that ends in
        # one ("draw.io", "o'clock") gets a lookahead instead of a boundary.
        head = r"\b" if cue[0].isalnum() else r"(?<!\w)"
        if cue[-1].isalpha():
            # A word that can be inflected. The leading \b is what does the
            # real work, it is why "tag" no longer matches "vintage", and the
            # ending only has to let the same word through in another number or
            # tense.
            tail = _INFLECTION + r"\b"
        elif cue[-1].isalnum():
            tail = r"\b"
        else:
            # "draw.io", "o'clock": \b does not fire beside a non-word
            # character, so ask for "not followed by more word" instead.
            tail = r"(?!\w)"
        out.append((re.compile(head + re.escape(cue) + tail, re.I), cue, weight))
    return out


def score_groups(
    text: str, groups: list[tuple[tuple[str, ...], tuple[str, ...]]]
) -> tuple[list[tuple[int, float]], list[str]]:
    """(ranked (index, score) pairs above the threshold, the cues that fired).

    Ranked so a caller with room for two groups can take the two that the
    sentence actually argued for, rather than the two that happen to come first
    in the table.
    """
    scored: list[tuple[int, float]] = []
    fired: list[str] = []
    for index, (_names, cues) in enumerate(groups):
        total = 0.0
        for pattern, cue, weight in _compile(cues):
            if pattern.search(text):
                total += weight
                fired.append(cue)
        if total >= SCORE_THRESHOLD:
            scored.append((index, total))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored, fired


def looks_like_a_question_about(text: str) -> bool:
    """Is this asking *about* a capability rather than asking for it?

    "How do I tag a note?" names tagging and wants an explanation. "Tag this
    note" names tagging and wants it tagged. The difference matters most on
    small models, which are the quickest to reach for a tool simply because it
    was in front of them.

    An imperative anywhere in the sentence wins: "what's the best way to do
    this: please tag them all" opens as a question and ends as an instruction.
    """
    text = (text or "").strip()
    if not text:
        return False
    if not _ASKING_ABOUT.match(text):
        return False
    # The question opener is only half of it. A sentence that also *asks* for
    # something is a request with a question-shaped preamble. Searched over the
    # whole message rather than what follows the opener: "can you explain how
    # to tag, and tag these for me" carries its marker at the end.
    return not _INSTRUCTION_MARKER.search(text)
