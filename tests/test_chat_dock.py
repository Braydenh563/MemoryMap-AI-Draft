"""The chat controls live with the chat input, not above the conversation.

Asked for directly: *"I was thinking of moving the majority of the ui controls
like the chat/agent pull, web search and stuff to the bottom bar with the chat
input."*

The split the dock encodes is between two questions a control can answer:

- **what happens to the next message**, Chat/Agent, Web, answer length,
  persona, the skill picker, the notes clipped to it. These belong beside the
  box you type in, because that is when you decide them.
- **what this conversation is**, its name, what it has cost, exporting it.
  Those stay in the header, which is now only about the thread as a whole.

This is a lint, not a behaviour test, and it exists for the same reason
`test_frontend_ids.py` does: the Python suite cannot see the DOM and the
sandbox has no browser, so nothing else would notice a control drifting back
up into the header, which is exactly how the header collected eight
unrelated buttons the first time (§36B).

It deliberately checks *containment*, not order or styling. Rearranging the
dock is fine; putting the response-mode picker back above a scrolled
conversation is what this catches.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._css_paths import css_text

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

#: Controls that decide what happens to the *next* message.
PER_MESSAGE_IDS = (
    "chat-mode-seg",
    "tools-toggle",
    "web-search-toggle",
    "response-mode-select",
    "persona-select",
    "persona-peek",
    "chat-input",
    "chat-send",
    "chat-skills",
    "chat-attachments",
    "attach-note",
)

#: …and the ones that are about the conversation, not the message.
CONVERSATION_IDS = ("chat-title", "chat-export", "chat-usage")


def _markup() -> str:
    """index.html with comments stripped, they quote tags and ids."""
    return re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)


def _block(markup: str, opening: str) -> str:
    """The markup of one element, by walking div depth from its opening tag.

    A regex cannot match nested elements and an HTML parser is a dependency
    this suite does not have. Counting `<div` against `</div>` is enough here
    because both regions are div-nested throughout.

    `opening` is a *pattern*, not a literal string, and that is deliberate.
    It used to be `markup.index('<div class="chat-toolbar">')`, which meant
    this test failed the moment the header took a second class
    (UI_MODERNISATION_PLAN.md Phase 8 added `.dock` beside `.chat-toolbar`)
    even though nothing it actually asserts had changed. A locator that
    breaks on an unrelated edit reports a false failure, which is the one
    thing a lint must not do.
    """
    found = re.search(opening, markup)
    assert found, f"no element matching {opening!r}"
    start = found.start()
    depth = 0
    for match in re.finditer(r"<div\b|</div>", markup[start:]):
        depth += 1 if match.group(0) == "<div" else -1
        if depth == 0:
            return markup[start : start + match.end()]
    raise AssertionError(f"{opening} is never closed")


def test_every_per_message_control_is_in_the_dock():
    dock = _block(_markup(), r'<div class="[^"]*\bchat-dock\b[^"]*"')
    missing = [name for name in PER_MESSAGE_IDS if f'id="{name}"' not in dock]
    assert not missing, (
        "these controls decide what happens to the next message and belong "
        f"beside the box that sends it: {missing}"
    )


def test_the_header_keeps_only_the_conversation_level_controls():
    markup = _markup()
    toolbar = _block(markup, r'<div class="[^"]*\bchat-toolbar\b[^"]*"')
    for name in CONVERSATION_IDS:
        assert f'id="{name}"' in toolbar, f"{name} is about the conversation"
    strays = [name for name in PER_MESSAGE_IDS if f'id="{name}"' in toolbar]
    assert not strays, (
        "the chat header is about the conversation as a whole; these are about "
        f"the next message and belong in the dock: {strays}"
    )


def _styles() -> str:
    return re.sub(r"/\*.*?\*/", "", css_text(), flags=re.S)


def test_the_dock_neutralises_the_margins_its_controls_arrive_with():
    """The alignment bug, and why a rule rather than a value is what fixes it.

    Reported: *"the chat bottom dock ui elements are off in size and alignment.
    Some are higher or lower than each other and different heights."* All true,
    and none of it visible in the markup: `.seg` carries `margin-bottom: 0.5rem`
    from the stacked forms it was built for, and `align-items: center` centres a
    flex item's **margin box**: so 8px underneath sits the control 4px above
    its neighbours *and* makes its group 8px taller, which pushes the next group
    4px down in turn. Two visible offsets from one invisible declaration.

    Measured in a browser before and after: three different group tops and four
    different composer heights (45.2 / 49.0 / 45.2 / 43.2), against one top and
    one height for each row now.

    So the strip states it once for everything inside it, and this is the check
    that it still does, a control added later inherits the neutralised margin
    instead of re-introducing the bug.
    """
    css = _styles()
    strip = re.search(r"\.chat-dock-controls select,.*?\n\}", css, re.S)
    assert strip, "the dock's control-sizing rule is gone"
    assert "margin: 0" in strip.group(0), (
        "the strip must zero the margins its controls bring with them, a "
        "margin on a flex item is centred with the item, so it becomes a "
        "vertical offset rather than a gap"
    )
    assert "--control-h" in strip.group(0)


def test_both_rows_of_the_dock_declare_one_control_height():
    """`--control-h` for the strip, `--composer-h` for the message row. Named
    rather than repeated, because the failure is four controls that each sized
    themselves from a different base rule."""
    css = _styles()
    assert "--control-h:" in css and "--composer-h:" in css


def test_the_composer_stays_bottom_aligned_as_the_box_grows():
    """`align-items: end`, not centre. The box is autogrow: a three-line
    question makes it taller, and the buttons have to stay level with the line
    the caret is on rather than drifting up the side of it."""
    css = _styles()
    composer = re.search(r"\.chat-dock \.chat-composer \{.*?\n\}", css, re.S)
    assert composer and "align-items: end" in composer.group(0)


def test_a_panel_opens_beside_the_button_that_opens_it():
    """A toggle at the bottom of the page that opens a panel at the top reads
    as a button that does nothing, so a disclosure lives with its trigger.

    The persona peek is a *disclosure*: two lines saying what the select next
    to it does. It stays in the dock.
    """
    dock = _block(_markup(), '<div class="chat-dock">')
    assert 'id="persona-peek-panel"' in dock


def test_the_web_panel_is_a_column_not_a_drawer_in_the_dock():
    """It used to be in the dock, and this test used to require that.

    The rule above is about *disclosures*, and the web panel is not one, it is
    a search box, a list of results and the full text of a web page. Inside the
    dock it had to be capped, because the dock's job is to stay short, and the
    cap made it unusable: reported as "squashed ugly … what it is right now
    isn't working". The two symptoms it produced, pushing the composer off the
    bottom, then being too small to read, were the same mistake from either
    side.

    So it is a sibling of #chat-main inside the chat page's <main>: a column,
    the full height of the page, beside the conversation rather than under it.
    """
    markup = _markup()
    dock = _block(markup, '<div class="chat-dock">')
    assert 'id="web-panel"' not in dock, "the web panel is a column, not a dock drawer"
    # Still on the chat page, and still a sibling of the conversation card, 
    # the point of the move is *where* it went, not merely that it left.
    chat_page = _block(markup, '<div class="tab-page hidden" id="tab-chat"')
    assert 'id="web-panel"' in chat_page
    assert chat_page.index('id="chat-main"') < chat_page.index('id="web-panel"')
