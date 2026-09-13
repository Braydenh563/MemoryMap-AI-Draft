"""Notes API extras: add-context recategorisation, threads, attachments,
pins, tag manager, capture templates, saved appearance looks.

(Duplicate-detection-on-save and the /related endpoint moved to
test_duplicates.py/test_related_notes.py: same domain as their other
coverage.)"""

from __future__ import annotations

import io

import pytest

from memorymap.core import deps


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- add context + recategorise --------------------------------------------------


def test_add_context_recategorises(ai_client):
    # Vague note → the fake files it as Misc.
    entry = _save(ai_client, "something I heard today")
    assert entry["category"] == "Misc"

    # Context makes it clearly a joke → janitor refiles it.
    updated = ai_client.post(
        f"/entries/{entry['id']}/context",
        json={"text": "it was a scarecrow joke, outstanding in his field"},
    ).json()
    assert "--- added context ---" in updated["content"]
    assert updated["category"] == "Dad Jokes"
    assert updated["filed_by"] in ("llm", "semantic-match")


def test_add_context_respects_user_filing(ai_client):
    entry = _save(ai_client, "my note", category="Personal")  # user's choice
    updated = ai_client.post(
        f"/entries/{entry['id']}/context",
        json={"text": "a funny joke actually"},
    ).json()
    # The user filed it, the janitor keeps its hands off.
    assert updated["category"] == "Personal"
    assert updated["user_filed"] is True


# --- threads ---------------------------------------------------------------------


def test_thread_child_inherits_parent_category(ai_client):
    parent = _save(ai_client, "a funny scarecrow joke")
    child = _save(ai_client, "and thinking more about it…", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]
    assert child["category"] == parent["category"]
    assert child["filed_by"] == "thread"


def test_thread_with_missing_parent_404s(client):
    response = client.post("/entries", json={"content": "orphan", "parent_id": 999})
    assert response.status_code == 404


# --- attachments ------------------------------------------------------------------


def test_upload_download_delete_attachment(client):
    entry = _save(client, "note with a file")
    upload = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("hello.txt", io.BytesIO(b"file contents"), "text/plain")},
    )
    assert upload.status_code == 201
    attachment = upload.json()["attachments"][0]
    assert attachment["filename"] == "hello.txt"
    assert attachment["is_image"] is False

    download = client.get(f"/files/{attachment['id']}")
    assert download.status_code == 200
    assert download.content == b"file contents"

    removed = client.delete(f"/files/{attachment['id']}").json()
    assert removed["attachments"] == []
    # Bytes are gone from disk too.
    uploads = list(deps.get_config().uploads_dir.iterdir())
    assert uploads == []


def test_an_incompatible_attachment_is_refused_with_a_clear_error(client):
    entry = _save(client, "note with an unwelcome file")
    upload = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("clip.mp4", io.BytesIO(b"not really a video"), "video/mp4")},
    )
    assert upload.status_code == 415
    assert "mp4" in upload.json()["detail"]
    # And nothing was attached or written to disk.
    assert client.get(f"/entries/{entry['id']}").json()["attachments"] == []
    assert list(deps.get_config().uploads_dir.iterdir()) == []


def test_hard_delete_removes_attachment_files(client):
    entry = _save(client, "doomed note")
    client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("bye.txt", io.BytesIO(b"x"), "text/plain")},
    )
    client.delete(f"/entries/{entry['id']}")
    client.post("/recycle-bin/empty")
    assert list(deps.get_config().uploads_dir.iterdir()) == []


def test_uploading_recreates_a_missing_uploads_folder(client):
    """The folder is made at startup, but it only has to vanish once.

    A cleanup tool, an unmounted data directory, or a restore that skipped an
    empty folder used to turn every upload into a 500 with a traceback. For a
    sketch that is the worst shape of failure: the note saves first, so only
    the drawing is lost and the caption is left behind pointing at nothing.
    """
    import shutil

    entry = _save(client, "a sketch caption", category="Sketches")
    uploads = deps.get_config().uploads_dir
    shutil.rmtree(uploads)
    assert not uploads.exists()

    response = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("sketch.png", b"\x89PNG\r\n\x1a\nnot-really", "image/png")},
    )
    assert response.status_code == 201
    assert response.json()["attachments"][0]["filename"] == "sketch.png"


# --- rename a file in the library ---------------------------------------------------
#
# `stored_name` (a uuid) and `mime` never change here: only the display
# `filename` does, so a rename can never touch the bytes on disk or what the
# download is served as. That is what these tests are checking: the good name
# lands, the bad ones are refused with a reason, two files on the same note
# can't end up sharing a name, and the two things that gate every other
# per-item file route (the right workspace, a note that isn't private) gate
# this one too.


def _upload(client, entry_id, filename="hello.txt", content=b"hi"):
    upload = client.post(
        f"/entries/{entry_id}/files",
        files={"file": (filename, io.BytesIO(content), "text/plain")},
    )
    assert upload.status_code == 201
    return upload.json()["attachments"][-1]


def test_rename_file_happy_path(client):
    entry = _save(client, "note with a file")
    attachment = _upload(client, entry["id"])

    renamed = client.put(f"/files/{attachment['id']}", json={"filename": "renamed.txt"})
    assert renamed.status_code == 200
    names = [a["filename"] for a in renamed.json()["attachments"]]
    assert names == ["renamed.txt"]

    # The bytes on disk didn't move: the same stored file still downloads.
    download = client.get(f"/files/{attachment['id']}")
    assert download.status_code == 200
    assert download.content == b"hi"


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "   ",
        "a/b.txt",
        "a\\b.txt",
        "..",
        "../escape.txt",
        "/etc/passwd",
        "C:\\Windows\\system32",
        "bad\x00name.txt",
        "bad\x01name.txt",
        ".hidden",
        "CON",
        "con.txt",
        "COM1",
        "lpt3.log",
        "a" * 300,
    ],
)
def test_rename_file_rejects_unsafe_names(client, bad_name):
    entry = _save(client, "note with a file")
    attachment = _upload(client, entry["id"])

    response = client.put(f"/files/{attachment['id']}", json={"filename": bad_name})
    assert response.status_code == 422, bad_name
    # The stored file is untouched by a rejected rename.
    assert client.get(f"/files/{attachment['id']}").status_code == 200


def test_rename_file_collision_is_rejected(client):
    entry = _save(client, "note with two files")
    first = _upload(client, entry["id"], filename="one.txt")
    second = _upload(client, entry["id"], filename="two.txt")

    response = client.put(f"/files/{second['id']}", json={"filename": "one.txt"})
    assert response.status_code == 409
    # Renaming onto its own current name is not a collision with itself.
    same = client.put(f"/files/{first['id']}", json={"filename": "one.txt"})
    assert same.status_code == 200


def test_rename_file_on_private_note_is_refused(client, session):
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    try:
        entry = _save(client, "a private note with a file")
        attachment = _upload(client, entry["id"])
        made_private = client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
        assert made_private.status_code == 200

        response = client.put(f"/files/{attachment['id']}", json={"filename": "renamed.txt"})
        assert response.status_code == 403
    finally:
        vault.close()


def test_rename_file_in_another_workspace_404s(client):
    entry = _save(client, "note in the default workspace")
    attachment = _upload(client, entry["id"])

    response = client.put(
        f"/files/{attachment['id']}",
        json={"filename": "renamed.txt"},
        headers={"X-Workspace-ID": "someone-elses-workspace"},
    )
    assert response.status_code == 404
    # Untouched from the workspace that actually owns it.
    still = client.get(f"/files/{attachment['id']}")
    assert still.status_code == 200


def test_rename_file_missing_attachment_404s(client):
    response = client.put("/files/999999", json={"filename": "x.txt"})
    assert response.status_code == 404


# --- pins ---------------------------------------------------------------------------


def test_pin_floats_entry_to_top(client):
    first = _save(client, "older note")
    _save(client, "newer note")
    client.put(f"/entries/{first['id']}", json={"pinned": True})

    listed = client.get("/entries").json()
    assert listed[0]["id"] == first["id"]
    assert listed[0]["pinned"] is True


# --- tag manager -------------------------------------------------------------------


def test_tag_rename_merge_delete(client):
    _save(client, "note one", tags=["joke", "work"])
    _save(client, "note two", tags=["jokes"])

    assert client.get("/tags").json() == {"joke": 1, "jokes": 1, "work": 1}

    # Rename "joke" → "jokes" merges them.
    assert client.post("/tags/rename", json={"old": "joke", "new": "jokes"}).json() == {
        "changed": 1
    }
    assert client.get("/tags").json() == {"jokes": 2, "work": 1}

    assert client.post("/tags/delete", json={"name": "work"}).json() == {"changed": 1}
    assert "work" not in client.get("/tags").json()


# --- capture templates --------------------------------------------------------------


def test_custom_templates_roundtrip(client):
    # Not "Journal", that's one of the four built-in names (BUILTIN_TEMPLATE_NAMES
    # in routes_settings.py, kept in sync by hand with BUILTIN_TEMPLATES in
    # app.js) and a custom template can no longer claim it; see
    # test_custom_template_cannot_shadow_a_builtin below.
    updated = client.put(
        "/preferences",
        json={"custom_templates": [{"name": "Reading log", "content": "Today I…"}]},
    ).json()
    assert updated["custom_templates"] == [
        {"name": "Reading log", "content": "Today I…", "description": ""}
    ]


def test_custom_template_add_edit_delete(client):
    """The happy path: add one, edit it in place (a rename counts), then
    delete it: exactly the sequence the Settings pane drives."""
    added = client.put(
        "/preferences",
        json={
            "custom_templates": [
                {"name": "Trip log", "description": "Where I went", "content": "Where: \nWho: "}
            ]
        },
    ).json()
    assert added["custom_templates"] == [
        {"name": "Trip log", "description": "Where I went", "content": "Where: \nWho: "}
    ]

    edited = client.put(
        "/preferences",
        json={
            "custom_templates": [
                {"name": "Travel log", "description": "Where I went", "content": "Where: \nWho: \nCost: "}
            ]
        },
    ).json()
    assert [t["name"] for t in edited["custom_templates"]] == ["Travel log"]

    deleted = client.put("/preferences", json={"custom_templates": []}).json()
    assert deleted["custom_templates"] == []


def test_custom_template_cannot_shadow_a_builtin(client):
    """Deleting a built-in isn't a real operation (it never lived in
    `custom_templates`), but saving a custom one *named* like a built-in
    would let it silently win wherever the merged list is drawn, so the
    server refuses the name outright."""
    response = client.put(
        "/preferences",
        json={"custom_templates": [{"name": "Journal", "content": "Dear diary…"}]},
    )
    assert response.status_code == 422
    assert "built-in" in response.json()["detail"]


def test_custom_template_name_collision_is_rejected_not_deduped(client):
    """Two customs can't share a name either, rejected, not silently
    de-duplicated, because de-duping would mean deleting whichever one
    lost, without the user ever having asked for that."""
    response = client.put(
        "/preferences",
        json={
            "custom_templates": [
                {"name": "Book notes", "content": "Title: "},
                {"name": "Book notes", "content": "Something else entirely"},
            ]
        },
    )
    assert response.status_code == 422
    assert "already used" in response.json()["detail"]


def test_custom_template_bad_payload_rejected(client):
    # No name at all.
    assert client.put(
        "/preferences", json={"custom_templates": [{"content": "no name here"}]}
    ).status_code == 422
    # Content over the 2000-char cap.
    assert client.put(
        "/preferences",
        json={"custom_templates": [{"name": "Too long", "content": "x" * 2001}]},
    ).status_code == 422


# --- saved appearance looks (§33 / IDEAS.md) ---------------------------------


def test_a_look_can_be_saved_and_read_back(ai_client):
    """Stored server-side rather than in the browser: a theme someone built by
    hand is a thing they would be upset to lose to a cleared cache, and here it
    rides along in the daily backup too."""
    theme = {
        "name": "Late night",
        "values": {"theme": "dark", "accent-custom": "#8b5cf6", "radius": "4"},
        "preset": "midnight",
    }
    assert ai_client.put("/preferences", json={"custom_themes": [theme]}).status_code == 200
    saved = ai_client.get("/preferences").json()["custom_themes"]
    assert saved == [theme]


def test_a_theme_cannot_become_an_arbitrary_blob(ai_client):
    """`values` is a free-form map because only the frontend knows what a
    setting key means: so it is bounded rather than trusted."""
    huge = {"name": "Too much", "values": {f"k{i}": "v" for i in range(60)}}
    assert ai_client.put("/preferences", json={"custom_themes": [huge]}).status_code == 422

    long_value = {"name": "Long", "values": {"accent": "x" * 500}}
    assert ai_client.put("/preferences", json={"custom_themes": [long_value]}).status_code == 422


def test_a_theme_needs_a_name(ai_client):
    assert (
        ai_client.put("/preferences", json={"custom_themes": [{"name": ""}]}).status_code
        == 422
    )


def test_saved_looks_default_to_empty(ai_client):
    assert ai_client.get("/preferences").json()["custom_themes"] == []
