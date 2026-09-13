"""The OpenAI `/v1/chat/completions` dialect: LM Studio, llama.cpp, Jan, vLLM (§6).

The ask was "support LM Studio". Building an LM Studio client would have been
the smaller change and bought exactly one backend; LM Studio's API is the
OpenAI shape, and so is llama.cpp's server, Jan's, vLLM's, and Ollama's own
`/v1` surface. **One provider gets all of them**, and the only thing that
distinguishes them is the base URL.

Four things differ from Ollama's native API, and each is a place this file
earns its keep:

1. **There is no `num_ctx`.** The window is fixed when the server loads the
   model, so unlike Ollama there is nothing to ask for, only something to
   discover and ration against. `runtime_options` therefore sends `max_tokens`
   alone, and `usable_context` becomes advisory rather than instructive. That
   is safe in the direction that matters: the app rations itself to at most
   what the server reported.
2. **Tool-call arguments arrive as a JSON string**, and when streaming they
   arrive in *fragments keyed by index*, `{"index": 0, "function":
   {"arguments": "{\\"ti"}}` then `{"index": 0, "function": {"arguments":
   "tle\\": ...}}`. Concatenating them in arrival order without keying on the
   index interleaves two calls into one unparseable blob the moment a model
   asks for two things at once, which small models do constantly.
3. **The stream is SSE**, not JSON lines: `data: {...}` with a `[DONE]`
   sentinel, deltas nested under `choices[0].delta`. `_ThinkTagSplitter` and
   `_ToolTextGate` sit *above* this and needed no change, the split is kept
   at "parse one chunk" precisely so they don't.
4. **Tool results are addressed by id.** Ollama accepts `{"role": "tool",
   "tool_name": ...}`; the OpenAI shape wants `tool_call_id` matching an id the
   assistant turn issued. The agent should not learn two dialects, so it keeps
   writing Ollama's shape and `_to_openai_messages` translates at the boundary.

**The trap §6 named, restated because it is easy to reintroduce:** every
generation path must send its options block. `tests/test_context_budget.py`
asserts this for the four Ollama call sites, and
`tests/test_providers.py` asserts the equivalent here, a payload that omits
`max_tokens` is a model running unbounded on the backend's defaults, which is
the bug §11a was spent fixing, arriving again through a different door.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from urllib.parse import urlparse, urlunparse

import requests

from memorymap.ai import sampling
from memorymap.ai.provider import (
    Provider,
    ProviderError,
    ToolsUnsupportedError,
    _ThinkTagSplitter,
    _ToolTextGate,
    context_from_catalog_entry,
    extract_text_tool_calls,
    is_transient_server_error,
    known_context,
    normalise_tool_calls,
    offered_tool_names,
    split_thinking,
)


def _looks_like_tools_rejection(status: int, body: str) -> bool:
    """Did the server refuse because the model can't do tools?

    Same judgement Ollama's path makes, against a wider set of phrasings
    because there are more servers here. A capability gap is a thing to fall
    back from, plain Q&A still works, so it must be told apart from an
    outage, which is a thing to report.
    """
    if status not in (400, 404, 422, 500):
        return False
    lowered = (body or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "does not support tools",
            "does not support tool",
            "tools are not supported",
            "tool calling is not supported",
            "tool_choice",
            "'tools'",
            '"tools"',
        )
    )


#: The sampling knobs the OpenAI chat-completions schema actually defines.
#:
#: llama.cpp's own server, LM Studio and vLLM all accept more than this, but
#: they disagree about which, and a server that validates strictly rejects the
#: entire request for one unknown field, which would break every turn rather
#: than ignore one setting. The intersection is the only safe set to send
#: blind; anything outside it stays an Ollama-dialect feature.
_OPENAI_SAMPLING = frozenset({"temperature", "top_p"})


class OpenAICompatClient(Provider):
    """Anything that serves `/v1/chat/completions`.

    `base_url` is the part before `/chat/completions`, `http://localhost:1234/v1`
    for LM Studio, `http://localhost:8080/v1` for llama.cpp, `http://localhost:8000/v1`
    for vLLM. `api_key` is optional and usually absent: local servers ignore it,
    and a gateway that wants one is still the same dialect.
    """

    name = "openai"

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        timeout: float = 600.0,
        api_key: str = "",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        # 120s used to be the default here and was too short by design, not
        # by accident, for the same reason as ollama_client.py's own version
        # of this comment: loading a model bigger than about 4B parameters
        # on modest hardware can take well past two minutes on its own, and
        # LM Studio/llama.cpp send nothing over the wire until that finishes
        #, so the old timeout fired mid-load, and the app reported "no
        # response" for a model that hadn't failed, just hadn't finished
        # loading yet. Reported live: "models larger than like 4B params
        # struggle to even load or respond". 600s covers a slow cold load on
        # CPU-only hardware while still eventually giving up with a clear
        # error rather than hanging forever.
        self.timeout = timeout
        self.api_key = (api_key or "").strip()
        # model id -> context length. Asked once per model per process, the
        # same as Ollama's: a restarted llama.cpp with a different `-c` is a
        # restarted app in practice, and re-probing per turn costs a round trip
        # on the path that is already the slowest thing the app does.
        self._context_lengths: dict[str, int | None] = {}
        self._catalog: list[dict] | None = None
        self._props: dict | None = None

    # --- plumbing -----------------------------------------------------------

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _origin(self) -> str:
        """Scheme + host, with the `/v1` stripped.

        LM Studio's richer catalogue lives at `/api/v0/models`, which is a
        sibling of `/v1` rather than a child of it.
        """
        parsed = urlparse(self.base_url)
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

    def is_running(self) -> bool:
        """Cheap reachability probe: short timeout so the UI never hangs
        just to discover the server is off."""
        try:
            response = requests.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=2
            )
            # 401/403 means "reachable, and it wants a key", which is a
            # configuration problem to report, not an unreachable server. The
            # status pill would otherwise say "offline" about a server that is
            # plainly answering.
            return response.status_code < 500
        except requests.RequestException:
            return False

    def _fetch_catalog(self, refresh: bool = False) -> list[dict]:
        """The `/models` list, cached per process.

        LM Studio's `/api/v0/models` is tried first because it reports
        `max_context_length` and `loaded_context_length` where the standard
        `/v1/models` reports neither; on every other server it 404s and costs
        one fast local round trip.
        """
        if self._catalog is not None and not refresh:
            return self._catalog
        catalog: list[dict] = []
        for url in (f"{self._origin()}/api/v0/models", f"{self.base_url}/models"):
            try:
                response = requests.get(url, headers=self._headers(), timeout=5)
                response.raise_for_status()
                entries = response.json().get("data") or []
            except (requests.RequestException, ValueError, AttributeError):
                continue
            if isinstance(entries, list) and entries:
                catalog = [e for e in entries if isinstance(e, dict)]
                break
        self._catalog = catalog
        return catalog

    def list_models(self) -> list[dict]:
        """Installed models in the shape the Models screen already renders.

        Ollama's `/api/tags` reports `name` and `size`; this reports `id` and
        usually no size at all. Translating here rather than in the UI means
        the screen keeps one shape to draw, and a server that does report a
        size still gets to show it.
        """
        models = []
        for entry in self._fetch_catalog(refresh=True):
            model_id = entry.get("id") or entry.get("name")
            if not model_id:
                continue
            models.append(
                {
                    "name": model_id,
                    # Absent on most OpenAI-compatible servers. 0 renders as
                    # blank rather than as a wrong number.
                    "size": entry.get("size") or 0,
                    "modified_at": entry.get("created") or "",
                    # Only LM Studio answers this; the UI can say "loaded".
                    "state": entry.get("state") or "",
                }
            )
        return models

    def context_length(self, model: str) -> int | None:
        """The window this server actually loaded the model with.

        Four sources, best first: what the catalogue reports for this exact
        model, then `llama-server`'s own `/props` (ROADMAP.md item A.2), then
        what the app knows about the model by name, then None.

        `loaded_context_length` beats `max_context_length` when both are
        present, and that ordering is the whole point on LM Studio: a model
        *capable* of 128k that was loaded at 4k will drop the front of the
        prompt, the system prompt, telling it that it has tools, if the app
        budgets against what it could have held rather than what it did.
        `/props`' own `n_ctx` is the same fact for `llama-server`, which
        reports neither `loaded_context_length` nor `max_context_length` on
        its plain `/v1/models`, the actual `-c` the server was started
        with beats this app's guess-from-model-name table for the same
        "what it could hold vs. what it did" reason.
        """
        if model in self._context_lengths:
            return self._context_lengths[model]
        length: int | None = None
        for entry in self._fetch_catalog():
            entry_id = entry.get("id") or entry.get("name") or ""
            if entry_id != model and entry_id.split("/")[-1] != model.split("/")[-1]:
                continue
            loaded = entry.get("loaded_context_length")
            if isinstance(loaded, (int, float)) and loaded > 0:
                length = int(loaded)
            else:
                length = context_from_catalog_entry(entry)
            break
        if length is None:
            n_ctx = self._fetch_props().get("n_ctx")
            if isinstance(n_ctx, (int, float)) and n_ctx > 0:
                length = int(n_ctx)
        if length is None:
            length = known_context(model)
        self._context_lengths[model] = length
        return length

    def _fetch_props(self) -> dict:
        """`llama-server`'s own `/props`, ROADMAP.md item A.2: "detect it".

        A sibling of `/v1`, the same shape `/api/v0/models` (LM Studio) is: 
        `self._origin()`, not `self.base_url`. Only `llama-server` answers
        this; every other OpenAI-compatible server 404s or times out, which
        is exactly why this is a *fallback* source in `context_length`
        rather than tried first. Cached for the life of the process, the
        same reasoning `self._catalog`'s own cache gives: `n_ctx` is fixed
        at server start (`-c`), so re-probing per turn would cost a round
        trip on the slowest path in the app for a value that cannot change
        without a restart.
        """
        if self._props is not None:
            return self._props
        try:
            response = requests.get(
                f"{self._origin()}/props", headers=self._headers(), timeout=2
            )
            response.raise_for_status()
            props = response.json()
        except (requests.RequestException, ValueError, AttributeError):
            props = {}
        self._props = props if isinstance(props, dict) else {}
        return self._props

    def is_llama_cpp(self) -> bool:
        """Whether this server is specifically `llama-server`, not just
        something OpenAI-shaped.

        `/props` is llama.cpp's own endpoint: nothing else in the
        OpenAI-compatible long tail implements it, so answering it at all
        (with the one field every version of it has always reported) is
        the identification itself, the same way LM Studio is told apart by
        `/api/v0/models` answering. No wire format is shared beyond that;
        this does not assume any other `/props` field's shape.
        """
        return "n_ctx" in self._fetch_props()

    def _catalog_entry(self, model: str) -> dict:
        """This model's row in the `/models` catalogue, or an empty dict.

        Matched on the trailing segment as well as the whole id, because a
        catalogue may carry a publisher prefix (`lmstudio-community/qwen3`)
        where the session stores the bare name.
        """
        for entry in self._fetch_catalog():
            entry_id = entry.get("id") or entry.get("name") or ""
            if entry_id == model or entry_id.split("/")[-1] == model.split("/")[-1]:
                return entry
        return {}

    def model_spec(self, model: str) -> dict:
        """What this server will say about the model, which varies a lot.

        LM Studio is generous, quantisation, architecture, both context
        numbers, whether it is currently loaded. Plain llama.cpp and vLLM
        report an id and little else, and that is fine: every field is optional
        and the UI omits what is missing rather than printing "unknown" six
        times.

        Capabilities are the one thing no OpenAI-compatible server reports in a
        standard way, so `supports` stays None here and the app keeps its
        existing behaviour: offer tools, and find out from the 400 if the
        model cannot do them. That fallback already exists and is tested.
        """
        entry = self._catalog_entry(model)
        loaded = entry.get("loaded_context_length")
        return {
            "name": model,
            "family": entry.get("arch") or entry.get("architecture"),
            "parameters": entry.get("parameter_size") or entry.get("size"),
            "quantisation": entry.get("quantization") or entry.get("quantization_level"),
            "context_length": self.context_length(model),
            "usable_context": self.usable_context(model),
            # Only LM Studio answers these two, and both are worth showing:
            # "loaded at 4k" explains a 128k model behaving like a small one.
            "loaded_context_length": int(loaded) if isinstance(loaded, (int, float)) and loaded > 0 else None,
            "state": entry.get("state") or None,
            "capabilities": [],
            "supports_tools": None,
            "supports_thinking": None,
            "supports_vision": None,
        }

    def runtime_options(
        self,
        model: str,
        max_output_tokens: int | None = None,
        mode: str | None = None,
    ) -> dict:
        """The neutral budget, translated into OpenAI's payload fields.

        Only half of the pair survives the translation, and deliberately:
        there is no `num_ctx` equivalent, because the window was fixed when the
        server loaded the model. `context_tokens` is still computed: the
        prompt is rationed against it upstream, it just has nowhere to be
        sent. `max_tokens` is the half that does, and it is the half that stops
        a rambling local model reading as a hang.
        """
        budget = self.generation_budget(model, max_output_tokens, mode)
        options = {"max_tokens": budget["max_output_tokens"]}
        preset_options = {}
        if "temperature" in budget:
            preset_options["temperature"] = budget["temperature"]
        # Sampling, same three layers as the Ollama dialect, but with only two
        # of them available. There is no `/api/show` here: the OpenAI shape has
        # no endpoint that reports a model's own recommended parameters, so
        # this dialect can offer the user's overrides and the task preset and
        # nothing in between. That is a real difference, not an oversight, and
        # it is why the settings panel says where each value came from.
        resolved = sampling.resolve(None, preset_options, self.sampling_overrides())
        # Only what this dialect actually accepts. `top_k`, `min_p`,
        # `repeat_penalty` and `repeat_last_n` are llama.cpp/Ollama names with
        # no place in the OpenAI schema, a strict server rejects the whole
        # request for an unknown field, so sending them would break every turn
        # against exactly the backends this dialect exists to support.
        for key, value in resolved.items():
            if key in _OPENAI_SAMPLING:
                options[key] = value
        return options

    # --- message translation ------------------------------------------------

    @staticmethod
    def _to_openai_messages(messages: list[dict]) -> list[dict]:
        """The app's Ollama-shaped conversation, in the OpenAI dialect.

        Two rewrites, both about tool calls:

        - an assistant turn's `tool_calls` need an `id` and a `type`, and their
          `arguments` must be a JSON *string* rather than an object;
        - a `{"role": "tool", "tool_name": X}` result must instead carry the
          `tool_call_id` of the call it answers.

        Ids are minted here (`call_0`, `call_1`, …) because Ollama never issued
        any, and results are matched to them **by name, oldest unanswered
        first**. That matters when a model calls the same tool twice in one
        turn: matching by name alone would address both results to the first
        call, and the server would reject the turn for leaving one call
        unanswered.
        """
        out: list[dict] = []
        pending: list[tuple[str, str]] = []  # (tool name, call id) awaiting a result
        counter = 0
        for message in messages:
            role = message.get("role")
            if role == "assistant" and message.get("tool_calls"):
                calls = []
                for raw in message["tool_calls"]:
                    function = raw.get("function") or {}
                    arguments = function.get("arguments")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments or {})
                    call_id = raw.get("id") or f"call_{counter}"
                    counter += 1
                    name = function.get("name", "")
                    calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    )
                    pending.append((name, call_id))
                out.append(
                    {
                        "role": "assistant",
                        # A null content alongside tool_calls is the spec, and
                        # some strict servers 400 on an empty string here.
                        "content": message.get("content") or None,
                        "tool_calls": calls,
                    }
                )
            elif role == "tool":
                name = message.get("tool_name") or message.get("name") or ""
                call_id = message.get("tool_call_id")
                if not call_id:
                    for index, (pending_name, pending_id) in enumerate(pending):
                        if pending_name == name:
                            call_id = pending_id
                            pending.pop(index)
                            break
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id or "call_0",
                        "content": message.get("content") or "",
                    }
                )
            elif message.get("images"):
                # `images` carries data URIs (the app's neutral shape: see
                # `ollama_client._to_ollama_messages`'s own docstring for why
                # a data URI rather than bare base64). The OpenAI dialect's
                # `image_url.url` accepts one directly, so unlike the Ollama
                # side this needs no stripping, only reshaping `content`
                # from a plain string into the multipart array vision
                # requires.
                parts = []
                text = message.get("content") or ""
                if text:
                    parts.append({"type": "text", "text": text})
                for uri in message["images"]:
                    parts.append({"type": "image_url", "image_url": {"url": uri}})
                out.append({"role": message.get("role"), "content": parts})
            else:
                out.append(
                    {k: v for k, v in message.items() if k in ("role", "content", "name")}
                )
        return out

    # --- stream parsing -----------------------------------------------------

    @staticmethod
    def _sse_payloads(response) -> Iterator[dict]:
        """Yield one parsed JSON object per SSE `data:` line.

        Everything above this, the think-tag splitter, the tool-text gate , 
        works on "one chunk at a time" and does not care that the chunks were
        framed differently on the wire. Keeping the split exactly here is why
        neither of them needed touching for a second provider.
        """
        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            text = text.strip()
            if not text.startswith("data:"):
                continue
            body = text[len("data:") :].strip()
            if body == "[DONE]":
                return
            try:
                yield json.loads(body)
            except ValueError:
                continue  # a keep-alive or a partial frame; not fatal

    @staticmethod
    def _delta_text(delta: dict) -> tuple[str, str]:
        """(content, thinking) out of one streamed delta.

        `reasoning_content` is what DeepSeek-R1 and several servers use to send
        thinking as its own field rather than inline `<think>` tags: the same
        distinction Ollama's native `thinking` field draws.
        """
        if not isinstance(delta, dict):
            return "", ""
        thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
        return delta.get("content") or "", thinking if isinstance(thinking, str) else ""

    @staticmethod
    def _accumulate_tool_calls(delta: dict, buckets: dict[int, dict]) -> None:
        """Fold one streamed tool-call fragment into its bucket, by index.

        This is the one piece of OpenAI streaming with no Ollama equivalent:
        arguments arrive as a partial JSON string spread over many chunks, and
        two concurrent calls interleave. The index is the only thing tying a
        fragment to the call it belongs to.
        """
        for fragment in delta.get("tool_calls") or []:
            if not isinstance(fragment, dict):
                continue
            index = fragment.get("index", 0)
            bucket = buckets.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if fragment.get("id"):
                bucket["id"] = fragment["id"]
            function = fragment.get("function") or {}
            if function.get("name"):
                bucket["name"] = function["name"]
            if function.get("arguments"):
                bucket["arguments"] += function["arguments"]

    @staticmethod
    def _buckets_to_raw_calls(buckets: dict[int, dict]) -> list[dict]:
        """Assembled buckets, in the app's internal (Ollama-ish) shape.

        Returned in index order, not arrival order, the model asked for them
        in a sequence and a model that says "search, then create" means it.
        """
        raw = []
        for index in sorted(buckets):
            bucket = buckets[index]
            if not bucket["name"]:
                continue
            raw.append(
                {
                    "id": bucket["id"] or f"call_{index}",
                    "function": {
                        "name": bucket["name"],
                        # Left as the string it arrived as; normalise_tool_calls
                        # parses it, and it must round-trip back to the server
                        # unchanged on the next turn.
                        "arguments": bucket["arguments"] or "{}",
                    },
                }
            )
        return raw

    def _stats_from(
        self,
        payload: dict,
        model: str,
        started: float,
        *,
        prompt_chars: int = 0,
        output_chars: int = 0,
    ) -> dict:
        """Token counts + timings, in the one shape the UI's metadata line wants.

        Three things differ from the Ollama path, and each is a small honesty
        problem rather than a plumbing one:

        - **There are no timings.** Where Ollama sends `total_duration` in
          nanoseconds, there is simply nothing, so the wall clock is measured
          here. That is the honest answer to "how long did that take".
        - **Not every server reports usage.** LM Studio and vLLM do; some
          llama.cpp builds and several gateways ignore `stream_options`
          entirely. Rather than showing a blank where a number belongs, the
          count is estimated from characters, and marked as an estimate, so
          the UI can say so. A number the user believes is measured, when it
          was guessed, is worse than no number.
        - **`context_tokens` is the window budgeted against**, so the UI can
          say how *full* the window got. 3,900 tokens means nothing on its own;
          "3,900 of 8,192" is what tells you an answer is about to start losing
          the top of its own prompt.
        """
        usage = payload.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        measured = prompt_tokens is not None or output_tokens is not None
        if not measured:
            # ~4 characters per token. Crude, and roughly right across English
            # prose and the JSON the tools trade in, which is what it is for.
            prompt_tokens = prompt_chars // 4 or None
            output_tokens = output_chars // 4 or None
        return {
            "model": payload.get("model") or model,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_ms": round((time.monotonic() - started) * 1000),
            "eval_ms": None,
            "context_tokens": self.usable_context(model),
            "usage_source": "real" if measured else "estimated",
        }

    @staticmethod
    def _chars_in(messages: list[dict]) -> int:
        """Roughly how much text went up, for when the server won't say."""
        total = 0
        for message in messages or []:
            content = message.get("content")
            if isinstance(content, str):
                total += len(content)
        return total

    def _payload(
        self, model: str, messages: list[dict], mode: str | None = None, **extra
    ) -> dict:
        payload = {
            "model": model,
            "messages": self._to_openai_messages(messages),
            **self.runtime_options(model, mode=mode),
            **self.request_extras(mode, model),
        }
        payload.update(extra)
        return payload

    def _post(self, payload: dict, stream: bool):
        return requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self._headers(),
            stream=stream,
            timeout=self.timeout,
        )

    # --- the four generation paths ------------------------------------------

    def chat(self, model: str, messages: list[dict], mode: str | None = None) -> dict:
        """One non-streamed chat turn.

        Returns {"content": str, "thinking": str | None}: the same shape the
        Ollama path returns, so nothing above this has to know which backend
        answered.

        Retries once on a transient 5xx, same reasoning and shape as
        `OllamaClient.chat`'s own retry (see `is_transient_server_error`).
        """
        started = time.monotonic()
        for attempt in range(2):
            try:
                response = self._post(
                    self._payload(model, messages, mode, stream=False), stream=False
                )
                response.raise_for_status()
                payload = response.json()
                message = (payload["choices"][0] or {}).get("message") or {}
                content, inline_thinking = split_thinking(message.get("content") or "")
                return {
                    "content": content,
                    "thinking": message.get("reasoning_content") or inline_thinking,
                    "stats": self._stats_from(
                        payload,
                        model,
                        started,
                        prompt_chars=self._chars_in(messages),
                        output_chars=len(message.get("content") or ""),
                    ),
                }
            except requests.HTTPError as exc:
                if attempt == 0 and is_transient_server_error(exc):
                    continue
                raise ProviderError(f"Chat with '{model}' failed: {exc}") from exc
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError(f"Chat with '{model}' failed: {exc}") from exc
        # Unreachable: every branch above either returns or raises. Only here
        # so the function reads as exhaustive rather than implicitly
        # returning None (CodeQL: "mixed implicit/explicit returns", #321).
        raise ProviderError(f"Chat with '{model}' failed: retries exhausted")

    def chat_stream(
        self, model: str, messages: list[dict], mode: str | None = None
    ) -> Iterator[dict]:
        """Streamed chat turn: yields {"thinking_delta"} and {"content_delta"}
        pieces as the model produces them, then one {"stats"}.

        Retries once on a transient 5xx, safe for the same structural reason
        as `OllamaClient.chat_stream`'s own retry: `raise_for_status()` is
        the only line here able to raise `HTTPError`, and it always runs
        before this attempt's first `yield`."""
        splitter = _ThinkTagSplitter()
        started = time.monotonic()
        for attempt in range(2):
            last: dict = {}
            streamed_chars = 0  # for the estimate, when the server reports no usage
            try:
                with self._post(
                    self._payload(
                        model,
                        messages,
                        mode,
                        stream=True,
                        # Without this, a streamed OpenAI response carries no usage
                        # block at all and the metadata line loses its token counts.
                        # Servers that don't know the field ignore it.
                        stream_options={"include_usage": True},
                    ),
                    stream=True,
                ) as response:
                    response.raise_for_status()
                    for payload in self._sse_payloads(response):
                        last = payload
                        choices = payload.get("choices") or []
                        delta = (choices[0] or {}).get("delta") if choices else None
                        content, thinking = self._delta_text(delta or {})
                        streamed_chars += len(content) + len(thinking)
                        if thinking:
                            yield {"thinking_delta": thinking}
                        if content:
                            yield from splitter.feed(content)
                    yield from splitter.flush()
                    yield {
                        "stats": self._stats_from(
                            last,
                            model,
                            started,
                            prompt_chars=self._chars_in(messages),
                            output_chars=streamed_chars,
                        )
                    }
                return
            except requests.HTTPError as exc:
                if attempt == 0 and is_transient_server_error(exc):
                    continue
                raise ProviderError(f"Chat with '{model}' failed: {exc}") from exc
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError(f"Chat with '{model}' failed: {exc}") from exc

    def chat_tools_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        mode: str | None = None,
    ) -> Iterator[dict]:
        """Streamed tool-calling turn: the agent loop's normal path.

        Yields, in order:
          {"thinking_delta": str}   zero or more
          {"content_delta": str}    zero or more
          {"final": {...}}          exactly one, same shape the Ollama path returns
        """
        splitter = _ThinkTagSplitter()
        gate = _ToolTextGate()
        content = ""       # everything the model wrote, gated or not
        thinking = ""
        shown = False      # did any prose actually reach the caller?
        buckets: dict[int, dict] = {}
        started = time.monotonic()
        last: dict = {}
        try:
            with self._post(
                self._payload(
                    model,
                    messages,
                    mode,
                    stream=True,
                    tools=tools,
                    stream_options={"include_usage": True},
                ),
                stream=True,
            ) as response:
                # A model without tool support is a gap to fall back from, not
                # an outage: the same distinction the Ollama path draws.
                if _looks_like_tools_rejection(response.status_code, response.text):
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

                for payload in self._sse_payloads(response):
                    last = payload
                    choices = payload.get("choices") or []
                    delta = ((choices[0] or {}).get("delta") if choices else None) or {}
                    text, reasoning = self._delta_text(delta)
                    if reasoning:
                        thinking += reasoning
                        yield {"thinking_delta": reasoning}
                    self._accumulate_tool_calls(delta, buckets)
                    if text:
                        for piece in splitter.feed(text):
                            yield from emit(piece)
                for piece in splitter.flush():
                    yield from emit(piece)
        except ToolsUnsupportedError:
            raise
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Tool chat with '{model}' failed: {exc}") from exc

        raw_calls = self._buckets_to_raw_calls(buckets)
        calls = normalise_tool_calls(raw_calls)
        clean = content
        if not calls:
            # Nothing structured: the text may itself be the call. Anything
            # still gated was never shown, so removing it costs the user
            # nothing.
            recovered, clean = extract_text_tool_calls(content, offered_tool_names(tools))
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
                "stats": self._stats_from(
                    last,
                    model,
                    started,
                    prompt_chars=self._chars_in(messages),
                    output_chars=len(content) + len(thinking),
                ),
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
        """One non-streamed chat turn with tools offered."""
        started = time.monotonic()
        try:
            response = self._post(
                self._payload(model, messages, mode, stream=False, tools=tools), stream=False
            )
            if _looks_like_tools_rejection(response.status_code, response.text):
                raise ToolsUnsupportedError(f"'{model}' can't use tools")
            response.raise_for_status()
            payload = response.json()
            message = (payload["choices"][0] or {}).get("message") or {}
            content, inline_thinking = split_thinking(message.get("content") or "")
            raw_calls = message.get("tool_calls") or []
            calls = normalise_tool_calls(raw_calls)

            # Fallback: some models write the call as TEXT instead of using the
            # structured field, so the note they "create" never gets made.
            if not calls:
                recovered, content = extract_text_tool_calls(
                    content, offered_tool_names(tools)
                )
                if recovered:
                    calls = recovered
                    raw_calls = [
                        {"function": {"name": c["name"], "arguments": c["arguments"]}}
                        for c in recovered
                    ]

            return {
                "content": content,
                "thinking": message.get("reasoning_content") or inline_thinking,
                "tool_calls": calls,
                "raw_tool_calls": raw_calls,
                "stats": self._stats_from(
                    payload,
                    model,
                    started,
                    prompt_chars=self._chars_in(messages),
                    output_chars=len(content or ""),
                ),
            }
        except ToolsUnsupportedError:
            raise
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"Tool chat with '{model}' failed: {exc}") from exc

    def embed(self, model: str, text: str) -> list[float]:
        """Embed one text through `/v1/embeddings`."""
        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": model, "input": text},
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
        except requests.HTTPError as exc:
            resp = exc.response
            body = (resp.text if resp is not None else "") or ""
            status = resp.status_code if resp is not None else None
            # Same misconfiguration Ollama's path calls out: people pick their
            # chat model as the embedding model, and the raw HTTP error tells
            # them nothing about which setting is wrong.
            if status in (400, 404, 501) or "does not support" in body.lower():
                raise ProviderError(
                    f"'{model}' can't create embeddings: it looks like a chat "
                    "model, not an embedding model. Load a dedicated embedding "
                    "model on this server and select it as the search engine."
                ) from exc
            raise ProviderError(f"Embedding with '{model}' failed: {exc}") from exc
        except (
            requests.RequestException,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise ProviderError(f"Embedding with '{model}' failed: {exc}") from exc
