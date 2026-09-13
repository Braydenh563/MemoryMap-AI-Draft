"""The roadmap split has to stay navigable (docs/ROADMAP.md).

The roadmap reached 4,500 lines across 47 sections and was split into four
files. The split has exactly one failure mode, and it is the reason this test
exists: **a session that reads only ROADMAP.md will rebuild something already
done, or re-derive a decision already made.** With a single file that happened
three times, so it is not hypothetical.

Two facts are load-bearing and live outside the main file:

- HISTORY.md answers "has this been built?", the audit that found four of §2's
  six "quick wins" already done is in there.
- ANALYSIS.md holds §33's constraint that **odysseus is AGPL and this project
  is MIT, so no code crosses in either direction**. That is invisible if you
  only read the backlog, and expensive to violate.

So this checks that every file announces the others, that the two facts above
are reachable, and, the one that actually matters, that no section was lost
in the split.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
ROADMAP = DOCS / "ROADMAP.md"
COMPANIONS = {
    name: DOCS / "roadmap" / f"{name}.md" for name in ("BACKLOG", "ANALYSIS", "HISTORY")
}


def test_the_split_lost_nothing():
    """Every numbered section §1-§36 resolves in exactly one file. A reference
    in a code comment that lands nowhere is the split having eaten something."""
    seen: dict[str, str] = {}
    for label, path in [("ROADMAP", ROADMAP), *COMPANIONS.items()]:
        body = path.read_text(encoding="utf-8")
        # A section split into (short pointer, real content) is fine and is how
        # §6 works: it was finished, so it lives in HISTORY, but the number is
        # kept in the backlog so a §6 reference still lands somewhere sensible.
        # A pointer is short and links to the file that holds the real thing.
        for match in re.finditer(r"(?m)^## (\d+[a-z]?)\. .*?(?=\n## |\Z)", body, re.S):
            number, section = match.group(1), match.group(0)
            is_pointer = len(section.split("\n")) < 10 and ".md)" in section
            if is_pointer:
                continue
            assert number not in seen, (
                f"§{number} has real content in both {seen[number]} and {label}"
            )
            seen[number] = label
    missing = [str(n) for n in range(1, 37) if str(n) not in seen]
    assert not missing, f"these sections resolve nowhere: {missing}"


def test_every_file_points_at_the_others():
    """Entering from any one of the four has to lead to the rest, that is the
    whole defence against reading one and stopping."""
    roadmap = ROADMAP.read_text(encoding="utf-8")
    for name in COMPANIONS:
        assert f"roadmap/{name}.md" in roadmap, f"ROADMAP.md never links to {name}.md"
    for name, path in COMPANIONS.items():
        body = path.read_text(encoding="utf-8")
        assert "../ROADMAP.md" in body, f"{name}.md never links back to ROADMAP.md"
        for other in COMPANIONS:
            if other != name:
                assert f"{other}.md" in body, f"{name}.md never links to {other}.md"


def test_the_two_load_bearing_facts_are_flagged_from_the_entry_point():
    """Someone reading only the first screen of ROADMAP.md must still learn
    that finished work and the licence constraint live elsewhere."""
    roadmap = ROADMAP.read_text(encoding="utf-8")
    # Anchored on the heading, not on a sentence inside it. This used to slice
    # at the literal "Ordered by *how much it unlocks*", which is prose: so
    # restructuring the list (exactly the thing this file is meant to survive)
    # made the assert raise `substring not found` rather than fail with a
    # reason. "Everything before the first list item" is the durable boundary.
    marker = "## Next up"
    assert marker in roadmap, "ROADMAP.md no longer has a 'Next up' section"
    opening = roadmap[: roadmap.index(marker)]
    assert "AGPL" in opening and "MIT" in opening
    assert "HISTORY.md" in opening


def test_the_standing_caveat_survived_the_split():
    """It is the one warning that applies to every file, and the easiest thing
    to lose when a document is cut up."""
    opening = ROADMAP.read_text(encoding="utf-8")[:6000]
    assert "fake transport" in opening


def test_the_entry_point_stayed_readable():
    """The split exists because 4,500 lines is not readable in one sitting.
    A ROADMAP.md that grows back past this has quietly undone it."""
    assert len(ROADMAP.read_text(encoding="utf-8").split("\n")) < 2000
