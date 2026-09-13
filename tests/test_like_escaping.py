"""A search for `100%` must find the note that says `100%`, not every note.

`%` and `_` are LIKE wildcards, and nothing in a search box says so. Every
search in this app went through `.ilike(f"%{term}%")` with the term dropped in
raw, so `100%` matched every row in the table and `a_b` matched `axb`. Not
injection (the value is still a bound parameter), but a search that quietly
answers a different question than the one asked, and a person who types a
percent sign has no way to tell. WORLD_CLASS_PLAN section 12, S7.

Two halves have to be right, and only one of them is visibly wrong when it is
not: the pattern must be escaped (`like_escape`), and the statement must say
what the escape character is (`escape=LIKE_ESCAPE`). A pattern escaped without
the second half finds *nothing*, because SQLite then reads the backslash as an
ordinary character. So this file checks behaviour through the API for the
searches a person uses, and then greps the source for the pairing, because a
new call site is how this comes back.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "memorymap"


def test_escaping_and_unescaping_round_trips():
    from memorymap.core.database import like_escape

    assert like_escape("100%") == r"100\%"
    assert like_escape("a_b") == r"a\_b"
    # The backslash is escaped first, or escaping `%` would double-escape the
    # backslash the function itself inserts.
    assert like_escape(r"c:\x") == r"c:\\x"
    assert like_escape("plain") == "plain"


def test_a_document_search_for_a_percent_finds_only_the_percent(client):
    client.post("/documents", json={"title": "Budget", "content": "we are at 100% now"})
    client.post("/documents", json={"title": "Notes", "content": "nothing numeric here"})
    client.post("/documents", json={"title": "Other", "content": "another document"})

    hits = client.get("/documents", params={"q": "100%"}).json()
    assert [d["title"] for d in hits] == ["Budget"]

    # The wildcard meaning is gone in both directions: a bare `%` is now a
    # search for a percent sign, not a search for everything.
    assert [d["title"] for d in client.get("/documents", params={"q": "%"}).json()] == [
        "Budget"
    ]


def test_an_underscore_is_a_character_not_a_wildcard(client):
    client.post("/documents", json={"title": "Snake", "content": "a_b is the key"})
    client.post("/documents", json={"title": "Near", "content": "axb is not the key"})

    hits = client.get("/documents", params={"q": "a_b"}).json()
    assert [d["title"] for d in hits] == ["Snake"]


def test_conversation_search_escapes_the_same_way(client):
    """A conversation is created by its first question, which becomes the
    title, so the search term has to travel through a real turn."""
    made = client.post(
        "/conversations", json={"question": "Costs at 100%", "answer": "yes"}
    ).json()
    client.post("/conversations", json={"question": "Something else", "answer": "no"})

    hits = client.get("/conversations", params={"q": "100%"}).json()
    assert [c["id"] for c in hits] == [made["id"]]


def test_every_like_call_site_escapes_or_is_a_literal_pattern():
    """The lint. A `.like(`/`.ilike(` whose pattern is built from a value must
    pass `escape=LIKE_ESCAPE`; one whose pattern is a string literal in the
    source (`"image/%"`, a deliberate wildcard) needs nothing.

    Call sites are matched across line breaks because the escaped form is
    usually too long for one line, which is exactly why a plain line-by-line
    grep would have passed the code this test was written against.
    """
    call = re.compile(r"\.i?like\(", re.MULTILINE)
    literal_only = re.compile(r'^\s*"[^"{}]*"\s*\)')
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in call.finditer(text):
            tail = text[match.end() : match.end() + 400]
            line = text.count("\n", 0, match.start()) + 1
            if literal_only.match(tail.replace("\n", " ")) or literal_only.match(tail):
                continue
            # The call ends at its own closing paren; nesting here is shallow
            # (one f-string, one keyword), so a depth count is enough.
            depth, end = 1, 0
            for index, char in enumerate(tail):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            body = tail[:end]
            if "escape=LIKE_ESCAPE" not in body:
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, (
        "these LIKE patterns take user text without declaring an escape "
        "character, so a `%` in the text is a wildcard: " + ", ".join(offenders)
    )
