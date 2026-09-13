"""Re-evaluate a note: refresh confidence + category, suggest tags & links."""

from __future__ import annotations


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_reevaluate_returns_entry_and_suggestions(ai_client):
    entry = _save(ai_client, "a funny dad joke about scarecrows")
    _save(ai_client, "another hilarious dad joke worth remembering")

    response = ai_client.post(f"/entries/{entry['id']}/reevaluate")
    assert response.status_code == 200
    body = response.json()

    assert body["entry"]["id"] == entry["id"]
    assert isinstance(body["suggested_tags"], list)
    assert isinstance(body["suggested_links"], list)
    assert "recategorised_to" in body


def test_reevaluate_missing_note_is_404(ai_client):
    assert ai_client.post("/entries/99999/reevaluate").status_code == 404


def test_reevaluate_leaves_user_filed_category_alone(ai_client):
    # A note the user filed themselves must keep its category.
    entry = _save(ai_client, "notes about the football scores", category="Personal")
    body = ai_client.post(f"/entries/{entry['id']}/reevaluate").json()
    assert body["entry"]["category"] == "Personal"
    assert body["recategorised_to"] is None


def test_reevaluate_survives_ai_offline(client):
    # The default `client` fixture has all AI unavailable, re-evaluate must
    # still return (empty) suggestions rather than error.
    entry = _save(client, "some note with no AI available")
    response = client.post(f"/entries/{entry['id']}/reevaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["suggested_tags"] == []
    assert body["suggested_links"] == []
