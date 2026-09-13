"""Vision-capable models in chat (ROADMAP.md's largest open item).

Two paths, chosen per turn by whether the chat model itself declares vision
(`routes_chat._chat_model_sees_images`):

- **The chat model can see.** An attached image reaches it directly as
  `images` on the last user message, see `routes_chat._resolve_chat_images`
  for how a `/media/upload` id becomes a data URI, and
  `ollama_client`/`openai_client`'s own `_to_*_messages` for how each
  dialect adapts that shape.
- **It can't.** Asked for directly, replacing an earlier design that swapped
  the whole turn to a different (vision-capable) model regardless of which
  chat model the user had actually chosen: the resolved vision model
  captions the image instead (`routes_chat._image_caption_context`,
  `captioning.caption_and_store`), and the *original* chat model answers
  using that caption folded into the question text. The chat model in
  `answered_by` never changes because of an attached image any more.

These tests exercise the plumbing end-to-end through the real routes, with
`FakeOllama` standing in for the model (this sandbox has no reachable
Ollama: see CLAUDE.md's own standing caveat) and confirm the one behaviour
bug an image attachment could silently trigger: a vision-only question
retrieving zero notes must not be mistaken for "nothing to answer with".
"""

from __future__ import annotations


def _upload_image(ai_client, monkeypatch) -> int:
    # A plain upload (no `direct`) is the staged case (core/media_process.py)
    #, OCR, captioning and vision OCR no longer run automatically here at
    # all, so there is no longer a background-thread race with this test's
    # own explicit /chat call to guard against (there was, before that
    # change: see test_media_process.py for the commit-time triggers this
    # replaced it with).
    response = ai_client.post(
        "/media/upload", files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_an_attached_image_reaches_a_vision_capable_chat_model_as_a_data_uri(
    ai_client, fake_ollama, monkeypatch
):
    """FakeOllama.supports() isn't per-model: declaring "vision" here makes
    it true for whichever model is asked, which is enough to stand in for
    "the chat model itself can see"."""
    fake_ollama.capabilities_declared = ["vision"]
    media_id = _upload_image(ai_client, monkeypatch)
    response = ai_client.post(
        "/chat", json={"question": "what is in this photo?", "image_media_ids": [media_id]}
    )
    assert response.status_code == 200
    sent = fake_ollama.chat_calls[-1][-1]
    assert sent["images"] and sent["images"][0].startswith("data:image/png;base64,")
    # The chat model answered directly - no separate captioning round-trip.
    assert len(fake_ollama.chat_calls) == 1


def test_a_vision_only_question_is_not_treated_as_no_matching_notes(
    ai_client, fake_ollama, monkeypatch
):
    """Retrieval never sees the image, so an empty search result must not
    stand in for "there's nothing to look at", the exact bug the guard in
    `librarian.answer` (and `routes_chat.chat_stream`'s `plain_events`)
    exists to prevent. No vision declared on the chat model here, so this
    also exercises the caption-relay path's own version of the same guard
    (`image_context`), an explicit vision_model still has to be set for a
    caption to be producible at all, same as any other caption-relay test."""
    from memorymap.core import deps

    deps.get_model_manager().set_vision_model("llava:latest")
    media_id = _upload_image(ai_client, monkeypatch)
    body = ai_client.post(
        "/chat",
        json={
            "question": "describe this completely unrelated to my notebook photo",
            "image_media_ids": [media_id],
        },
    ).json()
    assert body["ai_response"] != "I couldn't find any notes about that."
    assert body["ai_response"] == fake_ollama.librarian_reply


def test_streaming_chat_without_tools_also_carries_the_image(ai_client, fake_ollama, monkeypatch):
    """`use_tools: false` forces the plain (non-agent) streaming path: 
    `librarian.build_messages`, tracked via `chat_calls`."""
    fake_ollama.capabilities_declared = ["vision"]
    media_id = _upload_image(ai_client, monkeypatch)
    with ai_client.stream(
        "POST",
        "/chat/stream",
        json={"question": "what's this?", "image_media_ids": [media_id], "use_tools": False},
    ) as response:
        list(response.iter_lines())  # drain: the assertion is on what was sent
    sent = fake_ollama.chat_calls[-1][-1]
    assert sent.get("images")


def test_streaming_chat_in_agent_mode_also_carries_the_image(ai_client, fake_ollama, monkeypatch):
    """Agent/tools mode is the default, `agent.run_agent`, tracked via
    `tool_rounds` rather than `chat_calls` (`FakeOllama.chat_tools`)."""
    fake_ollama.capabilities_declared = ["vision"]
    media_id = _upload_image(ai_client, monkeypatch)
    with ai_client.stream(
        "POST",
        "/chat/stream",
        json={"question": "what's this?", "image_media_ids": [media_id]},
    ) as response:
        list(response.iter_lines())
    sent = fake_ollama.tool_rounds[-1][-1]
    assert sent.get("images")


def test_a_missing_media_id_is_dropped_rather_than_erroring(ai_client, fake_ollama):
    """The UI already confirmed the upload before sending its id, a miss
    means the file moved or was deleted after that, not a bad request."""
    response = ai_client.post(
        "/chat", json={"question": "hello", "image_media_ids": [999999]}
    )
    assert response.status_code == 200


def test_no_image_means_no_images_key_at_all(ai_client, fake_ollama):
    """The overwhelming majority of turns carry no attachment, this proves
    the new plumbing is a no-op for them, not just "doesn't crash". A note
    is attached so the turn actually reaches the model rather than short-
    circuiting on "no notes, no images, nothing to say" (the case the
    previous test already covers)."""
    note_id = ai_client.post("/entries", json={"content": "leftover pasta in the fridge"}).json()["id"]
    ai_client.post(
        "/chat", json={"question": "what should I have for lunch", "note_ids": [note_id]}
    )
    sent = fake_ollama.chat_calls[-1][-1]
    assert "images" not in sent


# --- the caption-relay path: a chat model with no vision of its own -------


def test_a_non_vision_chat_model_gets_a_caption_instead_of_the_raw_image(
    ai_client, fake_ollama, monkeypatch
):
    """Asked for directly: "if I am using a chat model with no vision
    capabilities, it will use the vision model to caption the image, then
    the chat model will take that caption and use it for its response."
    No capability declared here, so the (single, global-in-the-fake) chat
    model reads as unable to see - the explicit vision_model preference
    still resolves one for captioning, same as `resolve_vision_model`
    always has."""
    from memorymap.core import deps

    deps.get_model_manager().set_vision_model("llava:latest")
    media_id = _upload_image(ai_client, monkeypatch)
    ai_client.post(
        "/chat", json={"question": "what's this?", "image_media_ids": [media_id]}
    )
    # Two model calls: the caption round-trip, then the real answer.
    assert fake_ollama.chat_models == ["llava:latest", "llama3.2"]
    caption_call, answer_call = fake_ollama.chat_calls
    # The caption call is the image, described with the shared caption
    # prompt - never the user's own question.
    assert caption_call[-1]["images"]
    # The answer call reaches the ordinary chat model, no image bytes at
    # all, with the caption folded into the question text instead.
    assert "images" not in answer_call[-1]
    assert fake_ollama.librarian_reply in answer_call[-1]["content"]


def test_an_already_captioned_image_is_not_captioned_twice(ai_client, fake_ollama, monkeypatch):
    """caption_and_store's own write-once rule (core/captioning.py): a
    caption already on the upload from the background trigger must be
    reused, not regenerated, on every chat turn that references it."""
    from memorymap.core import deps

    deps.get_model_manager().set_vision_model("llava:latest")
    media_id = _upload_image(ai_client, monkeypatch)
    ai_client.post("/media/{}/caption".format(media_id), json={"text": "a hand-written caption"})
    ai_client.post(
        "/chat", json={"question": "what's this?", "image_media_ids": [media_id]}
    )
    # Only the final answer call - no caption round-trip, since one was
    # already stored (and it was set manually, not by this fake at all).
    assert fake_ollama.chat_models == ["llama3.2"]
    assert "a hand-written caption" in fake_ollama.chat_calls[-1][-1]["content"]


def test_a_question_with_no_image_still_uses_the_ordinary_chat_model(
    ai_client, fake_ollama, monkeypatch
):
    """A vision preference must never leak onto a turn that has no image,
    even with one explicitly configured."""
    from memorymap.core import deps

    deps.get_model_manager().set_vision_model("llama3.2-vision")
    note_id = ai_client.post("/entries", json={"content": "leftover pasta"}).json()["id"]
    ai_client.post("/chat", json={"question": "what should I have?", "note_ids": [note_id]})
    assert fake_ollama.chat_models[-1] != "llama3.2-vision"
