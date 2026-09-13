"""Remove every em-dash from the app's own files, with the punctuation a
careful editor would have used instead.

Asked for directly: "remove ALL INSTANCES of em-dashes, they give the
vibe-coded feel." Rules, applied per line:
- "— " at the start of a line (a bullet) becomes "- ".
- Two or more dashes on one line are a parenthetical pair: each becomes ", ".
- A single " — " after a short lead (three words or fewer since the last
  sentence end) is a label and gets ": "; after a longer clause it gets ", ".
- A bare "—" with no spaces becomes ", ".
Run: python scratchpad/emdash.py [paths...]  (defaults to frontend src tests)
"""
import re
import sys
from pathlib import Path

EXTS = {".js", ".html", ".css", ".py", ".md", ".txt", ".json"}
def fix_line(line: str) -> str:
    if "—" not in line:
        return line
    if line.lstrip().startswith("— "):
        indent = line[: len(line) - len(line.lstrip())]
        line = indent + "- " + line.lstrip()[2:]
    if line.count("—") >= 2:
        line = line.replace(" — ", ", ").replace("—", ", ")
        return line
    m = re.search(r"\s*—\s*", line)
    if not m:
        return line
    before = line[: m.start()]
    # Words since the last sentence end or the start of the string literal.
    tail = re.split(r"[.!?:;]\s+|[\"'`]|<[^>]*>|\{|\(|\[", before)[-1]
    words = [w for w in tail.strip().split() if re.search(r"\w", w)]
    joiner = ": " if 0 < len(words) <= 3 else ", "
    return line[: m.start()] + joiner + line[m.end():]


def fix_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    if "—" not in text:
        return 0
    lines = text.split("\n")
    out = [fix_line(line) for line in lines]
    new = "\n".join(out)
    path.write_text(new, encoding="utf-8")
    return text.count("—") - new.count("—")


def main(argv):
    roots = [Path(a) for a in argv] or [Path("frontend"), Path("src"), Path("tests")]
    total = 0
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.suffix in EXTS and "__pycache__" not in p.parts and "vendor" not in p.parts and "node_modules" not in p.parts]
        for f in files:
            n = fix_file(f)
            if n:
                total += n
                print(f"{f}: {n}")
    print(f"removed {total}")


if __name__ == "__main__":
    main(sys.argv[1:])
