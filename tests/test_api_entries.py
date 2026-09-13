"""The basic entries API responds over HTTP: health check, create/read,
missing-entry 404, the frontend mount, and validation."""

from __future__ import annotations

from tests._css_paths import CSS_FILES


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_post_then_get_entry(client):
    created = client.post(
        "/entries",
        json={"content": "Why did the scarecrow win an award?", "tags": ["joke"]},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["category"] == "Uncategorised"  # no AI in Phase 1
    assert body["tags"] == ["joke"]
    assert body["ai_confidence"] == 0

    listed = client.get("/entries")
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [body["id"]]

    single = client.get(f"/entries/{body['id']}")
    assert single.status_code == 200
    assert single.json()["content"] == "Why did the scarecrow win an award?"


def test_export_a_note_with_no_title_synthesises_one(client):
    # BACKLOG.md §95 item D.14: "Full export exists. There is no way to hand
    # one note to someone." Mirrors routes_documents.py's own export.md.
    created = client.post("/entries", json={"content": "Buy milk and eggs."}).json()
    response = client.get(f"/entries/{created['id']}/export.md")
    assert response.status_code == 200
    assert response.text.startswith("# Buy milk and eggs.")
    assert 'filename="Buy-milk-and-eggs.md"' in response.headers["content-disposition"]


def test_export_a_note_that_already_has_a_heading_does_not_double_it(client):
    created = client.post("/entries", json={"content": "# Recipe\n\nFlour, water."}).json()
    response = client.get(f"/entries/{created['id']}/export.md")
    assert response.text == "# Recipe\n\nFlour, water."


def test_export_filename_cannot_be_steered_by_note_content(client):
    created = client.post("/entries", json={"content": "# ../../etc/passwd"}).json()
    disposition = client.get(f"/entries/{created['id']}/export.md").headers[
        "content-disposition"
    ]
    assert "/" not in disposition.split("filename=")[1]
    assert ".." not in disposition.split("filename=")[1]


def test_a_deleted_note_cannot_be_exported(client):
    created = client.post("/entries", json={"content": "gone soon"}).json()
    client.delete(f"/entries/{created['id']}")
    assert client.get(f"/entries/{created['id']}/export.md").status_code == 404


def test_a_clippings_source_is_stored_as_real_metadata(client):
    """BACKLOG §65 ("source as metadata, not just folded into body text").
    The frontend's own `clippingMarkdown` still puts the same link in the
    body for portability: this is the queryable half that adds."""
    created = client.post(
        "/entries",
        json={
            "content": "> a clipped passage\n\n: [Example](https://example.com/page)",
            "source_url": "https://example.com/page",
            "source_title": "Example",
        },
    ).json()
    assert created["source_url"] == "https://example.com/page"
    assert created["source_title"] == "Example"

    fetched = client.get(f"/entries/{created['id']}").json()
    assert fetched["source_url"] == "https://example.com/page"
    assert fetched["source_title"] == "Example"


def test_a_source_title_is_optional(client):
    created = client.post(
        "/entries", json={"content": "clipped", "source_url": "https://example.com"}
    ).json()
    assert created["source_url"] == "https://example.com"
    assert created["source_title"] is None


def test_an_ordinary_note_has_no_source(client):
    """The overwhelming majority of notes are never a clipping, this
    proves the new columns are a no-op for them, not just "doesn't crash"."""
    created = client.post("/entries", json={"content": "an ordinary thought"}).json()
    assert created["source_url"] is None
    assert created["source_title"] is None


def test_missing_entry_is_404(client):
    assert client.get("/entries/9999").status_code == 404


# --- pagination (BACKLOG.md §20: GET /entries used to be genuinely
# unbounded, returning the whole notebook in one response every time) -------


def test_entries_page_and_report_the_real_total(client):
    for i in range(5):
        client.post("/entries", json={"content": f"note {i}"})

    first = client.get("/entries", params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    assert len(first.json()) == 2
    assert first.headers["X-Total-Count"] == "5"

    second = client.get("/entries", params={"limit": 2, "offset": 2})
    assert len(second.json()) == 2
    assert second.headers["X-Total-Count"] == "5"

    last = client.get("/entries", params={"limit": 2, "offset": 4})
    assert len(last.json()) == 1
    assert last.headers["X-Total-Count"] == "5"

    # No page overlaps or gaps: paging through with these params reconstructs
    # exactly the same set the old unpaginated response would have returned.
    paged_ids = {e["id"] for e in first.json() + second.json() + last.json()}
    whole = client.get("/entries", params={"limit": 100})
    assert paged_ids == {e["id"] for e in whole.json()}


def test_entries_default_page_size_is_bounded_but_generous(client):
    """No params at all still has to work exactly as before for any
    notebook under the default page size, the common case, and still
    report the true total either way."""
    for i in range(3):
        client.post("/entries", json={"content": f"note {i}"})
    response = client.get("/entries")
    assert response.status_code == 200
    assert len(response.json()) == 3
    assert response.headers["X-Total-Count"] == "3"


def test_entries_limit_is_validated(client):
    assert client.get("/entries", params={"limit": 0}).status_code == 422
    assert client.get("/entries", params={"limit": -1}).status_code == 422
    assert client.get("/entries", params={"offset": -1}).status_code == 422
    # Past the hard ceiling, a client can't force one giant page either.
    assert client.get("/entries", params={"limit": 999999}).status_code == 422


def test_frontend_served_at_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MemoryMap AI" in response.text
    assert client.get("/app.js").status_code == 200
    # Whiteboard subsystem split out of app.js into its own file (ROADMAP.md
    # Priority 0 item 2), loaded by a second <script> tag in index.html.
    assert client.get("/whiteboard.js").status_code == 200
    # Graph view split out of app.js into its own file (frontend refactor
    # path, the step after whiteboard), loaded by a third <script> tag: 
    # before app.js, not after, see index.html/graph.js for why.
    assert client.get("/graph.js").status_code == 200
    # style.css split into multiple linked files (ROADMAP.md Priority 0 item
    # 2): every one of them has to actually be reachable at the path
    # index.html's <link> tags use, not just the directory that holds them.
    for name in CSS_FILES:
        assert client.get(f"/css/{name.name}").status_code == 200


def test_empty_content_rejected(client):
    assert client.post("/entries", json={"content": ""}).status_code == 422


def test_a_note_has_the_same_ceiling_a_document_has(client):
    """The same app said yes and no to the same paste, by which box it went in.

    `routes_documents` has had `MAX_CONTENT` since it was written; capture
    never grew one. Measured 2026-09-12: a 5 MB note was accepted and took
    2.26 s of blocking handler time, while a 5 MB document was refused. This
    is not a new opinion about how long a note may be, it is the document's
    own number applied to the other box: 500,000 characters is a hundred
    times the longest note anyone writes.
    """
    assert client.post("/entries", json={"content": "word " * 1_000_000}).status_code == 422
    assert client.post("/entries", json={"content": "word " * 20_000}).status_code == 201


def test_a_tag_is_a_label_and_has_a_label_s_length(client):
    """A 50,000-character tag was accepted, which is a chip 50,000 characters
    wide in every list the note appears in. Clipped rather than refused: a
    save that fails because one tag was long throws the note away, which is a
    worse answer than a shortened tag. Blank tags drop out, which is what a
    trailing comma produces.
    """
    saved = client.post(
        "/entries", json={"content": "tagged", "tags": ["x" * 50_000, "   ", "fine"]}
    )
    assert saved.status_code == 201, saved.text
    assert [len(tag) for tag in saved.json()["tags"]] == [60, 4]
    # A list long enough to be a paste rather than a set of labels is refused.
    assert client.post(
        "/entries", json={"content": "t", "tags": [f"t{i}" for i in range(400)]}
    ).status_code == 422


def test_the_same_two_limits_hold_on_an_edit(client):
    """A cap that only guards the create path is not a cap.

    Every note in the notebook can be edited, so the long paste and the
    50,000-character tag simply arrive through `PUT` instead. Found by asking
    where else the shape this was fixed in can enter, rather than by a second
    report.
    """
    note = client.post("/entries", json={"content": "a note"}).json()
    assert client.put(
        f"/entries/{note['id']}", json={"content": "word " * 1_000_000}
    ).status_code == 422
    edited = client.put(f"/entries/{note['id']}", json={"tags": ["y" * 50_000, "ok"]})
    assert edited.status_code == 200, edited.text
    assert [len(tag) for tag in edited.json()["tags"]] == [60, 2]
