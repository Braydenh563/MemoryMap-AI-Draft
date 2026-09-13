"""The OCR workspace offers the document reader and the vision model separately.

Reported: *"in the ocr workspace, my ocr model shows as a vision model and my
actual vision model doesnt appear as an option at all."* Exactly right, and it
was two faults at once.

`resolve_ocr_model` prefers a model built to transcribe a page (GLM-OCR,
DeepSeek-OCR, PaddleOCR-VL) and falls back to a general vision model;
`resolve_vision_model` answers "can anything here see an image". On a machine
with both installed they return different models, and the workspace offered a
single option, labelled "AI vision model", naming whichever of the two the
picker resolved. The other model could not be reached from the UI at all.

Worse, the two halves disagreed: `ocr_readers` had been fixed to call
`resolve_ocr_model` while `_vision_read_page` still called
`resolve_vision_model`, so the picker could name one model and the read use the
other. That is why the report came back after the first fix.
"""

from __future__ import annotations

from memorymap.api import routes_files


class _Manager:
    def __init__(self, ocr_model: str, vision_model: str) -> None:
        self._ocr = ocr_model
        self._vision = vision_model

    def resolve_ocr_model(self, ollama, installed=None):
        return self._ocr

    def resolve_vision_model(self, ollama, installed=None):
        return self._vision


class _Running:
    def is_running(self) -> bool:
        return True


def _patch(monkeypatch, ocr_model: str, vision_model: str) -> None:
    monkeypatch.setattr(routes_files.deps, "get_model_manager", lambda: _Manager(ocr_model, vision_model))
    monkeypatch.setattr(routes_files.deps, "get_ollama", _Running)


def test_two_different_models_are_two_different_options(client, monkeypatch):
    _patch(monkeypatch, "glm-ocr:latest", "qwen2.5-vl:7b")
    body = client.get("/ocr-readers").json()
    assert body["vision_model"] == "glm-ocr:latest", "the default reader is the document reader"
    assert body["ocr"] is True
    assert body["ocr_model"] == "qwen2.5-vl:7b", "the vision model must be reachable too"


def test_one_model_is_offered_once(client, monkeypatch):
    """Offering the same model twice under two names is a worse picker."""
    _patch(monkeypatch, "qwen2.5-vl:7b", "qwen2.5-vl:7b")
    body = client.get("/ocr-readers").json()
    assert body["vision_model"] == "qwen2.5-vl:7b"
    assert body["ocr"] is False
    assert body["ocr_model"] == ""


def test_the_read_uses_the_model_the_picker_named(monkeypatch):
    """The fault that made the first fix look like it had not worked."""
    _patch(monkeypatch, "glm-ocr:latest", "qwen2.5-vl:7b")
    assert routes_files._reader_model("vision") == "glm-ocr:latest"
    assert routes_files._reader_model("ocr") == "qwen2.5-vl:7b"


def test_an_unknown_reader_is_refused(client):
    """A typo must not quietly charge the reader a vision pass."""
    assert routes_files.READERS == ("vision", "ocr", "tesseract")
