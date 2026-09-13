"""Quick / normal / detailed: one dial over the four settings a turn needs (§11).

The prompt side of a turn has been budgeted carefully since the context work;
the *output* side had one number for everything. `num_predict` was a flat 1,024
whether the question was "when did I write about beans" or "draft me a summary
of the last month", and output tokens are generated one at a time, so they
cost far more wall-clock each than prompt tokens do.

Two properties matter more than the numbers, and both are about not breaking
what already worked:

- **`normal` must be indistinguishable from before presets existed.** It is the
  default, so anything else means upgrading silently changed everyone's chats.
- **A setting a model can't do is not sent.** Sending nothing means "whatever
  the model does by default", which is what happened before. Sending a
  thinking toggle to a model without one is the request that errors.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import librarian, presets
from memorymap.ai.ollama_client import OllamaClient

from fakes_http import FakeResponse


@pytest.fixture
def ollama():
    c = OllamaClient(base_url="http://127.0.0.1:1")
    c._context_lengths = {"m": 8192}
    return c


# --- the default must not have moved ----------------------------------------


def test_normal_still_sends_exactly_the_runtime_options_it_always_did(ollama):
    """1,024 output tokens, no temperature, no thinking toggle.

    The *runtime* half of "upgrading must not change everyone's chats" still
    holds and is what this pins. The prompt half deliberately no longer does, 
    see the next test.
    """
    preset = presets.resolve("normal")
    assert preset.max_output_tokens == OllamaClient.DEFAULT_MAX_OUTPUT_TOKENS
    assert preset.temperature is None
    assert preset.think is None

    options = ollama.runtime_options("m", mode="normal")
    assert options == ollama.runtime_options("m")
    assert "temperature" not in options


def test_no_mode_at_all_is_the_default(ollama):
    assert ollama.runtime_options("m", mode=None) == ollama.runtime_options("m", mode="normal")


def test_an_unknown_mode_falls_back_rather_than_raising():
    """Reached from a preference file the user may have edited by hand and
    from a request body. A typo should cost the setting, not the chat."""
    assert presets.resolve("suuuper-detailed").id == "normal"
    assert presets.resolve("").id == "normal"
    assert presets.resolve(None).id == "normal"


def test_the_mode_name_is_not_case_sensitive():
    assert presets.resolve("QUICK").id == "quick"


# --- what actually changes ---------------------------------------------------


def test_quick_is_shorter_and_more_literal_than_detailed(ollama):
    quick = ollama.runtime_options("m", mode="quick")
    detailed = ollama.runtime_options("m", mode="detailed")
    assert quick["num_predict"] < detailed["num_predict"]
    assert quick["temperature"] < detailed["temperature"]


def test_the_window_is_the_same_whichever_mode(ollama):
    """A preset is about the *output* side. Changing how much the model may
    write must not change how much it is allowed to read, that is budgeted
    against the model's real window and has nothing to do with effort."""
    windows = {
        ollama.runtime_options("m", mode=m)["num_ctx"]
        for m in ("quick", "normal", "detailed")
    }
    assert len(windows) == 1


def test_an_explicit_cap_still_beats_the_preset(ollama):
    """A caller that names a number has a reason the preset cannot know.

    It names an *answer* length, though, so the thinking headroom (§35A.3) is
    still added on top, the caller has no more idea than the preset does how
    long the model will deliberate first, and a cap shared between the two is
    what produced a turn that thought and then said nothing.
    """
    expected = 77 + ollama.thinking_allowance("detailed", "m")
    assert ollama.runtime_options("m", 77, mode="detailed")["num_predict"] == expected


# --- failing closed on a model that can't ------------------------------------


def test_no_preset_ever_asks_a_model_to_start_thinking():
    """Turning thinking *on* where it isn't supported is the request that
    errors. That direction is simply never available."""
    assert all(preset.think is not True for preset in presets.MODES.values())


def test_the_thinking_toggle_needs_a_model_that_has_thinking(ollama):
    """Two guards, and this is the second one. Recent Ollama rejects `think`
    outright for a model without the `thinking` capability: so `quick` mode
    on an ordinary model would have failed *every* turn, the preset breaking
    the chat it was meant to speed up."""
    ollama._shown = {"thinker": {"capabilities": ["completion", "thinking"]}}
    assert ollama.request_extras("quick", "thinker") == {"think": False}


def test_a_model_without_thinking_is_not_sent_the_toggle(ollama):
    ollama._shown = {"plain": {"capabilities": ["completion", "tools"]}}
    assert ollama.request_extras("quick", "plain") == {}


def test_an_unknown_capability_sends_nothing_rather_than_guessing(ollama):
    """An older Ollama reports no `capabilities` field at all. Sending nothing
    means "whatever the model does by default", which is exactly the behaviour
    that predates presets: so unknown degrades to the old thing, not a broken
    one."""
    ollama._shown = {"ancient": {}}
    assert ollama.request_extras("quick", "ancient") == {}


def test_the_other_modes_never_send_a_toggle(ollama):
    ollama._shown = {"thinker": {"capabilities": ["thinking"]}}
    assert ollama.request_extras("normal", "thinker") == {}
    assert ollama.request_extras("detailed", "thinker") == {}


def test_an_unset_sampling_option_is_omitted_not_nulled():
    """A key present with a null is an explicit instruction to use nothing,
    which some backends reject and others read as zero. Absent means "your
    default", which is what every turn got before presets existed."""
    assert presets.sampling_options(presets.resolve("normal")) == {}
    assert "temperature" in presets.sampling_options(presets.resolve("quick"))


def test_the_openai_dialect_has_no_thinking_toggle_to_send(openai_client):
    """There is no standard spelling for it in the OpenAI shape, so nothing is
    sent rather than something guessed at."""
    assert openai_client.request_extras("quick") == {}


# --- both dialects translate the same preset ---------------------------------


def test_both_providers_cap_the_reply_the_same(openai_client, ollama):
    openai_client._context_lengths = {"m": 8192}
    for mode in ("quick", "normal", "detailed"):
        assert (
            ollama.runtime_options("m", mode=mode)["num_predict"]
            == openai_client.runtime_options("m", mode=mode)["max_tokens"]
        )


def test_the_openai_payload_carries_the_preset(openai_client, capture_post):
    capture_post.queue.append(
        FakeResponse(payload={"choices": [{"message": {"content": "hi"}}]})
    )
    openai_client.chat("m", [{"role": "user", "content": "hi"}], mode="quick")
    sent = capture_post.sent[0]["json"]
    # The preset's answer budget plus room to think (§35A.3). The OpenAI shape
    # has no thinking toggle to send, so the headroom always applies there.
    assert sent["max_tokens"] == (
        presets.resolve("quick").max_output_tokens
        + openai_client.thinking_allowance("quick", "m")
    )
    assert sent["temperature"] == presets.resolve("quick").temperature


# --- the hint, which is the half a cap cannot do -----------------------------


def test_a_cap_without_a_hint_would_truncate_rather_than_shorten():
    """The cap stops the model; the hint is what makes it produce an answer
    that *ends*. Every mode has to say so in words."""
    assert librarian.length_hint("quick")
    assert librarian.length_hint("detailed")


def test_normal_steers_too_rather_than_saying_nothing():
    """This asserted `== ""` until a user reported what that costs:

        *"I want the normal (balanced) setting to write a bit more. It writes
        too concisely and it is closer to the quick setting."*

    Correct, and the empty hint is the reason. Quick and Detailed both steer,
    so with no sentence of its own Normal inherited whatever the base prompt
    implied: and the base prompt is written for a local model on a token
    budget and leans terse. **A default that is the absence of an instruction
    is not a middle setting; it is whichever end the surrounding text pulls
    to.** The middle has to be asked for like the other two.

    The cap is untouched at 1,024 tokens (~750 words), which the short answers
    were nowhere near: the ceiling was never what was binding.
    """
    hint = librarian.length_hint("normal")
    assert hint, "Normal must steer, or it drifts to whatever the base prompt implies"
    assert hint != librarian.length_hint("quick")
    assert hint != librarian.length_hint("detailed")
    assert presets.resolve("normal").max_output_tokens == 1024


def test_the_hint_reaches_the_system_prompt():
    plain = librarian.build_messages("q", [{"content": "n", "category": "c"}])
    quick = librarian.build_messages(
        "q", [{"content": "n", "category": "c"}], mode="quick"
    )
    assert librarian.length_hint("quick") in quick[0]["content"]
    assert librarian.length_hint("quick") not in plain[0]["content"]


def test_the_agent_prompt_gets_it_too():
    from memorymap.ai import agent

    quick = agent.build_agent_messages("q", [], mode="quick")
    assert librarian.length_hint("quick") in quick[0]["content"]


def test_the_hint_is_counted_in_the_budget():
    """The agent measures its own system prompt to size everything else
    against it. A hint added to the prompt but left out of the measurement is
    a budget wrong by exactly the length of the thing just added, silently,
    and only in the mode that has the longest hint.

    Checked against the measurement expression rather than the final number
    because the number is only reachable through a live turn; what matters is
    that the two lists of pieces stay the same list.
    """
    from pathlib import Path

    source = Path("src/memorymap/ai/agent.py").read_text(encoding="utf-8")
    measurement = source.split("system_chars = len(")[1].split("budget = context.plan")[0]
    for piece in ("AGENT_GROUNDING", "tools_guide(", "length_hint(mode)"):
        assert piece in measurement, f"{piece} is in the prompt but not the budget"

    # The guide is now window-dependent (agent.tools_guide picks a short one
    # below 8k), which makes this stricter rather than looser: measuring the
    # long guide while sending the short one, or the reverse, would be a
    # budget wrong by 1,800 characters, in the mode that can least afford it.
    # So both call sites must ask the same function, not just name a constant.
    prompt = source.split('"content": f"{persona} {AGENT_GROUNDING} "')[1][:300]
    assert "tools_guide(" in prompt, "the prompt must use the same guide the budget measured"


# --- through the API ---------------------------------------------------------


def test_the_modes_are_served_rather_than_hard_coded_in_the_ui(ai_client):
    """Adding a fourth preset should be a change to `ai/presets.py` alone."""
    body = ai_client.get("/chat/modes").json()
    assert [m["id"] for m in body["modes"]] == list(presets.MODES)
    assert body["active"] == "normal"
    assert all(m["label"] and m["description"] for m in body["modes"])


def test_the_preference_sets_the_default(ai_client, app_state):
    app_state.set_preference("response_mode", "quick")
    assert ai_client.get("/chat/modes").json()["active"] == "quick"


def test_a_request_can_override_the_preference(ai_client, app_state, fake_ollama):
    """The picker is per-turn: one quick answer shouldn't change the setting."""
    app_state.set_preference("response_mode", "detailed")
    ai_client.post("/entries", json={"content": "beans need netting next week"})
    with ai_client.stream(
        "POST",
        "/chat/stream",
        json={"question": "when do the beans need netting?", "mode": "quick"},
    ) as r:
        events = [json.loads(line) for line in r.iter_lines() if line.strip()]
    assert any(e["type"] == "answer" for e in events)
    # The preference is untouched, the request said "this turn", not "always".
    assert app_state.get_preference("response_mode") == "detailed"
