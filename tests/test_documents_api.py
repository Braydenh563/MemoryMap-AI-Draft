"""Long-form documents: CRUD, export, and AI editing.

The rule that matters: an AI edit never writes to the document by itself.
"""

from __future__ import annotations


def test_create_read_update_delete(client):
    created = client.post(
        "/documents", json={"title": "My essay", "content": "# Intro\n\nSome text."}
    ).json()
    assert created["title"] == "My essay"
    assert created["words"] == 4  # "#" counts as a token, like most editors

    fetched = client.get(f"/documents/{created['id']}").json()
    assert fetched["content"] == "# Intro\n\nSome text."

    updated = client.put(
        f"/documents/{created['id']}", json={"content": "# Intro\n\nMore text now."}
    ).json()
    assert "More text now" in updated["content"]
    assert updated["title"] == "My essay"  # untouched fields stay put

    # Requests happen outside the asserts so they still run under `python -O`.
    deleted = client.delete(f"/documents/{created['id']}")
    assert deleted.json()["deleted"] is True
    gone = client.get(f"/documents/{created['id']}")
    assert gone.status_code == 404


def test_documents_are_listed_most_recently_edited_first(client):
    first = client.post("/documents", json={"title": "First"}).json()
    client.post("/documents", json={"title": "Second"}).json()
    client.put(f"/documents/{first['id']}", json={"content": "touched"})

    titles = [d["title"] for d in client.get("/documents").json()]
    assert titles[0] == "First"


def test_documents_past_the_page_size_are_still_reachable(client):
    """`list_documents` once had a `.limit(200)` with **no offset**: a
    notebook with more than 200 documents had no way, UI or API, to see the
    rest. The list is paged again (INBOX 117), so this guard stays and asks
    the question the old cap failed: is everything still reachable? It is,
    through `offset`, and `X-Total-Count` is how a caller knows to ask."""
    from memorymap.api import routes_documents

    size = routes_documents.DOCUMENTS_PAGE_SIZE
    for i in range(size + 5):
        client.post("/documents", json={"title": f"Doc {i}"})

    first = client.get("/documents")
    assert len(first.json()) == size
    assert first.headers["X-Total-Count"] == str(size + 5)

    rest = client.get("/documents", params={"offset": size})
    assert len(rest.json()) == 5
    seen = {d["id"] for d in first.json()} | {d["id"] for d in rest.json()}
    assert len(seen) == size + 5


def test_documents_search_matches_the_title(client):
    client.post("/documents", json={"title": "Sourdough notes", "content": "starter"})
    client.post("/documents", json={"title": "Trip planning", "content": "flights"})
    titles = [d["title"] for d in client.get("/documents?q=sourdough").json()]
    assert titles == ["Sourdough notes"]


def test_documents_search_matches_content_not_only_title(client):
    """The gap `GET /documents?q=` exists to close: `_summary()` never sends
    a document's body to the browser, so client-side filtering alone could
    only ever match a title, the AI's own `_list_documents` tool already
    searched title *and* content; this mirrors it rather than a title-only
    filter reachable from the API."""
    client.post("/documents", json={"title": "Untitled", "content": "carbonara guanciale"})
    client.post("/documents", json={"title": "Untitled", "content": "unrelated"})
    hits = client.get("/documents?q=guanciale").json()
    assert len(hits) == 1


def test_documents_search_is_case_insensitive(client):
    client.post("/documents", json={"title": "Sourdough", "content": ""})
    assert len(client.get("/documents?q=SOURDOUGH").json()) == 1


def test_documents_search_with_no_matches_is_an_empty_list_not_an_error(client):
    client.post("/documents", json={"title": "Sourdough"})
    assert client.get("/documents?q=nonexistentxyz").json() == []


def test_documents_empty_q_behaves_like_no_q_at_all(client):
    client.post("/documents", json={"title": "A"})
    client.post("/documents", json={"title": "B"})
    assert len(client.get("/documents?q=").json()) == 2


def test_documents_never_show_up_as_notes(client):
    """A document is not a captured thought; it must stay out of note search."""
    client.post("/documents", json={"title": "Essay", "content": "carbonara guanciale"})
    entries = client.get("/entries").json()
    assert entries == []


def test_markdown_export_includes_the_title_and_a_filename(client):
    created = client.post(
        "/documents", json={"title": "My Essay", "content": "Body text."}
    ).json()
    response = client.get(f"/documents/{created['id']}/export.md")

    assert response.status_code == 200
    assert response.text.startswith("# My Essay")
    assert "Body text." in response.text
    assert 'filename="My-Essay.md"' in response.headers["content-disposition"]


def test_export_filename_cannot_be_steered_by_the_title(client):
    """The title is user text, it must not decide where the file lands."""
    created = client.post(
        "/documents", json={"title": "../../etc/passwd", "content": "x"}
    ).json()
    disposition = client.get(f"/documents/{created['id']}/export.md").headers[
        "content-disposition"
    ]
    assert "/" not in disposition.split("filename=")[1]
    assert ".." not in disposition.split("filename=")[1]


def test_ai_edit_returns_a_revision_without_saving_it(ai_client, fake_ollama):
    """An AI edit that silently overwrote the document would be the most
    destructive thing in the app."""
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "The original text."}
    ).json()
    fake_ollama.librarian_reply = "The rewritten text."

    body = ai_client.post(
        f"/documents/{created['id']}/ai-edit", json={"instruction": "make it formal"}
    ).json()

    assert body["revised"] == "The rewritten text."
    assert body["replaced_selection"] is False
    # The stored document is untouched until the user accepts.
    stored = ai_client.get(f"/documents/{created['id']}").json()
    assert stored["content"] == "The original text."


def test_ai_edit_of_a_selection_only_sees_that_passage(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents",
        json={"title": "Essay", "content": "Paragraph one.\n\nParagraph two."},
    ).json()
    fake_ollama.librarian_reply = "Paragraph two, rewritten."

    body = ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={"instruction": "tighten this", "selection": "Paragraph two."},
    ).json()

    assert body["replaced_selection"] is True
    prompt = fake_ollama.chat_calls[-1][-1]["content"]
    assert "Paragraph two." in prompt
    assert "Paragraph one." not in prompt


def test_ai_edit_without_the_model_returns_the_text_unchanged(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "Careful prose."}
    ).json()
    fake_ollama.running = False

    body = ai_client.post(
        f"/documents/{created['id']}/ai-edit", json={"instruction": "improve it"}
    ).json()
    assert body["revised"] == "Careful prose."
    assert body["ollama_running"] is False


def test_ai_edit_of_an_empty_document_is_a_clean_400(ai_client):
    created = ai_client.post("/documents", json={"title": "Empty"}).json()
    response = ai_client.post(
        f"/documents/{created['id']}/ai-edit", json={"instruction": "write it"}
    )
    assert response.status_code == 400


# --- the write/remove verb set (reskinned from a single rewrite action) -----


def test_ai_write_inserts_new_content_without_needing_existing_text(ai_client, fake_ollama):
    """The one verb an empty document must NOT 400 on, there is nothing to
    edit yet, but there is plenty to write."""
    created = ai_client.post("/documents", json={"title": "Empty"}).json()
    fake_ollama.librarian_reply = "A brand new opening paragraph."

    response = ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={"instruction": "write an opening paragraph", "verb": "write"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verb"] == "write"
    assert body["revised"] == "A brand new opening paragraph."
    assert body["replaced_selection"] is False


def test_ai_write_requires_an_instruction(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "Some text."}
    ).json()
    response = ai_client.post(
        f"/documents/{created['id']}/ai-edit", json={"verb": "write"}
    )
    assert response.status_code == 400


def test_ai_write_uses_the_selection_as_the_insertion_point_not_the_target(
    ai_client, fake_ollama
):
    created = ai_client.post(
        "/documents",
        json={"title": "Essay", "content": "Paragraph one.\n\nParagraph two."},
    ).json()
    fake_ollama.librarian_reply = "A new sentence."

    ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={
            "instruction": "add a supporting sentence",
            "selection": "Paragraph one.",
            "verb": "write",
        },
    )
    prompt = fake_ollama.chat_calls[-1][-1]["content"]
    assert "Paragraph one." in prompt
    assert "INSERT DIRECTLY AFTER" in prompt


def test_ai_remove_deletes_a_selection_with_no_instruction_needed(ai_client, fake_ollama):
    """Asked for directly: a selection alone already says what to remove."""
    created = ai_client.post(
        "/documents",
        json={"title": "Essay", "content": "Paragraph one.\n\nParagraph two."},
    ).json()
    fake_ollama.librarian_reply = "Paragraph one."

    response = ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={"selection": "Paragraph two.", "verb": "remove"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verb"] == "remove"
    assert body["replaced_selection"] is True
    assert body["revised"] == "Paragraph one."


def test_ai_remove_with_no_selection_needs_an_instruction(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "Some text about cats."}
    ).json()
    response = ai_client.post(
        f"/documents/{created['id']}/ai-edit", json={"verb": "remove"}
    )
    assert response.status_code == 400


def test_ai_remove_leaves_the_document_untouched_until_accepted(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "Keep this. Remove that."}
    ).json()
    fake_ollama.librarian_reply = "Keep this."

    ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={"instruction": "remove the second sentence", "verb": "remove"},
    )
    stored = ai_client.get(f"/documents/{created['id']}").json()
    assert stored["content"] == "Keep this. Remove that."


# --- the AI-edit changelog ("allow edits made by the AI to be undone or
# altered before and after they are set") --------------------------------


def test_ai_edit_log_records_and_lists_an_entry(client):
    created = client.post(
        "/documents", json={"title": "Essay", "content": "Before text."}
    ).json()
    logged = client.post(
        f"/documents/{created['id']}/ai-edit-log",
        json={
            "verb": "edit",
            "instruction": "make it formal",
            "before_content": "Before text.",
            "after_content": "After text.",
        },
    )
    assert logged.status_code == 201
    assert logged.json()["verb"] == "edit"
    assert logged.json()["instruction"] == "make it formal"

    listed = client.get(f"/documents/{created['id']}/ai-edit-log").json()
    assert len(listed) == 1
    assert listed[0]["id"] == logged.json()["id"]


def test_ai_edit_log_stores_a_selection_excerpt_not_the_full_selection(client):
    created = client.post("/documents", json={"title": "Essay", "content": "x"}).json()
    long_selection = "word " * 100
    logged = client.post(
        f"/documents/{created['id']}/ai-edit-log",
        json={
            "instruction": "",
            "selection": long_selection,
            "before_content": "x",
            "after_content": "y",
        },
    ).json()
    assert len(logged["selection_excerpt"]) <= 161  # 160 chars + the ellipsis
    assert logged["selection_excerpt"].endswith("…")


def test_ai_edit_log_prunes_beyond_the_cap(client):
    from memorymap.api import routes_documents

    created = client.post("/documents", json={"title": "Essay", "content": "x"}).json()
    total = routes_documents.MAX_AI_EDIT_LOG_PER_DOCUMENT + 5
    for i in range(total):
        client.post(
            f"/documents/{created['id']}/ai-edit-log",
            json={
                "instruction": f"edit {i}",
                "before_content": "x",
                "after_content": "y",
            },
        )
    listed = client.get(f"/documents/{created['id']}/ai-edit-log").json()
    assert len(listed) == routes_documents.MAX_AI_EDIT_LOG_PER_DOCUMENT
    # Newest first, and the oldest ones are the ones that got pruned.
    assert listed[0]["instruction"] == f"edit {total - 1}"


def test_revert_ai_edit_restores_the_documents_content(client):
    created = client.post(
        "/documents", json={"title": "Essay", "content": "After the AI's edit."}
    ).json()
    logged = client.post(
        f"/documents/{created['id']}/ai-edit-log",
        json={
            "instruction": "tighten it",
            "before_content": "Before the AI's edit.",
            "after_content": "After the AI's edit.",
        },
    ).json()

    response = client.post(f"/documents/{created['id']}/ai-edit-log/{logged['id']}/revert")
    assert response.status_code == 200
    assert response.json()["content"] == "Before the AI's edit."

    stored = client.get(f"/documents/{created['id']}").json()
    assert stored["content"] == "Before the AI's edit."


def test_revert_ai_edit_records_its_own_changelog_entry(client):
    """The changelog stays a truthful record of everything that happened,
    including the revert itself, never a silent rewind."""
    created = client.post(
        "/documents", json={"title": "Essay", "content": "After."}
    ).json()
    logged = client.post(
        f"/documents/{created['id']}/ai-edit-log",
        json={"instruction": "do the thing", "before_content": "Before.", "after_content": "After."},
    ).json()

    client.post(f"/documents/{created['id']}/ai-edit-log/{logged['id']}/revert")

    listed = client.get(f"/documents/{created['id']}/ai-edit-log").json()
    assert len(listed) == 2
    assert listed[0]["verb"] == "revert"
    assert "do the thing" in listed[0]["instruction"]


def test_revert_ai_edit_can_itself_be_reverted(client):
    created = client.post("/documents", json={"title": "Essay", "content": "v2"}).json()
    logged = client.post(
        f"/documents/{created['id']}/ai-edit-log",
        json={"before_content": "v1", "after_content": "v2"},
    ).json()
    client.post(f"/documents/{created['id']}/ai-edit-log/{logged['id']}/revert")
    stored_after_revert = client.get(f"/documents/{created['id']}").json()
    assert stored_after_revert["content"] == "v1"

    # Revert the revert (the newest changelog entry), should bring v2 back.
    listed = client.get(f"/documents/{created['id']}/ai-edit-log").json()
    revert_entry_id = listed[0]["id"]
    client.post(f"/documents/{created['id']}/ai-edit-log/{revert_entry_id}/revert")
    stored_after_second_revert = client.get(f"/documents/{created['id']}").json()
    assert stored_after_second_revert["content"] == "v2"


def test_revert_ai_edit_404s_for_an_entry_from_a_different_document(client):
    doc_a = client.post("/documents", json={"title": "A", "content": "a"}).json()
    doc_b = client.post("/documents", json={"title": "B", "content": "b"}).json()
    logged = client.post(
        f"/documents/{doc_a['id']}/ai-edit-log",
        json={"before_content": "old", "after_content": "a"},
    ).json()
    response = client.post(f"/documents/{doc_b['id']}/ai-edit-log/{logged['id']}/revert")
    assert response.status_code == 404


def test_ai_write_without_the_model_returns_nothing_to_insert(ai_client, fake_ollama):
    created = ai_client.post(
        "/documents", json={"title": "Essay", "content": "Some text."}
    ).json()
    fake_ollama.running = False

    body = ai_client.post(
        f"/documents/{created['id']}/ai-edit",
        json={"instruction": "add a sentence", "verb": "write"},
    ).json()
    # Falling back to the existing content (compose()'s own contract) would
    # insert the whole document into itself, "write" must fall back to ""
    # instead, since there is nothing sensible to insert.
    assert body["revised"] == ""
    assert body["ollama_running"] is False


def test_missing_documents_are_404(client):
    fetched = client.get("/documents/9999")
    assert fetched.status_code == 404
    updated = client.put("/documents/9999", json={"title": "x"})
    assert updated.status_code == 404
    deleted = client.delete("/documents/9999")
    assert deleted.status_code == 404


def test_storage_says_where_the_notebook_actually_is(client, tmp_path):
    """"Where are my documents stored?" was asked outright, and the app had
    no answer anywhere in its interface. For a local-first notebook that is
    most of the promise: a file you can't locate isn't obviously yours."""
    body = client.get("/storage").json()

    assert body["database"].endswith(".db")
    # A real path to a file that exists, not a placeholder.
    from pathlib import Path

    assert Path(body["database"]).exists()
    assert Path(body["data_dir"]).is_dir()
    assert body["database_bytes"] > 0
    # The backups folder is part of the answer to "how do I keep a copy?".
    assert "backups" in body["backups_dir"].lower()


# --- file types (a document is no longer always markdown) ---------------------


def test_a_new_document_defaults_to_markdown(client):
    """By direct instruction: any file type, "though it should default to md"."""
    assert client.post("/documents", json={"title": "Notes"}).json()["file_type"] == "md"


def test_a_document_can_be_created_as_code(client):
    created = client.post(
        "/documents", json={"title": "Script", "content": "x = 1", "file_type": "py"}
    ).json()
    assert created["file_type"] == "py"


def test_the_type_can_be_changed_after_the_fact(client):
    created = client.post("/documents", json={"title": "Thing"}).json()
    updated = client.put(f"/documents/{created['id']}", json={"file_type": "sql"}).json()
    assert updated["file_type"] == "sql"


def test_an_autosave_of_content_alone_does_not_reset_the_type(client):
    """The failure this guards is silent and total: the editor autosaves
    content constantly, and a `file_type` that defaulted rather than staying
    None would turn every code document back into markdown mid-edit."""
    created = client.post(
        "/documents", json={"title": "Script", "file_type": "py"}
    ).json()
    updated = client.put(
        f"/documents/{created['id']}", json={"content": "print(1)"}
    ).json()
    assert updated["file_type"] == "py"


def test_an_unknown_type_falls_back_rather_than_refusing_the_save(client):
    """A 422 here would refuse to save someone's writing because of a field
    that only describes how to display it."""
    created = client.post(
        "/documents", json={"title": "Odd", "content": "hi", "file_type": "wat"}
    ).json()
    assert created["file_type"] == "md"
    assert created["content"] == "hi"


def test_a_dotted_extension_and_a_filename_both_work(client):
    """All three spellings turn up: the picker sends "py", an import sends
    ".py", and a drag-and-drop has a filename."""
    for sent in (".py", "script.py", "PY"):
        made = client.post("/documents", json={"title": "T", "file_type": sent}).json()
        assert made["file_type"] == "py", sent


def test_exporting_a_code_document_uses_its_own_extension(client):
    """A Python document must not download as a .md containing Python."""
    created = client.post(
        "/documents", json={"title": "My Script", "content": "x = 1", "file_type": "py"}
    ).json()
    response = client.get(f"/documents/{created['id']}/export.md")
    assert response.headers["content-disposition"].endswith('.py"')
    # No `# My Script` preamble: a markdown H1 at the top of a .py is a
    # comment by luck, and at the top of a .json it is a syntax error.
    assert response.text == "x = 1"


def test_exporting_a_markdown_document_still_carries_its_title(client):
    created = client.post(
        "/documents", json={"title": "My Essay", "content": "Body."}
    ).json()
    response = client.get(f"/documents/{created['id']}/export.md")
    assert response.headers["content-disposition"].endswith('.md"')
    assert response.text.startswith("# My Essay")


def test_the_file_type_table_is_served_for_the_editor(client):
    """The editor needs the table itself, not a lookup: indenting and
    comment-toggling happen on keystrokes."""
    body = client.get("/documents/file-types").json()
    assert body["default"] == "md"
    by_ext = {t["ext"]: t for t in body["types"]}
    assert by_ext["py"]["line_comment"] == "#"
    assert by_ext["py"]["indent"] == "    "
    assert by_ext["md"]["previewable"] is True
    assert by_ext["py"]["previewable"] is False
    # HTML has no line-comment form; toggling one has to wrap it instead.
    assert by_ext["html"]["line_comment"] == ""
    assert by_ext["html"]["block_comment"] == ["<!-- ", " -->"]


def test_the_file_types_route_is_not_swallowed_by_the_id_route(client):
    """FastAPI matches in definition order and "file-types" is a fine string
    for a path parameter typed int, registered the other way round this
    would 422 on every call."""
    assert client.get("/documents/file-types").status_code == 200


# --- pagination (INBOX 117: this list used to hand back the whole table,
# 300 documents measured at 116.7 KB in one response) ----------------------


def test_documents_page_and_report_the_real_total(client):
    for i in range(5):
        client.post("/documents", json={"title": f"Doc {i}", "content": "words here"})

    first = client.get("/documents", params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    assert len(first.json()) == 2
    assert first.headers["X-Total-Count"] == "5"

    second = client.get("/documents", params={"limit": 2, "offset": 2})
    assert len(second.json()) == 2
    assert second.headers["X-Total-Count"] == "5"

    last = client.get("/documents", params={"limit": 2, "offset": 4})
    assert len(last.json()) == 1
    assert last.headers["X-Total-Count"] == "5"

    # `offset` reaches the rest: paging through returns every document
    # exactly once, which is what stops a cap making page two unreachable.
    paged = [d["id"] for d in first.json() + second.json() + last.json()]
    assert len(set(paged)) == 5
    whole = client.get("/documents", params={"limit": 100})
    assert set(paged) == {d["id"] for d in whole.json()}


def test_documents_default_page_is_bounded_but_the_common_case_is_unchanged(client):
    """Any notebook under the default page size sees exactly what it saw
    before, and the header reports the true total either way."""
    from memorymap.api import routes_documents

    for i in range(3):
        client.post("/documents", json={"title": f"Doc {i}"})
    response = client.get("/documents")
    assert len(response.json()) == 3
    assert response.headers["X-Total-Count"] == "3"
    assert routes_documents.DOCUMENTS_PAGE_SIZE <= routes_documents.DOCUMENTS_PAGE_SIZE_MAX


def test_documents_search_total_counts_the_matches_not_the_table(client):
    """With `q` given, `X-Total-Count` has to be the size of the *search*:
    a caller paging a search against the whole table's count would loop
    past the end of its own results."""
    client.post("/documents", json={"title": "Sourdough notes", "content": "flour"})
    client.post("/documents", json={"title": "Sourdough again", "content": "water"})
    client.post("/documents", json={"title": "Tax return", "content": "receipts"})

    response = client.get("/documents", params={"q": "sourdough", "limit": 1})
    assert len(response.json()) == 1
    assert response.headers["X-Total-Count"] == "2"


def test_documents_limit_is_validated(client):
    from memorymap.api import routes_documents

    assert client.get("/documents", params={"limit": 0}).status_code == 422
    assert client.get("/documents", params={"offset": -1}).status_code == 422
    over = routes_documents.DOCUMENTS_PAGE_SIZE_MAX + 1
    assert client.get("/documents", params={"limit": over}).status_code == 422


def test_a_document_with_a_note_attached_can_still_be_deleted(client, session):
    """Four tables point at a document, and the delete knew about two.

    `DocumentLink` (the notes attached to this document) and
    `DocumentBookmark` (its saved links) hold a real foreign key with no
    cascade, so a document with a note attached could not be deleted **at
    all**: `FOREIGN KEY constraint failed`, a 500, and the document still
    there. The integration the owner asked for, notes and documents joined
    up, was what made a document undeletable.

    The same shape had already bitten once, for revisions and AI edits, and
    the comment recording that is still above the fix. The list is now taken
    from `grep 'ForeignKey("documents.id")'` rather than from memory, which
    is the only thing that stops it going stale a third time.
    """
    from sqlalchemy import func, select

    from memorymap.core.database import DocumentBookmark, DocumentLink

    note = client.post("/entries", json={"content": "a note to attach"}).json()
    document = client.post("/documents", json={"title": "Doc", "content": "body"}).json()
    assert client.post(
        f"/documents/{document['id']}/notes", json={"entry_id": note["id"]}
    ).status_code == 201
    session.commit()
    assert session.scalar(select(func.count()).select_from(DocumentLink)) == 1

    removed = client.delete(f"/documents/{document['id']}")
    assert removed.status_code == 200, removed.text
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(DocumentLink)) == 0
    assert session.scalar(select(func.count()).select_from(DocumentBookmark)) == 0
    # The note itself is not the document's to delete.
    assert client.get(f"/entries/{note['id']}").status_code == 200
