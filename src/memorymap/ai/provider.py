"""What every chat backend has to answer, and the parts that don't vary (§6).

MemoryMap talked to Ollama and only Ollama. Ollama is not the only thing that
serves a model on localhost any more: LM Studio, llama.cpp's server, Jan and
vLLM all speak the OpenAI shape on some other port, and asking for "LM Studio
support" specifically would have bought one backend instead of all of them.

So the split is by *dialect*, not by product. There are two:

  - Ollama's native `/api/chat`, `ai/ollama_client.py`
  - OpenAI's `/v1/chat/completions`, `ai/openai_client.py`

and every OpenAI-compatible server is the second one with a different base URL.

**This module is the part that is the same either way.** Three kinds of thing
live here:

1. The stream helpers (`_ThinkTagSplitter`, `_ToolTextGate`,
   `extract_text_tool_calls`, `split_thinking`). These were written for Ollama
   but nothing in them is Ollama-specific, they operate on text a model wrote,
   and a model writes `<think>` tags and prose-shaped tool calls whoever is
   serving it. They moved here rather than being copied, and `ollama_client`
   re-exports them so existing imports keep working.
2. `Provider`, the base class: the four questions a backend must answer, and
   the shared implementation of the ones whose answer doesn't depend on the
   dialect (the context ceiling, the preference that overrides it).
3. What the app knows *about models rather than about backends*, the
   known-context table, and how to read a window out of a `/models` catalog.

**Errors deliberately did not get a new name.** `ProviderError` is the same
class `OllamaError` has always been, aliased; every `except OllamaError` in the
routes therefore catches a failing LM Studio too. Introducing a parent class
instead would have been the tidier-looking change and would have silently
stopped those handlers firing for the new provider.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from urllib.parse import urlparse


#: Returns the user's stored sampling overrides, installed by the app's own
#: wiring so this module never has to import it.
#:
#: `ai/provider.py` is the bottom of the AI stack and `core.deps` is the wiring
#: that builds on it, so importing one from the other is a cycle (CodeQL
#: flagged it) as well as the wrong direction. None means "nothing registered",
#: which is the correct answer for a bare unit test as well as for a process
#: that has not finished wiring: no overrides, so every knob falls through to
#: the model's own recommendation.
_sampling_overrides_getter: Callable[[], object] | None = None


def set_sampling_overrides_getter(getter: Callable[[], object] | None) -> None:
    """Install the accessor `Provider.sampling_overrides` reads through."""
    global _sampling_overrides_getter
    _sampling_overrides_getter = getter


class ProviderError(RuntimeError):
    """The backend is unreachable, or it returned something unusable."""


class ToolsUnsupportedError(ProviderError):
    """The active model can't do tool calls, the caller should fall
    back to plain Q&A, never fail the whole chat."""


def is_transient_server_error(exc: Exception) -> bool:
    """A 5xx from the backend itself, not a 4xx: the request was well-formed
    but the server briefly couldn't handle it (a model still swapping in,
    momentary memory pressure): reported live, a chat call failing with a
    plain 500 and then succeeding on the exact same resend. Worth one silent
    retry, unlike a 4xx (bad request, model not found) where trying again
    changes nothing.

    Duck-typed against `.response.status_code` rather than importing
    `requests` here, so both HTTP-backed providers (ollama_client.py,
    openai_client.py) can share this without this module taking on a
    transport dependency it otherwise doesn't have."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and status >= 500


# --- what the app knows about models, not about backends --------------------

# Ollama's default when a model declares nothing. Everything that budgets
# against the window falls back to this, because being wrong in this direction
# only wastes headroom, while being wrong the other way silently drops the
# system prompt off the front of the context.
DEFAULT_CONTEXT_TOKENS = 4096

# The largest window this app will ask a backend to allocate by default.
#
# A model declaring 128k does not mean asking for 128k is free: the KV cache
# scales with the window, so a 7B at 128k wants several gigabytes that a laptop
# may not have, and the failure is an out-of-memory rather than a slow answer.
# 8k is comfortably more than the app's own worst-case prompt needs and costs a
# fraction of that, so it is the default; anyone with the memory to spare can
# raise it in preferences.
MAX_REQUESTED_CONTEXT = 8192

# Room for the reply. Unset, a backend will happily generate until it decides
# to stop, and a local model that rambles is the single most common reason an
# answer "takes ages", output tokens are generated one at a time, so they cost
# far more wall-clock each than prompt tokens do.
DEFAULT_MAX_OUTPUT_TOKENS = 1024


# Context windows for models whose server won't say. Ollama answers `/api/show`
# and LM Studio answers `/api/v0/models`, but plain llama.cpp and several cloud
# gateways report nothing at all, and the alternative to a table is budgeting
# every one of them against 4,096, which on a 128k model means withholding
# tools for no reason.
#
# Substring-matched against the model id, so `llama3.1:8b-instruct-q4_0` finds
# `llama3.1`. Keep keys as the shortest *unambiguous* prefix.
KNOWN_CONTEXT_WINDOWS: dict[str, int] = {
    # Local-first families: the ones this app is actually run with.
    "llama3.1": 131072,
    "llama3.2": 131072,
    "llama3.3": 131072,
    "llama3": 8192,
    "llama4": 1048576,
    "qwen2.5": 32768,
    "qwen3": 131072,
    "qwen3.5": 262144,
    "gemma2": 8192,
    "gemma3": 131072,
    "gemma4": 131072,
    "phi3": 131072,
    "phi4": 16384,
    "mistral": 32768,
    "mistral-nemo": 131072,
    "mixtral": 32768,
    "codestral": 32768,
    "granite3": 131072,
    "granite4": 131072,
    "deepseek-r1": 65536,
    "deepseek-v3": 65536,
    "smollm2": 8192,
    "tinyllama": 2048,
    "lfm2": 32768,
    # Embedding models, so a mis-selected one is budgeted sanely rather than
    # assumed to be a 128k chat model.
    "nomic-embed-text": 8192,
    "bge-": 512,
    "all-minilm": 512,
    # OpenAI-compatible gateways people point this at.
    "gpt-4o": 128000,
    "gpt-4.1": 1047576,
    "gpt-5": 400000,
    "o3": 200000,
    "o4-mini": 200000,
    "claude-3": 200000,
    "claude-haiku-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-opus-4": 200000,
}


def _squash_separators(text: str) -> str:
    """Drop `-`/`_`/space so `granite4` still finds `granite-4.1-3b-uncensored`.

    Community/fine-tuned imports (a manually `ollama create`d GGUF, an
    uncensored fine-tune pulled from Hugging Face) routinely punctuate a
    family name differently from Ollama's own library naming, `granite4`
    in the library becomes `granite-4.1-3b-uncensored` or `Granite 4.1
    Uncensored` in the wild, and a plain substring match against either of
    those never finds `granite4` at all, even though it's clearly the same
    family. Dots are kept: they carry real version information (`3` vs
    `3.1`) that this app's own table already keys on.
    """
    return re.sub(r"[-_\s]", "", text)


def known_context(model: str) -> int | None:
    """The window this app believes `model` has, or None if it has no idea.

    Matches the *longest* key rather than the first, which is the whole reason
    this is a loop and not a dict lookup: `llama3` and `llama3.1` both match
    `llama3.1:8b`, they differ by 16x, and first-match order would decide which
    one wins by dictionary insertion, a 131k model budgeted at 8k, or worse,
    the other way round.

    The tag (`:8b-q4_0`) and any registry prefix (`hf.co/user/`) are stripped
    first: they say how the model was quantised and where it came from, not how
    much it can hold. Matched with separators squashed out (see
    `_squash_separators`) so a differently-punctuated import of the same
    family, the common shape for a community fine-tune, still finds its
    table entry instead of silently falling through to the flat default.
    """
    name = _squash_separators((model or "").lower())
    bare = _squash_separators(name.split("/")[-1].split(":")[0])
    best_key: str | None = None
    best_context: int | None = None
    for raw_key, window in KNOWN_CONTEXT_WINDOWS.items():
        key = _squash_separators(raw_key)
        if key in bare or key in name:
            if best_key is None or len(key) > len(best_key):
                best_key, best_context = key, window
    return best_context


# Fields a `/models` catalog might report a window under. Every OpenAI-compatible
# server spells it differently, LM Studio says `max_context_length`, vLLM says
# `max_model_len`, llama.cpp nests `n_ctx` under `meta`, OpenRouter says
# `context_length`, so all of them are read rather than one being guessed at.
_CONTEXT_FIELDS = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_model_len",
    "max_seq_len",
)


def context_from_catalog_entry(entry: dict) -> int | None:
    """Read a positive context window out of one `/models` catalog entry."""
    if not isinstance(entry, dict):
        return None
    for field in _CONTEXT_FIELDS:
        value = entry.get(field)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    meta = entry.get("meta") or entry.get("model_extra") or {}
    if isinstance(meta, dict):
        # llama.cpp's `n_ctx` is the window the server was actually started
        # with (`-c`), which beats anything the model file declares.
        for field in ("n_ctx", *_CONTEXT_FIELDS):
            value = meta.get(field)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    return None


# Model ids that are not chat models. An OpenAI-shaped `/models` list is not
# ordered and routinely puts an embedding model first, so "just use the first
# one" picks something that cannot hold a conversation and fails at the point
# of asking a question rather than at the point of choosing.
_NOT_A_CHAT_MODEL = (
    "embed",
    "embedding",
    "bge-",
    "all-minilm",
    "rerank",
    "whisper",
    "tts-",
    "dall-e",
    "stable-diffusion",
    "clip-",
    "moderation",
)


def first_chat_model(models: list[str]) -> str | None:
    """The first id that looks like something you can chat with."""
    for name in models or []:
        if not any(hint in str(name).lower() for hint in _NOT_A_CHAT_MODEL):
            return name
    return (models or [None])[0]


def detect_provider(base_url: str) -> str:
    """Guess the dialect from the URL, for when the user hasn't said.

    Two rules, in this order, because the second is a catch-all:

      - a `/v1` path means the OpenAI shape, whoever is serving it, this is
        how Ollama's own compatibility surface gets used deliberately;
      - port 11434 with no `/v1` is Ollama's native API.

    Anything else falls back to `openai`, because that is what the long tail
    of servers implements. Guessing wrong is recoverable: the provider is a
    setting, and this only supplies its default.
    """
    try:
        parsed = urlparse((base_url or "").strip())
    except ValueError:
        return "ollama"
    path = (parsed.path or "").rstrip("/")
    if path == "/v1" or path.startswith("/v1/"):
        return "openai"
    if parsed.port == 11434 or path.startswith("/api"):
        return "ollama"
    return "openai" if path else "ollama"


class Provider:
    """The interface `agent.run_agent` and friends are written against.

    Subclasses implement the dialect-specific half, `context_length`,
    `is_running`, `list_models`, and the four generation paths (`chat`,
    `chat_stream`, `chat_tools`, `chat_tools_stream`) plus `embed`. What is
    shared lives here, and it is the part that took the measurements in §11a to
    get right: the ceiling on the window, and the fact that the number the app
    budgets against must be the same number it asks the backend for.
    """

    DEFAULT_CONTEXT_TOKENS = DEFAULT_CONTEXT_TOKENS
    MAX_REQUESTED_CONTEXT = MAX_REQUESTED_CONTEXT
    DEFAULT_MAX_OUTPUT_TOKENS = DEFAULT_MAX_OUTPUT_TOKENS

    #: Shown in Settings → Models and in the support bundle.
    name = "provider"

    def context_length(self, model: str) -> int | None:
        """How many tokens this model can hold, or None for "I can't tell".

        None is a real answer and callers handle it: a backend that cannot
        report a window degrades to `DEFAULT_CONTEXT_TOKENS` rather than
        failing the turn. Returning a *made-up* number instead would be worse
        than returning None, because the budget would then be scaled against
        something nobody verified.
        """
        raise NotImplementedError

    @property
    def max_requested_context(self) -> int:
        """The ceiling, overridable by the user who knows their own machine."""
        try:
            # `importlib`, not `from memorymap.core import deps`. That plain
            # import is what CodeQL py/cyclic-import #364 flagged, one hop
            # further along at `ai/embeddings.py:24`: the cycle it named is
            # `ai.embeddings -> ai.ollama_client -> ai.provider -> core.deps
            # -> ai.embeddings`, and this line is its only wrong-direction
            # edge: a provider is a leaf that the container builds, so it
            # has no business importing the container back. Deferring the
            # statement into the function body does not clear the alert
            # (`entry/manager.py` records the same finding); only dropping
            # the `import` statement itself does. Behaviour is unchanged:
            # the module is resolved at call time either way.
            deps = importlib.import_module("memorymap.core.deps")

            wanted = int(
                deps.get_config().get_preference(
                    "max_context_tokens", self.MAX_REQUESTED_CONTEXT
                )
            )
        except Exception:  # noqa: BLE001  # a bad preference must not stop a chat
            return self.MAX_REQUESTED_CONTEXT
        # Floor at the default: below it nothing works, and a typo like 40
        # should not silently make the app unusable.
        return max(self.DEFAULT_CONTEXT_TOKENS, wanted)

    def usable_context(self, model: str) -> int:
        """The window to budget against, and, on Ollama, to ask for.

        Deliberately the same number in both places. Ollama runs a model at
        `num_ctx`, which is its own default (commonly 4,096) *regardless of
        what the model was trained for*, so reading a 32k context length and
        budgeting against it, without also asking for 32k, would produce
        exactly the overflow the budget exists to prevent.

        On the OpenAI shape there is no `num_ctx` to send: the window is fixed
        when the server loads the model. That makes this number advisory there
        rather than instructive, which is *safe in the direction that matters*
        - the app rations itself to at most what the server reported.
        """
        declared = self.context_length(model) or self.DEFAULT_CONTEXT_TOKENS
        return max(
            self.DEFAULT_CONTEXT_TOKENS, min(declared, self.max_requested_context)
        )

    def generation_budget(
        self,
        model: str,
        max_output_tokens: int | None = None,
        mode: str | None = None,
    ) -> dict:
        """The neutral settings every backend needs, before dialect.

        §6 called this: either each provider translates a neutral
        `{context_tokens, max_output_tokens}`, or it owns the whole payload, 
        and the agent should not learn four dialects. This is that neutral set;
        `runtime_options` on each subclass is the translation.

        `mode` is a response preset (§11): quick, normal or detailed. An
        explicit `max_output_tokens` still wins over the preset's, because a
        caller that names a number has a reason the preset can't know about.
        """
        from memorymap.ai import presets

        preset = presets.resolve(mode)
        cap = max_output_tokens or preset.max_output_tokens
        return {
            "context_tokens": self.usable_context(model),
            "max_output_tokens": cap + self.thinking_allowance(mode, model),
            **presets.sampling_options(preset),
        }

    #: Tokens a reasoning model may spend deliberating before its answer
    #: starts. **Added to the reply cap rather than taken out of it**, which is
    #: the whole point: the reply cap becomes `num_predict`, and `num_predict`
    #: bounds *everything the model generates*, thinking included. A flat cap
    #: therefore means a model that thinks for 256 tokens has nothing left to
    #: answer with, which is precisely the reported failure (§35A.3): Quick
    #: mode on a thinking model, twice, thought for a while and then emitted no
    #: answer at all.
    THINKING_ALLOWANCE_TOKENS = 1_024

    #: **Detailed asks for more thinking, so it needs more room for it.**
    #: Reported: with "Detailed" selected, some turns came back with no
    #: answer at all (or a much shorter one than the setting promised), the
    #: original fix above gave every preset the *same* flat 1,024-token
    #: allowance, but Detailed's own `length_hint` explicitly asks the model
    #: to "work through the relevant notes, draw connections between them,
    #: and explain your reasoning", inviting a longer thinking trace than
    #: Quick or Normal ever asked for, on a preset whose grounding context is
    #: usually the largest of the three. A verbose reasoning model given more
    #: to think about and the same 1,024-token leash starves its own answer
    #: exactly like §35A.3's Quick-mode case did, just less often, this file
    #: already predicted it: "1,024 shared between deliberation and answer is
    #: the same trap in a larger size" (test_thinking_budget.py). Unused
    #: headroom still costs nothing (see below), so there is no downside to
    #: sizing Detailed's allowance for the reasoning its own prompt invites.
    THINKING_ALLOWANCE_BY_MODE = {"detailed": 3_072}

    def thinking_allowance(self, mode: str | None, model: str) -> int:
        """Headroom for deliberation, unless thinking was actually turned off.

        Keyed on **what was sent**, not on what the model declares. That is
        deliberate: §35C is a report of a thinking model whose capability list
        says otherwise, and the capability list is the only thing
        `request_extras` can consult before deciding to send `think: False`.
        Trusting it twice would mean a model that lies about thinking gets a
        flat cap *and* thinks anyway, the failure above.

        The two ways to be wrong are not symmetric, which settles it:

        - allowance added but unused → the reply *may* run longer than the
          preset intended, and `length_hint` is still telling the model to
          answer in two or three sentences. `num_predict` is a ceiling, not a
          target, so an unused ceiling costs nothing;
        - allowance missing when needed → no answer at all.

        A total failure on one side and a slightly long answer on the other is
        not a close call.
        """
        if self.request_extras(mode, model).get("think") is False:
            return 0
        return self.THINKING_ALLOWANCE_BY_MODE.get(mode or "", self.THINKING_ALLOWANCE_TOKENS)

    def runtime_options(
        self,
        model: str,
        max_output_tokens: int | None = None,
        mode: str | None = None,
    ) -> dict:
        """The dialect-specific options block sent with every generation."""
        raise NotImplementedError

    def sampling_overrides(self) -> dict:
        """The user's own sampling settings, or {}, see `ai/sampling.py`.

        Read here rather than passed in, because every generation path in the
        app goes through `runtime_options` and threading a settings dict
        through all of them would mean each one could forget. Stored sparsely:
        only the fields actually changed, so a model the user has never touched
        still gets its own recommendations for everything else.

        Deliberately tolerant of a bad value. This is a preference file a
        person can edit by hand, and a typo in it should cost that one setting,
        not every generation the app makes.
        """
        # Read through a registered getter, not by importing `core.deps`.
        #
        # CodeQL flagged the direct import as a cycle and it is right about the
        # layering as well as the graph: `ai/provider.py` is the lowest layer
        # of the AI stack, every client builds on it, while `core.deps` is
        # the app's wiring, which reaches back down into this module to build
        # the very object being configured. Deferring the import inside the
        # function hid the cycle from the interpreter without removing it.
        #
        # The getter is installed by whoever does the wiring (see
        # `core/deps.py`), so this module keeps knowing nothing about where
        # settings live, and a test can hand it a plain dict.
        if _sampling_overrides_getter is None:
            return {}
        try:
            stored = _sampling_overrides_getter()
        except Exception:  # noqa: BLE001  # settings must never break a request
            return {}
        return stored if isinstance(stored, dict) else {}

    def request_extras(self, mode: str | None = None, model: str = "") -> dict:
        """Top-level payload fields a preset needs that aren't options.

        Ollama's thinking toggle is one; the OpenAI shape has no standard
        equivalent, so its implementation returns nothing. Empty by default so
        a provider only overrides it if it has something to say.
        """
        return {}

    def is_running(self) -> bool:
        raise NotImplementedError

    def list_models(self) -> list[dict]:
        raise NotImplementedError

    def supports(self, model: str, capability: str) -> bool | None:
        """Can this model do `capability`, True, False, or None for unknown.

        Three answers rather than two, and the third is the important one.
        "This model has no thinking to turn off" and "I cannot tell you whether
        it does" want different behaviour: the first means don't bother, the
        second means send nothing rather than guess. Collapsing them into a
        bool forces a guess at exactly the point where guessing wrong disables
        a working feature.

        The base implementation answers None to everything, which is the safe
        answer for a backend that does not report capabilities at all.
        """
        return None

    def model_spec(self, model: str) -> dict:
        """The model's own specification, flat, for Settings → Models.

        The app knew a context length and nothing else, so the screen could not
        say how big a model was, how it was quantised, or whether it could use
        tools: which is the first thing to check when "agent mode does
        nothing". Every field is optional: a backend that cannot answer returns
        None and the UI omits the row rather than printing "unknown" six times.
        """
        return {
            "name": model,
            "family": None,
            "parameters": None,
            "quantisation": None,
            "context_length": self.context_length(model),
            "usable_context": self.usable_context(model),
            "capabilities": [],
            "supports_tools": self.supports(model, "tools"),
            "supports_thinking": self.supports(model, "thinking"),
        }

    def supports_pull(self) -> bool:
        """Can this backend download models on request?

        Only Ollama can. LM Studio, llama.cpp and vLLM are handed a model that
        is already on disk, so the UI's download panel is meaningless there and
        hides itself rather than offering a button that cannot work.
        """
        return False


# --- stream helpers: about what a model wrote, not about who served it -------


class _ThinkTagSplitter:
    """Routes streamed content into thinking vs answer pieces when a
    model reasons inline with <think>…</think>, the tags themselves can
    arrive split across chunks, so a little state is unavoidable."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._mode = "start"  # start → thinking? → answer

    def feed(self, chunk: str) -> list[dict]:
        self._buffer += chunk
        pieces: list[dict] = []

        if self._mode == "start":
            candidate = self._buffer.lstrip()
            if candidate.startswith(self.OPEN):
                self._mode = "thinking"
                self._buffer = candidate[len(self.OPEN) :]
            elif self.OPEN.startswith(candidate):
                return pieces  # could still become "<think>", wait
            else:
                self._mode = "answer"

        if self._mode == "thinking":
            end = self._buffer.find(self.CLOSE)
            if end != -1:
                pieces.append({"thinking_delta": self._buffer[:end]})
                self._buffer = self._buffer[end + len(self.CLOSE) :]
                self._mode = "answer"
            else:
                # Keep enough back that a half-arrived "</think>" isn't
                # emitted as thinking text.
                safe = len(self._buffer) - (len(self.CLOSE) - 1)
                if safe > 0:
                    pieces.append({"thinking_delta": self._buffer[:safe]})
                    self._buffer = self._buffer[safe:]
                return pieces

        if self._mode == "answer" and self._buffer:
            pieces.append({"content_delta": self._buffer})
            self._buffer = ""
        return pieces

    def flush(self) -> list[dict]:
        """The stream ended: emit whatever is left."""
        leftover, self._buffer = self._buffer, ""
        if not leftover:
            return []
        key = "thinking_delta" if self._mode == "thinking" else "content_delta"
        return [{key: leftover}]


class _ToolTextGate:
    """Holds back streamed text that might turn out to be a tool call in prose.

    Some small models write ``<tool_call>{...}</tool_call>``, or a bare JSON
    object: instead of using the structured tool_calls field.
    ``extract_text_tool_calls`` recovers those and strips them so they're
    executed rather than shown, but a streaming UI would already have printed
    the text by then. So content is gated until it's clearly *not* one of those
    shapes, released in one go at that moment, and passed straight through from
    then on.

    The cap matters: an answer that genuinely opens with "{" must not be held
    hostage forever, so past MAX_GATE characters the gate gives up and opens.
    """

    MAX_GATE = 1000
    OPENER = "<tool_call>"

    def __init__(self) -> None:
        self._buffer = ""
        self._open = False

    def feed(self, text: str) -> str:
        """Return whatever is safe to show now (possibly "")."""
        if self._open:
            return text
        self._buffer += text
        candidate = self._buffer.lstrip()
        if not candidate:
            return ""
        looks_like_call = (
            candidate.startswith("{")
            or candidate.startswith(self.OPENER)
            # A partially-arrived "<tool_call>", wait for the rest.
            or self.OPENER.startswith(candidate)
        )
        if looks_like_call and len(self._buffer) < self.MAX_GATE:
            return ""
        self._open = True
        held, self._buffer = self._buffer, ""
        return held

    def flush(self) -> str:
        """The stream ended while still gated, hand back what was held."""
        held, self._buffer = self._buffer, ""
        self._open = True
        return held

    @property
    def gated(self) -> bool:
        return not self._open


def _balanced_json_objects(text: str) -> list[tuple[int, int, str]]:
    """Every brace-balanced ``{...}`` substring in ``text``, as (start, end,
    substring) triples in the order they open.

    A model's tool-call arguments are routinely themselves an object or
    contain a list of objects, ``{"name": "create_note", "arguments":
    {"title": "x", "tags": ["a", "b"]}}`` is a completely ordinary call, not
    an edge case: so a scanner for this has to track real nesting depth
    rather than assume one flat level. Quoted braces (inside a JSON string
    value) are not counted, so a title like ``"Notes on {curly braces}"``
    can't desync the depth count.
    """
    found: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    found.append((i, j + 1, text[i : j + 1]))
                    break
            j += 1
        # Resume scanning right after this object (found) or right after the
        # unmatched '{' (ran off the end unbalanced), either way, before j+1
        # so an object nested immediately inside isn't scanned as if it were
        # top-level too.
        i = j + 1
    return found


# Verbs a model reaches for when it has forgotten the tool's real name, mapped
# to the verb this app actually uses. Reported with a screenshot of the popup
# agent: the model emitted, as plain text, `{"name": "make_note",
# "parameters": {...}}`, and **no note was made**. The text-call salvage
# below was already working; it dropped this one on the only check it could
# not pass, `name in tool_names`, because there is no `make_note`. There is
# `create_note`.
#
# A small model inventing a synonym for a verb is not the same failure as it
# inventing a whole capability, and the two deserve different answers: the
# first is a name to fix, the second is a refusal. So this only ever rewrites
# the *verb* of an otherwise real tool name, and only when exactly one real
# tool comes back: never a guess between `create_note` and `edit_note`.
_VERB_SYNONYMS = {
    "make": "create",
    "add": "create",
    "new": "create",
    "save": "create",
    "write": "create",
    "insert": "create",
    "store": "create",
    "read": "get",
    "open": "get",
    "fetch": "get",
    "show": "get",
    "view": "get",
    "load": "get",
    "find": "search",
    "lookup": "search",
    "query": "search",
    "remove": "delete",
    "destroy": "delete",
    "erase": "delete",
    "update": "edit",
    "change": "edit",
    "modify": "edit",
    "rewrite": "edit",
    "label": "tag",
    "connect": "link",
    "disconnect": "unlink",
}


def resolve_tool_name(name: object, tool_names: set[str]) -> object:
    """A real tool name for what the model wrote, or what it wrote unchanged.

    Only the verb is ever rewritten, and only to a single unambiguous match, 
    see `_VERB_SYNONYMS`. Anything this cannot resolve is returned untouched
    so the caller's own `name in tool_names` check still refuses it.
    """
    if not isinstance(name, str) or name in tool_names:
        return name
    cleaned = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
    if not cleaned:
        return name
    if cleaned in tool_names:
        return cleaned
    head, _, rest = cleaned.partition("_")
    if not rest:
        return name
    swapped = f"{_VERB_SYNONYMS.get(head, head)}_{rest}"
    if swapped in tool_names:
        return swapped
    # Same noun, singular/plural swapped: `create_notes` for `create_note`,
    # `list_note` for `list_notes`. Cheap, and a real thing small models do.
    for candidate in (swapped.rstrip("s"), f"{swapped}s"):
        if candidate in tool_names:
            return candidate
    return name


def extract_text_tool_calls(
    content: str, tool_names: set[str]
) -> tuple[list[dict], str]:
    """Recover tool calls that a model wrote as TEXT instead of using the
    structured tool_calls field (bug: small models narrate/emit
    calls in prose, so notes the AI 'creates' never actually get made).

    Handles both an explicit ``<tool_call>{...}</tool_call>`` wrapper and a
    bare JSON object that names a known tool, nested objects and arrays in
    ``arguments`` included, via `_balanced_json_objects` rather than a regex
    that only matched a single flat level (a call with, say, a `tags` list
    or a nested `arguments` object silently failed to recover, arguably the
    single most common shape a real tool call takes, and reported live as
    "the ai didn't actually call any tools"). Returns (calls, cleaned_text)
    where cleaned_text has the recovered JSON removed so it isn't shown to
    the user."""
    calls: list[dict] = []
    cleaned = content

    def _consume(blob: str, whole: str) -> bool:
        try:
            data = json.loads(blob)
        except ValueError:
            return False
        candidates = data if isinstance(data, list) else [data]
        matched = False
        for item in candidates:
            if not isinstance(item, dict):
                continue
            # Accept {"name","arguments"} and OpenAI-ish {"function":{...}}.
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = fn.get("name") if isinstance(fn, dict) else None
            name = resolve_tool_name(name, tool_names)
            if name in tool_names:
                args = fn.get("arguments") or fn.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                calls.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
                matched = True
        if matched:
            nonlocal cleaned
            cleaned = cleaned.replace(whole, "")
        return matched

    # 1) explicit <tool_call>…</tool_call> blocks (Qwen/Hermes style). The
    # object inside is found by scanning from the opening tag rather than a
    # `.*?` regex, which stops at the first `}`, the *first nested one* the
    # moment `arguments` is itself an object, well short of the call's own
    # close.
    for tag_match in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", content, re.S):
        inner = tag_match.group(1)
        # All of them, not just the first: a model that puts more than one
        # call inside one pair of tags (`<tool_call>[{...}, {...}]</tool_call>`,
        # or just two objects back to back) still means every call, not only
        # the first it wrote.
        for _start, _end, blob in _balanced_json_objects(inner):
            _consume(blob, tag_match.group(0))
    # 2) a bare top-level JSON object naming a known tool. `_balanced_json_
    # objects` only ever emits the outermost `{...}` at each position (it
    # jumps past a whole matched span rather than re-entering it), so a
    # call's own nested `arguments` object is never separately offered as a
    # second, spurious call.
    if not calls:
        for _start, _end, blob in _balanced_json_objects(content):
            if '"name"' not in blob:
                continue
            _consume(blob, blob)

    return calls, cleaned.strip()


def _ns_to_ms(value) -> int | None:
    """Ollama reports durations in nanoseconds; milliseconds read better."""
    try:
        return round(int(value) / 1_000_000)
    except (TypeError, ValueError):
        return None


def split_thinking(text: str) -> tuple[str, str | None]:
    """Separate a thinking model's <think>…</think> block from its answer.

    Models like DeepSeek-R1 or Qwen3 reason out loud inside think-tags;
    shown raw it looks like garbage, hidden entirely it wastes useful
    insight: so we return both parts and let the UI decide."""
    start = text.find("<think>")
    end = text.find("</think>")
    if start == -1 or end == -1 or end < start:
        return text.strip(), None
    thinking = text[start + len("<think>") : end].strip()
    clean = (text[:start] + text[end + len("</think>") :]).strip()
    return clean, thinking or None


def normalise_tool_calls(raw_calls: list[dict]) -> list[dict]:
    """`[{"function": {...}}]` in either dialect -> `[{"name", "arguments"}]`.

    The OpenAI shape sends `arguments` as a JSON *string* where Ollama sends an
    object: but Ollama models are inconsistent among themselves and some send
    the string too, which is why this already handled both before there was a
    second provider. One dialect fewer to add.
    """
    calls: list[dict] = []
    for item in raw_calls or []:
        function = item.get("function") or {}
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {}
        calls.append(
            {
                "name": function.get("name", ""),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return calls


def offered_tool_names(tools: list[dict]) -> set[str]:
    """The names in a tool schema list, for text-call recovery to match on."""
    return {
        t.get("function", {}).get("name") for t in tools or [] if isinstance(t, dict)
    }


__all__ = [
    "ProviderError",
    "ToolsUnsupportedError",
    "Provider",
    "DEFAULT_CONTEXT_TOKENS",
    "MAX_REQUESTED_CONTEXT",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "KNOWN_CONTEXT_WINDOWS",
    "known_context",
    "context_from_catalog_entry",
    "first_chat_model",
    "detect_provider",
    "extract_text_tool_calls",
    "normalise_tool_calls",
    "offered_tool_names",
    "split_thinking",
]
