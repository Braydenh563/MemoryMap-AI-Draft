"""A word added to the writing dictionary is still there tomorrow.

Reported: *"I swear I added 'idk' to the dictionary last night, make sure it
is persistent."* It was added, and then it was destroyed, by the browser
rather than by the server.

`docDictionary()` in documents.js memoised its `Set` with
`if (!docDictionarySet)`. An empty `Set` is truthy, so whatever the first call
built was the dictionary for the rest of the session, and the first call comes
from `renderDocTools()` on the last line of that file, which runs while
`prefsCache` is still null because the preferences fetch in app.js has not
resolved. Two consequences, the second of which is the report:

1. every word already in the dictionary read as unknown, all session;
2. `docDictionaryWrite` sends `[...docDictionary(), word]`, so the first word
   added after a page load replaced the whole stored list with that one word.

The server half was always right, which is why this file checks both: the
round trip through `/preferences` (so a regression there is caught too), and
the source shape in the browser, which is where the bug actually was and which
no Python test can otherwise see.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"


def test_the_server_keeps_the_words_it_is_given(client):
    client.put("/preferences", json={"writing_dictionary": ["idk", "memorymap"]})
    stored = client.get("/preferences").json()["writing_dictionary"]
    assert sorted(stored) == ["idk", "memorymap"]

    # A second word does not displace the first: the list is replaced whole by
    # design, so the browser sends the union, and this is the call it makes.
    client.put("/preferences", json={"writing_dictionary": ["idk", "memorymap", "uvicorn"]})
    assert sorted(client.get("/preferences").json()["writing_dictionary"]) == [
        "idk",
        "memorymap",
        "uvicorn",
    ]


def test_a_word_survives_a_restart(app_state, client):
    """The point of the report: *last night*. A preference read by a new
    process has to come back off disk, not out of the process that wrote it."""
    from memorymap.api.app import create_app
    from fastapi.testclient import TestClient

    client.put("/preferences", json={"writing_dictionary": ["idk"]})

    fresh = TestClient(create_app())
    token = client.headers.get("X-Auth-Token")
    if token:
        fresh.headers["X-Auth-Token"] = token
    again = fresh.get("/preferences")
    assert again.status_code == 200, again.text
    assert again.json()["writing_dictionary"] == ["idk"]


def test_the_browser_rebuilds_its_set_when_preferences_change():
    """The lint, and the half that was broken.

    `docDictionary()` must read `prefsCache` on every call and rebuild when it
    is not the array the set was built from. A version that memoises on the
    truthiness of the set alone is the bug, and it reads as correct.
    """
    source = DOCUMENTS_JS.read_text(encoding="utf-8")
    body = re.search(r"function docDictionary\(\) \{(.*?)\n\}", source, re.S)
    assert body, "docDictionary() is gone or has been renamed"
    text = body.group(1)

    assert "prefsCache" in text, (
        "docDictionary() no longer reads prefsCache inside the function, so a "
        "preferences reload cannot reach it"
    )
    assert "docDictionarySource" in text, (
        "docDictionary() no longer compares the array it built from, so the "
        "first call wins for the session: an empty Set is truthy, and the "
        "first call runs before the preferences fetch resolves"
    )
    assert not re.search(r"if \(!docDictionarySet\) \{", text), (
        "this is the exact memoisation that lost the dictionary: an empty Set "
        "is truthy, so a set built before preferences arrived was never "
        "rebuilt and the next add overwrote the stored list"
    )


def test_the_optimistic_add_is_pinned_to_the_preferences_it_speaks_for():
    """The other half: `docDictionaryWrite` sets the new set before its PUT
    resolves, so it must also claim the current source, or a read in that
    window rebuilds from the old array and throws the new word away."""
    source = DOCUMENTS_JS.read_text(encoding="utf-8")
    body = re.search(r"async function docDictionaryWrite\(words\) \{(.*?)\n\}", source, re.S)
    assert body, "docDictionaryWrite() is gone or has been renamed"
    assert "docDictionarySource =" in body.group(1), (
        "docDictionaryWrite no longer pins docDictionarySource, so a read "
        "between the optimistic set and the server's answer drops the word"
    )
