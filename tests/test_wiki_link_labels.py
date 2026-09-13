"""A note link shows the note's words, not the syntax it opens with.

Reported: *"note links have inline md not rendered or suppressed, when an ai
mentions a note that starts with a note that has a '# text' hashtag md
heading, it will write the hashtag"*, with a screenshot of
`[[# Girl with bell]]` drawn as "# Girl with bell" in both the editor and the
preview pane.

The raw text has to stay in the document: the `[[` picker inserts the target
note's first line verbatim, `# ` and all, and `resolveWikiTarget` matches that
form because every link already written in every existing note is in it.
Cleaning the stored text would break the links; cleaning the *label* is the
fix, and it is the same treatment `noteLabel` already gives a chat badge
(INBOX 35 and 40: "a badge is not a source view"), finally applied to the
other place a note's opening words are drawn as a control.

Asserted against the source because the label is built in the browser. The
behaviour itself was driven in Chromium: `wikiLinkLabel` maps
"# Girl with bell" to "Girl with bell", "**Ice Breakers:**" to "Ice Breakers:",
leaves ordinary prose alone and falls back to the raw name for "###"; and
`renderNoteText` on `**Links**: [[# Girl with bell]], [[I'm taking one IT
subject]]` produced chips reading "Girl with bell" and "I'm taking one IT
subject".
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
DOCUMENTS_JS = (ROOT / "frontend" / "documents.js").read_text(encoding="utf-8")


def test_the_helper_exists_and_falls_back():
    """A link whose text is nothing but markers is still a link somebody
    typed, and a button with no words in it cannot be clicked on purpose."""
    body = re.search(r"function wikiLinkLabel\(name\) \{(.*?)\n\}", APP_JS, re.S)
    assert body, "wikiLinkLabel is gone or has been renamed"
    assert "notePreviewText" in body.group(1), (
        "wikiLinkLabel no longer reuses notePreviewText, which is the one "
        "place that knows how this app strips markdown for a one-line label"
    )
    assert "|| name" in body.group(1), "the fallback to the raw name is gone"


def test_every_wiki_link_label_goes_through_it():
    """Three places draw a `[[name]]` as a control: the note renderer, the
    document-target branch beside it, and the documents pane's own renderer.
    A fourth added without the helper is this report coming back."""
    sites = []
    for filename, source in (("app.js", APP_JS), ("documents.js", DOCUMENTS_JS)):
        for match in re.finditer(r'className = "wiki-link";(.{0,400})', source, re.S):
            tail = match.group(1)
            # The label assignment for this button, whichever variable it uses.
            assignment = re.search(r"\.textContent = ([^;]+);", tail)
            if not assignment:
                continue
            if "wikiLinkLabel" in assignment.group(1) or "wikiLinkLabel" in tail[: assignment.start()]:
                continue
            line = source.count("\n", 0, match.start()) + 1
            sites.append(f"{filename}:{line} {assignment.group(1).strip()}")
    assert not sites, (
        "these wiki links draw their raw text, so a note whose first line is a "
        "markdown heading shows its `#` as part of the link: pass the label "
        "through wikiLinkLabel: " + ", ".join(sites)
    )


def test_the_resolver_still_matches_the_raw_form():
    """The other half of the decision, and the one that breaks silently: the
    label is cleaned, the stored text is not, so resolution must keep matching
    a `[[# Heading]]` written by the picker."""
    assert "openingTitle" in APP_JS, (
        "resolveWikiTarget no longer strips a heading marker from the content "
        "it compares, so a hand-typed link to a note that starts with a "
        "heading resolves to nothing"
    )
    assert re.search(r"replace\(/\^#\{1,6\}\[ \\t\]\*/, \"\"\)", APP_JS), (
        "the heading-marker strip in resolveWikiTarget has changed shape; "
        "check it still accepts one to six hashes and any spacing"
    )
