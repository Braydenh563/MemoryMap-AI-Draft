"""AI text-editing operations on a note's own content: Improve Writing
(proofread/rewrite/concise/custom) and generating or removing a title."""

from __future__ import annotations


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- improve writing ----------------------------------------------------------------


def test_improve_writing_returns_edited_text(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "I went to the shop."
    body = ai_client.post(
        "/entries/improve", json={"text": "i goed to teh shop", "mode": "proofread"}
    ).json()
    assert body["improved"] == "I went to the shop."
    assert body["original"] == "i goed to teh shop"


def test_improve_writing_offline_is_503(client):
    response = client.post("/entries/improve", json={"text": "fix me"})
    assert response.status_code == 503


def test_improve_writing_rejects_empty(ai_client):
    assert ai_client.post("/entries/improve", json={"text": "   "}).status_code == 400


def test_improve_writing_custom_instruction_reaches_the_model(ai_client, fake_ollama):
    """The three presets (proofread/rewrite/concise) are fixed instructions;
    "custom" is the user's own words instead, this is the one path where
    what they typed has to actually reach the system prompt, not just get
    accepted by the API."""
    fake_ollama.librarian_reply = "Bonjour, ceci est une note."
    body = ai_client.post(
        "/entries/improve",
        json={
            "text": "hello, this is a note",
            "mode": "custom",
            "custom_instruction": "translate to French",
        },
    ).json()
    assert body["improved"] == "Bonjour, ceci est une note."
    system_prompt = fake_ollama.chat_calls[-1][0]["content"]
    assert "translate to French" in system_prompt


def test_improve_writing_custom_mode_needs_an_instruction(ai_client):
    """Picking "Custom" with nothing typed yet is a real state the UI passes
    through (the mode switches before the person has typed anything), it
    must not reach the model with an empty steering instruction."""
    response = ai_client.post(
        "/entries/improve", json={"text": "fix me", "mode": "custom"}
    )
    assert response.status_code == 400


# --- generating and removing a title --------------------------------------------------


def test_generate_title_writes_a_heading(ai_client, fake_ollama):
    note = _save(ai_client, "Packed the tent and the good coffee. Left at dawn.")
    fake_ollama.librarian_reply = "Weekend trip to the coast"

    body = ai_client.post(f"/entries/{note['id']}/generate-title").json()
    assert body["title"] == "Weekend trip to the coast"
    assert body["content"].startswith("# Weekend trip to the coast\n")
    assert "Packed the tent" in body["content"]


def test_generate_title_replaces_an_existing_one(ai_client, fake_ollama):
    note = _save(ai_client, "# Old title\nsome body text")
    fake_ollama.librarian_reply = "A better title"

    body = ai_client.post(f"/entries/{note['id']}/generate-title").json()
    assert body["title"] == "A better title"
    assert body["content"].count("#") == 1


def test_generate_title_offline_is_503(client):
    note = _save(client, "some text")
    assert client.post(f"/entries/{note['id']}/generate-title").status_code == 503


def test_remove_title_takes_the_heading_out(ai_client):
    note = _save(ai_client, "# A trip\nPacked the tent.")
    body = ai_client.post(f"/entries/{note['id']}/remove-title").json()
    assert body["title"] is None
    assert body["content"] == "Packed the tent."


def test_remove_title_on_an_untitled_note_is_a_no_op(ai_client):
    note = _save(ai_client, "just a plain thought")
    body = ai_client.post(f"/entries/{note['id']}/remove-title").json()
    assert body["content"] == "just a plain thought"
