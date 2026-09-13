"""The system prompt's stable head must not move.

Asked for directly: *"Keep the system prompt + persona byte-identical turn
to turn so the cache is reused."* A prefix cache (Ollama's, llama.cpp's,
every backend that has one) keeps the tokens **before the first
difference** and re-processes everything after it. The agent prompt has
exactly one byte that changes on its own, the wall clock, so where that
byte sits decides whether the persona, the grounding line and the tools
guide (the large, unchanging majority of the prompt) survive a minute
ticking over mid-conversation.

These are lints in the same spirit as test_style_scale.py: they assert a
property no behaviour test would notice being lost, and the property is
free to keep and expensive to rediscover.
"""

from __future__ import annotations

import datetime as dt

from memorymap.ai import agent

CLOCK_MARKER = " The current date and time is "


def _system(monkeypatch, when: dt.datetime, **kwargs) -> str:
    from memorymap.core import config

    monkeypatch.setattr(config, "user_now", lambda cfg: when)
    messages = agent.build_agent_messages("what did I do?", [], **kwargs)
    return messages[0]["content"]


def test_the_clock_is_the_last_thing_in_the_system_prompt(app_state, monkeypatch):
    when = dt.datetime(2026, 4, 1, 9, 30, tzinfo=dt.timezone.utc)
    content = _system(monkeypatch, when)
    assert CLOCK_MARKER in content
    # Nothing may follow it: whatever comes after the clock is re-processed
    # every time the minute changes.
    tail = content[content.index(CLOCK_MARKER) :]
    assert tail.endswith(")") or tail.endswith(").")


def test_everything_before_the_clock_is_identical_across_minutes(app_state, monkeypatch):
    first = _system(monkeypatch, dt.datetime(2026, 4, 1, 9, 30, tzinfo=dt.timezone.utc))
    second = _system(monkeypatch, dt.datetime(2026, 4, 1, 9, 31, tzinfo=dt.timezone.utc))
    assert first != second  # the clock really did move
    head = first[: first.index(CLOCK_MARKER)]
    assert second.startswith(head)
    # And the cached head is the bulk of the prompt, not a token of it, the
    # whole point of the ordering.
    assert len(head) > 0.8 * len(first)


def test_the_clock_is_rounded_to_the_minute(app_state, monkeypatch):
    """Seconds would change between the rounds of a single turn, which is the
    case the ordering above cannot help with: rounds run seconds apart."""
    when = dt.datetime(2026, 4, 1, 9, 30, 45, 123456, tzinfo=dt.timezone.utc)
    content = _system(monkeypatch, when)
    assert "09:30:00" in content
    assert "45" not in content[content.index(CLOCK_MARKER) :]


def test_the_persona_leads_the_prompt_byte_for_byte(app_state, monkeypatch):
    """The persona is the first thing in the prompt and is sent verbatim, so a
    conversation that does not change it re-reads it from cache every round."""
    persona = "You are Ada, a careful archivist."
    content = _system(
        monkeypatch,
        dt.datetime(2026, 4, 1, 9, 30, tzinfo=dt.timezone.utc),
        persona_prompt=persona,
    )
    assert content.startswith(persona + " ")
