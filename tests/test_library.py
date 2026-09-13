"""The Library's one endpoint (§4, §36F).

Worth a real test file rather than a smoke check, because the Library is the
surface that *replaces* two others: if it silently drops a kind, the only
symptom is a thing you made not being anywhere, and the app has no other list
to fall back to any more.
"""

from __future__ import annotations

import json

from memorymap.core.database import Attachment, Conversation, Document, Entry

# `client` and `session` come from tests/conftest.py: one throwaway data
# directory per test and singletons rebuilt between them. Declaring a second
# `client` here silently shared one database across the file, and the two
# privacy tests below passed alone and failed in a run, which is the worst way
# for a privacy test to behave.


def _kinds(body: dict) -> set[str]:
    return {item["kind"] for item in body["items"]}


def _of_kind(body: dict, kind: str) -> list[dict]:
    return [item for item in body["items"] if item["kind"] == kind]


def test_every_kind_appears_in_one_list(client, session):
    """One call, four kinds. The point of assembling this server-side is that
    a client stitching four fetches together misses the fifth kind whenever
    somebody adds one."""
    session.add(Document(title="Bread notes", content="one two three four five"))
    session.add(
        Conversation(
            title="About sourdough",
            messages=json.dumps(
                [
                    {"role": "user", "content": "how do I prove dough"},
                    {"role": "assistant", "content": "slowly"},
                ]
            ),
        )
    )
    entry = Entry(content="a note with a photo on it")
    session.add(entry)
    session.flush()
    session.add(
        Attachment(
            entry_id=entry.id,
            filename="loaf.pdf",
            stored_name="abc123.pdf",
            mime="application/pdf",
            size=2048,
        )
    )
    binned = Entry(content="something I threw away")
    binned.is_deleted = True
    session.add(binned)
    session.commit()

    body = client.get("/library").json()
    # `note` and `activity` come along without being seeded: the live note the
    # attachment hangs on is one, and every insert above wrote an audit row.
    # That is the point, the Library is the app's management screen now, so a
    # kind missing from here is a thing with nowhere to be managed.
    assert {"document", "chat", "file", "archived", "note"} <= _kinds(body)
    for kind in ("document", "chat", "file", "archived"):
        assert body["counts"][kind] == 1, kind


def test_the_overview_agrees_with_the_grid_beneath_it(client, session):
    """A header saying "12 documents" over a grid showing 11 is worse than no
    header, so the overview is derived from the same list rather than counted
    again in its own query."""
    session.add(Document(title="One", content="a b c"))
    session.add(Document(title="Two", content="d e"))
    entry = Entry(content="a live note")
    session.add(entry)
    session.commit()

    body = client.get("/library").json()
    overview = body["overview"]
    assert overview["documents"] == len(_of_kind(body, "document")) == 2
    assert overview["notes"] == len(_of_kind(body, "note"))
    assert overview["words"] == 5  # 3 + 2, the two documents' own word counts


def test_a_private_note_is_counted_but_never_quoted(client, session):
    """Hiding it entirely would make the Library disagree with the notebook's
    own total; showing its text would defeat the encryption it is behind. So
    it is a locked row with a count and no content."""
    entry = Entry(content="the secret recipe for the good bread")
    entry.is_private = True
    session.add(entry)
    session.commit()

    body = client.get("/library").json()
    note = _of_kind(body, "note")[0]
    assert note["private"] is True
    assert note["preview"] == ""
    assert "secret recipe" not in json.dumps(body)
    assert body["overview"]["private_notes"] == 1


def test_the_activity_log_reads_in_words_not_in_verbs(client, session):
    """"queried" and "purged" are the app's own vocabulary. A record of what
    you did that only its author can read is not a record."""
    client.post("/entries", json={"content": "something worth logging"})

    activity = _of_kind(client.get("/library").json(), "activity")
    assert activity, "creating a note must show up in the activity kind"
    titles = [item["title"] for item in activity]
    assert any(t.startswith("Created") for t in titles), titles
    # The raw verbs must not reach the screen.
    assert not any("purged" in t or "queried" in t for t in titles), titles


def test_a_chat_is_previewed_by_its_first_question(client, session):
    """You remember what you asked far more often than what the chat ended up
    being called: the same reasoning the conversation sidebar already used,
    and it has to survive the move here or the move is a downgrade."""
    session.add(
        Conversation(
            title="Untitled chat",
            messages=json.dumps(
                [
                    {"role": "user", "content": "why do my tomatoes split"},
                    {"role": "assistant", "content": "uneven watering"},
                ]
            ),
        )
    )
    session.commit()

    chat = _of_kind(client.get("/library").json(), "chat")[0]
    assert chat["preview"] == "why do my tomatoes split"
    assert chat["detail"] == "1 turn"


def test_an_attachment_carries_the_note_it_hangs_on(client, session):
    """A filename with no context is a filename. (A PDF, not an image: image
    attachments are never "file" items, they belong to the Images sub-tab.)
    The reason you kept it is the
    note, so the card shows the note and the click can go there."""
    entry = Entry(content="the loaf that finally worked")
    session.add(entry)
    session.flush()
    session.add(
        Attachment(
            entry_id=entry.id,
            filename="loaf.pdf",
            stored_name="x.pdf",
            mime="application/pdf",
            size=4096,
        )
    )
    session.commit()

    item = _of_kind(client.get("/library").json(), "file")[0]
    assert item["entry_id"] == entry.id
    assert item["preview"] == "the loaf that finally worked"
    assert item["detail"] == "4 KB · PDF"


def test_a_private_note_keeps_its_attachments_out_of_the_library(client, session):
    """The Library is a browsing surface over everything you made, which makes
    it exactly the place a private note's contents would otherwise turn up in
    plain sight: as a filename and a preview of the note's own text."""
    entry = Entry(content="the private one")
    entry.is_private = True
    session.add(entry)
    session.flush()
    session.add(
        Attachment(
            entry_id=entry.id,
            filename="secret.pdf",
            stored_name="y.pdf",
            mime="application/pdf",
            size=10,
        )
    )
    session.commit()

    body = client.get("/library").json()
    assert _of_kind(body, "file") == []
    assert "secret.pdf" not in json.dumps(body)


def test_a_private_note_stays_out_of_the_archive_too(client, session):
    """Deleting a private note does not make it public."""
    entry = Entry(content="private and binned")
    entry.is_private = True
    entry.is_deleted = True
    session.add(entry)
    session.commit()

    body = client.get("/library").json()
    assert _of_kind(body, "archived") == []


def test_a_malformed_conversation_costs_its_preview_not_the_library(client, session):
    """A hand-edited or truncated messages blob must not take out the one list
    the app now has for finding anything."""
    conversation = Conversation(title="broken", messages="{not json")
    session.add(conversation)
    session.add(Document(title="still here", content="words"))
    session.commit()

    body = client.get("/library").json()
    assert _of_kind(body, "chat")[0]["preview"] == ""
    assert _of_kind(body, "document")[0]["title"] == "still here"


def test_a_shelved_note_appears_once_not_twice(client, session):
    """A real archive (BACKLOG §30b), distinct from `_archive()`'s bin
    despite the similar-sounding name, see routes_library.py's own
    comment on why the two are named differently at the code level.
    A shelved note must appear under "shelved" and *not* also under
    "note", or it would be double-counted and double-managed."""
    kept = Entry(content="still active")
    shelved = Entry(content="kept, but out of the way")
    session.add_all([kept, shelved])
    session.commit()
    client.post(f"/entries/{shelved.id}/archive")

    body = client.get("/library").json()
    assert len(_of_kind(body, "shelved")) == 1
    assert _of_kind(body, "shelved")[0]["entry_id"] == shelved.id
    note_ids = {item["entry_id"] for item in _of_kind(body, "note")}
    assert shelved.id not in note_ids
    assert kept.id in note_ids
    assert body["overview"]["shelved"] == 1


def test_a_draft_note_does_not_appear_in_the_library(client, session):
    """Reported directly ("draft notes appear as regular notes in the main
    library section"). A draft is unfinished by definition, the Notes tab
    already keeps it out of "All notes" and every category filter; the
    Library's mixed "note" list didn't."""
    kept = Entry(content="finished thought")
    draft = Entry(content="half a thought", is_draft=True)
    session.add_all([kept, draft])
    session.commit()

    body = client.get("/library").json()
    note_ids = {item["entry_id"] for item in _of_kind(body, "note")}
    assert kept.id in note_ids
    assert draft.id not in note_ids


def test_a_sketch_note_carries_a_thumbnail(client, session):
    """A sketch (saveSketch() in app.js) is a note whose real content is a
    PNG Attachment, not text, the note card had nothing to show but the
    caption, which is what made a sketch unrecognisable in the Library."""
    sketch = Entry(content="Sketch: a doodle", tags="[]")
    plain = Entry(content="an ordinary note with no attachment", tags="[]")
    session.add_all([sketch, plain])
    session.flush()
    session.add(
        Attachment(
            entry_id=sketch.id,
            filename="sketch.png",
            stored_name="deadbeef.png",
            mime="image/png",
            size=1024,
        )
    )
    session.commit()

    body = client.get("/library").json()
    by_entry = {item["entry_id"]: item for item in _of_kind(body, "note")}
    assert by_entry[sketch.id]["thumb_attachment_id"] is not None
    assert by_entry[plain.id]["thumb_attachment_id"] is None


def test_a_pasted_image_note_carries_a_thumbnail_too(client, session):
    """The other half of `test_a_sketch_note_carries_a_thumbnail`: a pasted
    or dropped image lives as inline markdown in the note's own content
    (`![alt](url)`), never as an Attachment, only a sketch's drawing is
    stored that way. Before this, a sketch card showed its drawing and a
    pasted-image note's card showed nothing at all, the exact
    inconsistency reported ("make sketches render the same as images").
    Its title and preview must also read as plain words, not literal
    markdown syntax.
    """
    pasted = Entry(
        content="Holiday photo\n\n![beach](/media/deadbeef.png)", tags="[]"
    )
    external = Entry(
        content="![a diagram](https://example.com/diagram.png)", tags="[]"
    )
    session.add_all([pasted, external])
    session.commit()

    body = client.get("/library").json()
    by_entry = {item["entry_id"]: item for item in _of_kind(body, "note")}

    assert by_entry[pasted.id]["thumb_attachment_id"] is None
    assert by_entry[pasted.id]["thumb_url"] == "/media/deadbeef.png"
    assert "![" not in by_entry[pasted.id]["title"]
    assert "![" not in by_entry[pasted.id]["preview"]

    # The note editor itself renders a plain https:// image inline
    # (isRenderableUrl in app.js): the Library shouldn't be pickier than
    # the surface that actually wrote the note.
    assert by_entry[external.id]["thumb_url"] == "https://example.com/diagram.png"


def test_a_sketchs_own_drawing_wins_over_its_caption_markdown(client, session):
    """A sketch whose caption happens to *mention* `![...]()` (unlikely, but
    the caption is free text) must still show its own drawing, the
    Attachment thumbnail always wins over the inline-content fallback."""
    sketch = Entry(content="See ![this](/media/other.png) for reference", tags="[]")
    session.add(sketch)
    session.flush()
    session.add(
        Attachment(
            entry_id=sketch.id,
            filename="sketch.png",
            stored_name="realsketch.png",
            mime="image/png",
            size=1024,
        )
    )
    session.commit()

    body = client.get("/library").json()
    item = next(i for i in _of_kind(body, "note") if i["entry_id"] == sketch.id)
    assert item["thumb_attachment_id"] is not None
    assert item["thumb_url"] is None


def test_a_private_note_never_leaks_a_thumbnail(client, session):
    """Hiding a private note's text but showing a thumbnail of what it's a
    photo of would be the same encryption bypass showing the preview text
    already isn't allowed to be. Covers both thumbnail sources, an
    Attachment (a private sketch) and inline content (a private pasted
    image): since only checking one would leave the other leaking."""
    entry = Entry(
        content="secret photo ![leak](/media/should-never-show.png)",
        tags="[]",
        is_private=True,
    )
    session.add(entry)
    session.flush()
    session.add(
        Attachment(
            entry_id=entry.id,
            filename="secret.png",
            stored_name="cafebabe.png",
            mime="image/png",
            size=512,
        )
    )
    session.commit()

    body = client.get("/library").json()
    item = next(i for i in _of_kind(body, "note") if i["entry_id"] == entry.id)
    assert item["thumb_attachment_id"] is None
    assert item["thumb_url"] is None


def test_tags_are_capped_like_every_other_kind_here(client, session, monkeypatch):
    """`_tags()` was the one kind section in this file with no `PER_KIND_LIMIT`
    slice: `manager.all_tags` was made cheap to *compute* (a fingerprint
    cache, §86) but nothing capped how many of the result this endpoint
    actually sent to the browser. Lowers the module's own limit to 3 rather
    than seeding 200+ notes, which is both slow and not what this test is
    about: the slicing logic, not the real-world threshold.
    """
    from memorymap.api import routes_library

    monkeypatch.setattr(routes_library, "PER_KIND_LIMIT", 3)
    for i in range(5):
        session.add(Entry(content=f"note {i}", tags=json.dumps([f"tag{i}"])))
    session.commit()

    body = client.get("/library").json()
    tags = _of_kind(body, "tag")
    assert len(tags) == 3


def test_tags_keep_the_most_used_ones_when_capped(client, session, monkeypatch):
    """The cap has to keep the *right* three, not an arbitrary three, 
    `all_tags()` is already most-used-first, so the slice should be too."""
    from memorymap.api import routes_library

    monkeypatch.setattr(routes_library, "PER_KIND_LIMIT", 2)
    # "popular" on 3 notes, "rare-a"/"rare-b" on 1 each: popular must survive
    # the cap, the two rare ones are the ones that should be dropped.
    for i in range(3):
        session.add(Entry(content=f"popular note {i}", tags=json.dumps(["popular"])))
    session.add(Entry(content="rare a", tags=json.dumps(["rare-a"])))
    session.add(Entry(content="rare b", tags=json.dumps(["rare-b"])))
    session.commit()

    body = client.get("/library").json()
    titles = {item["title"] for item in _of_kind(body, "tag")}
    assert "popular" in titles
    assert len(titles) == 2


def test_the_library_is_behind_the_unlock_gate(client):
    """It lists documents, chats, files and binned notes, every kind of thing
    the lock screen exists to keep behind it.

    Asserted by locking the app and knocking, rather than by reading app.py:
    registering a router on the unlocked list is a one-word mistake, and a test
    that reads the same line the mistake is in cannot see it.
    """
    client.post("/auth/setup", json={"password": "a password"})
    client.post("/auth/lock")
    assert client.get("/library").status_code == 401
