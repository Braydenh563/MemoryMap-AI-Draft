"""Extract notes (BACKLOG.md §62): split free text into one or more
AI-filed notes, auto-linked with real reasons.

The rule that matters most, mirrored from `test_link_reasons.py`: a link
this feature makes must never carry `manager.AUTO_REASON_TEXT`, every
assertion about a link's reason checks it is real text from
`generate_link_reason`, not the generic guessed placeholder.
"""

from __future__ import annotations

import json

from memorymap.ai import extractor
from memorymap.entry import manager


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- unit: propose_split ------------------------------------------------------


def test_propose_split_parses_the_models_json(fake_ollama):
    from memorymap.core import deps

    fake_ollama.extract_split_reply = json.dumps(
        {"notes": [{"title": "A", "content": "first topic"}, {"title": "B", "content": "second topic"}]}
    )
    notes = extractor.propose_split("whatever", deps.get_model_manager(), fake_ollama)
    assert [n.content for n in notes] == ["first topic", "second topic"]
    assert [n.title for n in notes] == ["A", "B"]


def test_propose_split_caps_at_max_extract_notes(fake_ollama):
    from memorymap.core import deps

    too_many = [{"title": f"T{i}", "content": f"content {i}"} for i in range(extractor.MAX_EXTRACT_NOTES + 5)]
    fake_ollama.extract_split_reply = json.dumps({"notes": too_many})
    notes = extractor.propose_split("whatever", deps.get_model_manager(), fake_ollama)
    assert len(notes) == extractor.MAX_EXTRACT_NOTES


def test_propose_split_raises_on_unparsable_reply(fake_ollama):
    from memorymap.core import deps

    fake_ollama.extract_split_reply = "not json at all"
    try:
        extractor.propose_split("whatever", deps.get_model_manager(), fake_ollama)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- unit: merge_near_duplicates ----------------------------------------------


def test_merge_folds_two_same_topic_notes_into_one(fake_embeddings):
    notes = [
        extractor.ExtractedNote(title="A", content="a funny scarecrow joke"),
        extractor.ExtractedNote(title="B", content="another funny pun"),
    ]
    merged = extractor.merge_near_duplicates(notes, fake_embeddings)
    assert len(merged) == 1
    assert "scarecrow" in merged[0].content and "pun" in merged[0].content


def test_merge_leaves_different_topic_notes_apart(fake_embeddings):
    notes = [
        extractor.ExtractedNote(title="A", content="a funny scarecrow joke"),
        extractor.ExtractedNote(title="B", content="buy milk and eggs"),
    ]
    merged = extractor.merge_near_duplicates(notes, fake_embeddings)
    assert len(merged) == 2


# --- build_extraction: offline / split-failure fallbacks ----------------------


def test_offline_falls_back_to_one_plain_note(client, session):
    from memorymap.core import deps

    result = extractor.build_extraction(
        session, "some thoughts to save", deps.get_embeddings(), deps.get_model_manager(), deps.get_ollama()
    )
    assert len(result["notes"]) == 1
    assert result["notes"][0]["content"] == "some thoughts to save"
    assert result["ollama_running"] is False
    assert result["links"] == []
    assert result["message"] == extractor.OFFLINE_MESSAGE


def test_unparsable_split_reply_falls_back_to_one_note_not_an_error(ai_client, fake_ollama, session):
    from memorymap.core import deps

    fake_ollama.extract_split_reply = "not json"
    result = extractor.build_extraction(
        session, "some thoughts", deps.get_embeddings(), deps.get_model_manager(), deps.get_ollama()
    )
    assert len(result["notes"]) == 1
    assert result["notes"][0]["content"] == "some thoughts"
    assert result["message"] == extractor.SPLIT_FAILED_MESSAGE


# --- API: /entries/extract/preview --------------------------------------------


def test_preview_empty_text_is_a_clean_400(ai_client):
    response = ai_client.post("/entries/extract/preview", json={"text": "   "})
    assert response.status_code == 400


def test_preview_splits_into_several_notes_with_sibling_links(ai_client, fake_ollama):
    fake_ollama.extract_split_reply = json.dumps(
        {
            "notes": [
                {"title": "Joke", "content": "a funny scarecrow joke"},
                {"title": "Groceries", "content": "buy milk and eggs"},
            ]
        }
    )
    fake_ollama.librarian_reply = "both jotted down during the same call"

    body = ai_client.post("/entries/extract/preview", json={"text": "raw thoughts here"}).json()

    assert len(body["notes"]) == 2
    contents = {n["content"] for n in body["notes"]}
    assert contents == {"a funny scarecrow joke", "buy milk and eggs"}
    # Distinct topics, distinct categories from the janitor's own pass.
    categories = {n["category"] for n in body["notes"]}
    assert len(categories) == 2

    sibling_links = [link for link in body["links"] if link["kind"] == "sibling"]
    assert len(sibling_links) == 1
    assert sibling_links[0]["reason"] == "both jotted down during the same call"
    assert sibling_links[0]["reason"] != manager.AUTO_REASON_TEXT


def test_a_single_topic_is_not_split(ai_client, fake_ollama):
    fake_ollama.extract_split_reply = json.dumps(
        {"notes": [{"title": "Joke", "content": "a funny scarecrow joke"}]}
    )
    body = ai_client.post("/entries/extract/preview", json={"text": "a funny scarecrow joke"}).json()
    assert len(body["notes"]) == 1
    assert body["links"] == []


def test_preview_finds_related_existing_notes_with_a_real_reason(ai_client, fake_ollama):
    _save(ai_client, "another funny pun")  # same topic axis as the new note
    fake_ollama.extract_split_reply = json.dumps(
        {"notes": [{"title": "Joke", "content": "a funny scarecrow joke"}]}
    )
    fake_ollama.librarian_reply = "both are jokes about wordplay"

    body = ai_client.post("/entries/extract/preview", json={"text": "a funny scarecrow joke"}).json()

    related = [link for link in body["links"] if link["kind"] == "related"]
    assert len(related) == 1
    assert related[0]["reason"] == "both are jokes about wordplay"
    assert related[0]["reason"] != manager.AUTO_REASON_TEXT
    assert related[0]["target_ref"].startswith("existing:")


def test_preview_links_back_to_explicit_source_notes(ai_client, fake_ollama):
    source = _save(ai_client, "race day at the carnival")
    fake_ollama.extract_split_reply = json.dumps(
        {"notes": [{"title": "Sprint", "content": "100m sprint results"}]}
    )
    fake_ollama.librarian_reply = "both about the same carnival race"

    body = ai_client.post(
        "/entries/extract/preview",
        json={"text": "100m sprint results", "source_entry_ids": [source["id"]]},
    ).json()

    source_links = [link for link in body["links"] if link["kind"] == "source"]
    assert len(source_links) == 1
    assert source_links[0]["target_ref"] == f"existing:{source['id']}"
    assert source_links[0]["reason"] == "both about the same carnival race"


def test_a_private_source_note_is_excluded_entirely(ai_client, fake_ollama, session):
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    try:
        source = _save(ai_client, "a private race day note")
        privacy = ai_client.post(f"/entries/{source['id']}/privacy", json={"private": True})
        assert privacy.status_code == 200

        fake_ollama.extract_split_reply = json.dumps(
            {"notes": [{"title": "Sprint", "content": "100m sprint results"}]}
        )
        body = ai_client.post(
            "/entries/extract/preview",
            json={"text": "100m sprint results", "source_entry_ids": [source["id"]]},
        ).json()

        assert body["links"] == []
    finally:
        vault.close()


def test_preview_without_ollama_is_one_plain_note_and_says_so(client):
    body = client.post("/entries/extract/preview", json={"text": "raw thoughts"}).json()
    assert len(body["notes"]) == 1
    assert body["notes"][0]["content"] == "raw thoughts"
    assert body["ollama_running"] is False
    assert body["message"] == extractor.OFFLINE_MESSAGE


# --- API: /entries/extract/commit ---------------------------------------------


def test_commit_creates_notes_and_links_with_the_reasons_it_was_given(ai_client):
    response = ai_client.post(
        "/entries/extract/commit",
        json={
            "notes": [
                {"ref": "n0", "title": "Joke", "content": "a funny scarecrow joke", "category": "Dad Jokes"},
                {"ref": "n1", "title": "Groceries", "content": "buy milk and eggs", "category": "Shopping"},
            ],
            "links": [
                {"source_ref": "n0", "target_ref": "n1", "reason": "written in the same sitting"},
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["notes"]) == 2
    assert body["links_created"] == 1

    all_entries = ai_client.get("/entries").json()
    contents = {e["content"] for e in all_entries}
    assert "a funny scarecrow joke" in contents
    assert "buy milk and eggs" in contents

    linked = next(e for e in all_entries if e["content"] == "a funny scarecrow joke")
    assert len(linked["links"]) == 1
    assert linked["links"][0]["reason"] == "written in the same sitting"
    assert linked["links"][0]["reason"] != manager.AUTO_REASON_TEXT


def test_commit_links_to_an_existing_note_by_ref(ai_client):
    existing = _save(ai_client, "an existing note")
    response = ai_client.post(
        "/entries/extract/commit",
        json={
            "notes": [{"ref": "n0", "content": "a brand new note"}],
            "links": [
                {"source_ref": "n0", "target_ref": f"existing:{existing['id']}", "reason": "they share a deadline"}
            ],
        },
    )
    assert response.status_code == 201
    assert response.json()["links_created"] == 1

    refreshed = ai_client.get(f"/entries/{existing['id']}").json()
    assert any(link["reason"] == "they share a deadline" for link in refreshed["links"])


def test_commit_silently_skips_a_link_to_a_note_deleted_since_preview(ai_client):
    existing = _save(ai_client, "will be deleted")
    ai_client.delete(f"/entries/{existing['id']}")

    response = ai_client.post(
        "/entries/extract/commit",
        json={
            "notes": [{"ref": "n0", "content": "a brand new note"}],
            "links": [
                {"source_ref": "n0", "target_ref": f"existing:{existing['id']}", "reason": "a reason"}
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["notes"]) == 1  # the note still saves
    assert body["links_created"] == 0  # the dangling link is just skipped


def test_commit_attaches_notes_to_the_source_document(ai_client):
    document = ai_client.post("/documents", json={"title": "Essay", "content": "some body text"}).json()

    response = ai_client.post(
        "/entries/extract/commit",
        json={
            "notes": [{"ref": "n0", "content": "an extracted note"}],
            "links": [],
            "source_document_id": document["id"],
        },
    )
    assert response.status_code == 201
    new_id = response.json()["notes"][0]["id"]

    refreshed = ai_client.get(f"/documents/{document['id']}").json()
    assert any(n["id"] == new_id for n in refreshed["notes"])


def test_commit_rejects_a_ref_used_by_two_notes(ai_client):
    response = ai_client.post(
        "/entries/extract/commit",
        json={
            "notes": [
                {"ref": "n0", "content": "first"},
                {"ref": "n0", "content": "second, same ref"},
            ],
            "links": [],
        },
    )
    assert response.status_code == 400


def test_commit_rejects_more_notes_than_max_extract_notes(ai_client):
    notes = [{"ref": f"n{i}", "content": f"note {i}"} for i in range(extractor.MAX_EXTRACT_NOTES + 1)]
    response = ai_client.post("/entries/extract/commit", json={"notes": notes, "links": []})
    assert response.status_code == 422  # FastAPI's own schema validation, not a hand-written 400


# --- the whole round trip: preview's own output commits cleanly ---------------


def test_a_previews_own_output_commits_without_modification(ai_client, fake_ollama):
    fake_ollama.extract_split_reply = json.dumps(
        {"notes": [{"title": "Joke", "content": "a funny scarecrow joke"}]}
    )
    fake_ollama.librarian_reply = "a real generated reason"
    existing = _save(ai_client, "race day at the carnival")

    preview = ai_client.post(
        "/entries/extract/preview",
        json={"text": "a funny scarecrow joke", "source_entry_ids": [existing["id"]]},
    ).json()

    commit_body = {
        "notes": [
            {
                "ref": n["ref"],
                "title": n["title"],
                "content": n["content"],
                "category": n["category"],
                "tags": n["tags"],
            }
            for n in preview["notes"]
        ],
        "links": [
            {"source_ref": link["source_ref"], "target_ref": link["target_ref"], "reason": link["reason"]}
            for link in preview["links"]
        ],
    }
    commit = ai_client.post("/entries/extract/commit", json=commit_body)
    assert commit.status_code == 201
    assert commit.json()["links_created"] == len(preview["links"])
