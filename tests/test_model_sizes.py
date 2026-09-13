"""Suggested-model sizes: measured where we can, marked where we can't (§35J).

Reported: "the approximate sizes for the suggested models are not correct".
They are hand-written, and §33 defends the hand-written *list* against
odysseus's Cookbook: a curated model database that has to be maintained or it
rots. That argument still holds for the list.

A hand-written *number* is a different thing. It goes stale every time a
publisher re-quantises a tag, and a wrong one is worse than none, because it is
the figure someone checks their free disk against before committing to a
download.

Only one half of this is knowable locally. For an installed model the backend
knows exactly how many bytes it took; for one that is not installed there is no
local source of truth, and asking a registry over the network is not a call
this app should make to draw a settings list. So the two are told apart rather
than blended: `measured` or `approximate`, and the UI can say which.
"""

from __future__ import annotations

from memorymap.ai.model_manager import SUGGESTED_MODELS


def _flat(body: dict) -> dict[str, dict]:
    return {m["name"]: m for models in body.values() for m in models}


def test_an_installed_model_reports_its_real_size(ai_client, fake_ollama):
    fake_ollama.installed = [{"name": "llama3.2", "size": 2_300_000_000}]
    entry = _flat(ai_client.get("/models/suggested").json())["llama3.2"]
    assert entry["size"] == "2.3 GB"
    assert entry["size_source"] == "measured"


def test_an_uninstalled_model_keeps_the_shipped_figure_and_says_so(ai_client, fake_ollama):
    fake_ollama.installed = []
    entry = _flat(ai_client.get("/models/suggested").json())["llama3.2"]
    shipped = next(m for m in SUGGESTED_MODELS["text"] if m["name"] == "llama3.2")
    assert entry["size"] == shipped["size"]
    assert entry["size_source"] == "approximate"


def test_embedding_models_are_measured_too(ai_client, fake_ollama):
    """They are the smaller download and the one people are least sure about."""
    fake_ollama.installed = [{"name": "nomic-embed-text", "size": 274_000_000}]
    entry = _flat(ai_client.get("/models/suggested").json())["nomic-embed-text"]
    assert entry["size"] == "274 MB"
    assert entry["size_source"] == "measured"


def test_a_backend_that_is_off_still_returns_the_list(ai_client, fake_ollama):
    """Choosing a model to download is exactly what you do when nothing is
    installed yet, so this list must never depend on the backend answering."""
    fake_ollama.running = False
    body = ai_client.get("/models/suggested").json()
    assert len(_flat(body)) == sum(len(v) for v in SUGGESTED_MODELS.values())
    assert all(m["size_source"] == "approximate" for m in _flat(body).values())


def test_every_shipped_entry_still_has_a_name_size_and_purpose():
    """The shape the settings list reads. A missing purpose is a row that says
    nothing about why you would pick it."""
    for models in SUGGESTED_MODELS.values():
        for model in models:
            assert model["name"] and model["size"] and model["purpose"]
