"""The command palette reads fields the API actually sends.

**Why this file exists.** The palette's reminder filter read `r.content`, and
a reminder has no `content`, its field is `text`. `undefined.toLowerCase()`
threw, and because the throw happened partway through `paletteMatches`, every
group was lost with it: notes, documents, reminders and conversations alike.
So Ctrl+K silently degraded to its static command list for anyone with a
single reminder saved, and the only trace was an exception in a console nobody
has open. It is the "feature that never ran once" shape CLAUDE.md warns about,
and no Python test could see it because the fault was a field name spanning
the API and the browser.

This ties the two sides together: the payload keys the palette depends on have
to keep existing, and the palette has to keep reading those names.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "frontend" / "app.js"


def _palette_matches_source() -> str:
    text = APP_JS.read_text(encoding="utf-8")
    start = text.index("function paletteMatches(")
    end = text.index("\nfunction ", start + 1)
    return text[start:end]


def test_a_reminder_payload_still_carries_text(ai_client):
    """The field the palette reads. If reminders are ever renamed back to
    `content`, this fails here rather than silently in a browser."""
    ai_client.post("/reminders", json={"text": "call mum", "due_at": "2030-01-01T09:00:00Z"})
    rows = ai_client.get("/reminders").json()
    assert rows, "expected at least one reminder"
    assert "text" in rows[0], f"reminder keys were {sorted(rows[0])}"


def test_the_palette_reads_reminder_text_not_content():
    """The other half of the same contract, checked statically because the
    palette runs in a browser this suite cannot start."""
    source = _palette_matches_source()
    assert "paletteReminders" in source
    reminder_block = source[source.index("paletteReminders") :]
    assert "r.text" in reminder_block, "the palette must read a reminder's `text`"
    assert "r.content" not in reminder_block, (
        "`r.content` is the bug this file exists for, a reminder has no `content`"
    )


def test_palette_field_reads_go_through_the_guard():
    """One malformed record must cost one missing group, not all of them.

    Every `.toLowerCase()` directly on a payload field inside `paletteMatches`
    is a chance for the whole function to throw, so they go through
    `paletteText`, which returns "" for anything that is not a string.
    """
    source = _palette_matches_source()
    raw = re.findall(r"\b[a-z]\.\w+\.toLowerCase\(\)", source)
    assert not raw, f"these bypass paletteText and can throw the palette away: {raw}"


def test_the_palette_resolves_every_kind_of_thing_the_app_holds():
    """REDESIGN.md R7.3: "one universal picker... resolving notes, documents,
    files and maps alike".

    It searched four of six, notes, documents, reminders, conversations, so
    a file or a board could only be reached by navigating to its tab first.
    That is the difference between a jump-to-note box and the way you move
    around the app.
    """
    source = _palette_matches_source()
    for group in ("Notes", "Documents", "Files", "Boards & maps", "Reminders", "Conversations"):
        assert f'"{group}"' in source, f"the palette no longer resolves {group}"


def test_the_palette_returns_every_group_it_builds():
    """A group that is built and then left out of the return is dead code that
    looks alive: the "never ran once" shape again. Every `*Matches` list the
    function builds has to appear in what it returns."""
    source = _palette_matches_source()
    built = set(re.findall(r"const (\w+Matches) =", source))
    returned = source[source.rindex("return ["):]
    missing = sorted(name for name in built if name not in returned)
    assert not missing, f"built but never returned: {missing}"
