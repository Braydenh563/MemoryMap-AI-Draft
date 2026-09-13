"""Notes and documents, joined up.

Asked for directly: "I want a way to link documents to new notes I create in
the capture tab; the documents and notes sections and features need to be more
integrated together." They are deliberately different things, a note is a
captured thought, a document is something you sit down and write, but they
are usually *about* the same thing, and nothing could say so.
"""

from __future__ import annotations


def _note(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def _doc(client, title="Trip plan", content="# Trip"):
    response = client.post("/documents", json={"title": title, "content": content})
    assert response.status_code == 201
    return response.json()


def test_a_note_can_be_attached_to_a_document_as_it_is_saved(client):
    """The point of doing it at capture: the connection is obvious while you
    are writing and forgotten by the time the note is in a list."""
    document = _doc(client)
    note = _note(client, "ferry leaves at 8", document_ids=[document["id"]])

    assert [d["title"] for d in note["documents"]] == ["Trip plan"]
    # And the document knows about it from the other side.
    assert [n["id"] for n in client.get(f"/documents/{document['id']}").json()["notes"]] == [
        note["id"]
    ]


def test_a_note_can_be_attached_to_several_documents(client):
    first, second = _doc(client, "Trip plan"), _doc(client, "Packing list")
    note = _note(client, "waterproofs", document_ids=[first["id"], second["id"]])
    assert sorted(d["title"] for d in note["documents"]) == ["Packing list", "Trip plan"]


def test_the_same_document_twice_links_once(client):
    document = _doc(client)
    note = _note(client, "once", document_ids=[document["id"], document["id"]])
    assert len(note["documents"]) == 1


def test_a_stale_document_id_never_costs_you_the_note(client):
    """The note is the thing being saved. Refusing it over an id that has
    since been deleted would be absurd."""
    note = _note(client, "still worth keeping", document_ids=[9999])
    assert note["id"] and note["documents"] == []


def test_a_note_can_be_attached_afterwards_and_detached(client):
    document = _doc(client)
    note = _note(client, "found the timetable")

    attached = client.post(
        f"/documents/{document['id']}/notes", json={"entry_id": note["id"]}
    )
    assert attached.status_code == 201
    assert [n["id"] for n in attached.json()["notes"]] == [note["id"]]

    detached = client.delete(f"/documents/{document['id']}/notes/{note['id']}")
    assert detached.json()["notes"] == []
    # Detaching is a connection being removed, not the note.
    assert client.get(f"/entries/{note['id']}").status_code == 200


def test_attaching_the_same_note_twice_is_not_an_error(client):
    document = _doc(client)
    note = _note(client, "twice")
    for _ in range(2):
        response = client.post(
            f"/documents/{document['id']}/notes", json={"entry_id": note["id"]}
        )
        assert response.status_code == 201
    assert len(response.json()["notes"]) == 1


def test_a_note_in_the_bin_stops_feeding_the_document(client):
    """A binned note should not still be propping up a draft."""
    document = _doc(client)
    note = _note(client, "a mistake", document_ids=[document["id"]])
    client.delete(f"/entries/{note['id']}")

    assert client.get(f"/documents/{document['id']}").json()["notes"] == []


def test_attaching_a_note_that_does_not_exist_says_so(client):
    document = _doc(client)
    response = client.post(f"/documents/{document['id']}/notes", json={"entry_id": 4321})
    assert response.status_code == 404


def test_the_link_shows_up_on_the_note_in_the_list(client):
    """The note list is where you look for a note, so that is where the
    connection has to be visible."""
    document = _doc(client, "Reading notes")
    _note(client, "chapter 3 was the good one", document_ids=[document["id"]])

    listed = client.get("/entries").json()[0]
    assert listed["documents"][0]["title"] == "Reading notes"


def test_attaching_afterwards_shows_up_on_the_note_straight_away(client):
    """"What about adding a document to a note??", the note list is where
    that is done from, so it is where the result has to appear. The note card
    reads `documents` off `GET /entries` and nothing else."""
    document = _doc(client, "Iceland trip")
    note = _note(client, "the ferry leaves at 8")
    client.post(f"/documents/{document['id']}/notes", json={"entry_id": note["id"]})

    listed = client.get("/entries").json()[0]
    assert [d["title"] for d in listed["documents"]] == ["Iceland trip"]


def test_detaching_from_the_note_side_leaves_the_note_alone(client):
    """The × on the note's ph:file-text chip removes a connection. Losing the note to it
    would be the worst possible reading of that button."""
    document = _doc(client, "Iceland trip")
    note = _note(client, "the ferry leaves at 8", document_ids=[document["id"]])

    client.delete(f"/documents/{document['id']}/notes/{note['id']}")

    listed = client.get("/entries").json()
    assert [n["id"] for n in listed] == [note["id"]]
    assert listed[0]["documents"] == []


def test_a_note_with_no_documents_says_so_rather_than_omitting_the_field(client):
    """The frontend renders what it is given; a missing key is a crash."""
    note = _note(client, "unattached")
    assert note["documents"] == []
