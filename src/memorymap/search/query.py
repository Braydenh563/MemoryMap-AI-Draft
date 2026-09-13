"""Reading the question before searching for it.

A question is not a query. *"What have I written in the last week about the
allotment?"* is three separate instructions, a time range, a subject, and a
verb that means nothing at all, and until now every word of it went straight
into an embedding and a `LIKE`. Two things went wrong with that, and both are
things a person notices immediately:

- **"in the last week" matched nothing and filtered nothing.** It is not a
  subject, so it dilutes the embedding; it is not a keyword anyone wrote in a
  note, so it drags the keyword search off course. Meanwhile the thing it
  actually meant, only show me notes from the last seven days, was never
  applied, so the answer came back full of notes from March.
- **The question words dominate a short query.** An embedding of "what did I
  write about beans" is meaningfully different from an embedding of "beans",
  and for a three-word subject the scaffolding is most of the sentence. The
  model is matching your phrasing rather than your subject.

So: lift the time range out and apply it as a filter, strip the scaffolding
before embedding, and leave everything else alone. Deliberately no model call, 
this runs on every question, and a round trip to *decide how to search* would
cost more than the search.

The time vocabulary is `entry.timewords`, reused rather than reimplemented: it
already resolves "last week", "three days ago" and "on tuesday" for note text,
and a notebook where a phrase means one thing in a note and another in a
question would be worse than one that understood neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from memorymap.entry import timewords

#: The filter keys `understand()` always returns, so every caller can index
#: the dict rather than `.get()` it. Named here rather than inline because
#: `search/engine.py` iterates the same list to decide which filters it knows
#: how to apply, and two copies of this list would drift.
FILTER_KEYS = ("tag", "kind", "space", "has", "is")


def _empty_filters() -> dict[str, list[str]]:
    return {key: [] for key in FILTER_KEYS}


@dataclass(frozen=True)
class Understood:
    """What a question turned out to be asking for."""

    #: The question with the time phrase and the scaffolding removed, what to
    #: embed and what to match words against.
    subject: str
    #: Inclusive date bounds, or None for "whenever".
    since: date | None = None
    until: date | None = None
    #: The phrase the range came from, so the UI can say *why* it filtered.
    when_phrase: str = ""
    #: True when the question was **entirely** about time ("what did I write
    #: last week?"). There is no subject to search for, so the honest answer is
    #: every note in the range rather than a similarity ranking of noise.
    time_only: bool = False
    #: True when the time word was **vague** rather than stated, "recently",
    #: "recent". Reported, and it is a real distinction rather than a nicety:
    #:
    #:   *"I have a note with a joke in it … when I go into the ask section and
    #:   say 'jokes I have saved recently', it doesn't show. Granted I did make
    #:   it 2 weeks ago but that is still kinda recent."*
    #:
    #: "Last Tuesday" is a **constraint**: the person knows when, and a note
    #: from Wednesday is not what they asked for. "Recently" is a **lean**:
    #: nobody saying it has a boundary in mind, and whatever number this file
    #: picks for it will be wrong for somebody by a day. Turning a lean into a
    #: hard filter is how a notebook tells you it has no jokes when it has two.
    #:
    #: So a soft range still orders and still labels; it just does not exclude.
    soft: bool = False
    #: The operators of WORLD_CLASS_PLAN 5.1, as `{"tag": ["work"], …}`.
    #: Keys: `tag`, `kind`, `space`, `has`, `is`. Always present, always a
    #: list, empty when the query used no operators, so a caller can read
    #: `u.filters["tag"]` without guarding first. `before:`/`after:` are not
    #: in here: they mean the same thing as a time phrase and go to
    #: `since`/`until`, or a caller would have to apply dates two ways.
    filters: dict[str, list[str]] = field(default_factory=_empty_filters)
    #: Quoted runs, `"exact phrase"`, in the order typed. The words stay in
    #: `subject` as well: the phrase is a *requirement* on top of the words,
    #: not a replacement for them, and the embedding still wants the text.
    phrases: list[str] = field(default_factory=list)
    #: Words after a leading `-`. A hit containing any of these is dropped,
    #: which is the whole of what the operator promises.
    excluded: list[str] = field(default_factory=list)

    @property
    def has_range(self) -> bool:
        return self.since is not None or self.until is not None

    @property
    def has_operators(self) -> bool:
        return (
            any(self.filters.values())
            or bool(self.phrases)
            or bool(self.excluded)
        )


# Phrases that mean "a stretch ending now" rather than a single day. `timewords`
# resolves "last week" to one date, the Monday of the previous week, which is
# right for a note that says "I'll do it last week" and wrong for a question,
# where the person means the whole stretch. So ranges are recognised here, and
# anything not in this list falls through to `timewords` and becomes a single
# day (widened by its own precision below).
#
# Ordered longest-first: "in the last couple of weeks" has to be tried before
# "the last week" or the shorter phrase eats the longer one's meaning.
_RANGE_RULES: list[tuple[str, object]] = [
    (
        r"(?:in|over|during|from|within)?\s*(?:the\s+)?(?:last|past|previous)\s+"
        r"(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|few|couple of)\s+(day|week|fortnight|month|year)s?",
        "back",
    ),
    (r"(?:in|over|during)?\s*(?:the\s+)?(?:last|past)\s+(week)\b", "back"),
    (r"(?:in|over|during)?\s*(?:the\s+)?(?:last|past)\s+(month)\b", "back"),
    (r"(?:in|over|during)?\s*(?:the\s+)?(?:last|past)\s+(year)\b", "back"),
    (r"\btoday\b", "today"),
    (r"\byesterday\b", "yesterday"),
    (r"\bthis\s+week\b", "this_week"),
    (r"\bthis\s+month\b", "this_month"),
    (r"\bthis\s+year\b", "this_year"),
    (r"\brecent(?:ly)?\b", "recent"),
]

_COMPILED_RANGES = [(re.compile(p, re.IGNORECASE), kind) for p, kind in _RANGE_RULES]

_UNIT_DAYS = {"day": 1, "week": 7, "fortnight": 14, "month": 30, "year": 365}

#: What "recently" means when nobody says. A fortnight: long enough that a
#: quiet week does not come back empty, short enough that "recently" still
#: means something.
RECENT_DAYS = 14


def _count(word: str) -> int:
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "few": 3, "couple of": 2,
    }.get(word, 1)


def _range_for(kind: str, match: re.Match, today: date) -> tuple[date, date]:
    if kind == "back":
        groups = [g for g in match.groups() if g]
        if len(groups) >= 2:
            days = _count(groups[0]) * _UNIT_DAYS[groups[1].lower()]
        else:
            days = _UNIT_DAYS[groups[0].lower()] if groups else RECENT_DAYS
        return today - timedelta(days=days), today
    if kind == "today":
        return today, today
    if kind == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if kind == "this_week":
        return today - timedelta(days=today.weekday()), today
    if kind == "this_month":
        return today.replace(day=1), today
    if kind == "this_year":
        return today.replace(month=1, day=1), today
    return today - timedelta(days=RECENT_DAYS), today  # "recent"


# The words a question is *made of* rather than about. Stripped before
# embedding, because for a short subject they are most of the sentence and the
# vector ends up describing the phrasing.
#
# Only ever removed from the ends of the query, never the middle: "notes on how
# to prove bread" must keep its "how", that one is the subject. A leading
# "what did I write about" is scaffolding; the same words inside a sentence may
# not be.
_SCAFFOLD = re.compile(
    r"^\s*(?:"
    r"what(?:'s| is| are| did| have| was| were)?|"
    r"which|show me|find( me)?|list|tell me( about)?|remind me( about)?|"
    r"can you (?:show|find|tell|list)( me)?|do i have|did i (?:write|save|note|say)|"
    r"have i (?:written|saved|noted|said)|i (?:wrote|saved|noted|write|save|note)|"
    r"any(?:thing)?|all (?:my|the)|my|the|about|any notes|notes|note|"
    # Pronouns and auxiliaries left behind once the phrase around them goes:
    # lifting "in the last week" out of "what notes have I saved in the last
    # week" leaves "have I saved", which is not a subject and must not become
    # one. Each is only ever stripped from the *front*, so a note about "I,
    # Claudius" keeps its words.
    r"i|have|has|had|did|do|does|was|were|been|get|got|save[ds]?|written|wrote|"
    # Connectives that a lifted phrase can leave stranded mid-sentence:
    # "anything from this month about the garden" → "from  about the garden".
    r"from|in|on|at|for|of|with"
    r")\b[\s,]*",
    re.IGNORECASE,
)

#: Punctuation a question can end with, dropped along with trailing space.
_TRAILING_CHARS = " \t\r\n,.?!"


def _tidy(text: str) -> str:
    """Collapse whitespace and drop trailing punctuation. No regex, on purpose.

    This was `re.sub(r"[\\s,.?!]+$", "", re.sub(r"\\s{2,}", " ", text).strip())`
    and CodeQL was right to flag it (`py/polynomial-redos`, high): an anchored
    `[…]+$` makes the engine retry the quantifier from every position, so a
    query of many tabs costs O(n²): and this runs on text that arrives
    straight from a search box, which is as uncontrolled as input gets in this
    app.

    `str.split` and `str.rstrip` are linear, do the same job, and are easier to
    read than the pattern they replace. `split()` with no argument also folds
    newlines and tabs into the single spaces the front-anchored matcher below
    expects, which the old `\\s{2,}` did not do for a *single* stray tab.
    """
    return " ".join(text.split()).rstrip(_TRAILING_CHARS)


#: The same idea from the other end, and it was a real gap. Front-stripping
#: alone assumes the time phrase is at the end of the sentence, and it usually
#: is not: lifting "recently" out of "jokes I have saved recently" leaves
#: "jokes I have saved", and lifting "the last month" out of "jokes from the
#: last month" leaves a dangling "jokes from". Both then went to the keyword
#: search as *two* required terms and to the embedder as a sentence about
#: saving rather than about jokes.
#:
#: Only filler is taken, and only from the very end, so a real subject can
#: never be eaten: "notes about my day" keeps "day" because "day" is not in the
#: list, while "jokes I have saved" loses three words that are.
#: A set and a `split()`, not a pattern: and for the same reason `_tidy`
#: above is not one. The regex this replaces was
#: `[\s,]*\b(?:i|me|my|…)\s*$`, and CodeQL flagged it as a second
#: `py/polynomial-redos` (high, alert #112) within a session of the first: an
#: unanchored `[\s,]*` in front of an alternation that must reach `$` makes the
#: engine retry from every position, so a query of many tabs costs O(n²). This
#: runs on whatever is typed into the search box, so "uncontrolled data" is
#: exactly right.
#:
#: The lesson is worth writing down because the same shape has now been written
#: twice in this one file: **a character class with `*` or `+` next to an
#: anchor is the shape to avoid**, and in both cases the linear replacement was
#: also the more readable one.
_TRAILING_SCAFFOLD_WORDS = frozenset(
    """
    i me my have has had did do does was were been get got
    save saved saves note noted notes wrote written write say said about
    from in on at for of with any all the a an
    """.split()
)


def _strip_trailing_scaffold(text: str) -> str:
    """Drop one filler word from the end, or return the text unchanged.

    One word per call, because the caller loops, the same contract the
    `count=1` on the old pattern had.
    """
    words = text.split()
    if not words:
        return text
    if words[-1].strip(",").lower() not in _TRAILING_SCAFFOLD_WORDS:
        return text
    return " ".join(words[:-1])


def _strip_scaffolding(text: str) -> str:
    """Peel question words off both ends, repeatedly.

    Repeatedly, because they stack: "what did I write about…" is three of these
    in a row. It stops as soon as nothing matches, and it never empties the
    string: a query that is *entirely* scaffolding ("what did I write?") keeps
    its last form, since searching for "" would match everything.

    Whitespace is collapsed first: lifting a time phrase out of the middle
    leaves a double space, and a double space stops the front-anchored pattern
    matching the word that is now at the front.
    """
    cleaned = _tidy(text)
    for _ in range(8):
        stripped = _tidy(_SCAFFOLD.sub("", cleaned, count=1))
        stripped = _tidy(_strip_trailing_scaffold(stripped))
        if not stripped or stripped == cleaned:
            break
        cleaned = stripped
    return cleaned


# --- the operators (WORLD_CLASS_PLAN 5.1) -------------------------------------
#
# One parser, used by Notes, Library, Timeline, the Chat scope and the palette,
# which is the point of §5.1: the alternative is five half-parsers that agree
# about `tag:` and disagree about everything else. They are *pure code*: the
# section they come from exists because the app has to be excellent with the
# model switched off, and an operator that needed a model to read would be the
# opposite of that.
#
# The names people type, mapped to the filter key they fill. Aliases are here
# because a person typing `type:` and a person typing `kind:` mean the same
# thing and the app knowing only one of them is a papercut nobody reports; they
# just conclude the feature does not work.
_OPERATOR_NAMES = {
    "tag": "tag",
    "tags": "tag",
    "kind": "kind",
    "type": "kind",
    "in": "space",
    "space": "space",
    "has": "has",
    "is": "is",
}

#: `before:` and `after:` are dates rather than filters: see `Understood.filters`.
_DATE_OPERATORS = ("before", "after", "since", "until")

# `name:value`, where the value may be quoted so `tag:"two words"` works, and
# where the name must start the token so a bare URL ("http://example.com") is
# never read as an operator. The lookbehind is on whitespace rather than `\b`
# for exactly that reason.
_OPERATOR = re.compile(
    r'(?<!\S)(' + "|".join([*_OPERATOR_NAMES, *_DATE_OPERATORS]) + r'):(?:"([^"]*)"|(\S+))',
    re.IGNORECASE,
)

#: A quoted run. Non-greedy would be wrong here: `"a" and "b"` is two phrases,
#: and `[^"]+` gets that right without backtracking, which matters because this
#: runs on search-box text (see `_tidy` on the two ReDoS alerts this file has
#: already collected).
_PHRASE = re.compile(r'"([^"]+)"')

#: A word the person does not want. Leading `-`, and only at the start of a
#: token, so "state-of-the-art" and a negative number keep their hyphens.
_EXCLUDED = re.compile(r"(?<!\S)-([\w][\w'-]*)")


def _parse_date_operator(value: str) -> date | None:
    """`2026-01-01`, `2026-01` or `2026` as a date. Anything else is None.

    Deliberately ISO only, and deliberately silent about the rest: a typed
    `before:tuesday` falls through to the free-text path below, where
    `timewords` already knows how to read it, rather than being rejected with
    an error message in a search box.
    """
    parts = value.strip().split("-")
    try:
        if len(parts) == 1:
            return date(int(parts[0]), 1, 1)
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (TypeError, ValueError):
        return None


def _split_values(raw: str) -> list[str]:
    """`work`, `work,home` and `"two words"` as a list of values.

    Commas split because `tag:work,home` is what people type when they mean
    "either", and the alternative (repeating the operator) is the one they
    reach for second.
    """
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_operators(text: str) -> tuple[str, dict[str, list[str]], list[str], list[str], date | None, date | None]:
    """Lift the operators out of a query and hand back what is left.

    The remainder goes on to the time and scaffolding passes exactly as an
    unoperatored query always did, which is why this runs first: `before:`
    holds a date, and letting the time reader see it would resolve the same
    constraint twice, once as a filter and once as a phrase.
    """
    filters = _empty_filters()
    since: date | None = None
    until: date | None = None
    remainder = text

    def take_operator(match: re.Match) -> str:
        nonlocal since, until
        name = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else (match.group(3) or "")
        if name in _DATE_OPERATORS:
            when = _parse_date_operator(value)
            if when is None:
                # Not a date this parser reads: leave the text in place so the
                # free-text path can try, rather than swallowing it silently.
                return match.group(0)
            if name in ("before", "until"):
                # Exclusive, the way every search box that has these treats
                # them: "before 2026-01-01" does not mean "including new
                # year's day". `until:` is the inclusive spelling for anyone
                # who wants the other reading.
                until = when - timedelta(days=1) if name == "before" else when
            else:
                since = when + timedelta(days=1) if name == "after" else when
            return " "
        key = _OPERATOR_NAMES[name]
        for value_part in _split_values(value):
            if value_part not in filters[key]:
                filters[key].append(value_part)
        return " "

    remainder = _OPERATOR.sub(take_operator, remainder)

    phrases = [m.group(1).strip() for m in _PHRASE.finditer(remainder) if m.group(1).strip()]
    # The quotes come off but the words stay: see `Understood.phrases`.
    remainder = _PHRASE.sub(lambda m: " " + m.group(1) + " ", remainder)

    excluded = [m.group(1).lower() for m in _EXCLUDED.finditer(remainder)]
    remainder = _EXCLUDED.sub(" ", remainder)

    return remainder, filters, phrases, excluded, since, until


def understand(question: str, now: datetime | date | None = None) -> Understood:
    """Read a question for a time range and a subject.

    Never raises and never returns nothing: a question it cannot read comes
    back as its own subject with no range, which is exactly what searching did
    before this existed.
    """
    text = (question or "").strip()
    if not text:
        return Understood(subject="")
    today = (now.date() if isinstance(now, datetime) else now) or date.today()

    # Operators first: they carry their own dates, and a `before:2026-01-01`
    # left in the text would be read a second time by the time pass below.
    remainder, filters, phrases, excluded, since, until = _parse_operators(text)
    phrase = ""
    soft = False
    operator_dates = since is not None or until is not None
    for pattern, kind in _COMPILED_RANGES:
        # A stated `before:`/`after:` is the more precise of the two, so a
        # phrase pass that could overwrite it does not run at all. Somebody
        # who typed both means the dates they typed.
        match = None if operator_dates else pattern.search(remainder)
        if not match:
            continue
        since, until = _range_for(kind, match, today)
        soft = kind == "recent"  # a lean, not a boundary, see `Understood.soft`
        phrase = match.group(0).strip()
        remainder = (remainder[: match.start()] + " " + remainder[match.end():]).strip()
        break

    if since is None and not operator_dates:
        # No range phrase. A single date might still be in there ("what did I
        # note on tuesday"), and `timewords` already knows how to read one, 
        # widened to its own precision, so "last month" is the month rather
        # than the 1st of it.
        mentions = timewords.find(remainder, today)
        if mentions:
            mention = mentions[0]
            since, until = _widen(mention)
            phrase = mention.phrase
            remainder = remainder.replace(mention.phrase, " ", 1).strip()

    subject = _strip_scaffolding(remainder)
    # Nothing left but filler once the date came out: the question was *only*
    # about time. Say so, so the caller lists the range instead of ranking
    # noise: "what did I save last week" has no subject to be similar to.
    #
    # An operator query is never "time only", even when it names nothing but a
    # range: `kind:document before:2026-01-01` has a constraint to apply, and
    # answering it with "every note in the window" would drop the one thing
    # the person actually typed.
    time_only = (
        since is not None
        and not _has_content(subject)
        and not (any(filters.values()) or phrases or excluded)
    )
    return Understood(
        subject=subject if _has_content(subject) else "",
        since=since,
        until=until,
        when_phrase=phrase,
        time_only=time_only,
        soft=soft,
        filters=filters,
        phrases=phrases,
        excluded=excluded,
    )


def _widen(mention: timewords.Mention) -> tuple[date, date]:
    """One resolved date, as the stretch its phrasing actually meant.

    A note that says "two weeks ago" is pinned to a day, and that is right for
    a note: it is describing one moment. A *question* saying the same words
    means "around then", and nobody remembers which day they wrote something
    two weeks ago. So a phrase measured in weeks or months gets a window around
    its date rather than the date itself, or the filter answers "nothing" to a
    question whose answer is plainly there.
    """
    at = mention.at
    if mention.precision == "week":
        return at, at + timedelta(days=6)
    if mention.precision == "month":
        return at.replace(day=1), _month_end(at)
    if mention.precision == "year":
        return at.replace(month=1, day=1), at.replace(month=12, day=31)
    phrase = mention.phrase.lower()
    if "week" in phrase or "fortnight" in phrase:
        return at - timedelta(days=3), at + timedelta(days=3)
    if "month" in phrase:
        return at - timedelta(days=15), at + timedelta(days=15)
    return at, at


def _month_end(day: date) -> date:
    if day.month == 12:
        return day.replace(day=31)
    return day.replace(month=day.month + 1, day=1) - timedelta(days=1)


#: Words left behind after stripping that do not amount to a subject. Without
#: this, "what did I write last week" leaves "write" and searches for it.
_FILLER = frozenset(
    """write wrote written save saved saves note notes noted say said anything
    something stuff things thing about down i me my have has had did do does
    was were been get got all any show find list tell""".split()
)


def _has_content(subject: str) -> bool:
    words = [w for w in re.split(r"\W+", subject.lower()) if w]
    return any(word not in _FILLER for word in words)


# --- the words worth matching on ----------------------------------------------
#
# Here rather than in `search_manager`, where these lived, because both the
# fusion search and the retrieval engine need them and the engine importing
# `search_manager` for one private helper drew an import edge that closed a
# cycle (`search.engine -> search.search_manager -> ai.embeddings ->
# ai.model_manager -> entry.manager -> search.engine`, caught by
# `tests/test_no_import_cycles.py`). This module imports nothing but
# `entry.timewords`, which imports nothing at all, so it is the right floor
# for anything both searches share. `search_manager._meaningful_terms` is
# still the name its own callers use; it passes through to this.

#: Words that carry no signal in a search. Matching on them is worse than
#: useless: "a" appears in nearly every note ever written, so a broad question
#: would return the whole notebook ranked by noise.
STOPWORDS = frozenset(
    """a an and are as at be been but by can did do does for from had has have
    how i if in into is it its me my of on or our so than that the their them
    then there these they this to was we were what when where which who why
    will with would you your""".split()
)


def search_terms(text: str) -> list[str]:
    """The words worth matching on, in the order they were typed.

    Single characters and stopwords are dropped. If that leaves nothing, the
    caller gets an empty list rather than a match against everything: an
    all-stopword query ("how do I") has no keywords in it, and inventing some
    from the raw words is how a search box answers with the whole notebook.
    """
    words = [w for w in re.split(r"\W+", (text or "").lower()) if w]
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]
