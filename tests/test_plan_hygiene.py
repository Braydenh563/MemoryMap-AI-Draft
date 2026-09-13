"""A plan holds open work only; what is built lives in HISTORY.md.

The owner, after the fourth time: "you, opus and sonnet have just marked
things as built in the roadmap and not actually moved them to history.md
... if they are fully built, they should not take up room where new
features, fixes and refinements should be." CLAUDE.md standing order 10.
"""

from __future__ import annotations

import re
from pathlib import Path

ROADMAP = Path(__file__).resolve().parent.parent / "docs" / "roadmap"
ROOT = Path(__file__).resolve().parent.parent

#: Directories the conflict-marker sweep below never walks: a checkout's own
#: plumbing, a virtual environment's vendored packages, and the browser
#: profiles the sweeps leave behind, none of which this project writes.
_SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".gate", "shots"}


def _skip(path: Path) -> bool:
    return any(part in _SKIP_PARTS for part in path.parts)
PLANS = sorted(ROADMAP.glob("*_PLAN.md")) + [ROADMAP / "AGENT_SKILLS_REFORM.md"]


def test_no_plan_carries_a_built_block() -> None:
    offenders = []
    for plan in PLANS:
        for line in plan.read_text(encoding="utf-8").splitlines():
            if re.match(r"^#{2,3} (\d+\. )?Built\b", line):
                body = plan.read_text(encoding="utf-8")
                after = body.split(line, 1)[1][:300]
                if "Moved to HISTORY.md" not in after:
                    offenders.append(f"{plan.name}: {line}")
    assert offenders == [], (
        "move these blocks whole into HISTORY.md ('Moved from the plans') and leave "
        "the one-line pointer: " + "; ".join(offenders)
    )


def test_handover_is_the_current_state_only() -> None:
    lines = (ROADMAP / "HANDOVER.md").read_text(encoding="utf-8").count("\n")
    assert lines < 600, f"HANDOVER.md is {lines} lines; append the session record to HISTORY.md"


def test_inbox_holds_open_reports_only() -> None:
    """A resolved report (fixed, not reproduced, checked) moves to HISTORY.md's
    "INBOX resolved" with its number; INBOX is what is still open."""
    text = (ROADMAP / "INBOX.md").read_text(encoding="utf-8")
    resolved = [
        line for line in text.splitlines()
        if re.match(r"^\d+\. \*\*\(?(fixed|Fixed|Not reproduced|checked|Checked|Done|done)", line)
    ]
    assert resolved == [], "move these to HISTORY.md, INBOX resolved: " + "; ".join(r[:60] for r in resolved)


def test_inbox_is_a_tray_not_a_backlog() -> None:
    """Under twenty open items: anything older is placed in its plan."""
    text = (ROADMAP / "INBOX.md").read_text(encoding="utf-8")
    count = len(re.findall(r"(?m)^\d+\. \*\*", text))
    assert count < 20, f"INBOX has {count} items; place the rest in their plans (Placed from INBOX)"


def test_no_conflict_marker_survives_a_merge():
    """A merge conflict must never reach the branch.

    It did, on 2026-09-09: three worktrees were merged in one shell loop with
    each merge piped to `tail`, so the pipeline's exit status was `tail`'s,
    `set -e` never saw the failure, the loop carried on, and the `git add -A`
    that follows the gate staged the conflicted files and committed them.
    Every lint in `scripts/gate.sh` passed, because none of them looked for a
    marker, and the result was pushed.

    Text files only, and the markers are built from parts so this file does
    not fail on its own source.
    """
    opener = "<" * 7 + " "
    divider = "=" * 7
    closer = ">" * 7 + " "
    offenders = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or _skip(path):
            continue
        if path.suffix.lower() not in {".md", ".py", ".js", ".css", ".html", ".json", ".txt", ".yml", ".yaml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(opener) or line.startswith(closer) or line.rstrip() == divider:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], (
        "an unresolved merge conflict is committed; resolve it rather than "
        "committing the markers:\n" + "\n".join(offenders[:40])
    )
