"""The Ask box answers like a research overview, not like a chat turn.

Reported directly: *"in the ask tab, the ai needs to summarise the notes, not
offer to do more as that isnt what the tab is for, it isnt a chatbot but
providing an ai overview and search result like perplexity for the user's
notes."*

`GROUNDING` produces a correctly-grounded answer in the wrong shape, it ends
"Would you like me to…", because nothing had told this surface it isn't a
chat. The results panel beside the answer already links every note, so that
offer is a question the UI has answered, taking the room the overview needs.
"""

from __future__ import annotations

from memorymap.ai import librarian


def test_the_ask_brief_forbids_the_chatbot_closer():
    brief = librarian.ASK_OVERVIEW
    assert "Do NOT end by offering to do anything else" in brief
    assert "do NOT ask what they would" in brief
    # And it says what to do *instead*, a rule with no replacement is one a
    # small model drops the moment the conversation gets long.
    assert "Summarise and synthesise" in brief
    assert "lead with the answer" in brief


def test_the_ask_system_prompt_swaps_the_brief_rather_than_stacking_it():
    """Both briefs say "use only these notes"; saying it twice in different
    words is two chances for a small model to weigh them against each other."""
    ask = librarian.system_content(ask_overview=True)
    assert librarian.ASK_OVERVIEW in ask
    assert librarian.GROUNDING not in ask


def test_the_chat_prompt_is_untouched():
    chat = librarian.system_content()
    assert librarian.GROUNDING in chat
    assert librarian.ASK_OVERVIEW not in chat


def test_the_persona_and_style_still_apply_to_an_ask():
    """The overview brief replaces the grounding sentence, not the whole
    prompt: a custom persona is still the user's own setting."""
    ask = librarian.system_content(
        style="brief", profile="Studies design", persona_prompt="You are Ada.", ask_overview=True
    )
    assert ask.startswith("You are Ada.")
    assert "Studies design" in ask


def test_build_messages_puts_the_ask_brief_in_the_system_message():
    messages = librarian.build_messages(
        "what did I write about league of legends?",
        [{"content": "I main Seraphine", "category": "Hobbies"}],
        ask_overview=True,
    )
    assert messages[0]["role"] == "system"
    assert librarian.ASK_OVERVIEW in messages[0]["content"]
