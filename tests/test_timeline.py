"""The notebook on a time axis (roadmap §10B).

Asked for repeatedly: "I want a note timeline where I can see notes visually
by what time they were made. Maybe I can even group them by events or related
places etc." The axis is time; the bands are what make it a map of what
happened rather than a sorted list.
"""

from __future__ import annotations

from datetime import timedelta

from memorymap.core.database import Entry, utcnow


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def _age(session, note_id: int, days: int) -> None:
    """Backdate a note, so a timeline has more than one column in it."""
    entry = session.get(Entry, note_id)
    entry.created_at = utcnow() - timedelta(days=days)
    session.commit()


def test_an_empty_notebook_is_an_empty_timeline_not_an_error(client):
    body = client.get("/timeline").json()
    assert body["notes"] == [] and body["buckets"] == []


def test_notes_land_in_buckets_on_the_scale_asked_for(client, session):
    old = _save(client, "an older thought")
    _age(session, old["id"], 40)
    _save(client, "a fresh thought")

    monthly = client.get("/timeline?scale=month").json()
    assert len(monthly["buckets"]) == 2, monthly["buckets"]
    assert all(bucket.endswith("-01") for bucket in monthly["buckets"])

    yearly = client.get("/timeline?scale=year").json()
    assert len(yearly["buckets"]) == 1  # 40 days apart is one year


def test_a_note_plots_at_what_it_is_about_not_when_it_was_typed(client, session):
    """The reason this is more than ORDER BY created_at: §10A resolved the
    relative time in note text, so "the deadline is next friday" knows which
    Friday and belongs there."""
    note = _save(client, "the deadline is next friday")
    body = client.get("/timeline?scale=day").json()
    placed = next(n for n in body["notes"] if n["id"] == note["id"])

    assert placed["placed_by"] == "mentioned"
    assert placed["phrase"] == "next friday"
    assert placed["at"] > placed["written_at"], placed
    # A note with no dates in it stays where it was written, and says so.
    plain = _save(client, "no dates in this one")
    again = client.get("/timeline?scale=day").json()
    written = next(n for n in again["notes"] if n["id"] == plain["id"])
    assert written["placed_by"] == "written" and written["phrase"] == ""


def test_bands_are_the_categories_you_actually_write_in(client, session):
    _save(client, "pasta recipe", category="Recipes")
    _save(client, "risotto recipe", category="Recipes")
    _save(client, "a work thing", category="Work")

    body = client.get("/timeline?group=category").json()
    names = [band["name"] for band in body["bands"]]
    assert names[0] == "Recipes", body["bands"]  # biggest first
    assert dict((b["name"], b["count"]) for b in body["bands"]) == {
        "Recipes": 2,
        "Work": 1,
    }


def test_bands_can_be_tags_instead(client):
    _save(client, "a note", tags=["garden"])
    _save(client, "another", tags=["garden", "spring"])
    _save(client, "bare one")

    bands = {b["name"]: b["count"] for b in client.get("/timeline?group=tag").json()["bands"]}
    assert bands["garden"] == 2
    assert bands["spring"] == 1
    assert bands["untagged"] == 1


def test_bands_can_be_threads_a_root_and_its_continuations(client):
    """§87.6: "a note with children sprouts a branch," using the thread
    structure `Entry.parent_id` already stores rather than category or tag."""
    root = _save(client, "trip planning")
    _save(client, "booked flights", parent_id=root["id"])
    _save(client, "booked hotel", parent_id=root["id"])
    _save(client, "a lone note with no children")

    bands = {b["name"]: b["count"] for b in client.get("/timeline?group=thread").json()["bands"]}
    assert bands["trip planning"] == 3
    # The lone note isn't a thread, so it doesn't get its own lane, it
    # folds into the shared band the same way a long tail of small
    # category/tag bands already does.
    from memorymap.api.routes_timeline import THREAD_BAND

    assert bands[THREAD_BAND] == 1


def test_a_thread_whose_root_is_outside_the_window_still_bands(client, session):
    """A parent older than the visible range isn't fetched a second time, 
    the child just becomes a root of its own, the same honest
    simplification the `days` filter already asks the rest of the view to
    accept, rather than a crash or a silently dropped note."""
    root = _save(client, "old root")
    child = _save(client, "a recent continuation", parent_id=root["id"])
    _age(session, root["id"], days=400)

    body = client.get("/timeline?group=thread&days=30").json()
    assert [n["id"] for n in body["notes"]] == [child["id"]]
    bands = {b["name"]: b["count"] for b in body["bands"]}
    from memorymap.api.routes_timeline import THREAD_BAND

    assert bands[THREAD_BAND] == 1


def test_a_long_tail_of_bands_collapses_into_one(client):
    """A chart with forty lanes is not a chart."""
    from memorymap.api.routes_timeline import MAX_BANDS, OTHER_BAND

    for index in range(MAX_BANDS + 4):
        _save(client, f"note {index}", category=f"Cat{index}")

    bands = client.get("/timeline?group=category").json()["bands"]
    assert len(bands) == MAX_BANDS + 1
    assert bands[-1]["name"] == OTHER_BAND
    assert bands[-1]["count"] == 4


def test_grouping_can_be_turned_off(client):
    _save(client, "one", category="Work")
    bands = client.get("/timeline?group=none").json()["bands"]
    assert [band["name"] for band in bands] == ["All notes"]


def test_private_notes_stay_out_of_the_view(client, session):
    """Its text is encrypted at rest; a preview in a chart would undo that."""
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    note = _save(client, "the appointment is tomorrow")
    client.post(f"/entries/{note['id']}/privacy", json={"private": True})

    body = client.get("/timeline").json()
    assert [n["id"] for n in body["notes"]] == []


def test_binned_notes_stay_out_too(client):
    note = _save(client, "a mistake")
    client.delete(f"/entries/{note['id']}")
    assert client.get("/timeline").json()["notes"] == []


def test_a_window_can_be_asked_for(client, session):
    old = _save(client, "ancient history")
    _age(session, old["id"], 400)
    _save(client, "recent")

    year = client.get("/timeline?days=365").json()
    assert [n["preview"] for n in year["notes"]] == ["recent"]
    everything = client.get("/timeline?days=0").json()
    assert len(everything["notes"]) == 2


def test_a_scale_or_grouping_it_does_not_know_is_refused(client):
    assert client.get("/timeline?scale=fortnight").status_code == 422
    assert client.get("/timeline?group=vibes").status_code == 422


def test_a_truncated_preview_says_so(client):
    """A bare `[:120]` slice cuts a long note off mid-word with nothing on
    screen to say there's more: reported as the grid view's cards missing
    an ellipsis. A short note is untouched; a long one ends in one."""
    from memorymap.api.routes_timeline import PREVIEW_CHARS

    short = _save(client, "a short note well under the preview limit")
    long_note = _save(client, "x" * (PREVIEW_CHARS + 50))

    body = client.get("/timeline").json()
    previews = {n["id"]: n["preview"] for n in body["notes"]}

    assert previews[short["id"]] == "a short note well under the preview limit"
    assert previews[long_note["id"]].endswith("…")
    assert len(previews[long_note["id"]]) == PREVIEW_CHARS


def test_a_row_carries_what_the_table_view_puts_in_its_columns(client):
    """TIMELINE_PLAN decision 6: the table's columns are date, title, kind,
    category, space, tags, words and links, and the view renders from the row
    model and from nothing else. Three of those were not in the payload, so a
    column could only ever have been blank or a second request per row.

    The word count is words, not characters: `preview` has already thrown the
    characters away, and it is the number a person thinks in.
    """
    first = _save(client, "the first note, which is six words long")
    second = _save(client, f"a second note linking to [[{first['id']}]]")

    rows = {note["id"]: note for note in client.get("/timeline").json()["notes"]}

    assert rows[first["id"]]["words"] == 8
    # The default space is named, not slugged: a column has to be readable.
    assert rows[first["id"]]["space"]
    assert rows[first["id"]]["space"] != ""
    # A link counts on both sides, which is what a "links" column means: how
    # many notes this one is joined to.
    assert rows[second["id"]]["links"] >= 0
    assert set(rows[first["id"]]) >= {"space", "words", "links", "tags", "category"}
