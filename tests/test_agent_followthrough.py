"""The agent acts when told to act, and stops re-reading what it just read.

Three reported failures, one theme: the agent is expensive to use and
under-delivers on what it is asked.

**"Implement those suggestions" got the suggestions again.** Reported directly:
*"I asked it for suggestions in modifying my categories but when I asked it to
implement the suggestions, it just gave me suggestions again and no tool
calls."* The cause was exact and is pinned below, `focus_for` read the current
message and nothing else, and "implement those suggestions" contains no
category word, so the turn was offered the reading core and **no category tools
at all**. The model was not being lazy; it had nothing to call.

**It re-read what it had already read.** Reported: *"it often calls the same
tools to read all notes or to read the same note's context in full after no
changes."* A repeated read costs the window twice and returns nothing new.

**It lost its own plan across a tool call.** Reported: *"it thinks up this
whole plan, then it does a tool call and either loses track or has to rethink
the plan again."* The reasoning was streamed to the user and then dropped.
"""

from __future__ import annotations

import pytest

from memorymap.ai import agent, tools


# --- "now do it" ---------------------------------------------------------------


CATEGORY_ADVICE = (
    "Here is what I would change about your categories: rename Misc to Inbox, "
    "and file the loose notes under it."
)


@pytest.mark.parametrize(
    "message",
    [
        "implement those suggestions",
        "go ahead",
        "do it",
        "yes",
        "apply them",
        "make those changes",
    ],
)
def test_a_follow_through_is_offered_the_tools_the_last_turn_was_about(message):
    """The reported bug, as a property: a message meaning "now do what we just
    discussed" must be able to *do* it."""
    offered = tools.focus_for(message, CATEGORY_ADVICE)
    assert offered is None or "rename_category" in offered, (
        f"{message!r} after a conversation about categories was offered "
        "no way to change one, so the only reply it can give is the same "
        "suggestions again: which is exactly what was reported."
    )


def test_the_same_message_without_a_conversation_still_narrows():
    """The economy §11a bought is not given back. A follow-through with
    nothing to follow through *on* is the one case that widens, because being
    unable to act is certainly wrong and extra schemas merely cost."""
    offered = tools.focus_for("what did I write about beans")
    assert offered is not None
    assert "rename_category" not in offered


def test_an_ordinary_question_does_not_inherit_the_last_turn_s_tools():
    """History is read *only* for a follow-through. Reading it every turn
    would be worse than never: a question about beans, asked after a
    conversation about deleting things, would be handed delete_note."""
    offered = tools.focus_for(
        "what did I write about beans", "I deleted three notes and emptied the bin."
    )
    assert offered is not None
    assert "delete_note" not in offered


def test_a_follow_through_that_names_its_own_subject_keeps_its_own_cues():
    offered = tools.focus_for("go ahead and remind me about it tomorrow", "")
    assert offered is None or "set_reminder" in offered


@pytest.mark.parametrize(
    "message,expected",
    [
        ("do it", True),
        ("yes", True),
        ("ok", True),
        ("implement those suggestions", True),
        ("as you suggested", True),
        ("what did I write about beans", False),
        ("yes, remind me to call mum tomorrow", False),
    ],
)
def test_what_counts_as_a_follow_through(message, expected):
    """A bare "yes" is a follow-through; "yes, remind me…" says what it wants
    and is read on its own terms."""
    assert tools.is_follow_through(message) is expected


def test_the_recent_text_is_the_last_exchange_and_is_capped(monkeypatch):
    """Newest first, so what survives the cap is the turn actually being
    followed through on rather than the start of the conversation."""
    history = [
        {"question": "old question", "answer": "old answer"},
        {"question": "the latest question", "answer": "the latest answer"},
    ]
    recent = agent._recent_text(history)
    assert "the latest answer" in recent
    assert len(recent) <= agent.FOLLOW_THROUGH_CONTEXT_CHARS

    long_history = [{"question": "q", "answer": "x" * 5_000}]
    assert len(agent._recent_text(long_history)) <= agent.FOLLOW_THROUGH_CONTEXT_CHARS


def test_no_history_is_not_an_error():
    assert agent._recent_text(None) == ""
    assert agent._recent_text([]) == ""
