"""What is the user actually asking for? (chat intent routing)

Every chat message used to take the same path: retrieve five notes, then tell
the model to answer "using ONLY the notes provided". For a real question that
is exactly right. For "hey" it is not: the model dutifully answers a greeting
with a summary of your notebook, which is why saying hello felt like being
handed a filing cabinet.

So messages are sorted first, and only the ones that are actually about the
notebook go through retrieval:

- ``smalltalk``, greetings, thanks, goodbyes. Answer as an assistant would.
- ``about_app``, "what can you do?". Answer from what the app can do.
- ``notes``, everything else: retrieve, and ground the answer in notes.

The classifier is deliberately a heuristic rather than a model call. It runs on
every message, so it has to be instant and predictable; a local model would add
latency to every turn and could itself misfire. Anything it isn't sure about
falls through to ``notes``, which is the behaviour that was there before, the
worst case is the old behaviour, never something worse.
"""

from __future__ import annotations

import re

SMALLTALK = "smalltalk"
ABOUT_APP = "about_app"
NOTES = "notes"

# Bare greetings and pleasantries. Matched whole so "hi" routes here but
# "hidden costs of the new plan" does not.
_SMALLTALK_PATTERNS = (
    r"h(?:i|ey|ello|iya)",
    r"yo|sup|howdy",
    r"good (?:morning|afternoon|evening|day)",
    r"how(?:'?s| is| are)(?: it going| things| you|you)?",
    r"what'?s up",
    r"thanks?(?: you| a lot| so much)?|ta|cheers|nice one",
    r"(?:ok(?:ay)?|cool|great|awesome|nice|lol|haha|sure|right|yep|yes|no|nope)",
    r"(?:good ?)?(?:bye|night)|see (?:ya|you)|later|cya",
    r"you'?re welcome|no worries|np",
    r"sorry|my bad",
    r"who are you|what(?:'?s| is) your name",
    r"are you (?:there|awake|ok|okay|alive)",
)

# "What can you do?", questions about the assistant rather than the notebook.
_ABOUT_APP_PATTERNS = (
    r"what can (?:you|this|the app|memorymap) do",
    r"what (?:are|do) (?:you|your) (?:capable of|abilities|features|tools)",
    r"what (?:tools|features|skills|commands) (?:do|can) you (?:have|use|offer)",
    r"what are you able to do",
    r"how (?:do|does) (?:this|the app|memorymap|you) work",
    r"(?:show|list|tell) me (?:your|the|what) (?:tools|features|commands|skills)",
    r"what (?:should|can) i ask",
    r"help me get started|how do i (?:start|use this)",
    r"what are you(?: for)?",
)

# Words that mean the message really is about the notebook, even when it is
# short or opens with a greeting. These win over the smalltalk patterns.
_NOTE_WORDS = re.compile(
    r"\b(note|notes|entry|entries|wrote|written|saved|capture[ds]?|remember(?:ed)?|"
    r"remind(?:er|ers)?|tag|tags|categor(?:y|ies)|notebook|search|find|summar(?:y|ise|ize)|"
    r"digest|todo|task|list|graph|journal|log)\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation and filler, collapse whitespace."""
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"[^\w\s']", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Leading filler ("so hey", "um hi") shouldn't stop a greeting matching.
    return re.sub(r"^(?:so|um+|uh+|well|hmm+|ah+|oh)\s+", "", cleaned)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    """True if the whole message is one of these phrases, allowing a
    trailing name or address ("hey there", "hi mate")."""
    tail = r"(?:\s+(?:there|mate|buddy|friend|again|assistant|memorymap|bot))*"
    return any(re.fullmatch(rf"{pattern}{tail}", text) for pattern in patterns)


def classify(message: str) -> str:
    """Route one chat message. Falls back to ``notes`` whenever unsure."""
    text = _normalise(message)
    if not text:
        return SMALLTALK

    # "hey, what did I write about pasta" is a question wearing a greeting.
    if _NOTE_WORDS.search(text):
        return NOTES

    if _matches_any(text, _ABOUT_APP_PATTERNS) or any(
        re.search(pattern, text) for pattern in _ABOUT_APP_PATTERNS
    ):
        return ABOUT_APP

    if _matches_any(text, _SMALLTALK_PATTERNS):
        return SMALLTALK

    return NOTES


def needs_retrieval(intent: str) -> bool:
    """Only note questions are worth searching the notebook for."""
    return intent == NOTES
