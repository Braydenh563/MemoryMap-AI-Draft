"""Reading an attached file shows up in Settings -> Background tasks.

Asked for twice, most recently as *"the describe with ai feature needs to show
in background process, same for all ocr processes"*. Describing a file or
reading one with a vision model was invisible: the button went quiet, the panel
that lists background work showed nothing, and on a slow local model the only
evidence anything was happening was that the app had not answered yet.

The interesting test is the last one. `/files/{id}/analyse` is synchronous, so
the claim being made is not "a job is queued" but "while this request is inside
the model call, another request to `/tasks` can see it". That is asserted from
inside the fake model, which is exactly where a real `/tasks` request would
land: on another worker thread, mid-call.
"""

from __future__ import annotations

import pytest

from memorymap.api import routes_files, routes_tasks
from memorymap.core import deps, filejobs


def test_a_reading_in_flight_is_listed():
    with filejobs.reading("describe", 7, "handout.md", "fake-utility"):
        rows = {task["kind"]: task for task in routes_tasks.collect()}
        assert "file-describe" in rows
        assert rows["file-describe"]["label"] == "Describing a file"
        assert "handout.md" in rows["file-describe"]["detail"]
        assert "fake-utility" in rows["file-describe"]["detail"]


def test_a_finished_reading_leaves_the_list():
    with filejobs.reading("ocr", 7, "scan.pdf"):
        pass
    assert all(not task["kind"].startswith("file-") for task in routes_tasks.collect())


def _the_model_falls_over() -> None:
    """What a model call does when Ollama is gone or the file cannot be read.

    A function rather than a bare `raise` inside the `with` below, for two
    reasons. It stands in for the real thing, which is always a call, and
    CodeQL read the inline version as making the assertion after the block
    unreachable (alert 395): `pytest.raises` swallows the exception, and
    nothing in the `raise` statement itself says so.
    """
    raise ValueError("the model fell over")


def test_a_reading_that_raises_leaves_the_list():
    # The failure mode every registry of this shape has: a model that throws
    # (no Ollama, an unreadable file) leaving a row on the panel for the rest
    # of the session.
    with pytest.raises(ValueError):
        with filejobs.reading("vision", 7, "scan.pdf", "fake-vision"):
            _the_model_falls_over()
    assert all(not task["kind"].startswith("file-") for task in routes_tasks.collect())


def test_two_readings_of_one_file_are_two_rows():
    # Keyed on (kind, id), not the id: describing a scan and OCR-ing it are two
    # different readings of one file and a person can start both.
    with filejobs.reading("describe", 7, "scan.pdf"):
        with filejobs.reading("ocr", 7, "scan.pdf"):
            kinds = [t["kind"] for t in routes_tasks.collect() if t["kind"].startswith("file-")]
    assert sorted(kinds) == ["file-describe", "file-ocr"]


def test_a_file_reading_is_not_offered_a_quit_button():
    # A single blocking model call owns nothing interruptible, and a Quit
    # button that did nothing would be worse than no button.
    with filejobs.reading("describe", 7, "handout.md"):
        rows = {task["kind"]: task for task in routes_tasks.collect()}
        assert rows["file-describe"].get("cancellable") in (None, False)


class _Models:
    def utility_model(self):
        return "fake-utility"


def test_describe_with_ai_announces_itself_while_the_model_runs(client, monkeypatch):
    """The end-to-end claim: the row exists *during* the request, not after."""
    seen: list[dict] = []

    class _Ollama:
        def is_running(self):
            return True

    def _describe(text, models, ollama):
        # Standing in for a concurrent GET /tasks on another worker thread.
        seen.extend(t for t in routes_tasks.collect() if t["kind"].startswith("file-"))
        return "A short description."

    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    monkeypatch.setattr(routes_files.captioning, "describe_document", _describe)

    entry_id = client.post("/entries", json={"content": "host note"}).json()["id"]
    made = client.post(
        f"/entries/{entry_id}/files",
        files={"file": ("handout.md", b"# Agents\n\nSome readable content.", "text/markdown")},
    )
    body = made.json()
    file_id = body["id"] if "id" in body else body["files"][0]["id"]

    got = client.post(f"/files/{file_id}/analyse", json={"kind": "caption", "force": True})
    assert got.status_code == 200, got.text
    assert [t["kind"] for t in seen] == ["file-describe"]
    assert "handout.md" in seen[0]["detail"]
    # And it is gone once the request has answered.
    assert all(not t["kind"].startswith("file-") for t in routes_tasks.collect())
