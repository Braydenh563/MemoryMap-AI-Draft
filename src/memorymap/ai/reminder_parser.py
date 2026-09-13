"""Turn a natural-language reminder into structured fields (Magic Add).

Reuses the local utility model, the same one the digest/janitor use, so
nothing leaves the machine. Parsing is best-effort: if the model is unavailable
or returns something unusable, callers get a sensible fallback (the raw text,
due tomorrow at 9am, normal priority) rather than an error.

The `now` handed in is the user's local wall-clock time, not the server's UTC:
"this evening" is meaningless against the wrong clock, and getting it wrong put
every relative reminder hours out.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

_PRIORITIES = ("low", "normal", "high")

# --- clock-level phrases, resolved without asking a model ------------------------
#
# Reported: "play league of legends in half an hour" was scheduled for 10am the
# next day. Two things were wrong and only one of them was the phrase.
#
# The bigger one was a timezone frame (see routes_reminders), which put the
# answer out by exactly the user's UTC offset. The other is that this module
# asked a 3B model to do arithmetic that a regex does perfectly: "in half an
# hour" is not a natural-language problem, it is a lookup, and delegating it
# meant the answer varied with which model happened to be installed.
#
# So the common shapes are resolved here first, and the model is the fallback
# rather than the first resort. That also makes Magic Add work with Ollama
# switched off, which matches the app's second design principle, the thing
# should still work when the AI doesn't.
#
# entry/timewords.py is deliberately NOT reused: it resolves to a DATE with a
# day/week/month precision, because it answers "what is this note about". A
# reminder needs a time of day, which that vocabulary cannot express.

_UNIT_SECONDS = {
    "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
}

_WORD_COUNTS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "fortyfive": 45, "sixty": 60, "ninety": 90,
    # The article-carrying forms are spelled out rather than handled with an
    # optional `(?:a\s+)?` prefix: with the alternation sorted longest-first,
    # "a couple of" is tried before the bare "a", which is what stops "in a
    # couple of hours" being read as "in a …" and then failing on "couple".
    "couple of": 2, "couple": 2, "few": 3,
    "a couple of": 2, "a couple": 2, "a few": 3,
}

# "in half an hour" and "in an hour and a half" are the two that a plain
# number-and-unit pattern cannot see, and both are ordinary English.
_FRACTIONS: list[tuple[str, timedelta]] = [
    (r"in\s+(?:half\s+an\s+hour|a\s+half\s+hour|30\s*mins?)\b", timedelta(minutes=30)),
    (r"in\s+(?:an?\s+)?hour\s+and\s+a\s+half\b", timedelta(minutes=90)),
    (r"in\s+(?:a\s+)?quarter\s+of\s+an\s+hour\b", timedelta(minutes=15)),
    (r"in\s+a\s+(?:little\s+)?while\b", timedelta(minutes=30)),
]

_COUNT_WORDS = "|".join(
    sorted((re.escape(w) for w in _WORD_COUNTS), key=len, reverse=True)
)
_IN_PATTERN = re.compile(
    rf"in\s+(\d{{1,4}}|{_COUNT_WORDS})\s*({'|'.join(sorted(_UNIT_SECONDS, key=len, reverse=True))})\b",
    re.IGNORECASE,
)
_FRACTION_PATTERNS = [(re.compile(p, re.IGNORECASE), d) for p, d in _FRACTIONS]


def relative_delta(text: str) -> tuple[timedelta, str] | None:
    """(how far ahead, the phrase that said so), or None if nothing matched.

    Only handles "in …" forms on purpose. "at 8pm" and "tomorrow morning" are
    a different problem: they name a wall-clock target rather than an offset,
    so they need the user's date, and getting those subtly wrong is how this
    bug happened in the first place. The model still handles them, now inside
    a timezone frame that is actually true.
    """
    for pattern, delta in _FRACTION_PATTERNS:
        found = pattern.search(text)
        if found:
            return delta, found.group(0)
    found = _IN_PATTERN.search(text)
    if not found:
        return None
    raw_count, unit = found.group(1).lower(), found.group(2).lower()
    count = _WORD_COUNTS.get(raw_count)
    if count is None:
        try:
            count = int(raw_count)
        except ValueError:
            return None
    if count <= 0:
        return None
    seconds = count * _UNIT_SECONDS[unit]
    # A year out is not a reminder, it is a typo with consequences.
    if seconds > 366 * 86400:
        return None
    return timedelta(seconds=seconds), found.group(0)


def _tidy(text: str, phrase: str) -> str:
    """The reminder text with the time phrase taken out of it.

    "play league of legends in half an hour" is a reminder to play league of
    legends; leaving "in half an hour" in the text would have it still saying
    so when it fires.
    """
    without = text.replace(phrase, " ")
    without = re.sub(r"\s+", " ", without).strip(" ,.;:-")
    if not without:
        return text.strip() or "Reminder"
    return without[0].upper() + without[1:]


def parse_relative(text: str, now: datetime) -> dict | None:
    """A reminder from an "in …" phrase, with no model involved."""
    found = relative_delta(text)
    if found is None:
        return None
    delta, phrase = found
    return {
        "text": _tidy(text, phrase)[:500],
        "due_at": now + delta,
        "priority": "normal",
        "source": "rule",
    }

_SYSTEM = (
    "You convert a short natural-language reminder into JSON. "
    "The current date and time is {now}. "
    'Reply with ONLY a JSON object of the form '
    '{{"text": string, "due_at": ISO-8601 date-time, "priority": one of '
    '"low"/"normal"/"high"}}. '
    "That time is the user's own local clock, answer on the same clock, and "
    "resolve relative times (tomorrow, this evening, next week, in 2 hours) "
    "against it. If a time of day is given but no date, choose the next time "
    "that is still in the future. If no time at all is given, use 9am the "
    "following morning. If no priority is given, use normal. Keep the reminder "
    "text short and imperative."
)


def _fallback(text: str, now: datetime) -> dict:
    due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {"text": text.strip() or "Reminder", "due_at": due, "priority": "normal"}


def _extract_json(content: str) -> dict | None:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(content[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_reminder(text: str, ollama, model_manager, now: datetime) -> dict:
    """Return {text, due_at: datetime, priority} parsed from natural language.

    An "in …" phrase is resolved here, before the model is asked. It is
    arithmetic, the answer does not vary with which model is installed, and it
    is the shape people actually type into Magic Add.
    """
    ruled = parse_relative(text, now)
    if ruled is not None:
        return ruled

    messages = [
        {"role": "system", "content": _SYSTEM.format(now=now.isoformat())},
        {"role": "user", "content": text},
    ]
    try:
        reply = ollama.chat(model_manager.utility_model(), messages)
    except Exception:  # noqa: BLE001  # any model failure degrades gracefully
        return _fallback(text, now)

    parsed = _extract_json(reply.get("content", "") if isinstance(reply, dict) else "")
    if not parsed:
        return _fallback(text, now)

    result = _fallback(text, now)
    if isinstance(parsed.get("text"), str) and parsed["text"].strip():
        result["text"] = parsed["text"].strip()[:500]
    priority = str(parsed.get("priority", "")).lower()
    if priority in _PRIORITIES:
        result["priority"] = priority
    due_raw = parsed.get("due_at")
    if isinstance(due_raw, str):
        try:
            result["due_at"] = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
        except ValueError:
            pass  # keep the fallback due time
    return result
