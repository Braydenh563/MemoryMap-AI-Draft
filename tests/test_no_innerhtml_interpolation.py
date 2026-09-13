"""No innerHTML built from an interpolated template (WORLD_CLASS_PLAN 10, F8).

Both sites that did this interpolated app-controlled strings, but the shape
is the XSS shape and the next author will interpolate a title. setLabel()
builds the same icon-plus-text with DOM nodes. Static, because the suite
cannot run the DOM.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PATTERN = re.compile(r"innerHTML\s*=\s*`[^`]*\$\{")


def test_no_innerhtml_assignment_interpolates():
    hits = []
    for path in FRONTEND.glob("*.js"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line):
                hits.append(f"{path.name}:{number}")
    assert not hits, "innerHTML built from a template with ${...}; use setLabel() or DOM nodes:\n" + "\n".join(hits)
