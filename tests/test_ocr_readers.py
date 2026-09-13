"""GET /ocr-readers: the OCR workspace's reader picker.

Reported live: "I can only select the vision models not OCR models."
`resolve_vision_model` and `resolve_ocr_model` both report *something* can
read a page when any vision-capable model is installed (an OCR-family model
is vision-capable too), so the bug was never "nothing to pick", it was that
the endpoint named the wrong model: whichever generic vision model
auto-detect found, never a dedicated document reader, even when one was
installed and even when the user had explicitly set it as their OCR model.
"""

from __future__ import annotations


def test_reports_the_ocr_family_model_not_a_generic_vision_one(ai_client, fake_ollama):
    fake_ollama.installed = [
        {"name": "llava:latest"},
        {"name": "glm-ocr:latest"},
    ]
    fake_ollama.capabilities_declared = ["vision"]
    body = ai_client.get("/ocr-readers").json()
    assert body["vision"] is True
    assert body["vision_model"] == "glm-ocr:latest"


def test_an_explicit_ocr_model_preference_wins(ai_client, fake_ollama):
    from memorymap.core import deps

    fake_ollama.installed = [{"name": "llava:latest"}, {"name": "some-ocr-model:latest"}]
    fake_ollama.capabilities_declared = ["vision"]
    deps.get_model_manager().set_ocr_model("some-ocr-model:latest")
    try:
        body = ai_client.get("/ocr-readers").json()
        assert body["vision_model"] == "some-ocr-model:latest"
    finally:
        deps.get_model_manager().set_ocr_model("")


def test_falls_back_to_a_generic_vision_model_when_no_reader_is_installed(ai_client, fake_ollama):
    fake_ollama.installed = [{"name": "llava:latest"}]
    fake_ollama.capabilities_declared = ["vision"]
    body = ai_client.get("/ocr-readers").json()
    assert body["vision"] is True
    assert body["vision_model"] == "llava:latest"


def test_offline_reports_not_running(client):
    body = client.get("/ocr-readers").json()
    assert body["vision"] is False
    assert body["vision_reason"] == "The AI model isn't running."
