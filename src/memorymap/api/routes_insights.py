"""Dashboard insights: stats, on-this-day, weekly digest."""

from __future__ import annotations

import difflib
import json
import random
import re
from collections.abc import Iterator
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.ai import librarian
from memorymap.ai.ollama_client import OllamaError
from memorymap.core import deps
from memorymap.core.database import Category, Entry, utcnow
from memorymap.core.deps import get_session
from memorymap.entry import manager, paths

router = APIRouter(prefix="/insights", tags=["insights"])

ACTIVITY_DAYS = 14  # the dashboard's little activity strip
HEATMAP_DAYS = 371  # 53 whole weeks, the contribution-style heatmap


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    total = session.scalar(
        select(func.count(Entry.id)).where(Entry.is_deleted == False)  # noqa: E712
    )
    by_category = session.execute(
        select(Category.name, func.count(Entry.id))
        .join(Entry, Entry.category_id == Category.id)
        .where(Entry.is_deleted == False)  # noqa: E712
        .group_by(Category.name)
        .order_by(func.count(Entry.id).desc())
    ).all()

    # Entries per day for the activity strip, oldest day first.
    start = utcnow() - timedelta(days=ACTIVITY_DAYS - 1)
    recent = session.scalars(
        select(Entry).where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.created_at >= start.replace(hour=0, minute=0, second=0),
        )
    )
    per_day = [0] * ACTIVITY_DAYS
    today = utcnow().date()
    for entry in recent:
        offset = (today - entry.created_at.date()).days
        if 0 <= offset < ACTIVITY_DAYS:
            per_day[ACTIVITY_DAYS - 1 - offset] += 1

    return {
        "total_entries": total or 0,
        "categories": [{"name": name, "count": count} for name, count in by_category],
        "per_day": per_day,
        "days": ACTIVITY_DAYS,
    }


# Time-of-day greeting phrases used when the local model isn't available.
# Deliberately name-free: the frontend appends the user's preferred name.
GREETING_FALLBACKS = {
    "morning": ["Good morning", "Morning", "Rise and shine", "A fresh start"],
    "afternoon": ["Good afternoon", "Afternoon", "Hope today's going well"],
    "evening": ["Good evening", "Evening", "Winding down"],
    "night": ["Still up", "Working late", "Burning the midnight oil"],
}

# Keep the greeting from settling into one rut: each generation is nudged
# toward a different flavour, so the banner feels like it's paying attention
# rather than replaying the same line.
GREETING_FLAVOURS = (
    "a plain warm hello",
    "a curious question about what they are working on",
    "a light remark about the time of day",
    "a gentle nudge to capture a thought",
    "a short welcome back",
    "an encouraging line about their notes",
    "a relaxed, casual aside",
)

GREETING_PROMPT = (
    "Write ONE short greeting for someone opening their personal notebook app. "
    "It is currently {block}. Make it {flavour}. Rules: 2 to 7 words, no name, "
    "no quotation marks, no emoji, and do not mention the app by name. It may "
    "be a question. End it with a full stop, question mark or exclamation "
    "mark. Reply with the greeting only."
)

# When the user has set a display name we usually ask the model to weave it in,
# so the greeting reads naturally ("Morning, Sam!") instead of always being a
# phrase with a name bolted on. The name comes from preferences, never
# hardcoded. Not every greeting uses it, so it doesn't get repetitive.
GREETING_PROMPT_NAMED = (
    "Write ONE short greeting for {name}, who is opening their personal "
    "notebook app. It is currently {block}. Make it {flavour}. Rules: 2 to 8 "
    "words, use the name {name} exactly once and spell it exactly as given, no "
    "quotation marks, no emoji, and do not mention the app by name. It may be a "
    "question. End it with a full stop, question mark or exclamation mark. "
    "Reply with the greeting only."
)

# How often a greeting addresses the user by name when one is set.
NAME_USE_CHANCE = 0.75

# The greeting is stored without its final mark so the display name can be
# appended cleanly ("Good morning" + ", Sam" + "!"). The mark travels
# separately in `punctuation`.
_TERMINAL_MARKS = ".!?"


def _clean_greeting(raw: str) -> tuple[str, str] | None:
    """Return (phrase, terminal mark): or None if the reply is unusable."""
    text = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    text = text.strip().strip("\"'`*").strip()
    mark = "."
    # Remember an exclamation/question so the greeting keeps its tone, then
    # strip trailing punctuation so a name can be appended after it.
    while text and text[-1] in _TERMINAL_MARKS + ",;:":
        if text[-1] in _TERMINAL_MARKS:
            mark = text[-1]
        text = text[:-1].rstrip()
    # A little headroom over the prompt's word limit, since a woven-in name
    # costs a word or two.
    if not text or len(text) > 56 or len(text.split()) > 9:
        return None
    # Small local models often answer in lowercase; the banner is a sentence,
    # so open it with a capital. Only the first character is touched, leaving
    # any legitimately capitalised words alone.
    return _sentence_case(text), mark


def _sentence_case(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


@router.get("/greeting")
def greeting(block: str = "morning") -> dict:
    """A short greeting phrase for the dashboard banner.

    AI-written when the local model is up, otherwise a handwritten fallback, 
    the banner must never depend on Ollama being available. The phrase never
    contains a name; the frontend adds one from preferences.
    """
    config = deps.get_config()
    options = GREETING_FALLBACKS.get(block) or GREETING_FALLBACKS["morning"]
    fallback = {
        "greeting": random.choice(options),
        "punctuation": ".",
        "append_name": True,  # handwritten phrases are name-free
        "source": "fallback",
    }

    ollama = deps.get_ollama()
    if not ollama.is_running():
        return fallback

    # The name is read from preferences here rather than trusted from the
    # client, so there is exactly one source of truth for it.
    name = str(config.get_preference("display_name", "") or "").strip()
    # Most greetings use the name, but not all, variety matters more than
    # rigid consistency here.
    use_name = bool(name) and random.random() < NAME_USE_CHANCE
    flavour = random.choice(GREETING_FLAVOURS)
    # dashboard_persona is an independent override (asked for directly: the
    # dashboard greeting shouldn't have to match whichever persona is active
    # for Chat/search). Empty/unset falls through to that same active
    # persona: resolve_persona_prompt's own `name or active_persona`
    # default: so nothing changes for anyone who hasn't set one.
    dashboard_persona_name = str(config.get_preference("dashboard_persona", "") or "").strip() or None
    persona = librarian.resolve_persona_prompt(dashboard_persona_name, config)
    system = (
        GREETING_PROMPT_NAMED.format(block=block, name=name, flavour=flavour)
        if use_name
        else GREETING_PROMPT.format(block=block, flavour=flavour)
    )
    if persona:
        system = f"{persona.strip()} {system}"
    ask = f"It is {block}. Greet {name}." if use_name else f"It is {block}. Greet me."
    try:
        reply = ollama.chat(
            deps.get_model_manager().utility_model(),
            [
                {"role": "system", "content": system},
                {"role": "user", "content": ask},
            ],
        )
    except Exception:  # noqa: BLE001  # any model failure degrades to fallback
        return fallback

    cleaned = _clean_greeting(reply.get("content", "") if isinstance(reply, dict) else "")
    if not cleaned:
        return fallback
    phrase, mark = cleaned

    # `append_name` tells the frontend whether to add the name itself. It only
    # does so when we asked for a named greeting and the model failed to use
    # one: so the name appears exactly once when wanted, and not at all on the
    # deliberately nameless ones.
    append_name = use_name
    if name:
        match = re.search(re.escape(name), phrase, re.IGNORECASE)
        if match:
            # Normalise to the spelling the user saved, in case the model
            # lower-cased it.
            phrase = phrase[: match.start()] + name + phrase[match.end() :]
            append_name = False
        else:
            phrase, fixed = _repair_misspelt_name(phrase, name)
            if fixed:
                append_name = False

    # **A greeting must never call the user by a name they did not save.**
    # Reported: "the model spelt my name wrong in the dashboard welcome
    # message." The exact-match normalisation above is the only thing that ever
    # touched the model's spelling, so a near miss, "Braden" for "Brayden" , 
    # sailed straight through it, and `append_name` stayed True on top, which
    # is how the banner ends up greeting two people.
    #
    # `_repair_misspelt_name` catches the near misses. This catches the rest: a
    # model that invents a different name entirely, or addresses someone when
    # no name is saved at all. There is no repairing that, so the handwritten
    # greeting is used instead, being greeted impersonally is a non-event, and
    # being greeted by the wrong name is the kind of small wrongness that makes
    # a person stop trusting everything else the app says.
    if _greets_a_stranger(phrase, name):
        return fallback

    return {
        "greeting": phrase,
        "punctuation": mark,
        "append_name": append_name,
        "source": "ai",
    }


#: How close a word has to be to the saved name before it is treated as the
#: model's attempt at it rather than as a different word. 0.72 accepts
#: "Braden"/"Brayden" (0.77) and "Sammy"/"Sam" (0.75) while refusing ordinary
#: words that merely share letters, "Sunday"/"Sam" scores 0.44.
NAME_SIMILARITY = 0.72


def _name_like_words(phrase: str) -> list[str]:
    """The capitalised words in a greeting that could be someone's name.

    The first word is skipped: every greeting starts with one ("Morning",
    "Welcome") and it is capitalised because it opens the sentence, not because
    it is a name.
    """
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", phrase)
    return [word for word in words[1:] if word[:1].isupper()]


def _repair_misspelt_name(phrase: str, name: str) -> tuple[str, bool]:
    """Put the saved spelling back where the model got it nearly right.

    Returns the phrase and whether anything was replaced. Only the *closest*
    candidate is replaced, and only one: a greeting with two near-miss names in
    it is not a spelling slip, it is a greeting for somebody else.
    """
    best: tuple[float, str] | None = None
    for word in _name_like_words(phrase):
        if word.lower() == name.lower():
            continue
        score = difflib.SequenceMatcher(None, word.lower(), name.lower()).ratio()
        if score >= NAME_SIMILARITY and (best is None or score > best[0]):
            best = (score, word)
    if best is None:
        return phrase, False
    return re.sub(rf"\b{re.escape(best[1])}\b", name, phrase, count=1), True


def _greets_a_stranger(phrase: str, name: str) -> bool:
    """True when the greeting addresses a name that is not the saved one.

    A vocative only: "Hello, Dave" and "Welcome back, Dave!" address someone,
    while "Time to write" and "Morning: Tuesday already" do not. Matching on
    the comma is what keeps ordinary capitalised words (a weekday, a place a
    persona mentions) from being read as names.
    """
    vocative = re.search(r",\s*([A-Z][A-Za-z'\-]*)\s*[.!?]?\s*$", phrase.strip())
    if not vocative:
        return False
    spoken = vocative.group(1)
    if not name:
        return True  # nobody to greet, so any name here is invented
    return spoken.lower() != name.lower()


@router.get("/heatmap")
def heatmap(session: Session = Depends(get_session)) -> dict:
    """Daily note counts for the last ~year, for the activity heatmap.

    Returned oldest-first with the ISO date of the first day so the frontend
    can lay the weeks out without guessing.
    """
    today = utcnow().date()
    start = today - timedelta(days=HEATMAP_DAYS - 1)
    counts = [0] * HEATMAP_DAYS
    rows = session.scalars(
        select(Entry).where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.created_at >= utcnow() - timedelta(days=HEATMAP_DAYS),
        )
    )
    for entry in rows:
        offset = (entry.created_at.date() - start).days
        if 0 <= offset < HEATMAP_DAYS:
            counts[offset] += 1
    return {
        "start": start.isoformat(),
        "days": HEATMAP_DAYS,
        "counts": counts,
        "total": sum(counts),
        "busiest": max(counts) if counts else 0,
    }


@router.get("/tag-cloud")
def tag_cloud(session: Session = Depends(get_session)) -> list[dict]:
    """Every tag with its frequency, most-used first, for a weighted cloud.

    Was its own independent full-entry scan + tag-JSON decode, duplicating
    `manager.all_tags`, the same computation, run twice in two places.
    """
    ordered = manager.all_tags(session).items()
    return [{"tag": tag, "count": count} for tag, count in list(ordered)[:60]]


@router.get("/on-this-day")
def on_this_day(session: Session = Depends(get_session)) -> list[dict]:
    """Notes captured on today's date in earlier months/years, a gentle
    resurfacing of old thoughts (from the original idea doc).

    The day-of-month and "at least 28 days old" checks used to load every
    non-deleted entry and filter in a Python loop; SQLite does both in the
    WHERE clause instead now, so only matching rows are ever hydrated into
    ORM objects. Also now excludes private notes, every other view in this
    app does (search, timeline, embeddings...), and this one, uniquely,
    read `entry.content` straight off the column, which is ciphertext for a
    private note, not the private-note placeholder every other surface uses.
    """
    now = utcnow()
    matched_entries = list(
        session.scalars(
            select(Entry).where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
                Entry.created_at <= now - timedelta(days=28),
                func.strftime("%d", Entry.created_at) == f"{now.day:02d}",
            )
        )
    )
    matches = []
    category_names = manager.bulk_category_names(session, matched_entries)
    
    for entry in matched_entries:
        matches.append(
            {
                "id": entry.id,
                "content": entry.content,
                "category": category_names.get(entry.category_id, manager.UNCATEGORISED),
                "created_at": entry.created_at.isoformat(),
            }
        )
    return matches[:5]


DIGEST_QUESTION = (
    "Give me a short digest of what I saved this week, group by topic and "
    "call out anything that looks important or unfinished."
)


def _digest_notes(session: Session) -> list[dict]:
    cutoff = utcnow() - timedelta(days=7)
    # `is_private == False`: this content is handed straight to the AI, and a
    # private note's `content` column is ciphertext at rest, sending it here
    # put encrypted bytes in the model's prompt (and, since the model doesn't
    # know that, sometimes into the digest text a user then reads). Every
    # other surface that feeds the AI already excludes private notes;
    # `digest_structure_note` below does too for its own sentence, this was
    # the one place a private note's row still reached the model.
    entries = list(
        session.scalars(
            select(Entry)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
                Entry.created_at >= cutoff,
            )
            .order_by(Entry.created_at)
            .limit(30)
        )
    )
    category_names = manager.bulk_category_names(session, entries)
    return [
        {"content": e.content, "category": category_names.get(e.category_id, manager.UNCATEGORISED)}
        for e in entries
    ]


def digest_structure_note(session: Session) -> str:
    """One sentence about how this week's notes sit in the notebook, or "".

    The digest could see the week's notes and their categories and nothing
    else: which means it could summarise *what* you wrote and never notice
    that five of those notes are joined to nothing, or that three of them
    landed in the same corner of the notebook. That is the thing a weekly recap
    is actually for, and it is exactly what the graph knows.

    Deliberately **facts, not adjectives**: counts the model can repeat and the
    user can verify by clicking, rather than a judgement it would have to take
    on trust. And deliberately one sentence, this rides in the prompt of a
    background job on a utility model, and §11a's budget applies here as much
    as anywhere.
    """
    cutoff = utcnow() - timedelta(days=7)
    fresh = list(
        session.scalars(
            select(Entry).where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
                Entry.created_at >= cutoff,
            )
        )
    )
    if not fresh:
        return ""
    index = paths.build(session, include_private=False)
    loose = set(paths.orphans(index))
    unconnected = [entry for entry in fresh if entry.id in loose]
    if not unconnected:
        return (
            f" Every one of this week's {len(fresh)} notes is connected to "
            "something else in the notebook, say so briefly, it is worth "
            "knowing."
        )
    return (
        f" Of this week's {len(fresh)} notes, {len(unconnected)} are connected "
        "to nothing else in the notebook, no link, no reply, no shared tag. "
        "Mention that count and name one or two of them, so they can be tied "
        "in. Do not guess at connections that are not there."
    )


@router.post("/digest/stream")
def weekly_digest_stream(session: Session = Depends(get_session)) -> StreamingResponse:
    """The weekly digest, streamed token by token (NDJSON).

    Same content as POST /digest, this one just arrives progressively, so a
    slow local model shows words instead of a spinner.
    """
    notes = _digest_notes(session)
    config = deps.get_config()
    ollama = deps.get_ollama()
    model_manager = deps.get_model_manager()

    def lines() -> Iterator[str]:
        def event(payload: dict) -> str:
            return json.dumps(payload) + "\n"

        if not notes:
            yield event({"type": "answer", "delta": "Nothing was saved in the last 7 days."})
            yield event({"type": "done", "cacheable": True})
            return
        if not ollama.is_running():
            yield event({"type": "answer", "delta": librarian.OFFLINE_MESSAGE})
            yield event({"type": "done", "cacheable": False})
            return

        digest_style = config.get_preference("communication_style", "friendly")
        digest_persona = librarian.resolve_persona_prompt(None, config)
        messages = librarian.build_messages(
            DIGEST_QUESTION + digest_structure_note(session),
            notes,
            style=digest_style,
            profile="",
            persona_prompt=digest_persona,
            # The digest is the worst case for an unbudgeted prompt: it hands
            # over a week of notes at once, so "however many turned up" was
            # never a number anyone checked. Budgeted against the utility
            # model, which is what streams it below, and which is often the
            # *small* model, with the smallest window in the app.
            budget=librarian.plan_budget(
                model_manager.utility_model(), ollama, digest_style, "", digest_persona
            ),
        )
        try:
            for piece in ollama.chat_stream(model_manager.utility_model(), messages):
                if "content_delta" in piece:
                    yield event({"type": "answer", "delta": piece["content_delta"]})
                elif "thinking_delta" in piece:
                    yield event({"type": "thinking", "delta": piece["thinking_delta"]})
        except OllamaError:
            yield event({"type": "answer", "delta": f"\n\n{librarian.OFFLINE_MESSAGE}"})
            yield event({"type": "done", "cacheable": False})
            return
        yield event({"type": "done", "cacheable": True})

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post("/digest")
def weekly_digest(session: Session = Depends(get_session)) -> dict:
    """An on-demand AI recap of the last 7 days (reads only)."""
    cutoff = utcnow() - timedelta(days=7)
    # See _digest_notes' comment above: a private note's `content` is
    # ciphertext at rest and must never reach the model's prompt.
    entries = list(
        session.scalars(
            select(Entry)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
                Entry.created_at >= cutoff,
            )
            .order_by(Entry.created_at)
            .limit(30)
        )
    )
    if not entries:
        # A real, stable fact, safe for the UI to cache for the day.
        return {
            "digest": "Nothing was saved in the last 7 days.",
            "thinking": None,
            "cacheable": True,
        }

    category_names = manager.bulk_category_names(session, entries)
    notes = [
        {"content": e.content, "category": category_names.get(e.category_id, manager.UNCATEGORISED)}
        for e in entries
    ]
    config = deps.get_config()
    # Only a genuine AI answer is worth caching, if Ollama is down the
    # digest is just the offline notice, which should be retried, not
    # frozen for the day.
    ollama_running = deps.get_ollama().is_running()
    digest, thinking = librarian.answer(
        DIGEST_QUESTION + digest_structure_note(session),
        notes,
        deps.get_model_manager(),
        deps.get_ollama(),
        style=config.get_preference("communication_style", "friendly"),
        persona_prompt=None,
        use_utility_model=True,  # a background job, keep the chat model free
    )
    return {"digest": digest, "thinking": thinking, "cacheable": ollama_running}
