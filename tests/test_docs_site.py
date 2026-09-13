"""The GitHub Pages site can actually load its own documentation.

Reported: *"the embedded documentation still won't load, even when I have my
adblockers turned off."* Two previous fixes had been aimed at the fetch logic, 
a malformed fallback URL, then a same-origin candidate, and neither could
work, because of something outside the JavaScript entirely:

**there was no `.nojekyll`.** GitHub Pages runs Jekyll over `/docs` by default,
and Jekyll does not publish source `.md` files: it *converts* them. So
`ARCHITECTURE.md` was never at that origin at all, the same-origin fetch 404'd
on every load for everyone, and the whole feature rested on two cross-origin
hosts. That is exactly the shape of "it won't load even with the adblocker
off". Jekyll was also reading `{{placeholders}}` in the docs as Liquid
variables and rendering them away.

The second half is that three of the eight documents live at the repo root,
which Pages never publishes under this source setting. They are copied into
`/docs`, and this file is what stops the copies drifting, a stale copy of
SECURITY.md on the public site is worse than no copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SITE = DOCS / "index.html"

#: Files that live at the repo root and are mirrored into /docs for the site.
MIRRORED = ("CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md")


def test_jekyll_is_switched_off():
    """The whole fix. Without this file Pages processes /docs with Jekyll,
    which means the markdown this site fetches is not served at all."""
    assert (DOCS / ".nojekyll").exists(), (
        "docs/.nojekyll is missing. Without it GitHub Pages runs Jekyll over "
        "the docs folder, .md sources are converted rather than published, and "
        "every same-origin documentation fetch on the site 404s."
    )


@pytest.mark.parametrize("name", MIRRORED)
def test_the_mirrored_docs_match_the_originals(name):
    """A copy that has drifted is worse than no copy: the public site would be
    confidently showing an old security policy."""
    original = (ROOT / name).read_text(encoding="utf-8")
    mirrored = (DOCS / name).read_text(encoding="utf-8")
    assert mirrored == original, (
        f"docs/{name} has drifted from {name} at the repo root. The site serves "
        f"the copy, because Pages publishes /docs only, re-copy it: "
        f"cp {name} docs/{name}"
    )


def test_every_document_the_site_offers_is_actually_there():
    """Each tab's `same:` path is what the page fetches from its own origin.
    A tab pointing at a file that is not published is a tab that spins and
    then shows an error, which is the bug this whole file is about."""
    source = SITE.read_text(encoding="utf-8")
    block = re.search(r"const DOC_MAP = \{(.*?)\n\};", source, re.S)
    assert block, "DOC_MAP not found in docs/index.html"
    paths = re.findall(r"same:\s*'([^']+)'", block.group(1))
    assert len(paths) >= 8, "expected every documentation tab to load same-origin"
    for path in paths:
        assert (DOCS / path).is_file(), (
            f"docs/index.html offers '{path}' but docs/{path} does not exist, "
            "so that tab cannot load from the site's own origin."
        )


def test_every_tab_has_an_entry_and_every_entry_has_a_tab():
    """A button with no map entry throws; a map entry with no button is a
    document nobody can reach."""
    source = SITE.read_text(encoding="utf-8")
    buttons = set(re.findall(r'class="dpill[^"]*"\s+data-doc="([^"]+)"', source))
    block = re.search(r"const DOC_MAP = \{(.*?)\n\};", source, re.S)
    keys = set(re.findall(r"^\s{2}(\w+):\s*\{", block.group(1), re.M))
    assert buttons == keys, (
        f"documentation tabs and DOC_MAP disagree: "
        f"buttons only={buttons - keys}, map only={keys - buttons}"
    )
