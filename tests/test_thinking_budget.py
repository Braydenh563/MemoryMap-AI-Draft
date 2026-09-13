"""Thinking must not be able to starve the answer (roadmap §35A.3, §35D).

Reported twice, same shape both times: Quick mode on a thinking model thinks
for a while, stops about three-quarters of the way through, and emits **no
answer at all**. Not a short answer, nothing.

The cause is that the reply cap becomes `num_predict`, and `num_predict` bounds
everything the model generates, thinking included. Quick's cap is 256 tokens.
A model that spends 256 tokens deliberating has none left to answer with, and
what the user sees is a turn that thought and then died.

So the allowance is **added to** the reply cap rather than shared with it, and
keyed on whether `think: false` was actually sent, not on what the model
declares it can do. §35C is a report of a model whose capability list is wrong
about exactly this, and the capability list is the only thing `request_extras`
consults before deciding to suppress thinking. Trusting it twice would give a
lying model a flat cap *and* let it think anyway, which is the failure above.

The two ways of being wrong are not symmetric, and that is the whole argument:
an unused ceiling costs nothing, a missing one costs the entire answer.
"""

from __future__ import annotations

import pytest

from memorymap.ai import presets
from memorymap.ai.ollama_client import OllamaClient


class _Client(OllamaClient):
    """An Ollama client whose capability answer we control."""

    declared: list[str] = []

    def capabilities(self, model: str) -> set[str]:
        return set(self.declared)

    def context_length(self, model: str) -> int | None:
        return 32_768


@pytest.fixture()
def client():
    return _Client()


# --- the reported failure ---------------------------------------------------


def test_quick_on_an_undeclared_thinker_keeps_room_to_answer(client):
    """The exact reported case. The model does not declare `thinking`, so
    `think: false` is never sent: and it thinks anyway. Without headroom its
    whole 256-token budget goes on deliberation."""
    client.declared = ["completion"]
    options = client.runtime_options("gemma", mode="quick")
    assert options["num_predict"] > presets.MODES["quick"].max_output_tokens
    assert options["num_predict"] == (
        presets.MODES["quick"].max_output_tokens + OllamaClient.THINKING_ALLOWANCE_TOKENS
    )


def test_no_allowance_once_thinking_is_actually_turned_off(client):
    """A model that declares `thinking` gets `think: false` in Quick mode, so
    there is nothing to make room for and the preset's cap stands exactly."""
    client.declared = ["completion", "thinking"]
    assert client.request_extras("quick", "qwen") == {"think": False}
    options = client.runtime_options("qwen", mode="quick")
    assert options["num_predict"] == presets.MODES["quick"].max_output_tokens


def test_an_unknown_capability_gets_the_allowance(client):
    """An older Ollama reports no capabilities at all. `supports` answers
    None, "can't tell", so thinking is not suppressed and the headroom has
    to be there."""
    client.declared = []
    assert client.request_extras("quick", "mystery") == {}
    assert client.runtime_options("mystery", mode="quick")["num_predict"] > 256


# --- the other presets ------------------------------------------------------


def test_normal_and_detailed_also_get_headroom(client):
    """Neither asks for thinking to be off, so both can be thought over. 1,024
    shared between deliberation and answer is the same trap in a larger size."""
    client.declared = ["completion", "thinking"]
    for mode in ("normal", "detailed"):
        cap = presets.MODES[mode].max_output_tokens
        assert client.runtime_options("qwen", mode=mode)["num_predict"] > cap


def test_detailed_gets_more_headroom_than_normal(client):
    """Reported: "Detailed" sometimes came back with no answer, or a much
    shorter one than the setting promised. Detailed's own length_hint asks
    the model to "work through the relevant notes, draw connections between
    them, and explain your reasoning", inviting more deliberation than
    Normal or Quick ever asked for, so giving it the same flat 1,024-token
    allowance as the other two is the exact trap this file's own docstring
    already named ("the same trap in a larger size"), just less often. A
    verbose reasoning model given more to think about and no more room for
    it starves its own answer precisely like the original Quick-mode bug."""
    client.declared = ["completion", "thinking"]
    assert client.thinking_allowance("detailed", "qwen") > client.thinking_allowance(
        "normal", "qwen"
    )
    assert client.thinking_allowance("detailed", "qwen") > OllamaClient.THINKING_ALLOWANCE_TOKENS


def test_an_explicit_cap_still_gets_headroom(client):
    """A caller that names a number is naming an *answer* length. It has no
    more idea than the preset does how long the model will think first."""
    client.declared = []
    options = client.runtime_options("mystery", max_output_tokens=500, mode="normal")
    assert options["num_predict"] == 500 + OllamaClient.THINKING_ALLOWANCE_TOKENS


# --- what must not change ---------------------------------------------------


def test_the_context_window_is_untouched(client):
    """This is a change to the *output* budget only. The input side is
    rationed by ai/context.py and must not move."""
    client.declared = ["completion", "thinking"]
    with_think = client.runtime_options("qwen", mode="quick")["num_ctx"]
    client.declared = []
    without = client.runtime_options("mystery", mode="quick")["num_ctx"]
    assert with_think == without


def test_the_direction_guard_still_holds(client):
    """Thinking is only ever turned off, never on, turning it on where it
    isn't supported is the request that errors."""
    client.declared = ["completion", "thinking"]
    for mode in ("normal", "detailed"):
        assert client.request_extras(mode, "qwen") == {}
