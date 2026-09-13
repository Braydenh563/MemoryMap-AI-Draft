"""Stand-ins for Ollama and the embedding model, so the test suite runs
fast and fully offline (plan §7). They behave just predictably enough
to prove the real logic around them works.
"""

from __future__ import annotations

import numpy as np

from memorymap.ai.embeddings import EmbeddingService
from memorymap.ai.ollama_client import OllamaError, ToolsUnsupportedError

# Three "topics" the fake embedder understands, one axis each. The 4th
# axis is a catch-all so no vector is ever all-zero.
_TOPIC_WORDS = {
    0: ("joke", "funny", "pun", "scarecrow"),
    1: ("buy", "shopping", "milk", "groceries", "eggs"),
    2: ("race", "athletics", "carnival", "100m", "sprint"),
}


class FakeEmbeddingService(EmbeddingService):
    """Keyword-based 4-dim vectors: same text topic → same direction."""

    def __init__(self, available: bool = True) -> None:
        # No real model manager / ollama needed, we override everything
        # that would touch them.
        super().__init__(model_manager=None, ollama_client=None)  # type: ignore[arg-type]
        self.available = available

    def backend_id(self) -> str:
        return "fake:keywords-v1"

    def active_model(self) -> str:
        # The real one asks the model manager, which this fake doesn't have.
        return "fake-embeddings"

    def is_ready(self) -> bool:
        return self.available

    def embed_text(self, text: str) -> np.ndarray | None:
        if not self.available:
            return None
        lowered = text.lower()
        vector = np.zeros(4, dtype="float32")
        for axis, words in _TOPIC_WORDS.items():
            if any(word in lowered for word in words):
                vector[axis] = 1.0
        if not vector.any():
            vector[3] = 1.0  # unknown topic
        return vector


class FakeOllama:
    """Canned chat replies keyed off the prompts the app actually sends."""

    def __init__(self, running: bool = True) -> None:
        self.running = running
        # Every provider reports where it is and whether it can fetch a model,
        # because Settings → Models shows both (§6). The fake stands in for the
        # Ollama one, so it answers as Ollama does.
        self.base_url = "http://localhost:11434"
        self.chat_calls: list[list[dict]] = []
        self.chat_models: list[str] = []  # which model each chat() used (Wave N)
        self.librarian_reply = "Here's what I found in your notebook!"
        self.librarian_thinking: str | None = None  # set to fake a thinking model
        # `ai.extractor.propose_split`'s own JSON reply, kept apart from
        # `librarian_reply` (which every OTHER non-janitor prompt shares,
        # including `generate_link_reason`) because a split reply has to be
        # valid `{"notes": [...]}` JSON, not prose. Empty by default: no
        # '{' in it means `_extract_json_object` raises, which is exactly
        # `build_extraction`'s single-note-fallback path: a safe default
        # for tests that don't care about splitting specifically.
        self.extract_split_reply = ""
        self.installed = [{"name": "llama3.2:latest", "size": 2_000_000_000}]
        # Agent mode (Wave G). tool_script is a queue: each item is the
        # list of tool calls "the model" makes on one chat_tools round;
        # when it runs dry the fake gives its final text answer.
        self.supports_tools = True
        self.tool_script: list[list[dict]] = []
        self.tool_rounds: list[list[dict]] = []  # messages seen per round
        self.text_tool_reply: str | None = None  # a call the model wrote as text
        # Token counts, as both chat_stream and chat_tools report them.
        self.stats = {
            "prompt_tokens": 120,
            "output_tokens": 40,
            "total_ms": 900,
            "eval_ms": 800,
            # The window the turn was budgeted against, so the UI can report
            # how full it got rather than only how much was spent.
            "context_tokens": 32_768,
            "usage_source": "real",
        }

    def is_running(self) -> bool:
        return self.running

    def supports_pull(self) -> bool:
        return True

    #: What "the model" declares it can do. Empty is the honest default for a
    #: fake standing in for an unknown backend: `supports` then answers None
    #: ("can't tell"), which is what every caller has to cope with anyway.
    capabilities_declared: list[str] = []

    def capabilities(self, model: str) -> set[str]:
        return {c.lower() for c in self.capabilities_declared}

    def supports(self, model: str, capability: str) -> bool | None:
        declared = self.capabilities(model)
        return None if not declared else capability in declared

    def model_spec(self, model: str) -> dict:
        return {
            "name": model,
            "family": "fake",
            "parameters": "1B",
            "quantisation": "Q4_K_M",
            "context_length": self.context_tokens,
            "usable_context": self.usable_context(model),
            "capabilities": sorted(self.capabilities(model)),
            "supports_tools": self.supports(model, "tools"),
            "supports_thinking": self.supports(model, "thinking"),
        }

    # The agent budgets its tool schemas against the model's real window
    # (see tools.within_budget). Generous here on purpose: a test asserting
    # what the agent does with tools should not be silently narrowed by a
    # tight fake window. Tests about the budget itself set this explicitly.
    context_tokens: int = 32_768

    def context_length(self, model: str) -> int | None:
        return self.context_tokens

    def usable_context(self, model: str) -> int:
        return self.context_tokens or 4096

    def chat(self, model: str, messages: list[dict], mode: str | None = None) -> dict:
        self.chat_models.append(model)
        return {"content": self._reply_text(messages), "thinking": self.librarian_thinking}

    def chat_stream(self, model: str, messages: list[dict], mode: str | None = None):
        """Chunks the canned reply like real streaming would."""
        text = self._reply_text(messages)
        if self.librarian_thinking:
            yield {"thinking_delta": self.librarian_thinking}
        middle = max(1, len(text) // 2)
        yield {"content_delta": text[:middle]}
        yield {"content_delta": text[middle:]}
        # The real client's final chunk carries token counts; the message
        # metadata line is built from these.
        yield {"stats": dict(self.stats, model=model)}

    def chat_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        mode: str | None = None,
    ) -> dict:
        """Plays back tool_script one round at a time (Wave G)."""
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        if not self.supports_tools:
            raise ToolsUnsupportedError(f"'{model}' can't use tools (fake)")
        self.tool_rounds.append(messages)
        if self.tool_script:
            calls = self.tool_script.pop(0)
            return {
                "content": "",
                "thinking": self.librarian_thinking,
                "tool_calls": calls,
                "raw_tool_calls": [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ],
                "stats": dict(self.stats, model=model),
            }
        # Mimic the real client recovering a tool call the model wrote as
        # text (Wave O): one-shot, so the second round returns the answer.
        if self.text_tool_reply:
            from memorymap.ai.ollama_client import extract_text_tool_calls

            offered = {t.get("function", {}).get("name") for t in tools}
            recovered, cleaned = extract_text_tool_calls(self.text_tool_reply, offered)
            self.text_tool_reply = None
            return {
                "content": cleaned,
                "thinking": None,
                "tool_calls": recovered,
                "raw_tool_calls": [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in recovered
                ],
                "stats": dict(self.stats, model=model),
            }
        return {
            "content": self.librarian_reply,
            "thinking": self.librarian_thinking,
            "tool_calls": [],
            "raw_tool_calls": [],
            "stats": dict(self.stats, model=model),
        }

    def chat_tools_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        mode: str | None = None,
    ):
        """The streaming shape of chat_tools, what the agent loop calls now.

        Delegates so both paths stay in lockstep and the existing tool_script /
        tool_rounds fixtures keep working unchanged.
        """
        reply = self.chat_tools(model, messages, tools)
        if reply.get("thinking"):
            yield {"thinking_delta": reply["thinking"]}
        text = reply.get("content") or ""
        if text:
            middle = max(1, len(text) // 2)
            yield {"content_delta": text[:middle]}
            yield {"content_delta": text[middle:]}
        # streamed=True tells the agent the prose already reached the user, so
        # it must not send the final text a second time.
        yield {"final": {**reply, "streamed": bool(text)}}

    def _reply_text(self, messages: list[dict]) -> str:
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        self.chat_calls.append(messages)

        system = messages[0]["content"].lower()
        user = messages[-1]["content"].lower()
        if "filing assistant" in system:  # the janitor asking
            # Match topics against the note only, the prompt also lists
            # existing category names (e.g. "Dad Jokes"), which would
            # otherwise trip the keyword match.
            if "note:" in user:
                user = user.split("note:", 1)[1]
            if any(w in user for w in _TOPIC_WORDS[0]):
                return '{"category": "Dad Jokes", "confidence": 88}'
            if any(w in user for w in _TOPIC_WORDS[1]):
                return '{"category": "Shopping", "confidence": 85}'
            if any(w in user for w in _TOPIC_WORDS[2]):
                return '{"category": "Sport Results", "confidence": 82}'
            return '{"category": "Misc", "confidence": 40}'
        if "splitting a piece of free writing" in system:  # ai.extractor asking
            return self.extract_split_reply
        return self.librarian_reply  # the librarian asking

    def embed(self, model: str, text: str) -> list[float]:
        raise OllamaError("fake has no embedding models")

    def list_models(self) -> list[dict]:
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        return list(self.installed)

    def pull(self, name: str):
        """Streams a few progress updates like the real API, then
        'installs' the model."""
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        total = 1_000
        for completed in (250, 600, 1_000):
            yield {"status": "pulling", "completed": completed, "total": total}
        yield {"status": "success"}
        self.installed.append({"name": name, "size": total})

    def delete(self, name: str) -> None:
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        before = len(self.installed)
        self.installed = [m for m in self.installed if m["name"] != name]
        if len(self.installed) == before:
            raise OllamaError(f"model '{name}' not found (fake)")


class GarbageOllama(FakeOllama):
    """A model having a bad day, replies with no JSON at all."""

    def _reply_text(self, messages: list[dict]) -> str:
        if not self.running:
            raise OllamaError("Ollama is not running (fake)")
        self.chat_calls.append(messages)
        return "Hmm, that's a tough one! Could be anything really."
