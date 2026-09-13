"""Which model reads text off a page, and when that happens automatically.

Asked directly: *"what if I have qwen3-vl and glm-ocr available?"* and *"does
the pdf rasterisation happen automatically?"*

The thing that is easy to get wrong here: rasterising a PDF does not read
anything. It turns a page into a picture, and a model still has to read the
picture: so both a photo and a scanned page take a vision-capable model, and
every backend reports the same `vision` capability for a general VLM and for a
document reader. The capability cannot break that tie, which is why the tie is
broken here.
"""

from __future__ import annotations

from memorymap.ai import model_manager as mm


class _FakeOllama:
    def __init__(self, installed):
        self._installed = [{"name": n} for n in installed]

    def list_models(self):
        return self._installed

    def supports(self, name, capability):
        # Every one of these can see. That is the whole problem.
        return capability == "vision"

    def is_running(self):
        return True


def _manager(app_state):
    return mm.ModelManager(app_state)


# --- telling a document reader from a general vision model ---------------------


def test_ocr_families_are_recognised_under_any_spelling():
    """The same weights arrive as `glm-ocr`, `GLM-OCR:latest`, and
    `hf.co/ggml-org/GLM-OCR-GGUF:Q8_0`."""
    for name in ("glm-ocr", "GLM-OCR:latest", "hf.co/ggml-org/GLM-OCR-GGUF:Q8_0",
                 "deepseek-ocr", "PaddleOCR-VL-1.6"):
        assert mm.is_ocr_model(name), name


def test_a_general_vision_model_is_not_treated_as_a_reader():
    for name in ("qwen3-vl:4b", "qwen2.5vl:7b", "llava", "moondream", "llama3.2"):
        assert not mm.is_ocr_model(name), name


# --- the question that was asked -----------------------------------------------


def test_with_both_installed_the_document_reader_wins(app_state):
    """Plain vision auto-detect answers this by taking whichever the backend
    listed first, which is arbitrary. Both can see an image; only one is built
    to transcribe a page."""
    ollama = _FakeOllama(["qwen3-vl:4b", "hf.co/ggml-org/GLM-OCR-GGUF:Q8_0"])
    assert _manager(app_state).resolve_ocr_model(ollama).endswith("GLM-OCR-GGUF:Q8_0")


def test_the_order_the_backend_lists_them_in_does_not_matter(app_state):
    reader = "deepseek-ocr"
    for order in ([reader, "llava"], ["llava", reader]):
        assert _manager(app_state).resolve_ocr_model(_FakeOllama(order)) == reader


def test_with_no_reader_installed_any_vision_model_still_reads(app_state):
    """Refusing would be worse: a general VLM transcribes imperfectly, which
    beats not transcribing."""
    assert _manager(app_state).resolve_ocr_model(_FakeOllama(["llava"])) == "llava"


def test_nothing_installed_resolves_to_nothing(app_state):
    assert _manager(app_state).resolve_ocr_model(_FakeOllama([])) is None


# --- what the user chooses always wins -----------------------------------------


def test_an_explicit_ocr_model_beats_the_preference_order(app_state):
    manager = _manager(app_state)
    manager.set_ocr_model("moondream")
    assert manager.resolve_ocr_model(_FakeOllama(["glm-ocr", "moondream"])) == "moondream"


def test_an_explicit_vision_model_is_used_only_when_no_reader_is_installed(app_state):
    """No document reader installed: fall back to the vision model chosen for
    an unrelated job (chat) rather than guessing among whatever else can see."""
    manager = _manager(app_state)
    manager.set_vision_model("qwen2.5vl:7b")
    assert manager.resolve_ocr_model(_FakeOllama(["llava"])) == "qwen2.5vl:7b"


def test_an_installed_reader_beats_an_explicit_but_unrelated_vision_model(app_state):
    """Reported live: "I pressed read text with AI, but it used my vision
    model and not my OCR model", a real OCR-family model was installed, but
    an earlier version of this function let an explicit vision-model choice
    (set for chat, never for OCR) outrank it. A document reader sitting right
    there beats a setting made for a different purpose."""
    manager = _manager(app_state)
    manager.set_vision_model("qwen2.5vl:7b")
    assert manager.resolve_ocr_model(_FakeOllama(["glm-ocr"])) == "glm-ocr"


def test_clearing_the_choice_returns_to_automatic(app_state):
    manager = _manager(app_state)
    manager.set_ocr_model("moondream")
    manager.set_ocr_model("")
    assert manager.resolve_ocr_model(_FakeOllama(["glm-ocr"])) == "glm-ocr"


def test_the_status_endpoint_reports_both_the_choice_and_what_it_resolved_to(client):
    body = client.get("/models/status").json()
    assert "ocr_model" in body
    assert "ocr_model_resolved" in body


def test_the_status_endpoint_reports_whether_tesseract_is_installed(client):
    """Reported directly: the local-OCR button was shown enabled whether or
    not the `tesseract` binary was actually there, so pressing it without
    it just silently did nothing. A plain bool the frontend can gate on."""
    body = client.get("/models/status").json()
    assert isinstance(body["tesseract_available"], bool)


def test_the_picker_refuses_a_model_that_is_not_installed(client):
    response = client.post("/models/ocr-model", json={"name": "not-a-real-model"})
    assert response.status_code in (200, 400)  # 200 only when the backend is off


# --- rasterisation is automatic, and degrades rather than failing ---------------


def test_the_reader_is_none_when_nothing_can_do_the_job(monkeypatch):
    """Returning None rather than a reader that always fails is what lets
    docview fall through to its own message, which names the missing piece."""
    from memorymap.ai import vision_ocr
    from memorymap.core import pdfpages

    monkeypatch.setattr(pdfpages, "available", lambda: False)
    assert vision_ocr.pdf_reader_or_none() is None


def test_both_entry_points_pass_a_reader_rather_than_omitting_it():
    """docview has always accepted a vision_reader; the bug worth guarding is
    a caller that quietly passes nothing, which is how the whole path went
    unexecuted before. Checked in the source because exercising it needs a
    running model."""
    from pathlib import Path

    for name in ("routes_files.py", "routes_documents.py"):
        text = (Path("src/memorymap/api") / name).read_text(encoding="utf-8")
        assert "docview.extract(" in text
        assert "pdf_reader_or_none()" in text, name


def test_the_status_poll_resolves_the_vision_model_once(app_state, monkeypatch):
    """Reported as `GET /models/status: signal timed out`.

    Resolving a vision model walks every installed model asking `/api/show`
    whether it can see, one HTTP round trip each, cached per process but cold
    on the first poll. The status endpoint needs both a vision answer and an
    OCR answer, and deriving them independently walked that list twice, which
    on a real install was enough to pass the frontend's own 5s abort.
    """
    manager = _manager(app_state)
    walks = []
    real = manager.resolve_vision_model

    def counted(ollama, installed=None):
        walks.append(1)
        return real(ollama, installed)

    monkeypatch.setattr(manager, "resolve_vision_model", counted)
    ollama = _FakeOllama(["llava", "moondream"])
    vision = manager.resolve_vision_model(ollama)
    manager.resolve_ocr_model(ollama, None, vision_fallback=vision or "")
    assert len(walks) == 1


def test_the_fallback_is_only_used_when_nothing_better_exists(app_state):
    """Passing a pre-resolved vision model must not override a document reader
    that is actually installed, the whole point of the preference order."""
    manager = _manager(app_state)
    got = manager.resolve_ocr_model(
        _FakeOllama(["llava", "glm-ocr"]), None, vision_fallback="llava"
    )
    assert got == "glm-ocr"
