"""Deleting a file can take its `![...]()` out of the notes that showed it.

Reported directly: *"notes still mention removed images"*. Deleting the file
used to leave the markdown behind, so every note that embedded it rendered a
"this image was removed" placeholder for the rest of its life, with no way to
tidy it but editing the note by hand and knowing what to look for.

Off by default on the route, because deleting a file and editing someone's
notes are two different acts: the caller asks for the second one (the Library's
delete confirm offers it as a tickbox, ticked).
"""

from __future__ import annotations

from memorymap.api.routes_files import _embed_pattern


def _upload(client, name="pic.png"):
    files = {"file": (name, b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}
    return client.post("/media/upload", files=files).json()


def test_an_embed_is_removed_from_the_note(client):
    upload = _upload(client)
    note = client.post(
        "/entries", json={"content": f"Before\n\n![a photo]({upload['url']})\n\nAfter"}
    ).json()

    client.delete(f"/media/{upload['id']}?strip_references=true")

    after = client.get(f"/entries/{note['id']}").json()
    assert "![a photo]" not in after["content"]
    assert after["content"] == "Before\n\nAfter"


def test_the_default_leaves_the_note_alone(client):
    """Deleting a file is not permission to edit notes, the placeholder is
    still the right answer when nobody asked for the tidy-up."""
    upload = _upload(client)
    body = f"Keep this\n\n![a photo]({upload['url']})"
    note = client.post("/entries", json={"content": body}).json()

    client.delete(f"/media/{upload['id']}")

    assert client.get(f"/entries/{note['id']}").json()["content"] == body


def test_a_link_to_the_file_survives(client):
    """`[see the scan](/media/x.png)` is a sentence the author wrote. Removing
    it would leave a hole in their prose; only the *embed* goes."""
    upload = _upload(client)
    body = f"As in [the scan]({upload['url']}), the total was 42."
    note = client.post("/entries", json={"content": body}).json()

    client.delete(f"/media/{upload['id']}?strip_references=true")

    assert client.get(f"/entries/{note['id']}").json()["content"] == body


def test_other_notes_and_other_images_are_untouched(client):
    first = _upload(client, "one.png")
    second = _upload(client, "two.png")
    keeper = client.post("/entries", json={"content": f"![two]({second['url']})"}).json()
    doomed = client.post("/entries", json={"content": f"![one]({first['url']})"}).json()

    client.delete(f"/media/{first['id']}?strip_references=true")

    assert client.get(f"/entries/{keeper['id']}").json()["content"] == f"![two]({second['url']})"
    assert client.get(f"/entries/{doomed['id']}").json()["content"] == ""


def test_an_attachment_embed_is_removed_too(client):
    """The other table, the other url shape (`/files/{id}`), same rule."""
    note = client.post("/entries", json={"content": "host"}).json()
    files = {"file": ("scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}
    attachment = client.post(f"/entries/{note['id']}/files", files=files).json()["attachments"][-1]
    client.put(
        f"/entries/{note['id']}",
        json={"content": f"host\n\n![scan](/files/{attachment['id']})"},
    )

    client.delete(f"/files/{attachment['id']}?strip_references=true")

    assert client.get(f"/entries/{note['id']}").json()["content"] == "host"


def test_the_response_names_the_notes_it_edited(client):
    """So the UI can say what it did rather than quietly rewriting notes."""
    upload = _upload(client)
    note = client.post("/entries", json={"content": f"x ![p]({upload['url']})"}).json()
    body = client.delete(f"/media/{upload['id']}?strip_references=true").json()
    assert body["cleaned_notes"] == [note["id"]]


def test_the_pattern_matches_markdown_titles_but_not_neighbours():
    pattern = _embed_pattern("/media/a.png")
    assert pattern.search('![x](/media/a.png "A title")')
    assert pattern.search("![x](/media/a.png 'A title')")
    assert not pattern.search("![x](/media/ab.png)")
    assert not pattern.search("[x](/media/a.png)")


# --- the rebuild suggestion --------------------------------------------------
#
# Asked for: "suggest rebuilding the search index upon large changes." The
# counter is the whole mechanism, it decides whether the app says anything at
# all, so it is worth pinning down what moves it and what clears it.


def test_a_bulk_import_marks_the_index_stale(client):
    files = [("files", (f"note{i}.md", b"some text", "text/markdown")) for i in range(3)]
    client.post("/import/markdown", files=files)
    status = client.get("/models/status").json()
    assert status["index_stale_notes"] == 3


def test_saving_one_note_the_normal_way_does_not(client):
    """A note written in the app embeds itself as it is saved. Counting those
    would make the suggestion fire on ordinary use, which is how a suggestion
    becomes something people learn to ignore."""
    client.post("/entries", json={"content": "just typing"})
    assert client.get("/models/status").json()["index_stale_notes"] == 0


def test_the_threshold_travels_with_the_count(client):
    """The UI must not hard-code a number the backend can change."""
    status = client.get("/models/status").json()
    assert status["index_stale_suggest_at"] >= 1
