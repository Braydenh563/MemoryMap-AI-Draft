"""Private notes: encrypted at rest, and kept away from search and the AI.

The three things that must hold, in order of how bad it is to get them wrong:
  1. A private note's text is not in the database in the clear.
  2. Marking a note private never loses it.
  3. A private note never reaches search results or the model's context.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from memorymap.ai import agent, tools
from memorymap.core import crypto, vault
from memorymap.core.database import EmbeddingRecord, Entry


@pytest.fixture(autouse=True)
def open_vault(session):
    """Tests don't go through setup/unlock, so open the vault by hand.

    Closed again afterwards so a test that locks it can't leak that state into
    the next one.
    """
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    yield
    vault.close()


def _make_private(client, session, content):
    entry = client.post("/entries", json={"content": content}).json()
    body = client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    assert body.status_code == 200
    return body.json()


def test_opening_a_private_note_leaves_an_audit_trail(client, session):
    """The whole value of a private note is confidence, and nothing recorded
    *when* one was decrypted for viewing, asked about directly. A regular
    note doesn't get this extra log line (it already has plenty of other
    activity logged), only a private one."""
    private = _make_private(client, session, "the spare key is under the mat")
    public = client.post("/entries", json={"content": "buy milk"}).json()

    before = client.get("/audit?entity_type=entry&limit=200").json()
    client.get(f"/entries/{private['id']}")
    client.get(f"/entries/{public['id']}")
    after = client.get("/audit?entity_type=entry&limit=200").json()

    new_rows = after[: len(after) - len(before)]
    decrypted = [r for r in new_rows if r["action"] == "decrypted"]
    assert len(decrypted) == 1
    assert decrypted[0]["entity_id"] == private["id"]


def test_a_private_note_is_not_stored_in_the_clear(client, session):
    secret = "my bank pin is 4715 and the spare key is under the mat"
    _make_private(client, session, secret)

    stored = session.scalars(select(Entry)).all()[-1]
    assert crypto.is_encrypted(stored.content)
    assert secret not in stored.content
    assert stored.is_private is True


def test_a_private_note_still_reads_back_correctly(client, session):
    secret = "the actual text, unchanged"
    marked = _make_private(client, session, secret)
    assert marked["content"] == secret
    assert marked["is_private"] is True

    # And through a normal fetch, not just the response to the change.
    again = client.get(f"/entries/{marked['id']}").json()
    assert again["content"] == secret


def test_making_a_note_private_and_back_again_loses_nothing(client, session):
    original = "round trip me"
    marked = _make_private(client, session, original)

    back = client.post(f"/entries/{marked['id']}/privacy", json={"private": False}).json()
    assert back["content"] == original
    assert back["is_private"] is False

    stored = session.get(Entry, marked["id"])
    assert stored.content == original  # plaintext again on disk


def test_a_private_note_has_its_embedding_removed(client, session):
    """A vector encodes what the note is about, keeping one leaks the point."""
    entry = client.post("/entries", json={"content": "something to embed"}).json()
    session.add(
        EmbeddingRecord(entry_id=entry["id"], embedding=b"\x00" * 8, dim=2, model_version="test")
    )
    session.commit()
    assert session.scalar(
        select(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry["id"])
    ) is not None

    client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    remaining = session.scalar(
        select(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry["id"])
    )
    assert remaining is None


def test_private_notes_are_kept_out_of_search(client, session):
    from memorymap.search import search_manager

    _make_private(client, session, "pineapple submarine, a very distinctive phrase")
    client.post("/entries", json={"content": "an ordinary public note"})

    found = search_manager.keyword_search(session, "pineapple")
    assert found == []
    recent = search_manager.recent_entries(session)
    assert all(not e.is_private for e in recent)


def test_private_notes_never_reach_the_model(ai_client, fake_ollama, session):
    """The one that matters most: the AI must not be handed a private note.

    The secret is deliberately different from the question, so finding it in
    the prompt can only mean the note leaked, not that the query echoed.
    """
    secret = "codeword ELDERFLOWER opens the safe"
    _make_private(ai_client, session, f"about submarines: {secret}")
    ai_client.post("/entries", json={"content": "an ordinary public note on submarines"})
    fake_ollama.librarian_reply = "Here's what I found."

    body = ai_client.post("/chat", json={"question": "tell me about submarines"}).json()

    assert all("ELDERFLOWER" not in r["content"] for r in body["raw_results"])
    prompt = " ".join(m["content"] for m in fake_ollama.chat_calls[-1])
    assert "ELDERFLOWER" not in prompt


def test_a_private_note_cannot_be_attached_by_id_either(ai_client, fake_ollama, session):
    """The gap the search-side guard above doesn't cover: `note_ids` is a
    client-supplied list, the one path into the chat prompt that never went
    through `tools._require_note`, the only other thing that refuses a
    private note. A forged or stale id in that list must not put the note's
    id, category or content in front of the model just because it was named
    directly instead of found."""
    secret = "codeword FOXGLOVE opens the safe"
    private = _make_private(ai_client, session, f"about kayaking: {secret}")
    ai_client.post("/entries", json={"content": "an ordinary public note on kayaking"})
    fake_ollama.librarian_reply = "Here's what I found."

    # Everything up to here (creating and filing both notes) is allowed to
    # have shown the model the plaintext, that's the janitor auto-filing a
    # note that only became private afterwards, unrelated to this request.
    # Only what the /chat call itself sends is under test.
    before = len(fake_ollama.chat_calls)
    body = ai_client.post(
        "/chat", json={"question": "what do you make of this?", "note_ids": [private["id"]]}
    ).json()

    assert private["id"] not in [r["id"] for r in body["raw_results"]]
    sent_this_request = " ".join(
        m["content"] for call in fake_ollama.chat_calls[before:] for m in call
    )
    assert "FOXGLOVE" not in sent_this_request
    assert "kayaking:" not in sent_this_request  # the private note's own content prefix


def test_generate_title_refuses_a_private_note(ai_client, fake_ollama, session):
    """`generate-title` reads `readable_content` (decrypted) and writes the
    result straight back to `entry.content`, for a private note that would
    silently replace the ciphertext with plaintext, un-encrypting the note
    as a side effect of titling it. Refused outright."""
    private = _make_private(ai_client, session, "a private thought")
    fake_ollama.librarian_reply = "A generated title"

    response = ai_client.post(f"/entries/{private['id']}/generate-title")
    assert response.status_code == 400

    stored = session.get(Entry, private["id"])
    assert crypto.is_encrypted(stored.content)


def test_remove_title_refuses_a_private_note(ai_client, session):
    private = _make_private(ai_client, session, "# A title\na private thought")
    response = ai_client.post(f"/entries/{private['id']}/remove-title")
    assert response.status_code == 400

    stored = session.get(Entry, private["id"])
    assert crypto.is_encrypted(stored.content)


def test_privacy_needs_an_open_vault(client, session):
    """The key only exists in memory while unlocked."""
    entry = client.post("/entries", json={"content": "x"}).json()
    vault.close()
    response = client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    assert response.status_code == 409
    assert "Unlock" in response.json()["detail"]


def test_a_locked_vault_shows_a_placeholder_rather_than_breaking(client, session):
    """A private note must not take the whole notes list down with it."""
    marked = _make_private(client, session, "secret text")
    vault.close()

    listed = client.get("/entries").json()
    private = next(e for e in listed if e["id"] == marked["id"])
    assert "secret text" not in private["content"]
    assert "Private note" in private["content"]
    # Everything else still lists normally.
    assert isinstance(listed, list)


def test_exports_decrypt_while_unlocked(client, session):
    """An export is for taking notes elsewhere; ciphertext isn't your notes."""
    secret = "ELDERFLOWER export check"
    _make_private(client, session, secret)

    as_json = client.get("/export/json").json()
    assert any(secret in e["content"] for e in as_json["entries"])

    as_csv = client.get("/export/csv").text
    assert secret in as_csv


def test_exports_do_not_leak_when_locked(client, session):
    """With no key there is nothing to decrypt with, say so, don't guess."""
    secret = "ELDERFLOWER locked export"
    _make_private(client, session, secret)
    vault.close()

    as_json = client.get("/export/json").json()
    assert all(secret not in e["content"] for e in as_json["entries"])
    assert any("Private note" in e["content"] for e in as_json["entries"])


def test_an_existing_notebook_upgrades_without_a_reset(tmp_path):
    """Adding encryption must not ask anyone to rebuild their database.

    Simulates a database made before this feature existed: notes and a user,
    but no vault row and no is_private column.
    """
    import bcrypt
    from memorymap.core.database import DatabaseManager, Entry, User, Vault

    db_path = tmp_path / "existing.db"
    manager = DatabaseManager(db_path)
    old = manager.session()
    old.add(
        User(
            username="owner",
            password_hash=bcrypt.hashpw(b"their-password", bcrypt.gensalt()).decode(),
        )
    )
    old.add(Entry(content="a note written months ago", ai_confidence=0))
    old.commit()
    old.close()

    # The app restarts on the new code against the same file.
    upgraded = DatabaseManager(db_path).session()
    vault.close()
    assert vault.open_with(upgraded, "their-password") is True
    upgraded.commit()

    assert len(upgraded.scalars(select(Vault)).all()) == 1
    surviving = upgraded.scalars(select(Entry)).all()
    assert [e.content for e in surviving] == ["a note written months ago"]
    assert all(e.is_private is False for e in surviving)  # backfilled, not null
    upgraded.close()
    vault.close()


# --- the AI tool boundary: a private note refuses every write path -----------


def _note(session, content="a note", tags=None, private=False):
    entry = Entry(content=content, tags=json.dumps(tags or []), is_private=private)
    session.add(entry)
    session.commit()
    return entry


@pytest.mark.parametrize(
    ("name", "extra"),
    [("tag_note", {"add": ["snooped"]}), ("link_notes", {})],
)
def test_the_batch_write_tools_still_refuse_a_private_note(session, name, extra):
    """`tag_note` and `link_notes` grew batch arguments and, in doing so,
    stopped calling `_require_note` for the notes in the batch, which is the
    single place that refuses a private note. Tagging one worked; linking to
    one leaked its existence into the graph."""
    public = _note(session, "public")
    private = _note(session, "codeword ELDERFLOWER", private=True)

    args = {"note_id": private.id, **extra}
    if name == "link_notes":
        args = {"note_id": public.id, "other_note_ids": [private.id]}
    result = tools.execute_tool(session, name, args)
    assert "error" in result and "private" in result["error"].lower()


def test_a_batch_tag_does_not_rewrite_the_callers_arguments(session):
    """The id list was built by appending to `args["note_ids"]` in place.

    The agent loop fingerprints a call as `json.dumps(arguments)` *before*
    running it, to spot repeats, so a tool that edits that dict leaves the
    ledger holding a fingerprint the arguments no longer match, and the
    repeated-call guard stops recognising the repeat.
    """
    first, second = _note(session, "one"), _note(session, "two")
    args = {"note_ids": [first.id], "note_id": second.id, "add": ["x"]}
    before = json.dumps(args, sort_keys=True)

    tools.execute_tool(session, "tag_note", dict(args))
    assert json.dumps(args, sort_keys=True) == before


def test_tagging_several_notes_at_once_can_still_be_undone(session):
    """Only single-note calls kept an undo (`undos[0] if len(undos) == 1`), so
    a batch retag of twenty notes was a change with no way back."""
    notes = [_note(session, f"note {i}") for i in range(3)]
    result = tools.execute_tool(
        session,
        "tag_note",
        {"note_ids": [n.id for n in notes], "add": ["batch"]},
    )
    assert result["tagged"] == [n.id for n in notes]
    assert result["undo"] and result["undo"]["steps"]
    assert len(result["undo"]["steps"]) == len(notes)


def test_a_single_note_tag_still_reports_its_id_and_tags(session):
    entry = _note(session, "one")
    result = tools.execute_tool(session, "tag_note", {"note_id": entry.id, "add": ["a"]})
    assert result["id"] == entry.id
    assert result["tags"] == ["a"]
    # The change list reads the note id back out of the result; it must find one.
    assert agent._change_note_id("tag_note", result) == entry.id


def test_a_locked_vault_hands_out_no_private_text_anywhere(client, session):
    """The promise of a private note, checked across every read at once.

    `test_a_private_note_is_not_stored_in_the_clear` proves the bytes on disk;
    this proves the surfaces. Twelve read endpoints plus the retrieval path
    that feeds the model, because the exclusion is only as good as its least
    careful caller and one missed path hands a private note to an LLM.

    **The trap this test carries, found while writing it.** `/search` echoes
    the query back in its own response, so searching for the secret word and
    then grepping the response for that word finds it every time, hits or no
    hits. A first run of this reported a locked vault leaking plaintext; it
    was the probe reading its own input. The echo is stripped below, and the
    lesson is worth more than the test: a privacy check that greps a response
    must first subtract whatever the caller put into the request.
    """
    from memorymap.core import deps
    from memorymap.search import search_manager

    secret = "zarquonsecret"
    made = _make_private(client, session, f"a private thought about {secret}")
    entry_id = made["id"]

    paths = [
        "/entries", f"/search?q={secret}", "/graph", "/timeline", "/insights",
        "/duplicates", "/tags", "/entries/link-suggestions", "/resurface",
        "/entries/most-accessed", "/ask-history", "/library/all",
    ]

    def leaking() -> list[str]:
        out = []
        for path in paths:
            reply = client.get(path)
            if reply.status_code != 200:
                continue
            body = reply.text.replace(f'"query":"{secret}"', '"query":""')
            if secret in body:
                out.append(path)
        return out

    # With the key loaded the owner is reading their own notebook, so the note
    # is theirs to see. Asserting *that* it appears somewhere keeps this test
    # honest: a version that hid everything would pass the locked half for the
    # wrong reason.
    assert leaking(), "the private note vanished even with the vault open"

    vault.close()
    assert leaking() == [], "a locked vault handed out the plaintext"

    vault.create(session, "test-passphrase")
    session.commit()
    entries, _mode = search_manager.retrieve(session, secret, deps.get_embeddings(), limit=10)
    assert entry_id not in [e.id for e in entries], "retrieval fed a private note to the model"
