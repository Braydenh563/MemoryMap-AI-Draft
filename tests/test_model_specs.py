"""What the backend actually says about a model, read rather than guessed at.

The app knew one thing about the active model, its context length, and
guessed or ignored the rest. Ollama's `/api/show` has been reporting the
parameter count, the quantisation and, most usefully, a `capabilities` list
(`tools`, `thinking`, `vision`, …) that nothing here looked at.

That list is not cosmetic. Two places behave differently for knowing it:

- **The thinking toggle.** Recent Ollama rejects `think` outright for a model
  that has no thinking, so `quick` mode would have failed *every* turn on an
  ordinary model: the preset breaking the chat it was meant to speed up.
- **"Agent mode does nothing."** Whether the model can call tools at all was
  previously discoverable only by trying it and reading the 400.

The rule that makes it safe is tri-state. `supports()` returns True, False, or
**None for "this backend doesn't say"**, and None is never treated as False:
an older Ollama reports no capability list, and reading its silence as "can't"
would disable working features for everyone on it.
"""

from __future__ import annotations

import pytest

from memorymap.ai.ollama_client import OllamaClient
from memorymap.ai.openai_client import OpenAICompatClient
from memorymap.ai.provider import known_context


@pytest.fixture
def ollama():
    c = OllamaClient(base_url="http://127.0.0.1:1")  # nothing listening
    c._shown = {}
    return c


SHOW_PAYLOAD = {
    "capabilities": ["completion", "tools", "thinking"],
    "details": {
        "family": "llama",
        "parameter_size": "3.2B",
        "quantization_level": "Q4_K_M",
    },
    "model_info": {
        "general.architecture": "llama",
        "llama.context_length": 131072,
        "llama.embedding_length": 3072,
    },
}


# --- reading the spec --------------------------------------------------------


def test_the_whole_spec_is_read_from_one_call(ollama):
    ollama._shown = {"m": SHOW_PAYLOAD}
    spec = ollama.model_spec("m")
    assert spec["family"] == "llama"
    assert spec["parameters"] == "3.2B"
    assert spec["quantisation"] == "Q4_K_M"
    assert spec["context_length"] == 131072
    assert spec["capabilities"] == ["completion", "thinking", "tools"]


def test_the_context_length_key_is_found_by_suffix_not_guessed(ollama):
    """The prefix is the architecture and varies by family, so `gemma3` reports
    `gemma3.context_length`. Guessing the prefix would work for llama and
    silently fail for everything else."""
    ollama._shown = {"g": {"model_info": {"gemma3.context_length": 8192}}}
    assert ollama.context_length("g") == 8192


def test_declared_and_usable_are_different_numbers_and_both_are_reported(ollama):
    """A 128k model is deliberately *run* at less, because the KV cache scales
    with the window. Reporting only one of them makes the message-level window
    percentage look wrong to anyone who knows what the model can hold."""
    ollama._shown = {"m": SHOW_PAYLOAD}
    spec = ollama.model_spec("m")
    assert spec["context_length"] == 131072
    assert spec["usable_context"] == OllamaClient.MAX_REQUESTED_CONTEXT
    assert spec["usable_context"] < spec["context_length"]


def test_one_call_answers_every_question(ollama):
    """`/api/show` is asked once per model per process, not once per field.
    Three questions costing three round trips would be three round trips on
    the path that already feels slowest."""
    calls = []

    class CountingClient(OllamaClient):
        def show(self, model):
            calls.append(model)
            return super().show(model)

    client = CountingClient(base_url="http://127.0.0.1:1")
    client._shown = {"m": SHOW_PAYLOAD}
    client.model_spec("m")
    assert len(set(calls)) == 1


# --- the tri-state, which is the whole safety property ----------------------


def test_a_declared_capability_is_true(ollama):
    ollama._shown = {"m": SHOW_PAYLOAD}
    assert ollama.supports("m", "tools") is True
    assert ollama.supports("m", "thinking") is True


def test_an_absent_capability_on_a_model_that_listed_others_is_false(ollama):
    ollama._shown = {"m": {"capabilities": ["completion"]}}
    assert ollama.supports("m", "tools") is False


def test_a_backend_that_says_nothing_answers_none_not_false(ollama):
    """The property everything else rests on. An older Ollama reports no
    capability list; reading that silence as "can't" would turn off tools and
    thinking for every model it serves."""
    ollama._shown = {"m": {}}
    assert ollama.supports("m", "tools") is None
    assert ollama.supports("m", "thinking") is None


def test_an_unreachable_backend_answers_none_too(ollama):
    """Nothing is listening on this port. That is not evidence about the model."""
    assert ollama.supports("never-asked", "tools") is None


def test_a_malformed_capability_list_is_treated_as_no_answer(ollama):
    ollama._shown = {"m": {"capabilities": "tools"}}  # a string, not a list
    assert ollama.supports("m", "tools") is None


def test_capabilities_are_matched_case_insensitively(ollama):
    ollama._shown = {"m": {"capabilities": ["Tools", "THINKING"]}}
    assert ollama.supports("m", "tools") is True


# --- the OpenAI side, which reports less and must not pretend otherwise ------


def test_lm_studio_reports_a_rich_spec():
    c = OpenAICompatClient(base_url="http://localhost:1234/v1")
    c._props = {}
    c._catalog = [
        {
            "id": "qwen3-8b",
            "arch": "qwen3",
            "quantization": "Q4_K_M",
            "max_context_length": 131072,
            "loaded_context_length": 8192,
            "state": "loaded",
        }
    ]
    spec = c.model_spec("qwen3-8b")
    assert spec["family"] == "qwen3"
    assert spec["quantisation"] == "Q4_K_M"
    assert spec["loaded_context_length"] == 8192
    assert spec["state"] == "loaded"
    # The loaded window is the one budgeted against, not the bigger one.
    assert spec["context_length"] == 8192


def test_a_sparse_server_reports_what_little_it_has():
    """Plain llama.cpp and vLLM give an id and not much else. Every field is
    optional, and the UI omits what is missing rather than printing "unknown"
    six times."""
    c = OpenAICompatClient(base_url="http://localhost:8080/v1")
    c._catalog = [{"id": "qwen3"}]
    c._props = {}
    spec = c.model_spec("qwen3")
    assert spec["family"] is None
    assert spec["quantisation"] is None
    assert spec["context_length"] == known_context("qwen3")


def test_the_openai_dialect_admits_it_cannot_report_capabilities():
    """No OpenAI-compatible server reports them in a standard way. Saying
    "unknown" keeps the existing behaviour, offer tools, and find out from
    the 400: instead of inventing an answer."""
    c = OpenAICompatClient(base_url="http://localhost:1234/v1")
    c._catalog = []
    c._props = {}
    assert c.supports("m", "tools") is None
    assert c.model_spec("m")["supports_tools"] is None


def test_a_publisher_prefix_still_matches():
    c = OpenAICompatClient(base_url="http://localhost:1234/v1")
    c._catalog = [{"id": "lmstudio-community/qwen3-8b", "arch": "qwen3"}]
    c._props = {}
    assert c.model_spec("qwen3-8b")["family"] == "qwen3"


# --- through the endpoint ----------------------------------------------------


def test_the_endpoint_describes_the_active_model_by_default(ai_client):
    body = ai_client.get("/models/spec").json()
    assert body["name"]
    assert "usable_context" in body and "capabilities" in body


def test_the_endpoint_can_be_asked_about_a_named_model(ai_client):
    body = ai_client.get("/models/spec", params={"name": "llama3.2"}).json()
    assert body["name"] == "llama3.2"


def test_unknown_capabilities_serialise_as_null_not_false(ai_client):
    """Over the wire too: the UI has to be able to tell "no" from "no idea",
    and JSON `false` would erase that distinction."""
    body = ai_client.get("/models/spec", params={"name": "llama3.2"}).json()
    assert body["supports_tools"] is None
