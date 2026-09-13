"""How full did the window get, and was that number measured or guessed?

A token count on its own doesn't answer the question anyone actually has.
"3,900 tokens" is not information; "3,900 of 8,192" is, because it says whether
the *next* turn of this conversation is the one that starts dropping the top of
its own prompt. That failure is silent, the model doesn't error, it just stops
knowing it has tools, so the number has to be visible before it happens rather
than diagnosable after.

The second half is honesty. Ollama counts tokens itself, so its numbers are
measured. Several OpenAI-compatible servers report no usage block at all, and a
guessed number the user believes is measured is worse than a blank. Anything
estimated says so.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai.ollama_client import OllamaClient

from fakes_http import FakeResponse, sse


# --- the window travels with the counts -------------------------------------


def test_ollama_reports_the_window_it_budgeted_against():
    c = OllamaClient(base_url="http://127.0.0.1:1")
    c._context_lengths = {"m": 8192}
    stats = c._stats_from({"prompt_eval_count": 3900, "eval_count": 120}, "m")
    assert stats["context_tokens"] == c.usable_context("m")
    assert stats["prompt_tokens"] == 3900


def test_the_openai_path_reports_it_too(openai_client):
    stats = openai_client._stats_from(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 5}}, "m", 0.0
    )
    assert stats["context_tokens"] == openai_client.usable_context("m")


def test_ollama_counts_are_measured_not_estimated():
    """It counts tokens itself, so there is nothing to guess."""
    c = OllamaClient(base_url="http://127.0.0.1:1")
    c._context_lengths = {"m": 8192}
    assert c._stats_from({"prompt_eval_count": 10}, "m")["usage_source"] == "real"


def test_a_server_that_reports_usage_is_believed(openai_client):
    stats = openai_client._stats_from(
        {"usage": {"prompt_tokens": 4242, "completion_tokens": 7}},
        "m",
        0.0,
        prompt_chars=999999,  # would give a wildly different estimate
    )
    assert stats["usage_source"] == "real"
    assert stats["prompt_tokens"] == 4242


def test_a_silent_server_is_estimated_and_says_so(openai_client):
    """Some llama.cpp builds and several gateways ignore `stream_options`
    entirely. A blank where a number belongs is unhelpful; a guessed number
    the user believes is measured is worse."""
    stats = openai_client._stats_from({}, "m", 0.0, prompt_chars=4000, output_chars=400)
    assert stats["usage_source"] == "estimated"
    assert stats["prompt_tokens"] == 1000  # ~4 chars per token
    assert stats["output_tokens"] == 100


def test_an_estimate_of_nothing_is_not_zero(openai_client):
    """Zero is a claim. None is the absence of one, and the UI draws "?"."""
    stats = openai_client._stats_from({}, "m", 0.0, prompt_chars=0, output_chars=0)
    assert stats["prompt_tokens"] is None
    assert stats["output_tokens"] is None


# --- through the streaming paths --------------------------------------------


def test_a_streamed_turn_carries_the_window_to_the_ui(openai_client, capture_post):
    capture_post.queue.append(
        FakeResponse(
            lines=sse(
                {"choices": [{"delta": {"content": "hi"}}]},
                {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 2}},
            )
        )
    )
    stats = [
        p["stats"] for p in openai_client.chat_stream("m", [{"role": "user", "content": "q"}])
        if "stats" in p
    ][0]
    assert stats["context_tokens"] == openai_client.usable_context("m")
    assert stats["prompt_tokens"] == 50


def test_an_agent_turn_carries_it_too(openai_client, capture_post):
    capture_post.queue.append(
        FakeResponse(
            lines=sse(
                {"choices": [{"delta": {"content": "done"}}]},
                {"choices": [], "usage": {"prompt_tokens": 70, "completion_tokens": 3}},
            )
        )
    )
    final = [p["final"] for p in openai_client.chat_tools_stream("m", [], []) if "final" in p][0]
    assert final["stats"]["context_tokens"] == openai_client.usable_context("m")


def test_the_estimate_counts_what_actually_streamed(openai_client, capture_post):
    """The output half of a streamed estimate can only come from the text that
    went past: there is no payload at the end to read it off."""
    capture_post.queue.append(
        FakeResponse(lines=sse({"choices": [{"delta": {"content": "x" * 400}}]}))
    )
    stats = [
        p["stats"] for p in openai_client.chat_stream("m", [{"role": "user", "content": "q"}])
        if "stats" in p
    ][0]
    assert stats["usage_source"] == "estimated"
    assert stats["output_tokens"] == 100


# --- the agent forwards it ---------------------------------------------------


def _events(http, question, **body):
    with http.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


@pytest.mark.parametrize("use_tools", [True, False])
def test_both_chat_paths_pass_the_window_through(ai_client, fake_ollama, use_tools):
    """Both the agent and plain Q&A spread the whole stats dict into their
    event, so a new field reaches the UI without either path learning about it.
    That property is what is asserted here, the field itself is the easy half,
    and the agent path is the one that has historically dropped stats entirely.
    """
    ai_client.post("/entries", json={"content": "the beans need netting next week"})
    fake_ollama.stats = {**fake_ollama.stats, "context_tokens": 4096}
    fake_ollama.librarian_reply = "You wrote about beans."

    events = _events(ai_client, "what did I write about beans?", use_tools=use_tools)
    stats = [e for e in events if e["type"] == "stats"]
    assert stats, "a turn should report what it cost"
    assert stats[0]["context_tokens"] == 4096
    assert stats[0]["usage_source"] == "real"
