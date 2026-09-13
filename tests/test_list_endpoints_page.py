"""Every list that grows with the notebook takes a page, and the rest say why.

WORLD_CLASS_PLAN section 10, F2: "25 list endpoints, 3 accept `limit`. Every
list is O(notebook)." Three have been paged since (documents, reminders,
media, then entries and the chat list), and the rest were never triaged, so
the row stayed true and nothing said which of the remaining ones actually
matter.

This is that triage, kept honest by a lint rather than by a memo. The rule:
a `list_*` route either takes a `limit`, or it is named below with the reason
its size is bounded by something other than how much the person has written.
A new list endpoint fails this test until its author decides which it is,
which is the whole point: the decision is cheap to make while writing it and
expensive to find afterwards, when a notebook of ten thousand notes hands the
browser a response nobody measured.

**Bounded by the app** means the row count is set by this codebase: the chat
modes it ships, the file types it knows, the skills in its own folder. Those
can be listed whole for ever. **Bounded by the notebook** means the person's
own writing decides it, and that is what needs a page.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "src" / "memorymap" / "api"

#: Lists whose size this app decides, with the reason each is bounded. Adding
#: a row here is a claim that can be checked by reading the code it names.
BOUNDED_BY_THE_APP = {
    "list_modes": "the chat modes this app ships, a fixed list in code",
    "list_tools": "the AI tools this app defines, a fixed list in code",
    "list_file_types": "the file types this app knows how to read",
    "list_embedding_models": "the embedding models this app offers",
    "list_extras": "the optional installs this app knows about",
    "list_skills": "the skill folders shipped with the app plus a handful the person adds",
    "list_releases": "the last few releases, already capped by the GitHub call",
    "list_backups": "one row per backup file the person made on purpose, and they are large and few",
    "list_memory": "the facts the person told the assistant to remember, a short list by design",
    "list_duplicates": "pairs above a similarity threshold, already capped by the scan that finds them",
    "list_orphaned_media": "uploads no note references, which is a cleanup screen and empty in a healthy notebook",
    "list_tasks": "the jobs running or recently finished in this process, capped by the task history",
    "list_ai_edits": "the AI edits on one document, bounded by that document's own history",
    "list_attachment_gallery": "the images attached to one note, bounded by that note",
}


def _list_routes():
    """Every `list_*` route function with its argument list."""
    pattern = re.compile(r"^(?:async )?def (list_\w+)\((.*?)\)\s*->", re.S | re.M)
    for path in sorted(ROUTES.glob("routes_*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield path.name, match.group(1), match.group(2), line


def test_every_growing_list_takes_a_page():
    unpaged = []
    for filename, name, args, line in _list_routes():
        if "limit" in args:
            continue
        if name in BOUNDED_BY_THE_APP:
            continue
        unpaged.append(f"{filename}:{line} {name}")
    assert not unpaged, (
        "these list endpoints grow with the notebook and hand back all of it: "
        "give each a `limit` (and an `X-Total-Count`, so a caller that wants "
        "everything can page), or name it in BOUNDED_BY_THE_APP with the "
        "reason its size is not the person's to grow: " + ", ".join(unpaged)
    )


def test_the_bounded_list_is_not_carrying_a_name_that_no_longer_exists():
    """A reason written for a route that has since been renamed is an
    exemption nobody is reading, waiting for the name to be reused."""
    live = {name for _file, name, _args, _line in _list_routes()}
    stale = sorted(name for name in BOUNDED_BY_THE_APP if name not in live)
    assert not stale, f"exempted but no longer a route: {stale}"


def test_a_paged_list_says_how_many_there_are(client):
    """A page without a total is a page a caller cannot finish: `apiPagedList`
    in the browser loops until `X-Total-Count` is satisfied, so a list that
    pages silently is one the frontend reads exactly one page of."""
    for index in range(3):
        client.post("/documents", json={"title": f"Doc {index}"})
        client.post("/entries", json={"content": f"Note {index}"})

    for path in ("/documents", "/entries", "/conversations", "/media", "/reminders"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "X-Total-Count" in response.headers, f"{path} pages without saying how many there are"


def test_a_bookmark_past_the_page_is_still_reachable(client):
    """The same question INBOX 117 asked of documents, asked of the lists
    paged after it: is everything still reachable through `offset`?"""
    from memorymap.api import routes_bookmarks

    size = routes_bookmarks.BOOKMARKS_PAGE_SIZE
    for index in range(size + 3):
        client.post("/bookmarks", json={"url": f"https://example.test/{index}"})

    first = client.get("/bookmarks")
    assert len(first.json()) == size
    assert first.headers["X-Total-Count"] == str(size + 3)
    rest = client.get("/bookmarks", params={"offset": size})
    assert len(rest.json()) == 3
    seen = {b["id"] for b in first.json()} | {b["id"] for b in rest.json()}
    assert len(seen) == size + 3


def test_the_tag_and_category_lists_say_how_many_there_are(client):
    """Neither is a list anyone pages through: both feed a picker, and a
    picker showing the first page of your tags is a picker that lost some. The
    cap is a guard against a pathological notebook, and the count is what says
    it bit."""
    client.post("/entries", json={"content": "A note", "tags": ["alpha", "beta"]})

    tags = client.get("/tags")
    assert tags.headers["X-Total-Count"] == str(len(tags.json()))
    categories = client.get("/categories")
    assert categories.headers["X-Total-Count"] == str(len(categories.json()))
