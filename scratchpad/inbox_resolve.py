"""Move resolved INBOX items to HISTORY.md ("INBOX resolved").

    python scratchpad/inbox_resolve.py 74 82 91

Each numbered item (from its "N. **" line to the next item or section) is
cut from docs/roadmap/INBOX.md and appended under HISTORY.md's
"## INBOX resolved, <today>" section, number kept. The plan-hygiene lint
fails on a "Fixed" item left in INBOX, so mark and move in the same commit.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "docs" / "roadmap" / "INBOX.md"
HISTORY = ROOT / "docs" / "roadmap" / "HISTORY.md"


def main(numbers: list[str]) -> int:
    wanted = {int(n) for n in numbers}
    text = INBOX.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=\d+\. \*\*)", text)
    kept, moved = [parts[0]], []
    for part in parts[1:]:
        match = re.match(r"^(\d+)\. \*\*", part)
        number = int(match.group(1)) if match else -1
        tail = ""
        section = re.search(r"(?m)^## ", part)
        if section:
            tail = part[section.start():]
            part = part[: section.start()]
        if number in wanted:
            moved.append(part.rstrip("\n") + "\n")
            if tail:
                kept.append(tail)
        else:
            kept.append(part + tail)
    if not moved:
        print("nothing moved: numbers not found")
        return 1
    INBOX.write_text("".join(kept), encoding="utf-8")
    today = datetime.date.today().isoformat()
    history = HISTORY.read_text(encoding="utf-8").rstrip("\n")
    heading = f"\n## INBOX resolved, {today}\n"
    block = "".join(moved)
    if heading in history:
        head, rest = history.split(heading, 1)
        # append at the end of that section (before the next "## " heading)
        nxt = re.search(r"(?m)^## ", rest)
        if nxt:
            rest = rest[: nxt.start()].rstrip("\n") + "\n\n" + block + "\n" + rest[nxt.start():]
        else:
            rest = rest.rstrip("\n") + "\n\n" + block
        history = head + heading + rest
    else:
        history += heading + "\n" + block
    HISTORY.write_text(history + "\n", encoding="utf-8")
    print(f"moved {len(moved)} item(s) to HISTORY.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
