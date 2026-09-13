"""No em-dashes in the app's own files.

Asked for directly: "remove ALL INSTANCES of em-dashes, they give the
vibe-coded feel." The sweep (scratchpad/emdash.py) removed 10,879 of them
from frontend/, src/ and tests/; this keeps them out. Vendored third-party
files are excluded because they are not this app's copy. Fix a hit by
rewriting the sentence (a colon, a comma or a full stop), never by
substituting an en-dash.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOTS = (ROOT / "frontend", ROOT / "src", ROOT / "tests")
EXTS = {".js", ".html", ".css", ".py", ".json", ".md", ".txt"}
SKIP_PARTS = {"vendor", "node_modules", "__pycache__"}
EM_DASH = chr(0x2014)  # built, not written, so this file passes its own check


def _files():
    for root in ROOTS:
        for path in root.rglob("*"):
            if path.suffix in EXTS and not (SKIP_PARTS & set(path.parts)):
                yield path


def test_the_apps_own_files_carry_no_em_dash():
    hits = []
    for path in _files():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if EM_DASH in line:
                hits.append(f"{path.relative_to(ROOT)}:{number}")
    assert not hits, (
        "an em-dash in the app's own files; rewrite the sentence "
        "(colon, comma or full stop), never an en-dash:\n" + "\n".join(hits[:40])
    )
