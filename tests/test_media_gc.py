"""Orphaned `/media/` garbage collection (ROADMAP.md item 20a).

An upload is orphaned when nothing left in the notebook, a note, a
document, or a whiteboard image object, still points at it. The one case
worth getting exactly right: a private note's content is encrypted, so an
image referenced only from a currently-locked private note must never be
treated as unreferenced.
"""

from __future__ import annotations

import pytest

from memorymap.core import vault


def _upload(ai_client, name="photo.png"):
    return ai_client.post(
        "/media/upload", files={"file": (name, b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()


def test_an_unreferenced_upload_is_orphaned(ai_client):
    uploaded = _upload(ai_client)

    listed = ai_client.get("/media/orphans").json()
    assert listed["skipped_private"] is False
    assert any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_an_upload_referenced_by_a_note_is_not_orphaned(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post("/entries", json={"content": f"look at this: ![img]({uploaded['url']})"})

    listed = ai_client.get("/media/orphans").json()
    assert not any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_an_upload_referenced_by_a_document_is_not_orphaned(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post("/documents", json={"title": "Doc", "content": f"![img]({uploaded['url']})"})

    listed = ai_client.get("/media/orphans").json()
    assert not any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_an_upload_referenced_by_a_whiteboard_image_object_is_not_orphaned(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "data": {"url": uploaded["url"]}, "board_id": None},
    )

    listed = ai_client.get("/media/orphans").json()
    assert not any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_clean_deletes_only_orphans(ai_client):
    orphan = _upload(ai_client, "orphan.png")
    referenced = _upload(ai_client, "referenced.png")
    ai_client.post("/entries", json={"content": f"![img]({referenced['url']})"})

    result = ai_client.delete("/media/orphans").json()
    assert result["skipped_private"] is False

    remaining_urls = {row["url"] for row in ai_client.get("/media").json()}
    assert orphan["url"] not in remaining_urls
    assert referenced["url"] in remaining_urls
    assert ai_client.get(orphan["url"]).status_code == 404
    assert ai_client.get(referenced["url"]).status_code == 200


def test_a_locked_private_note_blocks_deletion_of_everything(ai_client, session):
    """The risky case: an image referenced only inside a private note whose
    vault is currently locked must never be deleted, nor may any other
    orphan, since the pass as a whole can no longer prove the list is
    complete.
    """
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()

    referenced_only_privately = _upload(ai_client, "private-ref.png")
    truly_orphaned = _upload(ai_client, "genuinely-orphaned.png")

    created = ai_client.post(
        "/entries", json={"content": f"secret: ![img]({referenced_only_privately['url']})"}
    ).json()
    ai_client.post(f"/entries/{created['id']}/privacy", json={"private": True})

    vault.close()  # lock it: the state a real "left the app open" session ends in

    dry_run = ai_client.get("/media/orphans").json()
    assert dry_run["skipped_private"] is True

    result = ai_client.delete("/media/orphans").json()
    assert result["skipped_private"] is True
    assert result["deleted"] == 0

    remaining_urls = {row["url"] for row in ai_client.get("/media").json()}
    assert referenced_only_privately["url"] in remaining_urls
    assert truly_orphaned["url"] in remaining_urls

    vault.close()


def test_an_upload_attached_to_a_saved_chat_turn_is_not_orphaned(ai_client):
    """A conversation stores its images as ids
    (TurnBody.image_media_ids), not `/media/…` markdown text, so this is a
    separate check from the note/document/whiteboard cases above, without
    it, every image ever sent in chat read as orphaned and "Clean orphaned
    media" would have deleted a real, sent attachment's file."""
    uploaded = _upload(ai_client)
    ai_client.post(
        "/conversations",
        json={
            "question": "what's in this photo?",
            "answer": "A photo.",
            "image_media_ids": [uploaded["id"]],
        },
    )

    listed = ai_client.get("/media/orphans").json()
    assert not any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_an_upload_only_ever_staged_for_chat_and_never_sent_is_still_orphaned(ai_client):
    """The other side of the fix above: an upload nothing has actually
    referenced yet (staged in the composer, never sent) must still show up
    as orphaned: this is not a blanket exemption for every image that
    passed through /media/upload."""
    uploaded = _upload(ai_client)

    listed = ai_client.get("/media/orphans").json()
    assert any(o["url"] == uploaded["url"] for o in listed["orphans"])


def test_clean_does_not_delete_an_image_attached_to_a_saved_chat_turn(ai_client):
    referenced = _upload(ai_client, "chat-image.png")
    orphan = _upload(ai_client, "orphan.png")
    ai_client.post(
        "/conversations",
        json={"question": "hi", "answer": "hello", "image_media_ids": [referenced["id"]]},
    )

    result = ai_client.delete("/media/orphans").json()
    assert result["skipped_private"] is False

    remaining_urls = {row["url"] for row in ai_client.get("/media").json()}
    assert referenced["url"] in remaining_urls
    assert orphan["url"] not in remaining_urls


def test_orphans_route_is_not_shadowed_by_the_upload_id_route(ai_client):
    """`/media/orphans` must resolve to the dedicated handler, not fall into
    `/media/{upload_id}` and 422 on trying to parse "orphans" as an int."""
    get_response = ai_client.get("/media/orphans")
    assert get_response.status_code == 200

    delete_response = ai_client.delete("/media/orphans")
    assert delete_response.status_code == 200


# --- the reverse question: where is this file used? -------------------------
#
# The Library's Files & Images gallery showed a thumbnail, a filename and two
# empty prompts, and could not answer the only question anyone brings to it, 
# what is this attached to? `usage_map` inverts the orphan scan to answer it.
# It shares `referenced_names` with that scan deliberately: a file the gallery
# called "used" while the collector called it orphaned would be a file deleted
# out from under a live note.


def test_usage_map_names_the_note_a_file_is_used_in(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post("/entries", json={"content": f"# Lecture notes\nsee ![img]({uploaded['url']})"})

    listed = ai_client.get("/media").json()
    row = next(m for m in listed if m["url"] == uploaded["url"])
    assert [u["kind"] for u in row["used_by"]] == ["note"]
    assert "Lecture notes" in row["used_by"][0]["label"]
    assert row["usage_incomplete"] is False


def test_usage_map_names_the_document_a_file_is_used_in(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post("/documents", json={"title": "Thesis", "content": f"![i]({uploaded['url']})"})

    listed = ai_client.get("/media").json()
    row = next(m for m in listed if m["url"] == uploaded["url"])
    assert [(u["kind"], u["label"]) for u in row["used_by"]] == [("document", "Thesis")]


def test_a_file_used_in_two_places_reports_both(ai_client):
    uploaded = _upload(ai_client)
    ai_client.post("/entries", json={"content": f"one ![i]({uploaded['url']})"})
    ai_client.post("/documents", json={"title": "Two", "content": f"![i]({uploaded['url']})"})

    listed = ai_client.get("/media").json()
    row = next(m for m in listed if m["url"] == uploaded["url"])
    assert sorted(u["kind"] for u in row["used_by"]) == ["document", "note"]


def test_an_unused_file_reports_no_usage(ai_client):
    """And says so as an empty list rather than omitting the field, so the UI
    can tell "not used" from "not checked", which is the distinction that
    stops it inviting someone to delete a file that a locked private note is
    still using."""
    uploaded = _upload(ai_client)

    listed = ai_client.get("/media").json()
    row = next(m for m in listed if m["url"] == uploaded["url"])
    assert row["used_by"] == []
    assert row["usage_incomplete"] is False


def test_usage_and_the_orphan_check_agree(ai_client):
    """The property that matters most: anything with usage must not be
    orphaned, and anything orphaned must have no usage."""
    used = _upload(ai_client, "used.png")
    unused = _upload(ai_client, "unused.png")
    ai_client.post("/entries", json={"content": f"![i]({used['url']})"})

    listed = {m["url"]: m for m in ai_client.get("/media").json()}
    orphan_urls = {o["url"] for o in ai_client.get("/media/orphans").json()["orphans"]}

    assert listed[used["url"]]["used_by"] != []
    assert used["url"] not in orphan_urls
    assert listed[unused["url"]]["used_by"] == []
    assert unused["url"] in orphan_urls


@pytest.fixture
def open_vault(session):
    """A note can only be made private once a vault exists, `POST
    /entries/{id}/privacy` answers 409 otherwise, which is what an earlier
    version of the test below actually hit. Opened by hand because these tests
    do not go through setup/unlock, and closed again so the state cannot leak
    into the next test."""
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    yield
    vault.close()


def test_a_private_note_contributes_the_link_but_not_its_words(ai_client, session, open_vault):
    """The label is rendered on a wall of thumbnails in the Library. The first
    line of a private note must not appear there, even with the vault unlocked
    and the content perfectly readable to the server.

    The connection itself is still reported: knowing *that* a file is in use is
    what stops it being deleted as an orphan. Only the wording is withheld, 
    the same answer `routes_documents._linked_notes` already gives a document's
    linked private notes.

    Getting to this state took two corrections worth recording. `POST /entries`
    silently ignores an `is_private` field, so the first version of this test
    asserted against a note that was never private. And privacy needs a vault:
    without one, `POST /entries/{id}/privacy` returns 409, not 200.
    """
    uploaded = _upload(ai_client)
    entry = ai_client.post(
        "/entries", json={"content": f"SECRET diary line ![i]({uploaded['url']})"}
    ).json()
    marked = ai_client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    assert marked.status_code == 200, marked.text
    assert marked.json()["is_private"] is True

    row = next(m for m in ai_client.get("/media").json() if m["url"] == uploaded["url"])
    assert [u["kind"] for u in row["used_by"]] == ["note"]
    assert row["used_by"][0]["label"] == "Private note"
    assert "SECRET" not in str(row["used_by"])
