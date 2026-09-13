"""What "yesterday" meant, on the day it was written (roadmap §10A).

Notes are full of relative time, "tomorrow", "last week", "in three days" , 
and every one of those phrases is correct when it is typed and misleading
forever afterwards. Nothing recorded what they resolved to, so a note saying
"the deadline is next Friday" is unanswerable a month later, and the AI
answering questions about it can only guess.

This resolves them at capture and stores the answer alongside the note.

**Deliberately deterministic.** `ai/reminder_parser.py` asks the model to do
the same job for a reminder, and that is the right trade there: one reminder,
typed on purpose, worth a model call. This runs on *every* note that is saved,
including when Ollama is off, the app's second design principle, so it is
regular expressions and arithmetic, and nothing here can make a save fail or
slow.

The reference clock is the user's, not the server's. "Tonight" resolved
against UTC on a machine in Brisbane is the wrong night, which is exactly the
bug the reminder columns were fixed for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# How exact the phrase was. A note saying "last week" did not mean a day, and
# showing it as one would be inventing precision the writer did not use.
DAY = "day"
WEEK = "week"
MONTH = "month"
YEAR = "year"

MAX_MENTIONS = 8  # a note is not a calendar; this only guards runaway text

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "couple of": 2, "few": 3,
}

_UNIT_DAYS = {"day": 1, "week": 7, "fortnight": 14}


@dataclass(frozen=True)
class Mention:
    """One phrase, and the date it meant when it was written."""

    phrase: str
    at: date
    precision: str


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _add_months(day: date, months: int) -> date:
    """Month arithmetic without a dependency. The 31st of a short month lands
    on its last day rather than overflowing into the next one."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    last = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(day.day, last))


def _count(word: str) -> int | None:
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word)


# Every pattern gets the match and "today" and returns (date, precision).
# Order matters: the longer phrase has to be tried before the shorter one it
# contains, or "the day after tomorrow" resolves as "tomorrow".
_RULES: list[tuple[str, object]] = [
    (r"the day after tomorrow", lambda m, t: (t + timedelta(days=2), DAY)),
    (r"the day before yesterday", lambda m, t: (t - timedelta(days=2), DAY)),
    (r"tomorrow(?: morning| afternoon| evening| night)?",
     lambda m, t: (t + timedelta(days=1), DAY)),
    (r"yesterday(?: morning| afternoon| evening)?",
     lambda m, t: (t - timedelta(days=1), DAY)),
    (r"last night", lambda m, t: (t - timedelta(days=1), DAY)),
    (r"(?:today|tonight|this (?:morning|afternoon|evening))",
     lambda m, t: (t, DAY)),
    (r"last week", lambda m, t: (_monday(t) - timedelta(days=7), WEEK)),
    (r"next week", lambda m, t: (_monday(t) + timedelta(days=7), WEEK)),
    (r"this week", lambda m, t: (_monday(t), WEEK)),
    (r"last month", lambda m, t: (_add_months(t, -1), MONTH)),
    (r"next month", lambda m, t: (_add_months(t, 1), MONTH)),
    (r"this month", lambda m, t: (t, MONTH)),
    (r"last year", lambda m, t: (date(t.year - 1, t.month, 1), YEAR)),
    (r"next year", lambda m, t: (date(t.year + 1, t.month, 1), YEAR)),
    # "in three days", "in 2 weeks", "in a fortnight"
    (r"in (\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
     r"eleven|twelve|few|couple of) (day|week|fortnight)s?",
     lambda m, t: _offset(m, t, forward=True)),
    (r"in (\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
     r"eleven|twelve|few|couple of) months?",
     lambda m, t: (_add_months(t, _count(m.group(1)) or 0), MONTH)),
    # "three days ago", "a week ago"
    (r"(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
     r"twelve|few|couple of) (day|week|fortnight)s? ago",
     lambda m, t: _offset(m, t, forward=False)),
    (r"(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
     r"twelve|few|couple of) months? ago",
     lambda m, t: (_add_months(t, -(_count(m.group(1)) or 0)), MONTH)),
    # "last friday", "next tues", "this monday", "on wednesday"
    # The lambda is NOT redundant, though CodeQL's `py/unnecessary-lambda`
    # says so (#47) and the suggested `_weekday` is a NameError: this table is
    # built at import time and `_weekday` is defined below it. The lambda
    # defers the lookup to call time, which is the only reason the module
    # imports at all. Checked by replacing it and watching the suite fail.
    (r"(last|next|this|on) (" + "|".join(_WEEKDAYS) + r")\b",
     lambda m, t: _weekday(m, t)),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), resolve) for pattern, resolve in _RULES]


def _offset(match: re.Match, today: date, forward: bool):
    count = _count(match.group(1))
    if count is None:
        return None
    days = count * _UNIT_DAYS[match.group(2).lower()]
    return (today + timedelta(days=days if forward else -days), DAY)


def _weekday(match: re.Match, today: date):
    """"Next Friday" is the Friday of next week; "on Friday" is the coming one.

    Both readings exist in ordinary speech and neither is wrong. The rule is
    written down here so the answer is at least consistent, and the phrase is
    always shown next to the date so a reader can disagree with it.
    """
    which, name = match.group(1).lower(), match.group(2).lower()
    target = _WEEKDAYS[name]
    ahead = (target - today.weekday()) % 7
    if which == "last":
        behind = (today.weekday() - target) % 7 or 7
        return (today - timedelta(days=behind), DAY)
    if which == "next":
        return (_monday(today) + timedelta(days=7 + target), DAY)
    return (today + timedelta(days=ahead), DAY)  # "this"/"on": the coming one


def find(text: str, now: datetime | date) -> list[Mention]:
    """Every temporal phrase in `text`, resolved against `now`.

    Overlapping matches are resolved in favour of the earliest, longest one,
    so "the day after tomorrow" is never also counted as "tomorrow".
    """
    today = now.date() if isinstance(now, datetime) else now
    claimed: list[tuple[int, int]] = []
    found: list[tuple[int, Mention]] = []
    for pattern, resolve in _COMPILED:
        for match in pattern.finditer(text or ""):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in claimed):
                continue
            try:
                answer = resolve(match, today)
            except (ValueError, KeyError, TypeError):
                continue  # a phrase we thought we understood and didn't
            if answer is None:
                continue
            at, precision = answer
            claimed.append(span)
            found.append((span[0], Mention(match.group(0), at, precision)))
    found.sort(key=lambda pair: pair[0])
    return [mention for _, mention in found[:MAX_MENTIONS]]
