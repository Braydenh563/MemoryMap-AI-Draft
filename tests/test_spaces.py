"""Spaces (workspace partitioning): CRUD, id/icon/name validation, and the
delete-time reassignment that keeps rows from becoming invisible.
"""

from __future__ import annotations

from memorymap.core.database import Category, Entry, EntryLink, Document


def _row(session, model, **kwargs):
    obj = model(**kwargs)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def test_create_rename_delete_happy_path(client):
    created = client.post("/spaces", json={"name": "Garden Notes"}).json()
    assert created["id"] == "garden-notes"
    assert created["name"] == "Garden Notes"
    assert created["icon"] == "ph-circles-four"

    renamed = client.put(
        f"/spaces/{created['id']}", json={"name": "Garden"}
    ).json()
    assert renamed["name"] == "Garden"
    assert renamed["icon"] == "ph-circles-four"  # untouched field survives

    deleted = client.delete(f"/spaces/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["id"] == created["id"]

    ids = [s["id"] for s in client.get("/spaces").json()]
    assert created["id"] not in ids


def test_client_supplied_id_is_ignored(client):
    """A client-sent id (including a reserved sentinel) never wins, the
    server always slugifies `name` itself."""
    resp = client.post("/spaces", json={"id": "all", "name": "My Space"}).json()
    assert resp["id"] == "my-space"


def test_name_that_slugifies_to_a_reserved_word_is_deduped(client):
    resp = client.post("/spaces", json={"name": "All"}).json()
    assert resp["id"] != "all"
    assert resp["id"] not in ("all", "default")


def test_duplicate_names_get_a_numeric_suffix(client):
    first = client.post("/spaces", json={"name": "Work"}).json()
    second = client.post("/spaces", json={"name": "Work"}).json()
    assert first["id"] != second["id"]
    assert second["id"].startswith("work-")


def test_bad_icon_refused_on_create(client):
    resp = client.post(
        "/spaces", json={"name": "X", "icon": "evil\" onclick=\"alert(1)"}
    )
    assert resp.status_code == 400


def test_bad_icon_refused_on_update(client):
    created = client.post("/spaces", json={"name": "X"}).json()
    resp = client.put(f"/spaces/{created['id']}", json={"icon": "not-an-icon"})
    assert resp.status_code == 400


def test_bad_name_refused_empty(client):
    resp = client.post("/spaces", json={"name": "   "})
    assert resp.status_code == 400


def test_bad_name_refused_too_long(client):
    resp = client.post("/spaces", json={"name": "x" * 61})
    assert resp.status_code == 400


def test_update_only_applies_provided_fields(client):
    created = client.post(
        "/spaces", json={"name": "Keep Icon", "icon": "ph-star"}
    ).json()
    updated = client.put(
        f"/spaces/{created['id']}", json={"name": "Keep Icon Renamed"}
    ).json()
    assert updated["icon"] == "ph-star"


def test_renaming_a_missing_space_404s(client):
    resp = client.put("/spaces/does-not-exist", json={"name": "New"})
    assert resp.status_code == 404


def test_deleting_default_refused(client):
    resp = client.delete("/spaces/default")
    assert resp.status_code == 400


def test_deleting_all_refused(client):
    resp = client.delete("/spaces/all")
    assert resp.status_code == 400


def test_deleting_missing_space_404s(client):
    resp = client.delete("/spaces/does-not-exist")
    assert resp.status_code == 404


def test_a_chat_made_in_one_space_is_invisible_from_another(client):
    created = client.post("/spaces", json={"name": "Focus Room"}).json()
    space_id = created["id"]

    resp = client.post(
        "/conversations",
        json={"question": "a question asked in Focus Room", "answer": "an answer"},
        headers={"X-Workspace-ID": space_id},
    )
    assert resp.status_code == 201
    conversation_id = resp.json()["id"]

    # Visible from its own space, and from "all".
    assert conversation_id in [
        c["id"] for c in client.get("/conversations", headers={"X-Workspace-ID": space_id}).json()
    ]
    assert conversation_id in [
        c["id"] for c in client.get("/conversations", headers={"X-Workspace-ID": "all"}).json()
    ]

    # Not visible from an unrelated space, or the default one. (No header at
    # all means unfiltered, same as "all", so that is not the negative case
    # here; a *named* space that isn't this one is.)
    assert conversation_id not in [
        c["id"]
        for c in client.get("/conversations", headers={"X-Workspace-ID": "default"}).json()
    ]
    other = client.post("/spaces", json={"name": "Somewhere Else"}).json()
    assert conversation_id not in [
        c["id"]
        for c in client.get(
            "/conversations", headers={"X-Workspace-ID": other["id"]}
        ).json()
    ]


def test_a_hidden_space_leaves_all_spaces_but_still_works_when_selected(client):
    """Asked for directly: "how do I hide a specific space's notes and
    images/documents etc, all the content from the 'all spaces' space if I
    wish??" There was no way, `Space` carried only id/name/icon, and "all"
    switched the workspace filter off entirely, so it showed everything.

    The flag is a *view* filter and this pins both halves of that: the space
    drops out of the everything-view, and stays completely usable when it is
    the one selected.
    """
    private = client.post("/spaces", json={"name": "Journal"}).json()
    other = client.post("/spaces", json={"name": "Work"}).json()

    client.post(
        "/entries",
        json={"content": "a private thought", "defer_filing": True},
        headers={"X-Workspace-ID": private["id"]},
    )
    client.post(
        "/entries",
        json={"content": "a work note", "defer_filing": True},
        headers={"X-Workspace-ID": other["id"]},
    )

    def contents(workspace):
        rows = client.get("/entries", headers={"X-Workspace-ID": workspace}).json()
        return {e["content"] for e in rows}

    # Before hiding, "all" sees both.
    everything = contents("all")
    assert "a private thought" in everything
    assert "a work note" in everything

    hidden = client.put(f"/spaces/{private['id']}", json={"hidden_from_all": True})
    assert hidden.status_code == 200
    assert hidden.json()["hidden_from_all"] is True

    # Gone from the everything-view, and nothing else went with it.
    after = contents("all")
    assert "a private thought" not in after
    assert "a work note" in after

    # Still entirely usable when you actually go there.
    assert "a private thought" in contents(private["id"])

    # And it comes back.
    client.put(f"/spaces/{private['id']}", json={"hidden_from_all": False})
    assert "a private thought" in contents("all")


def test_the_default_space_cannot_be_hidden(client):
    """It is where a deleted space's notes land, so hiding it would quietly
    empty the everything-view of anything that ever fell back to it.
    """
    refused = client.put("/spaces/default", json={"hidden_from_all": True})
    assert refused.status_code == 400


# --- delete cascades ---------------------------------------------------------
#
# These four replaced the "reassign everything to default" tests. Asked for
# directly: "make sure that if a specific space is deleted too, that all the
# content including notes files and images etc originating in that specific
# space get deleted with it as well." Reassigning was the opposite of what
# the word means: the notes did not go away, they turned up in another space.


def _gone(session, model, row_id) -> bool:
    # `session.get` on an instance the identity map still holds raises
    # ObjectDeletedError once the row is gone; a fresh query just says no.
    session.expunge_all()
    return session.query(model).filter_by(id=row_id).first() is None


def test_delete_removes_every_workspace_scoped_row_of_that_space(client, session):
    created = client.post("/spaces", json={"name": "Doomed"}).json()
    space_id = created["id"]
    category = _row(session, Category, name="doomed-cat", workspace_id=space_id)
    entry = _row(session, Entry, content="a note", workspace_id=space_id)
    other_entry = _row(session, Entry, content="another note", workspace_id=space_id)
    link = _row(
        session, EntryLink, source_entry_id=entry.id, target_entry_id=other_entry.id,
        workspace_id=space_id,
    )
    document = _row(session, Document, title="doomed doc", content="", workspace_id=space_id)
    survivor = _row(session, Entry, content="stays", workspace_id="default")
    doomed = [
        (Category, category.id), (Entry, entry.id), (Entry, other_entry.id),
        (EntryLink, link.id), (Document, document.id),
    ]
    survivor_id = survivor.id

    resp = client.delete(f"/spaces/{space_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == space_id  # response captured before the row was gone

    for model, row_id in doomed:
        assert _gone(session, model, row_id), f"{model.__name__} survived its space"
    assert not _gone(session, Entry, survivor_id), "another space's note was taken too"


def test_deleting_a_space_with_a_same_named_category_does_not_crash(client, session):
    """The old merge-by-name code existed because a blind UPDATE collided on
    `(workspace_id, name)`. A delete has no such collision; this pins that the
    default space's own category is untouched."""
    created = client.post("/spaces", json={"name": "Doomed Twin"}).json()
    space_id = created["id"]
    default_uncat = _row(session, Category, name="Uncategorised", workspace_id="default")
    doomed_uncat = _row(session, Category, name="Uncategorised", workspace_id=space_id)
    _row(session, Entry, content="filed", workspace_id=space_id, category_id=doomed_uncat.id)
    doomed_id, default_id = doomed_uncat.id, default_uncat.id

    resp = client.delete(f"/spaces/{space_id}")
    assert resp.status_code == 200, resp.text
    assert _gone(session, Category, doomed_id)
    assert not _gone(session, Category, default_id)


def test_a_foreign_note_pointing_at_a_doomed_category_keeps_the_note(client, session):
    """A note in *another* space that was filed under this space's category
    is not ours to delete, it loses the pointer, exactly as if the category
    had been deleted on its own."""
    created = client.post("/spaces", json={"name": "Doomed Unique"}).json()
    space_id = created["id"]
    category = _row(session, Category, name="doomed-only-cat", workspace_id=space_id)
    foreign = _row(session, Entry, content="elsewhere", workspace_id="default",
                   category_id=category.id)
    category_id, foreign_id = category.id, foreign.id

    resp = client.delete(f"/spaces/{space_id}")
    assert resp.status_code == 200, resp.text
    assert _gone(session, Category, category_id)
    kept = session.query(Entry).filter_by(id=foreign_id).first()
    assert kept is not None and kept.category_id is None


def test_deleting_a_space_deletes_its_chats(client, session):
    from memorymap.core.database import Conversation

    created = client.post("/spaces", json={"name": "Temporary"}).json()
    space_id = created["id"]
    conversation = _row(
        session, Conversation, title="doomed chat", messages="[]", workspace_id=space_id
    )
    deleted = client.delete(f"/spaces/{space_id}")
    assert deleted.status_code == 200
    assert _gone(session, Conversation, conversation.id)
