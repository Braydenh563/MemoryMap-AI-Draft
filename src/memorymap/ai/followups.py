"""What to ask next, after an answer.

A chat that ends every turn with a blank box asks the reader to do the work of
knowing what else the notebook could tell them. The empty-state chips
(`/chat/suggestions`) already solved that for the *first* question and then
stopped: the moment a real message exists they hide, and from there on you are
on your own.

This is the same idea for the turn you just read: two or three short questions
the answer itself opens up, offered as chips under it.

Three rules shape the whole module, and all three exist because a bad follow-up
is worse than none:

- **It never blocks the answer.** Generating these is a second model call. It
  runs after the turn is on screen and is allowed to fail silently, a request
  that returns ``[]`` costs the reader nothing, while one that delays the
  answer costs them the thing they were waiting for.
- **It uses the utility model, not the chat model.** Writing three short
  questions is exactly the kind of quick background job
  ``ModelManager.utility_model`` exists for; tying up a 30B chat model to do it
  would make the next real question wait.
- **Anything the model returns is scrubbed hard.** Small local models answer
  this prompt with numbered lists, preambles ("Here are three questions:"),
  markdown bullets and trailing commentary about as often as they answer it
  cleanly. Parsing is therefore forgiving about shape and strict about the
  result: a line has to look like a question a person would actually type, or
  it is dropped.
"""

from __future__ import annotations

import re

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError

#: How many to offer. Two or three chips fit on one line under an answer at
#: most widths; four wrap and start looking like the app is nagging.
MAX_FOLLOWUPS = 3

#: Longer than this is not a chip, it is a paragraph, and a model that
#: produced one has misunderstood the instruction rather than written a long
#: question.
MAX_LENGTH = 90

#: Below this a "question" is a fragment ("Why?", "More?") that says nothing
#: about the notebook.
MIN_LENGTH = 12

FOLLOWUP_PROMPT = (
    "The user asked a question about their personal notebook and got the "
    "answer below. Suggest short follow-up questions they might ask next.\n"
    "- Write ONLY the questions, one per line. No numbering, no bullets, no "
    "preamble, no commentary.\n"
    "- At most three.\n"
    "- Each must be a question the notebook could plausibly answer, about "
    "their own notes, not about the world.\n"
    "- Each under twelve words, phrased the way the user would type it.\n"
    "- Do not repeat the question they just asked."
)

#: Leading list markers of every shape a small model reaches for: "1.", "1)",
#: "-", "*", "•", "Q:". Stripped rather than rejected, because the question
#: after them is usually fine.
_LIST_MARKER = re.compile(r"^\s*(?:[-*•–]|\d+[.)]|[Qq]\d*[.:)])\s*")

#: A line that is introducing the list rather than being part of it.
_PREAMBLE = re.compile(
    r"^(?:here|sure|of course|certainly|these|below|some|follow[- ]?up)\b", re.I
)

#: A model that was told "one per line" often puts the whole list on one line
#: anyway: ``What did I note? 2) When is it due?``. Splitting only on newlines
#: turned that into a single chip with "? 2)" sitting in the middle of it, 
#: visible debris, and the reason a turn could come back with one nonsense
#: suggestion instead of three good ones. Split after a question mark when real
#: text follows, and at an inline list marker.
_INLINE_SPLIT = re.compile(r"(?<=\?)\s+(?=\S)|\s+(?:\d+[.)]|[-*•])\s+")

#: Small models answer this prompt with imperatives about as often as with
#: questions: "Show my notes on the deadline", "Summarise the budget thread".
#: Those are perfectly good chips, and requiring a question mark dropped every
#: one of them, which is most of why a turn sometimes offered nothing at all.
#: The verb list is the guard that a bare question mark used to provide: a
#: heading or a sign-off does not open with one of these.
_IMPERATIVE = re.compile(
    r"^(?:show|list|find|search|summari[sz]e|compare|tell me|remind me|"
    r"pull up|open|draft|explain|describe)\b",
    re.I,
)


def _clean(line: str) -> str:
    """One raw line into a usable chip, or "" if it is not one.

    Deliberately conservative: this runs on output from a model that was asked
    for bare questions and may have produced anything, and a chip that reads
    like debris is worse for trust than three chips instead of four.
    """
    text = _LIST_MARKER.sub("", line).strip()
    # Models like to wrap each item in quotes or bold it. Neither belongs in a
    # chip, and both are trivially removable without touching the words.
    text = text.strip("\"'`*_ ").strip()
    if not text or _PREAMBLE.match(text):
        return ""
    # Question-shaped or request-shaped. Without one of these, headings
    # ("Follow-up questions"), sign-offs and stray commentary all pass, and a
    # chip that is neither does not belong under an answer.
    if not (text.endswith("?") or _IMPERATIVE.match(text)):
        return ""
    if not (MIN_LENGTH <= len(text) <= MAX_LENGTH):
        return ""
    return text


def parse_followups(reply: str, asked: str = "") -> list[str]:
    """Model output into at most ``MAX_FOLLOWUPS`` clean questions.

    Split out from ``suggest_followups`` so the scrubbing: the part that
    actually decides what a person sees, is testable without a transport.
    ``asked`` is the question that was just answered; a model that echoes it
    back is offering the reader a loop, so it is dropped.
    """
    already = (asked or "").strip().casefold().rstrip("?")
    out: list[str] = []
    seen: set[str] = set()
    for line in (reply or "").splitlines():
        for candidate in _INLINE_SPLIT.split(line):
            cleaned = _clean(candidate)
            if not cleaned:
                continue
            key = cleaned.casefold().rstrip("?")
            if key == already or key in seen:
                continue
            seen.add(key)
            out.append(cleaned)
            if len(out) == MAX_FOLLOWUPS:
                return out
    return out


def suggest_followups(
    question: str,
    answer: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
) -> list[str]:
    """Follow-up questions for one answered turn, or ``[]``.

    ``[]`` on every failure path, offline, transport error, an unusable
    reply: because there is no honest error state for this. A row of chips
    that says "couldn't think of anything" is worse than the row simply not
    being there, which is what a reader who never noticed the feature sees
    anyway.
    """
    question = (question or "").strip()
    answer = (answer or "").strip()
    if not question or not answer or not ollama.is_running():
        return []
    try:
        reply = ollama.chat(
            model_manager.utility_model(),
            [
                {"role": "system", "content": FOLLOWUP_PROMPT},
                # Clipped: the follow-ups come from what the answer opened up,
                # and the first part of a long answer carries that. Sending an
                # unbounded answer back would make this call cost more than the
                # turn it is decorating.
                {
                    "role": "user",
                    "content": f"QUESTION: {question[:500]}\n\nANSWER:\n{answer[:2000]}",
                },
            ],
        )
    except OllamaError:
        return []
    return parse_followups(reply.get("content") or "", question)
