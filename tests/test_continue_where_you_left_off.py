"""Opening a note counts as coming back to it.

Reported: *"the opens a note you opened or edited most recently button doesnt
update and just shows my latest note"*.

The dashboard's Continue pill promised "opened or edited" and ranked on
`updated_at` alone. `updated_at` moves when the text changes, so the one case
the pill exists for, going back to something you were *reading*, was the one
case it could not serve: whatever you wrote last stayed on the pill however
many old notes you opened afterwards.

The entry already carried `access_count`, which says how many times without
ever saying when. `last_opened_at` is the missing half, stamped on the same
path, under the same guard: a note read on its way out of the bin has not been
come back to, and must not climb this ranking.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = ROOT / "frontend" / "dashboard.js"


def test_opening_an_entry_stamps_when(client):
    made = client.post("/entries", json={"content": "A note to come back to"}).json()
    assert client.get("/entries", params={"limit": 5}).json()[0]["last_opened_at"] is None

    opened = client.get(f"/entries/{made['id']}").json()
    assert opened["last_opened_at"], "opening an entry did not record when"
    assert opened["access_count"] == 1


def test_the_older_note_wins_once_you_open_it(client):
    """The report, as a test. Note A is written first, note B second, so B is
    the newest by every timestamp the old ranking looked at. Opening A has to
    put A back in front."""
    first = client.post("/entries", json={"content": "The older note"}).json()
    second = client.post("/entries", json={"content": "The newer note"}).json()

    client.get(f"/entries/{first['id']}")

    rows = {row["id"]: row for row in client.get("/entries", params={"limit": 50}).json()}

    def touched(row):
        return max(
            value
            for value in (row.get("last_opened_at"), row.get("updated_at"), row.get("created_at"))
            if value
        )

    assert touched(rows[first["id"]]) > touched(rows[second["id"]]), (
        "the note just opened does not rank above the note written after it, "
        "so the Continue pill still points at whatever is newest"
    )


def test_reading_a_binned_note_is_not_coming_back_to_it(client):
    """The same guard `access_count` already has, for the same reason: a note
    you looked at on the way to deleting it for good is not where you left
    off."""
    made = client.post("/entries", json={"content": "On its way out"}).json()
    client.delete(f"/entries/{made['id']}")

    read = client.get(f"/entries/{made['id']}", params={"deleted": "true"})
    assert read.status_code == 200, read.text
    assert read.json()["last_opened_at"] is None
    assert read.json()["access_count"] == 0


def test_the_pill_ranks_on_both_and_says_so():
    """The browser half. A ranking that reads one field is the bug; a hint
    that promises two while the code reads one is how it stayed hidden."""
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    body = re.search(r"async function renderContinueLink\(row\) \{(.*?)\n\}", source, re.S)
    assert body, "renderContinueLink is gone or has been renamed"
    assert "last_opened_at" in body.group(1), (
        "the Continue pill no longer reads last_opened_at, so opening a note "
        "does not move it"
    )
    assert "Opens the note you opened or edited most recently" in source, (
        "the pill's hint no longer matches what it ranks on"
    )
