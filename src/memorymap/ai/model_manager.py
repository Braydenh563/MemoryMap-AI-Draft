"""Model management (plan §6.5): which models are active, the curated
suggested-models catalog, and the two background jobs, re-indexing
after an embedding switch, and downloading a model with progress.

The janitor, librarian, and embedding service must never hardcode a
model name (plan §4): they ask this module, which reads the user's
saved preferences and falls back to the defaults.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select

from memorymap.ai.ollama_client import OllamaClient, OllamaError
from memorymap.core.config import ConfigManager
from memorymap.core import taskhistory
from memorymap.core.database import DatabaseManager, EmbeddingRecord, Entry
from memorymap.entry.manager import log_action


class Embedder(Protocol):
    """The two methods the re-index job needs from an embedding service.

    Stated structurally rather than by importing `EmbeddingService`, because
    that import points back at `ai/embeddings.py`, which imports this module, 
    a genuine cycle that a `TYPE_CHECKING` guard hides at runtime without
    removing. Writing down the contract is also the more honest description:
    re-indexing does not need an `EmbeddingService`, it needs something that
    can embed an entry and name its backend, which is what the tests pass.
    """

    def store_for_entry(self, session, entry: Entry) -> bool:
        pass

    def backend_id(self) -> str:
        pass

# Curated catalog, stored as data so it's trivial to edit (plan §6.5).
# There's no Ollama API to browse the online library, hence hardcoded.
#
# **Ordered smallest-first within each purpose, and that is the ordering that
# matters.** Someone reading this list is choosing hardware they already own.
# A list sorted by quality puts the model they cannot run at the top and the
# one they should start with out of sight; sorted by size, the first thing they
# see is the thing most likely to work.
#
# `purpose` says what the model is *for* rather than how good it is. "Strong
# all-rounder" is not a decision anyone can act on; "the smallest one worth
# using: fine on a laptop with no GPU" is.
#
# Sizes are the default quantisation Ollama pulls (usually Q4_K_M) and are
# approximate. They matter more than the parameter count here: a 7B at Q4 and
# a 3B at Q8 land in the same place on an 8 GB machine.
#
# This is a hand-maintained list against a registry that moves, so a tag here
# can go stale. That fails safely and legibly: the pull returns Ollama's own
# "model not found" and the Models screen shows it, rather than the app
# pretending to know something it doesn't. Nothing else reads these names.
SUGGESTED_MODELS: dict[str, list[dict[str, str]]] = {
    # Split by type (text / vision / embedding / moe), asked for directly, 
    # this dict drives the Settings -> Models suggested-downloads list
    # generically (frontend/app.js's renderSuggested() does a plain
    # `Object.entries()` over it and labels each model with its own top-
    # level key), so a new key here needs no frontend change at all. "moe"
    # split out of the old flat "chat" list rather than staying folded into
    # it: a MoE model's RAM/speed trade-off (see its own comment below) is
    # different enough from a dense model's that grouping them together
    # under one label was misleading, not just imprecise.
    # Sizes below were checked against the live Ollama library this session
    # (this file previously had no way to do that, see the vision/ocr
    # groups' own history). Two real tag mistakes, not just size drift, came
    # out of it: "qwen3.5:8b" doesn't exist (the real tag between 4b and 27b
    # is 9b) and "gemma4:26b-a4b" doesn't exist as a plain tag (the model is
    # a MoE *by construction* under the bare "gemma4:26b" tag: the "-a4b"
    # suffix belongs to a more specific quantisation variant, not the
    # ordinary pull). Both would have 404'd for anyone who tried them.
    "text": [
        # --- runs on almost anything, no GPU needed ---
        {"name": "qwen3.5:2b", "size": "~2.7 GB", "purpose": "The lightest one genuinely worth using"},
        {"name": "llama3.2", "size": "~2.0 GB", "purpose": "Fast all-rounder: the default, and a good first choice"},
        {"name": "granite4.1:3b", "size": "~2.1 GB", "purpose": "Strong instruction-following at a small size"},
        {"name": "qwen3.5:4b", "size": "~3.4 GB", "purpose": "Follows instructions closely: good for agent mode"},
        # --- 8 GB of RAM, or any modern GPU ---
        {"name": "llama3.1:8b", "size": "~4.9 GB", "purpose": "Better reasoning and reliable tool calls"},
        {"name": "qwen3.5:9b", "size": "~6.6 GB", "purpose": "Best tool use at this size. Thinks, so slower per answer"},
        {"name": "mistral-nemo", "size": "~7.1 GB", "purpose": "Long-document work: a large context window"},
        {"name": "gemma4:12b", "size": "~7.6 GB", "purpose": "Long-form writing and summarising"},
    ],
    # Mixture-of-experts: big download, small working set. These need the
    # RAM of the model they are named after and run at roughly the speed of
    # the *active* half: 26b holds 26B of weights and computes with roughly
    # 4B of them (it is a MoE model by construction under its own bare tag,
    # not a separate "-a4b" variant: see the note above this dict). That is
    # the one thing worth explaining about them, because judged on download
    # size alone nobody with 16 GB would try one, and they are the best
    # answer for that machine.
    "moe": [
        {"name": "gemma4:e2b", "size": "~7.2 GB", "purpose": "MoE: 2B-class speed with more capability. Try it if bigger models are too slow"},
        {"name": "gemma4:e4b", "size": "~9.6 GB", "purpose": "MoE: noticeably more capable + better writing than the e2b"},
        {"name": "gemma4:26b", "size": "~19 GB", "purpose": "MoE: 12B-class speed with far better answers. Needs ~16 GB"},
        {"name": "qwen3.5:35b-a3b", "size": "~21 GB", "purpose": "MoE: the most capable here, still quick. Needs ~24 GB"},
    ],
    "embedding": [
        {"name": "nomic-embed-text", "size": "~274 MB", "purpose": "Solid general-purpose embeddings"},
        {"name": "mxbai-embed-large", "size": "~670 MB", "purpose": "Higher quality, a little slower"},
        {"name": "bge-m3", "size": "~1.2 GB", "purpose": "Better on long notes and mixed languages"},
    ],
    # Any of these can be picked as the explicit vision-model override in
    # Settings → Models (ModelManager.vision_model()), for chat image
    # captions (ai/captioning.py) and image-carrying chat turns
    # (routes_chat._chat_model_sees_images). Asked for directly.
    #
    # **qwen3-vl's tags were unconfirmed when this list was first written (no
    # live registry access) and have since been checked against the real
    # Ollama library (ollama.com/library/qwen3-vl/tags): 2b/4b/8b/30b/32b/235b
    # all exist, so the hedge on those three entries is gone.** lfm2.5-vl is
    # the opposite finding: checked, and it is **not** a bare Ollama library
    # tag the way qwen3-vl's are: `ollama.com/library/lfm2.5-vl` does not
    # exist (only `lfm2.5`, the text-only sibling, is in the curated
    # library), so the entry below now pulls the GGUF straight from the
    # publisher's own Hugging Face repo, the same `hf.co/…` shape the OCR
    # group below already uses for exactly this situation. glm-4v and
    # deepseek-vl2 were asked about by name but are still not included at
    # all: neither is published under any tag on Ollama's library or as a
    # findable GGUF repo, and this file's own "fails safely" rule (a stale
    # *tag* just 404s cleanly) does not cover suggesting a model that was
    # never offered in the first place.
    "vision": [
        {"name": "moondream", "size": "~1.7 GB", "purpose": "Tiny and fast: the one to try on modest hardware"},
        {"name": "hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF", "size": "~1.6 GB", "purpose": "Liquid's small vision model, not in Ollama's own library, pulled from its publisher's Hub repo instead"},
        {"name": "qwen3-vl:2b", "size": "~1.9 GB", "purpose": "Smallest of the Qwen-VL line"},
        {"name": "qwen2.5vl:3b", "size": "~2.2 GB", "purpose": "A fallback for the 2B/4B Qwen3-VL entries either side of it, if either is ever pulled from Ollama's library and not this catalogue"},
        {"name": "qwen3-vl:4b", "size": "~3.3 GB", "purpose": "A step up from the 2B"},
        {"name": "minicpm-v", "size": "~5.5 GB", "purpose": "Notably strong at reading text in images"},
        {"name": "llava", "size": "~4.7 GB", "purpose": "General-purpose vision, the longest-established option"},
        {"name": "qwen2.5vl:7b", "size": "~6.0 GB", "purpose": "Strong all-round vision and text reading"},
        {"name": "qwen3-vl:8b", "size": "~6.1 GB", "purpose": "The largest of the small Qwen3-VL tags"},
        {"name": "qwen2.5vl:32b", "size": "~21 GB", "purpose": "The most capable here. Needs ~24 GB"},
    ],
    # Document readers, as opposed to the general vision models above. Asked
    # for by name (deepseek-ocr, glm-ocr, qwen3-vl).
    #
    # **These entries were checked against the live Hugging Face Hub**, unlike
    # the "unconfirmed tag" notes on the vision list above, that session had
    # no registry access and said so. Downloads and file sizes below are read
    # from the repos themselves, so a 404 here would be a repo being deleted
    # rather than a name this file guessed at.
    #
    # `hf.co/…` rather than a bare Ollama tag: Ollama pulls a GGUF straight
    # from the Hub with `ollama pull hf.co/{repo}:{quant}`, and none of these
    # are in Ollama's own curated library. Sizes are the weights plus the
    # mmproj projector that a vision GGUF needs alongside them, Ollama fetches
    # both from the same repo, and quoting only the weights would understate
    # every one of these by several hundred megabytes.
    #
    # Why a separate category rather than more "vision" entries: a general VLM
    # is asked "what is in this picture", and a document reader is asked "give
    # me the text, the tables and the layout". The second is what
    # core/docview.py's scanned-page path wants, and picking moondream for it
    # gets a description of a page instead of the page.
    "ocr": [
        {"name": "hf.co/ggml-org/GLM-OCR-GGUF:Q8_0", "size": "~1.4 GB",
         "purpose": "Best size-to-accuracy here. Tables and layout, 8 languages, start with this one"},
        {"name": "hf.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF:Q8_0", "size": "~1.8 GB",
         "purpose": "Layout, tables, formulas, charts. Strong on structured pages"},
        {"name": "hf.co/unsloth/Qwen3-VL-4B-Instruct-GGUF:Q4_K_M", "size": "~2.5 GB",
         "purpose": "Reads documents and answers about them, a VLM as well as a reader"},
        {"name": "hf.co/ggml-org/DeepSeek-OCR-GGUF:Q8_0", "size": "~3.6 GB",
         "purpose": "The most accurate on dense and handwritten pages. Needs ~8 GB"},
    ],
}


#: Families whose whole purpose is reading a page, rather than describing a
#: picture. Derived from the `ocr` group above and kept beside it, so adding an
#: entry there is enough to make auto-detect prefer it.
#:
#: Matched as substrings of a lowercased model name because the same weights
#: arrive under many spellings, `glm-ocr`, `hf.co/ggml-org/GLM-OCR-GGUF:Q8_0`,
#: `GLM-OCR:latest`, and the family is the part that never changes.
OCR_MODEL_MARKERS: tuple[str, ...] = (
    "glm-ocr", "glm_ocr",
    "deepseek-ocr", "deepseek_ocr",
    "paddleocr", "paddle-ocr",
    "olmocr", "olm-ocr",
    "got-ocr", "nanonets-ocr", "dots.ocr", "minicpm-o",
)


def is_ocr_model(name: str) -> bool:
    """Is this model a document reader rather than a general vision model?

    Deliberately not "does the name contain 'ocr'": `qwen2.5vl` reads text
    perfectly well and contains no such string, while a chat model called
    `ocr-helper` is not one. A named-family list is wrong in a way that is
    visible and fixable; a substring rule is wrong in a way that is not.
    """
    lowered = (name or "").lower()
    return any(marker in lowered for marker in OCR_MODEL_MARKERS)


#: Below this many billion parameters, a model is "small" for the purposes of
#: how much is asked of it in one turn. 8B is where tool calling stops being a
#: coin flip in this app's own use: the 4B models in the catalogue above narrate
#: instead of calling, and the 8B entries are described there as "reliable tool
#: calls" for exactly that reason. A threshold, not a cliff, everything it
#: gates is a *simplification*, so being wrong in either direction costs
#: clarity rather than capability.
SMALL_MODEL_PARAMS_B = 8.0

#: `qwen3.5:4b`, `granite4.1:3b`, `llama-3.2-3b-instruct`, `qwen3.5:35b-a3b`.
#: The size is written into the tag rather than reported by the API, which is
#: why this is a name rule: reading it costs nothing, works before the model
#: has ever been loaded, and works for every provider the app can talk to
#: (`/api/show` is Ollama's, and llama.cpp/Jan/vLLM answer nothing like it).
_PARAM_TAG = re.compile(r"(?:^|[:\-_/])(\d{1,3}(?:\.\d)?)\s*b(?![a-z0-9])", re.IGNORECASE)


def parameter_count(name: str) -> float | None:
    """Billions of parameters, read off the model's own name: or None.

    **None means "no idea", and every caller has to treat it as such.** A
    model called `llama3.2` genuinely is a 3B, and this returns None for it,
    because the alternative is guessing from a family name and a version
    number that shifts every release. Silence is the honest answer, and the
    one setting that reads this defaults to off when it gets one: narrowing a
    capable model's toolbox on a guess is worse than leaving a small model
    with the full set it was coping with yesterday.

    A mixture-of-experts tag (`qwen3.5:35b-a3b`) reports the *first* number,
    which is the total rather than the active count, deliberate: what the
    active-parameter count predicts is speed, and what this is asked about is
    instruction-following, which tracks the total far better.
    """
    match = _PARAM_TAG.search(str(name or ""))
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:  # pragma: no cover: the regex only matches numbers
        return None


class ModelManager:
    """Reads/writes the active-model preferences."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def chat_model(self) -> str:
        return self._config.get_preference("chat_model", "llama3.2")

    def chat_model_is_small(self) -> bool | None:
        """Is the chat model small enough to need the simplified treatment?

        True / False / **None for "the name doesn't say"**, the three states
        matter, the same way `OllamaClient.supports` keeps them apart. A caller
        that collapses None into True narrows every run on an unrecognised
        name; one that collapses it into False never turns on for the models
        this exists for. The one caller (`small_model_mode` = "auto") treats
        None as off and says so.
        """
        size = parameter_count(self.chat_model())
        return None if size is None else size < SMALL_MODEL_PARAMS_B

    def utility_model(self) -> str:
        """The model for quick background jobs, filing (janitor), the
        weekly digest, tidy suggestions, writing fixes. Defaults
        to the chat model, but the user can point it at a small fast model
        so the big chat model isn't tied up categorising every note."""
        if not self._config.get_preference("smart_model_routing_enabled", True):
            return self.chat_model()
        return self._config.get_preference("utility_model", "") or self.chat_model()

    def set_utility_model(self, name: str) -> None:
        # Empty string means "same as chat model".
        self._config.set_preference("utility_model", name or "")

    def vision_model(self) -> str:
        """The explicit vision-model override, or "" for auto-detect.

        Deliberately the *opposite* default from `utility_model()` above:
        every other model preference in this app falls back to "same as
        chat model" when unset, because that is a safe default, the chat
        model can always do the job the utility model does. A chat model
        cannot always see images, so falling back to it here would silently
        turn "attach a photo" into "attach a photo the model ignores" on
        any notebook that hasn't touched this setting. Auto-detect is the
        default specifically *because* it is the useful zero-config
        behaviour for this one preference; a specific model name is an
        explicit choice on top of it, not a second default."""
        return self._config.get_preference("vision_model", "")

    def set_vision_model(self, name: str) -> None:
        # Empty string means "auto-detect", see resolve_vision_model.
        self._config.set_preference("vision_model", name or "")

    def resolve_vision_model(self, ollama, installed: list[dict] | None = None) -> str | None:
        """The model an image-carrying turn should actually use, or None if
        nothing on this backend can.

        An explicit choice always wins, even one `installed` doesn't confirm
        is on disk right now, the same trust `chat_model()` already extends
        (routes_models.py surfaces "not installed" as its own warning rather
        than silently substituting something else). Auto-detect (the
        default) asks each installed model's declared capabilities in turn
        and stops at the first `True`; `OllamaClient.capabilities()` caches
        per model per process, so this costs one real round trip per model
        at most once, not once per chat turn."""
        explicit = self.vision_model()
        if explicit:
            return explicit
        if installed is None:
            try:
                installed = ollama.list_models()
            except OllamaError:
                installed = []
        supports = getattr(ollama, "supports", None)
        if not callable(supports):
            return None
        for entry in installed:
            name = entry.get("name") if isinstance(entry, dict) else None
            if name and supports(name, "vision"):
                return name
        return None

    def ocr_model(self) -> str:
        """The explicit model for *reading text off a page*, or "" for auto.

        Separate from `vision_model` because the two jobs are separate, which
        is not obvious and was asked about directly. Rasterising a PDF does not
        read anything: it turns a page into a picture, and a model still has
        to read the picture. So the same *kind* of model handles a photo and a
        scanned page; what differs is which one is good at it:

        - A general VLM (moondream, llava, qwen2.5vl) is trained to answer
          "what is in this image". Ask it for a scanned invoice and it will
          often describe the invoice instead of transcribing it.
        - A document reader (GLM-OCR, DeepSeek-OCR, PaddleOCR-VL: the `ocr`
          group in SUGGESTED_MODELS) is trained to return the text, the tables
          and the layout, and is usually far smaller for that job.

        Hence three tiers rather than two, and the order matters: an explicit
        OCR model, else an installed document-reader model auto-detected by
        family name, else the vision model the user already chose (if any),
        else whatever else can see. Requiring an OCR model before any OCR
        works would make this a setting people must find before the feature
        does anything, hence the auto-detect tier existing at all.

        The auto-detected reader now outranks an explicit-but-unrelated
        vision-model choice, reversed from an earlier version of this
        function that had it the other way, reported live, directly
        against what that version assumed: "I pressed read text with AI,
        but it used my vision model and not my OCR model" from someone who
        had a real OCR-family model installed and a vision model set for
        chat, never an OCR model. Deferring to the *explicit* choice sounded
        right in the abstract, but in practice it means a document reader
        sitting right there in the installed list is never used for the one
        job it's actually built for, on the strength of a setting that was
        made for an unrelated purpose (chat). An explicit OCR model still
        wins outright: that one really is the deliberate, on-purpose case.
        """
        return self._config.get_preference("ocr_model", "")

    def set_ocr_model(self, name: str) -> None:
        self._config.set_preference("ocr_model", name or "")

    def resolve_ocr_model(
        self,
        ollama,
        installed: list[dict] | None = None,
        vision_fallback: str | None = None,
    ) -> str | None:
        """The model that should read text off an image or a rasterised page.

        See `ocr_model` for why this is not simply `resolve_vision_model`.
        """
        explicit = self.ocr_model()
        if explicit:
            return explicit

        # No explicit OCR model. Asked directly: "what if I have qwen3-vl and
        # glm-ocr available?", and plain vision auto-detect answers that
        # badly, by taking whichever the backend happens to list first. Both
        # can see an image; only one of them is built to transcribe a page.
        # Tried before the vision-model fallback below, not after, see this
        # function's own docstring for why that order flipped.
        #
        # Matched on the family names in SUGGESTED_MODELS["ocr"] rather than
        # on capabilities, because no backend reports "good at OCR", 
        # `capabilities` says `vision` for both, which is exactly why the tie
        # needed breaking here.
        if installed is None:
            try:
                installed = ollama.list_models()
            except OllamaError:
                installed = []
        names = [
            entry.get("name")
            for entry in (installed or [])
            if isinstance(entry, dict) and entry.get("name")
        ]
        for name in names:
            if is_ocr_model(name):
                return name

        # No reader installed. An explicit *vision* model is still a
        # deliberate choice and beats guessing among whatever else can see.
        if self.vision_model():
            return self.vision_model()
        #
        # `vision_fallback` is for the caller that has already resolved it.
        # Resolving it here walks every installed model asking `/api/show`
        # whether it can see, one HTTP round trip each, cached per process but
        # cold on the first poll. `/models/status` needs both answers, and
        # deriving them independently made that poll slow enough to trip the
        # frontend's own 5s abort: reported as
        # `GET /models/status: signal timed out`.
        if vision_fallback is not None:
            return vision_fallback or None
        return self.resolve_vision_model(ollama, installed)

    def embedding_backend(self) -> str:
        """'sentence-transformers' (built-in default) or 'ollama'."""
        return self._config.get_preference("embedding_backend", "sentence-transformers")

    def embedding_model(self) -> str:
        """Only meaningful when the backend is 'ollama'."""
        return self._config.get_preference("embedding_model", "nomic-embed-text")

    def set_chat_model(self, name: str) -> None:
        # Chat model switches apply instantly, no re-index needed (§6.5).
        self._config.set_preference("chat_model", name)

    def set_embedding_backend(self, backend: str, model: str | None = None) -> None:
        # The caller MUST kick off a re-index after this, vectors from
        # different models are not comparable (§6.5).
        self._config.set_preference("embedding_backend", backend)
        if model:
            self._config.set_preference("embedding_model", model)


# --- background jobs ---------------------------------------------------------
# Simple module-level state: this is a single-process, single-user app.


@dataclass
class Job:
    kind: str  # "reindex" or "pull"
    name: str = ""  # model name for pulls
    total: int = 0  # entries (reindex) or bytes (pull)
    done: int = 0
    status: str = "running"  # running | success | error | cancelled
    error: str = ""
    cancel_requested: bool = False  # cooperative stop (tasks manager)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "total": self.total,
            "done": self.done,
            "status": self.status,
            "error": self.error,
        }


_lock = threading.Lock()
_reindex_job: Job | None = None
_pull_jobs: dict[str, Job] = {}


def reset_jobs() -> None:
    """Forget finished/failed job records, used between tests."""
    global _reindex_job
    with _lock:
        _reindex_job = None
        _pull_jobs.clear()


def reindex_status() -> dict | None:
    with _lock:
        return _reindex_job.as_dict() if _reindex_job else None


def pull_statuses() -> dict[str, dict]:
    with _lock:
        return {name: job.as_dict() for name, job in _pull_jobs.items()}


def cancel_reindex() -> bool:
    """Ask a running re-index to stop. Cooperative: the worker
    checks the flag between entries. Returns True if one was running."""
    with _lock:
        if _reindex_job is not None and _reindex_job.status == "running":
            _reindex_job.cancel_requested = True
            return True
    return False


def cancel_pull(name: str) -> bool:
    """Ask a running download to stop."""
    with _lock:
        job = _pull_jobs.get(name)
        if job is not None and job.status == "running":
            job.cancel_requested = True
            return True
    return False


def start_reindex(db: DatabaseManager, embeddings: Embedder) -> bool:
    """Regenerate every non-deleted entry's embedding with the current
    backend, in a background thread. Returns False if one is already
    running. While it runs, old vectors no longer match the new
    backend_id, so semantic search safely falls back to keyword search
    until each entry is re-embedded (§6.5)."""
    global _reindex_job
    with _lock:
        if _reindex_job is not None and _reindex_job.status == "running":
            return False
        _reindex_job = Job(kind="reindex")
        job = _reindex_job
    threading.Thread(
        target=_run_reindex, args=(db, embeddings, job), name="reindex", daemon=True
    ).start()
    return True


def _run_reindex(db: DatabaseManager, embeddings: Embedder, job: Job) -> None:
    started = time.monotonic()
    session = db.session()
    try:
        entries = list(
            session.scalars(select(Entry).where(Entry.is_deleted == False))  # noqa: E712
        )
        job.total = len(entries)
        for entry in entries:
            if job.cancel_requested:  # user quit it from the tasks manager
                job.status = "cancelled"
                taskhistory.record(
                    "reindex",
                    "Re-indexing your notes",
                    "cancelled",
                    f"stopped after {job.done} of {job.total}",
                    duration_ms=(time.monotonic() - started) * 1000,
                )
                return
            # Drop the stale vector first so a failed re-embed never
            # leaves an old-model vector looking current.
            session.execute(
                delete(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry.id)
            )
            session.commit()
            embeddings.store_for_entry(session, entry)  # False = skip, keep going
            job.done += 1
        log_action(
            session,
            "reindexed",
            "embeddings",
            detail=f"{job.done} entries -> {embeddings.backend_id()}",
        )
        session.commit()
        job.status = "success"
        taskhistory.record(
            "reindex",
            "Re-indexing your notes",
            "completed",
            f"{job.done} notes re-embedded with {embeddings.backend_id()}",
            duration_ms=(time.monotonic() - started) * 1000,
        )
    except Exception as exc:  # a failed job must report, never crash the app
        job.status = "error"
        job.error = str(exc)
        # The ending that mattered most and was hardest to see: a re-index that
        # dies halfway used to leave exactly the same empty screen as one that
        # finished, with the reason only in the log console.
        taskhistory.record(
            "reindex",
            "Re-indexing your notes",
            "failed",
            str(exc),
            duration_ms=(time.monotonic() - started) * 1000,
        )
    finally:
        session.close()


def start_pull(client: OllamaClient, name: str) -> bool:
    """Download a model via Ollama in a background thread. Returns False
    if that model is already downloading."""
    with _lock:
        existing = _pull_jobs.get(name)
        if existing is not None and existing.status == "running":
            return False
        job = Job(kind="pull", name=name)
        _pull_jobs[name] = job
    threading.Thread(
        target=_run_pull, args=(client, name, job), name=f"pull-{name}", daemon=True
    ).start()
    return True


def _run_pull(client: OllamaClient, name: str, job: Job) -> None:
    started = time.monotonic()
    try:
        # Ollama streams progress lines with completed/total bytes (§6.5).
        for update in client.pull(name):
            if job.cancel_requested:  # user quit it from the tasks manager
                job.status = "cancelled"
                taskhistory.record(
                    "pull",
                    f"Downloading {name}",
                    "cancelled",
                    name=name,
                    duration_ms=(time.monotonic() - started) * 1000,
                )
                return
            if update.get("error"):
                raise OllamaError(update["error"])
            if update.get("total"):
                job.total = int(update["total"])
                job.done = int(update.get("completed", job.done))
        job.status = "success"
        taskhistory.record(
            "pull",
            f"Downloaded {name}",
            "completed",
            name=name,
            duration_ms=(time.monotonic() - started) * 1000,
        )
    except OllamaError as exc:
        # Surface the failure so the UI can offer a retry, never leave
        # a half-download looking installed (§6.5).
        job.status = "error"
        job.error = str(exc)
        taskhistory.record(
            "pull",
            f"Downloading {name}",
            "failed",
            str(exc),
            name=name,
            duration_ms=(time.monotonic() - started) * 1000,
        )
