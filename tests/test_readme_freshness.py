"""The README's numbers and names are checked against the code.

The owner: "the readme and related documents keep going stale because you
forget them". A number in the README that the code can compute is asserted
here, so a tool added, a skill added or a version bump fails the build until
the README says the same.
"""

from __future__ import annotations

import re
from pathlib import Path

from memorymap import __version__
from memorymap.ai import skills, tools

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_tool_count_matches_the_registry() -> None:
    assert f"has {len(tools.TOOLS)} tools" in README, (
        f"README says a different tool count; the registry has {len(tools.TOOLS)}"
    )


def test_the_skill_count_matches_the_built_ins() -> None:
    assert f"{len(skills.BUILTIN_SKILLS)} built-in skills" in README


def test_the_version_matches_the_package() -> None:
    assert f"Version {__version__}." in README


def test_the_mode_names_are_the_current_ones() -> None:
    """Request mode was renamed Agent mode (CHAT batch B); the README kept
    the old name for a day."""
    assert "Request mode" not in README
    assert "Agent mode" in README


def test_the_test_count_claim_is_not_stale_by_an_order() -> None:
    """A rough gate: the README's "N,000+ tests" must be within one thousand
    of the collected count, which the suite knows without running."""
    claim = re.search(r"(\d),000\+ tests", README)
    assert claim, "README should state the test count as N,000+ tests"
    files = list((ROOT / "tests").glob("test_*.py"))
    approx = sum(len(re.findall(r"^\s*def test_", f.read_text(encoding='utf-8'), re.M)) for f in files)
    assert int(claim.group(1)) * 1000 <= approx < (int(claim.group(1)) + 2) * 1000, (
        f"README claims {claim.group(0)}, the tree defines about {approx}"
    )


def test_every_screenshot_the_readme_shows_is_on_disk() -> None:
    """A picture the README points at has to exist, and no more than that.

    The tour is the first thing anyone sees, and a renamed or deleted capture
    shows up on GitHub as a broken-image glyph with the alt text underneath,
    which reads as an abandoned project rather than as a missing file. Nothing
    else in the suite opens the README's `<img>` tags.

    The second half is the same rule pointing the other way: a capture nobody
    shows is a file that will go stale silently, since the recapture script
    (`scratchpad/ui-sweeps/readmeshots.js`) writes the set it knows about and
    leaves anything else at whatever version of the UI it was taken from.
    """
    shown = set(re.findall(r'src="docs/screenshots/([\w.-]+)"', README))
    assert shown, "the README shows no screenshots at all"
    on_disk = {path.name for path in (ROOT / "docs" / "screenshots").glob("*.png")}
    missing = sorted(shown - on_disk)
    assert not missing, f"the README points at screenshots that do not exist: {missing}"
    orphans = sorted(on_disk - shown)
    assert not orphans, (
        f"these screenshots are in docs/screenshots but shown nowhere: {orphans}. "
        "Show them in the README or delete them; an unshown capture is one "
        "nothing keeps up to date."
    )
