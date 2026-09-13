"""Ollama's native `/api` dialect (plan §6.5, generalised in §6).

One of two backends MemoryMap speaks. The parts of this file that were never
about Ollama: the think-tag splitter, the tool-text gate and recovery, the
error classes, the context ceiling, now live in `ai/provider.py` and are
shared with `ai/openai_client.py`; they are re-exported below so the imports
that already point here keep working.

What stays is genuinely Ollama's own: `/api/chat` with a JSON-lines stream, an
`options` block carrying `num_ctx` and `num_predict`, `/api/show` for the
context window, and `/api/pull`, the one thing no OpenAI-compatible server
can do, because those are handed a model that is already on disk.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from memorymap.ai import sampling
from memorymap.ai.provider import (
    Provider,
    ProviderError,
    ToolsUnsupportedError,
    _ThinkTagSplitter,
    _ToolTextGate,
    _ns_to_ms,
    extract_text_tool_calls,
    is_transient_server_error,
    known_context,
    normalise_tool_calls,
    offered_tool_names,
    split_thinking,
)

# `OllamaError` is not a subclass of the neutral error, it *is* the neutral
# error. Every `except OllamaError` in the routes was written to mean "the AI
# backend failed", and aliasing keeps all of them catching a failing LM Studio
# too. A new parent class would have looked tidier and quietly stopped those
# handlers firing for the second provider.
OllamaError = ProviderError

__all__ = [
    "OllamaClient",
    "OllamaError",
    "ProviderError",
    "ToolsUnsupportedError",
    "extract_text_tool_calls",
    "split_thinking",
    "_ThinkTagSplitter",
    "_ToolTextGate",
    "describe_http_error",
]


def describe_http_error(exc: requests.HTTPError, model: str) -> str:
    """Turn a `requests.HTTPError` from Ollama into something the user can act
    on, instead of the bare status line.

    Reported as "the AI is broken", with nothing more to go on than
    `ProviderError: Chat with 'my-model' failed: 500 Server Error: Internal
    Server Error for url: http://127.0.0.1:11434/api/chat`. That message names
    the transport and hides the diagnosis: **Ollama puts the actual reason in
    the response body**, as `{"error": "..."}`, and `str(HTTPError)` never
    looks at it. Every 500 in this app read identically no matter whether the
    model failed to load, the machine was out of memory, or the GGUF was
    incompatible.

    So: quote the server's own words, and where the wording is one of the
    handful of failures that are actually common with a locally-built or
    downloaded GGUF, say what to do about it. The raw text is always kept, 
    a message that replaces the server's diagnosis with a guess is worse than
    one that adds to it.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    detail = ""
    if response is not None:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("error") or "").strip()
        except ValueError:
            detail = (response.text or "").strip()
    detail = detail[:400]

    if not detail:
        # **An empty body is the case that keeps being reported**, and the
        # bare transport line is the least useful thing this function can
        # say. Reported verbatim, from a custom HF GGUF:
        #
        #     Tool chat with 'hf.co/…/Gemma-4-E2B-…:Q4_K_M' failed:
        #     500 Server Error: Internal Server Error for url:
        #     http://localhost:11434/api/chat
        #
        # Ollama usually puts a reason in `{"error": …}`, and the branches
        # below read it: but when the runner dies mid-request the body can
        # come back empty, and then the user is told only that something
        # went wrong somewhere. The app knows more than that: it knows which
        # model was asked, that the failure was a 5xx from a local server,
        # and (because 500s on this path are dominated by two causes) what
        # is worth checking first.
        #
        # Still no guessing about *which* it was, the raw error stays in
        # the text, exactly as the docstring above requires.
        if isinstance(status, int) and status >= 500:
            return (
                f"Chat with '{model}' failed: Ollama returned {status} and no "
                "reason. That is almost always the model itself, either it "
                "could not be loaded (a GGUF built for a newer llama.cpp than "
                "this Ollama, or a truncated download) or it ran out of "
                "memory partway through. Ollama's own log has the real "
                f"message. Original error: {exc}"
            )
        return f"Chat with '{model}' failed: {exc}"

    lowered = detail.lower()
    if "memory" in lowered:
        advice = (
            " This machine does not have enough free memory to run the model. "
            "Close something large, or pick a smaller model or a smaller "
            "quantisation (a q4 build of the same model needs roughly half "
            "what a q8 does)."
        )
    elif "runner process has terminated" in lowered or "unable to load model" in lowered:
        advice = (
            " Ollama could not load the model file itself. That is usually a "
            "GGUF built for a newer llama.cpp than this Ollama has, or a "
            "truncated download: try `ollama pull` again, or update Ollama."
        )
    elif status == 404 or "not found" in lowered:
        advice = (
            f" Ollama does not have '{model}'. Pull it first, or choose a "
            "different model in Settings."
        )
    else:
        advice = ""

    return f"Chat with '{model}' failed: Ollama said: {detail}.{advice}"


class OllamaClient(Provider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 600.0,
        keep_alive: str = "30m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # 120s used to be the default here and was too short by design, not
        # by accident: on modest hardware, loading a model bigger than about
        # 4B parameters into RAM/VRAM for the first time can take well past
        # two minutes on its own, before a single token is generated. Ollama
        # sends nothing over the wire during that load, so `requests` read
        # timeout fires and the app reports "the model didn't respond" for a
        # model that was, in fact, still loading. Reported live: "models
        # larger than like 4B params struggle to even load or respond".
        # 600s is generous enough to cover a slow cold load on CPU-only
        # hardware while still eventually giving up with a clear error
        # rather than hanging forever.
        self.timeout = timeout
        # Ollama unloads an idle model after its own default keep-alive (5
        # minutes) and reloads it, cold, hitting the same timeout risk
        # above: on the next request. A notebook app used on and off through
        # the day spends most of its requests idle-then-reload under that
        # default. 30 minutes keeps a model warm across a normal working
        # session instead of paying the load cost on almost every turn.
        self.keep_alive = keep_alive
        # model name -> context length in tokens. Asked once per model per
        # process: it cannot change without the model being re-pulled, and the
        # answer is needed on every agent round.
        self._context_lengths: dict[str, int | None] = {}
        # The whole `/api/show` payload, cached alongside it: the context
        # length, the parameter count, and the capability list all come from
        # the same call, and asking three times for one answer each is three
        # round trips on the path that already feels slowest.
        self._shown: dict[str, dict] = {}

    def supports_pull(self) -> bool:
        """Ollama is the only backend that can fetch a model it doesn't have."""
        return True

    def show(self, model: str) -> dict:
        """Everything `/api/show` says about a model, cached per process.

        One call answers several questions the app used to guess at or ignore:
        the context length, the parameter count and quantisation, and, the
        one that changes behaviour, `capabilities`, where Ollama lists what
        the model can actually do (`tools`, `thinking`, `vision`, …).

        Cached because none of it can change without the model being re-pulled,
        and `context_length` is needed on every agent round.

        An empty dict means "couldn't ask". Every caller treats that as
        "unknown" rather than as "no", because an older Ollama build reports no
        `capabilities` field at all, and reading its silence as "this model
        can't use tools" would disable agent mode for everyone on it.
        """
        if model in self._shown:
            return self._shown[model]
        info: dict = {}
        try:
            response = requests.post(
                f"{self.base_url}/api/show", json={"model": model}, timeout=5
            )
            response.raise_for_status()
            payload = response.json()
            info = payload if isinstance(payload, dict) else {}
        except (requests.RequestException, ValueError, AttributeError):
            info = {}
        self._shown[model] = info
        return info

    def capabilities(self, model: str) -> set[str]:
        """What Ollama says this model can do, or an empty set if it won't say.

        Empty means *unknown*, never *none*, see `show`. Callers must fail
        open on an empty set: the alternative is an older Ollama build turning
        off tools and thinking for every model it serves.
        """
        declared = self.show(model).get("capabilities")
        if not isinstance(declared, list):
            return set()
        return {str(c).lower() for c in declared}

    def supports(self, model: str, capability: str) -> bool | None:
        """True / False / None-for-unknown, so a caller can tell the three apart.

        The distinction is the whole point. "This model has no thinking to turn
        off" and "I have no idea whether it does" want different behaviour: the
        first means don't bother sending the toggle, the second means send
        nothing rather than guess.
        """
        declared = self.capabilities(model)
        if not declared:
            return None
        return capability in declared

    def model_spec(self, model: str) -> dict:
        """The model's own specification, in one flat shape for the UI (§11).

        Reading these was the gap: the app knew the context length and nothing
        else, so Settings → Models could not say how big a model was, how it
        was quantised, or whether it could use tools at all, which is the
        first thing to check when "agent mode does nothing".
        """
        info = self.show(model)
        details = info.get("details") or {}
        model_info = info.get("model_info") or {}
        declared = self.context_length(model)
        return {
            "name": model,
            "family": details.get("family") or model_info.get("general.architecture"),
            "parameters": details.get("parameter_size"),
            "quantisation": details.get("quantization_level"),
            "context_length": declared,
            # What the app will actually run it at, which is the number the
            # window percentage on each message is measured against, and is
            # often *lower* than the declared one, deliberately (KV cache).
            "usable_context": self.usable_context(model),
            "capabilities": sorted(self.capabilities(model)),
            "supports_tools": self.supports(model, "tools"),
            "supports_thinking": self.supports(model, "thinking"),
            "supports_vision": self.supports(model, "vision"),
        }

    def context_length(self, model: str) -> int | None:
        """How many tokens this model can actually hold, or None if unknown.

        The app used to assume 4096 for everyone, which is Ollama's fallback
        rather than a fact about any particular model, most current ones
        declare 8k, 32k or far more. Rationing the tool schemas against 4096
        on a model with 128k means withholding tools for no reason; assuming
        128k on a 3B model means the system prompt falls off the front and it
        stops knowing it has tools at all. So: ask.

        Reported by `/api/show` under `model_info` as `<architecture>.
        context_length`, the prefix varies by model family, so the key is
        found by suffix rather than guessed.

        When Ollama says nothing, an old build, or a model whose manifest
        omits it: the shared known-model table is asked before giving up. That
        table is a guess and `/api/show` is a fact, so it is only ever the
        fallback, never the first answer.
        """
        if model in self._context_lengths:
            return self._context_lengths[model]
        length: int | None = None
        info = self.show(model).get("model_info") or {}
        for key, value in info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                length = value
                break
        if length is None:
            length = known_context(model)
        self._context_lengths[model] = length
        return length

    def runtime_options(
        self,
        model: str,
        max_output_tokens: int | None = None,
        mode: str | None = None,
    ) -> dict:
        """The neutral budget, translated into Ollama's `options` block.

        Nothing was sent before this, which meant two things at once: the
        window was whatever Ollama felt like (not what the app had budgeted
        for), and the reply length was unbounded.
        """
        budget = self.generation_budget(model, max_output_tokens, mode)
        options = {
            "num_ctx": budget["context_tokens"],
            "num_predict": budget["max_output_tokens"],
        }
        # Sampling, from three layers, see ai/sampling.py for the order and
        # why omission means "the backend's own default".
        #
        # The model's own recommendations come from the `/api/show` payload
        # this client already fetches and caches for the context window and the
        # capability list; the `parameters` field was being dropped. A GGUF
        # ships its author's recommended temperature/top_p/repeat_penalty, so
        # "the right settings for this model" is something to read rather than
        # to guess at: and a table maintained by hand would be right the day
        # it was written and quietly wrong later.
        preset_options = {}
        if "temperature" in budget:
            preset_options["temperature"] = budget["temperature"]
        options.update(
            sampling.resolve(
                sampling.parse_model_parameters(self.show(model)),
                preset_options,
                self.sampling_overrides(),
            )
        )
        return options

    def request_extras(self, mode: str | None = None, model: str = "") -> dict:
        """Ollama's thinking toggle, which is top-level rather than an option.

        Only ever sent to turn thinking *off*, and only to a model that has
        thinking to turn off. Two separate guards, because they fail for
        different reasons:

        - **Direction.** Turning it *on* where it isn't supported is the
          request that errors, so that direction is never sent at all.
        - **Capability.** Ollama rejects `think` outright for a model without
          the `thinking` capability on recent builds, so `quick` mode on an
          ordinary model would have failed *every* turn, the preset breaking
          the chat it was meant to speed up. `capabilities` is what makes the
          check possible; before it, the app could only guess.

        An *unknown* capability (an older Ollama that reports none) sends
        nothing. Not sending means "whatever the model does by default", which
        is exactly what happened before presets existed, so unknown degrades
        to the old behaviour rather than to a broken one.
        """
        from memorymap.ai import presets

        preset = presets.resolve(mode)
        if preset.think is not False:
            return {}
        return {"think": False} if self.supports(model, "thinking") else {}

    def is_running(self) -> bool:
        """Cheap reachability probe: short timeout so the UI never hangs
        just to discover Ollama is off (plan §6.5)."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def list_models(self) -> list[dict]:
        """Installed models (name, size, modified date, ...)."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            return response.json().get("models", [])
        except (requests.RequestException, ValueError) as exc:
            raise OllamaError(f"Could not list Ollama models: {exc}") from exc

    def pull(self, name: str) -> Iterator[dict]:
        """Download a model. Ollama streams JSON lines with 'status' and
        'completed'/'total' bytes: yield each so a progress bar can be
        driven from them (used by the Model Manager)."""
        try:
            with requests.post(
                f"{self.base_url}/api/pull",
                json={"name": name},
                stream=True,
                timeout=None,  # a multi-GB download has no sane timeout
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        yield json.loads(line)
        except (requests.RequestException, ValueError) as exc:
            raise OllamaError(f"Downloading '{name}' failed: {exc}") from exc

    def delete(self, name: str) -> None:
        """Uninstall a model from Ollama (frees the disk it used). Raises
        OllamaError if it isn't installed or the call fails."""
        try:
            response = requests.delete(
                f"{self.base_url}/api/delete", json={"name": name}, timeout=30
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"Removing '{name}' failed: {exc}") from exc

    @staticmethod
    def _to_ollama_messages(messages: list[dict]) -> list[dict]:
        """Strip the `data:image/…;base64,` prefix `images` carries internally.

        A data URI is the app's own neutral representation (it round-trips
        through `openai_client._to_openai_messages` unchanged: that dialect's
        `image_url.url` accepts one directly). Ollama's `/api/chat` wants a
        flat list of *bare* base64 strings instead and sniffs the format
        itself, so this is the one place that has to know the difference.
        Messages without an `images` key pass through untouched, most of
        them, since only a turn with an attached image ever carries one.
        """
        out = []
        for message in messages:
            images = message.get("images")
            if not images:
                out.append(message)
                continue
            stripped = [img.split(",", 1)[-1] if img.startswith("data:") else img for img in images]
            out.append({**message, "images": stripped})
        return out

    def chat(self, model: str, messages: list[dict], mode: str | None = None) -> dict:
        """One non-streamed chat turn.

        Returns {"content": str, "thinking": str | None}: thinking is
        filled from Ollama's native field (newer thinking models) or by
        splitting inline <think> tags out of the content.

        Retries once on a transient 5xx (reported live: a chat call and a
        captioning call both failing on a plain 500 and succeeding on the
        exact same resend): see `is_transient_server_error`'s docstring."""
        for attempt in range(2):
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": self._to_ollama_messages(messages),
                        "stream": False,
                        "keep_alive": self.keep_alive,
                        "options": self.runtime_options(model, mode=mode),
                        **self.request_extras(mode, model),
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                message = response.json()["message"]
                content, inline_thinking = split_thinking(message["content"])
                return {
                    "content": content,
                    "thinking": message.get("thinking") or inline_thinking,
                }
            except requests.HTTPError as exc:
                if attempt == 0 and is_transient_server_error(exc):
                    continue
                raise OllamaError(describe_http_error(exc, model)) from exc
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                raise OllamaError(f"Chat with '{model}' failed: {exc}") from exc
        # Unreachable: every branch above either returns or raises. Only here
        # so the function reads as exhaustive rather than implicitly
        # returning None (CodeQL: "mixed implicit/explicit returns", #320).
        raise OllamaError(f"Chat with '{model}' failed: retries exhausted")

    def chat_stream(
        self, model: str, messages: list[dict], mode: str | None = None
    ) -> Iterator[dict]:
        """Streamed chat turn: yields {"thinking_delta": str} and
        {"content_delta": str} pieces as the model produces them.
        Inline <think> tags are routed to thinking_delta too, even when
        a tag is split across two chunks.

        Retries once on a transient 5xx, same as `chat` above: safe here
        specifically because `raise_for_status()` is the only line in this
        attempt able to raise `HTTPError`, and it always runs before this
        attempt's first `yield`, so a retry can never duplicate output
        already handed to the caller."""
        splitter = _ThinkTagSplitter()
        for attempt in range(2):
            try:
                with requests.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": self._to_ollama_messages(messages),
                        "stream": True,
                        "keep_alive": self.keep_alive,
                        "options": self.runtime_options(model, mode=mode),
                        **self.request_extras(mode, model),
                    },
                    stream=True,
                    timeout=self.timeout,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        message = data.get("message", {})
                        if message.get("thinking"):  # native thinking models
                            yield {"thinking_delta": message["thinking"]}
                        if message.get("content"):
                            yield from splitter.feed(message["content"])
                        if data.get("done"):
                            yield from splitter.flush()
                            # Ollama's final chunk carries token counts and
                            # timings: worth surfacing, so the UI can show
                            # what the answer actually cost.
                            yield {"stats": self._stats_from(data, model)}
                return
            except requests.HTTPError as exc:
                if attempt == 0 and is_transient_server_error(exc):
                    continue
                raise OllamaError(describe_http_error(exc, model)) from exc
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                raise OllamaError(f"Chat with '{model}' failed: {exc}") from exc

    # Both dialects normalise the same way, see `provider.normalise_tool_calls`.
    _normalise_tool_calls = staticmethod(normalise_tool_calls)

    def _stats_from(self, payload: dict, model: str) -> dict:
        """Token counts + timings, in the one shape the UI's metadata line wants.

        `context_tokens` is the window the turn was budgeted against, carried
        alongside the counts so the UI can say *how full* the window got rather
        than only how many tokens were spent. 3,900 tokens means nothing on its
        own; "3,900 of 8,192" is the number that tells you an answer is about
        to start losing the top of its own prompt.
        """
        return {
            "model": payload.get("model") or model,
            "prompt_tokens": payload.get("prompt_eval_count"),
            "output_tokens": payload.get("eval_count"),
            "total_ms": _ns_to_ms(payload.get("total_duration")),
            "eval_ms": _ns_to_ms(payload.get("eval_duration")),
            "context_tokens": self.usable_context(model),
            # Ollama counts tokens itself, so these are measured rather than
            # guessed. The OpenAI path cannot always say the same, and the UI
            # marks an estimate as one.
            "usage_source": "real",
        }

    _offered_names = staticmethod(offered_tool_names)

    def _tools_path_is_broken(self, model: str, messages: list[dict], mode) -> bool:
        """Did the *tools* half of that request fail, or the server itself?

        Reported live: a skill run died with `500 Server Error … /api/chat` on
        a 3B abliterated GGUF, twice in a row, while ordinary chat with the
        same model worked fine. Ollama answers 400 with "does not support
        tools" for a model that declares no tool support, but a model whose
        *chat template* breaks on the tools path answers 500, and for the user
        those are the same situation: the request cannot be made this way.
        Community finetunes and re-quants hit this often, because the template
        is exactly the part that gets rewritten.

        Guessing from the status code alone would be wrong in the other
        direction, though. A genuine outage, a model still swapping in, or
        memory pressure also produce 500s, and permanently treating a working
        model as tool-incapable because the server hiccuped is worse than the
        error itself.

        So this asks rather than guesses: the same messages, the same model, no
        `tools` key. If that succeeds the tools path is what is broken and the
        caller should fall back to a plain answer; if it fails too the backend
        is genuinely unwell and the original error is the honest one. One short
        extra request, on a path that has already failed twice.
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": self._to_ollama_messages(messages),
                    "stream": False,
                    "keep_alive": self.keep_alive,
                    # A probe, not an answer: one token is enough to learn
                    # whether the request is accepted at all.
                    "options": {
                        **self.runtime_options(model, mode=mode),
                        "num_predict": 1,
                    },
                },
                timeout=min(self.timeout, 60),
            )
            return bool(response.ok)
        except requests.RequestException:
            return False

    def chat_tools_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        mode: str | None = None,
    ) -> Iterator[dict]:
        """Streamed tool-calling turn: the agent loop's normal path.

        Same decisions as chat_tools, but the assistant's prose arrives as it's
        written instead of in one block at the end. That difference is the
        whole point: with tools switched on (the default) the answer used to
        appear all at once, which read as the model hanging and then dumping
        (user-reported).

        Yields, in order:
          {"thinking_delta": str}   zero or more
          {"content_delta": str}    zero or more
          {"final": {...}}          exactly one, same shape chat_tools returns
        """
        splitter = _ThinkTagSplitter()
        gate = _ToolTextGate()
        content = ""       # everything the model wrote, gated or not
        thinking = ""
        shown = False      # did any prose actually reach the caller?
        raw_calls: list[dict] = []
        stats: dict = {}
        try:
            with requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": self._to_ollama_messages(messages),
                    "stream": True,
                    "tools": tools,
                    "keep_alive": self.keep_alive,
                    "options": self.runtime_options(model, mode=mode),
                    **self.request_extras(mode, model),
                },
                stream=True,
                timeout=self.timeout,
            ) as response:
                # Same capability probe as chat_tools: a model without tool
                # support is a gap to fall back from, not an outage.
                if response.status_code == 400 and "tool" in response.text.lower():
                    raise ToolsUnsupportedError(f"'{model}' can't use tools")
                response.raise_for_status()

                def emit(piece: dict) -> Iterator[dict]:
                    """Route one splitter piece, gating candidate tool-call text."""
                    nonlocal content, thinking, shown
                    if "thinking_delta" in piece:
                        thinking += piece["thinking_delta"]
                        yield piece
                        return
                    chunk = piece["content_delta"]
                    content += chunk
                    visible = gate.feed(chunk)
                    if visible:
                        shown = True
                        yield {"content_delta": visible}

                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    message = data.get("message", {})
                    if message.get("thinking"):  # native thinking models
                        thinking += message["thinking"]
                        yield {"thinking_delta": message["thinking"]}
                    if message.get("tool_calls"):
                        raw_calls.extend(message["tool_calls"])
                    if message.get("content"):
                        for piece in splitter.feed(message["content"]):
                            yield from emit(piece)
                    if data.get("done"):
                        for piece in splitter.flush():
                            yield from emit(piece)
                        stats = self._stats_from(data, model)
        except ToolsUnsupportedError:
            raise
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            # A 5xx here may be an outage, or a model whose chat template
            # breaks on the tools path, see _tools_path_is_broken, which
            # settles it by asking rather than by reading the status code.
            if (
                tools
                and is_transient_server_error(exc)
                and self._tools_path_is_broken(model, messages, mode)
            ):
                raise ToolsUnsupportedError(
                    f"'{model}' answers without tools but fails with them"
                ) from exc
            # Same reasoning as `describe_http_error`: a 500 whose body says
            # *why* must not reach the user as a bare status line. Only an
            # HTTPError carries a response to read; everything else here
            # (connection refused, a malformed chunk) is already self-
            # describing in its own string.
            if isinstance(exc, requests.HTTPError):
                raise OllamaError(
                    describe_http_error(exc, model).replace(
                        "Chat with", "Tool chat with", 1
                    )
                ) from exc
            raise OllamaError(f"Tool chat with '{model}' failed: {exc}") from exc

        calls = self._normalise_tool_calls(raw_calls)
        clean = content
        if not calls:
            # Nothing structured: the text may itself be the call. Anything
            # still gated was never shown, so removing it costs the user
            # nothing; if the gate had already opened, recovery still strips
            # the JSON from what we hand back as the final answer.
            recovered, clean = extract_text_tool_calls(content, self._offered_names(tools))
            if recovered:
                calls = recovered
                raw_calls = [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in recovered
                ]
        held = gate.flush()
        if held and not calls:
            # Gated text that turned out to be ordinary prose (a short answer
            # that merely started with "{"). Show it rather than lose it.
            shown = True
            yield {"content_delta": held}

        yield {
            "final": {
                "content": clean.strip(),
                "thinking": thinking or None,
                "tool_calls": calls,
                "raw_tool_calls": raw_calls,
                "stats": stats,
                # True when prose already reached the caller, so it must not
                # send the final text again as a second copy.
                "streamed": shown,
            }
        }

    def chat_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        mode: str | None = None,
    ) -> dict:
        """One non-streamed chat turn with tools offered.

        Returns {"content", "thinking", "tool_calls", "raw_tool_calls"}.
        tool_calls is normalised to [{"name": str, "arguments": dict}];
        raw_tool_calls is Ollama's own shape, for replaying back into the
        conversation. Non-streamed on purpose: tool-call rounds are short
        and this works on every Ollama version that supports tools."""
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": self._to_ollama_messages(messages),
                    "stream": False,
                    "tools": tools,
                    "keep_alive": self.keep_alive,
                    "options": self.runtime_options(model, mode=mode),
                    **self.request_extras(mode, model),
                },
                timeout=self.timeout,
            )
            # Ollama answers 400 with a "...does not support tools" body
            # for models without tool support, that's a capability gap,
            # not an outage, so signal it distinctly.
            if response.status_code == 400 and "tool" in response.text.lower():
                raise ToolsUnsupportedError(f"'{model}' can't use tools")
            response.raise_for_status()
            payload = response.json()
            message = payload["message"]
            content, inline_thinking = split_thinking(message.get("content") or "")
            raw_calls = message.get("tool_calls") or []
            calls = []
            for item in raw_calls:
                function = item.get("function") or {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):  # some models emit JSON text
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                calls.append({"name": function.get("name", ""), "arguments": arguments})

            # Fallback: some models write the call as TEXT instead of using
            # the structured field, so the note they "create" never actually
            # gets made. Recover those and strip them from the shown text.
            if not calls:
                offered = {
                    t.get("function", {}).get("name")
                    for t in tools
                    if isinstance(t, dict)
                }
                recovered, content = extract_text_tool_calls(content, offered)
                if recovered:
                    calls = recovered
                    raw_calls = [
                        {"function": {"name": c["name"], "arguments": c["arguments"]}}
                        for c in recovered
                    ]

            return {
                "content": content,
                "thinking": message.get("thinking") or inline_thinking,
                "tool_calls": calls,
                "raw_tool_calls": raw_calls,
                # Same shape chat_stream reports, so the message metadata line
                # can be filled in from an agent turn too. Without this, using
                # tools (the default) silently dropped the token counts.
                "stats": self._stats_from(payload, model),
            }
        except ToolsUnsupportedError:
            raise
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            # A 5xx here may be an outage, or a model whose chat template
            # breaks on the tools path, see _tools_path_is_broken, which
            # settles it by asking rather than by reading the status code.
            if (
                tools
                and is_transient_server_error(exc)
                and self._tools_path_is_broken(model, messages, mode)
            ):
                raise ToolsUnsupportedError(
                    f"'{model}' answers without tools but fails with them"
                ) from exc
            # Same reasoning as `describe_http_error`: a 500 whose body says
            # *why* must not reach the user as a bare status line. Only an
            # HTTPError carries a response to read; everything else here
            # (connection refused, a malformed chunk) is already self-
            # describing in its own string.
            if isinstance(exc, requests.HTTPError):
                raise OllamaError(
                    describe_http_error(exc, model).replace(
                        "Chat with", "Tool chat with", 1
                    )
                ) from exc
            raise OllamaError(f"Tool chat with '{model}' failed: {exc}") from exc

    def embed(self, model: str, text: str) -> list[float]:
        """Embed one text with an Ollama embedding model (only used when
        the user switches off the built-in default backend)."""
        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["embeddings"][0]
        except requests.HTTPError as exc:
            # A chat/generation model can't embed: Ollama answers /api/embed
            # with 501 Not Implemented (older builds: 400 "does not support
            # embeddings"). Surface a message the user can act on instead of a
            # raw HTTP error: this is the #1 way people misconfigure the
            # Ollama search engine (they pick their chat model by mistake).
            resp = exc.response
            body = (resp.text if resp is not None else "") or ""
            status = resp.status_code if resp is not None else None
            if status in (400, 501) or "does not support" in body.lower():
                raise OllamaError(
                    f"'{model}' can't create embeddings: it looks like a chat "
                    "model, not an embedding model. Download and select a "
                    "dedicated embedding model such as 'nomic-embed-text' as the "
                    "search engine."
                ) from exc
            raise OllamaError(f"Embedding with '{model}' failed: {exc}") from exc
        except (
            requests.RequestException,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise OllamaError(f"Embedding with '{model}' failed: {exc}") from exc
