"""Voice capture endpoints: the browser records, the server
transcribes with local Whisper, nothing is sent anywhere.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from memorymap.ai import librarian, voice
from memorymap.core import deps
from memorymap.core.deps import get_session
from memorymap.entry.manager import log_action

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # a spoken note, not a podcast
# A meeting or a lecture runs far longer than a spoken note, 300MB covers
# several hours of compressed voice audio (WebM/Opus at typical browser
# bitrates), well past what CPU-based Whisper could transcribe in a sitting
# anyway, so this is a sanity ceiling, not the expected common case.
MAX_MEETING_AUDIO_BYTES = 300 * 1024 * 1024


@router.get("/status")
def status() -> dict:
    available = voice.whisper_available()
    return {
        "available": available,
        "model": deps.get_config().get_preference("voice_model", "base"),
        "hint": None if available else voice.INSTALL_HINT,
    }


def _transcribe_upload(
    file: UploadFile, session: Session, max_bytes: int, over_limit_detail: str
) -> dict:
    if not voice.whisper_available():
        raise HTTPException(status_code=503, detail=voice.INSTALL_HINT)

    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=over_limit_detail)
    if not data:
        raise HTTPException(status_code=400, detail="The recording is empty")

    suffix = Path(file.filename or "clip.webm").suffix[:8] or ".webm"
    # delete=True keeps the file open under this handle for the `with` block's
    # whole lifetime: harmless on POSIX, where a second handle can still open
    # the same path, but Windows locks a file exclusively while any handle on
    # it is open. faster-whisper's own reader opening that path for decoding
    # then failed with "Permission denied" on every Windows machine, which
    # this sandbox is not, so nothing here had ever seen it fail. Closed by
    # hand and cleaned up in `finally` instead, so nothing holds it open while
    # `voice.transcribe` reads it.
    clip = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        clip.write(data)
        clip.close()
        try:
            text = voice.transcribe(
                Path(clip.name),
                model_size=deps.get_config().get_preference("voice_model", "base"),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # a bad clip must not 500 mysteriously
            raise HTTPException(
                status_code=422, detail=f"Couldn't transcribe that recording: {exc}"
            ) from exc
    finally:
        Path(clip.name).unlink(missing_ok=True)

    log_action(session, "transcribed", "voice", detail=f"{len(data)} bytes")
    session.commit()
    return {"text": text}


@router.post("/transcribe")
def transcribe(file: UploadFile, session: Session = Depends(get_session)) -> dict:
    return _transcribe_upload(
        file, session, MAX_AUDIO_BYTES, "Recording is larger than 25 MB"
    )


@router.post("/transcribe-meeting")
def transcribe_meeting(file: UploadFile, session: Session = Depends(get_session)) -> dict:
    """The longer-recording sibling of `/transcribe` (§17: meeting notes):
    same engine, same response shape, just a ceiling sized for a meeting or a
    lecture rather than a spoken note."""
    return _transcribe_upload(
        file,
        session,
        MAX_MEETING_AUDIO_BYTES,
        "Recording is larger than 300 MB",
    )


class SummarizeBody(BaseModel):
    text: str


@router.post("/summarize")
def summarize(body: SummarizeBody) -> dict:
    """Decisions/action-items extraction for a meeting transcript (§25).
    Best-effort like `/entries/suggest-tags`: a model that's offline or
    errors mid-call must never block saving the meeting note, so every
    failure here just means an empty summary, not a 5xx."""
    text = body.text.strip()
    if not text:
        return {"summary": ""}
    try:
        summary = librarian.summarize_meeting(
            text, deps.get_model_manager(), deps.get_ollama()
        )
    except Exception:
        summary = ""
    return {"summary": summary}
