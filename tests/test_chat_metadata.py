"""Search results and message metadata must survive a thinking model.

Reported: with a thinking model, neither the "matching notes" disclosure nor
the metadata line at the bottom of a message showed up. Both are driven by
stream events, so these tests assert on the events themselves.
"""

from __future__ import annotations

import json


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def test_meta_and_stats_arrive_with_a_thinking_model(ai_client, fake_ollama):
    ai_client.post("/entries", json={"content": "carbonara needs guanciale, not bacon"})
    fake_ollama.librarian_thinking = "Let me consider the notes about pasta."
    fake_ollama.librarian_reply = "You wrote that carbonara needs guanciale."

    events = _events(ai_client, "what did I write about carbonara?", use_tools=False)
    kinds = [e["type"] for e in events]

    assert "thinking" in kinds  # the model really did think
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["raw_results"], "the matching notes disclosure had nothing to show"
    assert meta["search_mode"]
    stats = next(e for e in events if e["type"] == "stats")
    assert stats["output_tokens"] and stats["prompt_tokens"]


def test_agent_mode_still_reports_stats(ai_client, fake_ollama):
    """Tools are on by default, and that path used to emit no stats at all."""
    ai_client.post("/entries", json={"content": "a note about cycling"})
    fake_ollama.librarian_reply = "Done."

    events = _events(ai_client, "what did I write about cycling?", use_tools=True)
    stats = [e for e in events if e["type"] == "stats"]
    assert stats, "agent turns reported no token counts"
    assert stats[0]["output_tokens"]
    assert stats[0]["model"]


def test_agent_mode_reports_stats_for_every_round(ai_client, fake_ollama):
    """Multi-round turns report per round; the UI adds them up."""
    fake_ollama.librarian_reply = "All done."
    fake_ollama.tool_script = [
        [{"name": "count_notes", "arguments": {}}],
        [{"name": "list_categories", "arguments": {}}],
    ]
    events = _events(ai_client, "how many notes do I have and in what categories?")
    stats = [e for e in events if e["type"] == "stats"]
    assert len(stats) >= 2  # one per round, so the totals can accumulate


def test_agent_mode_stats_carry_a_per_stage_token_estimate(ai_client, fake_ollama):
    """§88.4 item 4: a token estimate per stage, not just a total.

    Attached only to the first round's stats event: see agent.py's own
    comment on why a later round isn't re-measured: so the UI's metadata
    line (whose accumulation logic just spreads the first event wholesale)
    ends up carrying it for the whole turn.
    """
    ai_client.post("/entries", json={"content": "a note about woodworking"})
    fake_ollama.librarian_reply = "Done."
    fake_ollama.tool_script = [
        [{"name": "count_notes", "arguments": {}}],
        [{"name": "list_categories", "arguments": {}}],
    ]
    events = _events(ai_client, "how many notes do I have and in what categories?")
    stats = [e for e in events if e["type"] == "stats"]
    assert len(stats) >= 2
    first, rest = stats[0], stats[1:]

    composition = first["composition"]
    assert set(composition) == {"system", "history", "notes", "tool_schemas"}
    assert all(isinstance(v, int) for v in composition.values())
    # Tools are on and the registry is non-empty, so this can't be zero: 
    # a zero here would mean the schemas were measured before `offered` was
    # ever populated.
    assert composition["tool_schemas"] > 0

    for later in rest:
        assert "composition" not in later


def test_ask_mode_stats_carry_a_composition_with_no_tool_schemas(ai_client, fake_ollama):
    """The no-tools path (build_messages) gets the same breakdown, minus the
    schemas half that only exists when tools are offered at all."""
    ai_client.post("/entries", json={"content": "a note about kayaking"})
    fake_ollama.librarian_reply = "You wrote about kayaking."

    events = _events(ai_client, "what did I write about kayaking?", use_tools=False)
    stats = next(e for e in events if e["type"] == "stats")
    composition = stats["composition"]
    assert set(composition) == {"system", "history", "notes", "tool_schemas"}
    assert composition["tool_schemas"] == 0
    assert composition["notes"] > 0  # the retrieved note went in this message


def test_thinking_model_in_agent_mode_reports_both(ai_client, fake_ollama):
    """The exact reported combination: thinking model + tools on."""
    ai_client.post("/entries", json={"content": "a note about gardening"})
    fake_ollama.librarian_thinking = "Considering the request."
    fake_ollama.librarian_reply = "Here's what I found."

    events = _events(ai_client, "what have I saved about gardening?", use_tools=True)
    kinds = [e["type"] for e in events]
    assert "thinking" in kinds
    assert "stats" in kinds
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["raw_results"]
    assert meta["answered_by"]


def test_the_latest_answer_reaches_a_follow_up_nearly_whole():
    """Reported: "difficult to get the agent to explain something, and then
    make it as a note." The explanation is the previous answer, and clipping
    it to 600 characters meant "save that" saved a stump. The most recent
    answer travels nearly whole; older ones stay clipped hard."""
    from memorymap.ai import librarian

    turns = [
        {"question": f"q{i}", "answer": "old " * 500} for i in range(3)
    ] + [{"question": "explain seraphine", "answer": "the explanation " * 500}]
    messages = librarian.history_messages(turns)
    answers = [m["content"] for m in messages if m["role"] == "assistant"]
    assert all(
        len(a) <= librarian.MAX_HISTORY_ANSWER_CHARS for a in answers[:-1]
    )
    assert len(answers[-1]) == librarian.LAST_ANSWER_CHARS


# --- surviving a reload (IDEAS.md: "metadata disappears on reload") ----------


def test_a_saved_turn_keeps_the_whole_metadata_line(ai_client):
    """`tokens` is a sum, which is the right shape for the conversation total
    and useless for rebuilding the per-message line, you cannot get "3.9k of
    8k, 12 tok/s, llama3.2" back out of a single integer. So the line simply
    vanished on reload and the answer looked like it came from nowhere."""
    stats = {
        "model": "llama3.2",
        "prompt_tokens": 3900,
        "output_tokens": 120,
        "eval_ms": 800,
        "context_tokens": 8192,
        "usage_source": "real",
    }
    created = ai_client.post(
        "/conversations",
        json={
            "question": "what did I write about beans?",
            "answer": "You wrote about netting them.",
            "tokens": 4020,
            "stats": stats,
            "elapsed_ms": 1500,
        },
    ).json()

    full = ai_client.get(f"/conversations/{created['id']}").json()
    assistant = next(m for m in full["messages"] if m["role"] == "assistant")
    assert assistant["stats"] == stats
    assert assistant["elapsed_ms"] == 1500
    # The running total still works, this adds to it rather than replacing it.
    assert full["tokens"] == 4020


def test_an_older_turn_without_stats_still_loads(ai_client):
    """Chats saved before this stored no stats. They must render without a
    metadata line rather than with a row of "?"s: or worse, an error."""
    created = ai_client.post(
        "/conversations", json={"question": "q", "answer": "a", "tokens": 10}
    ).json()
    assistant = next(
        m
        for m in ai_client.get(f"/conversations/{created['id']}").json()["messages"]
        if m["role"] == "assistant"
    )
    assert "stats" not in assistant
    assert "elapsed_ms" not in assistant


def test_the_window_and_the_estimate_flag_survive_too(ai_client):
    """The two fields that make the line worth reading: how full the window
    got, and whether the numbers were measured or guessed."""
    created = ai_client.post(
        "/conversations",
        json={
            "question": "q",
            "answer": "a",
            "stats": {"prompt_tokens": 100, "context_tokens": 4096, "usage_source": "estimated"},
        },
    ).json()
    assistant = next(
        m
        for m in ai_client.get(f"/conversations/{created['id']}").json()["messages"]
        if m["role"] == "assistant"
    )
    assert assistant["stats"]["context_tokens"] == 4096
    assert assistant["stats"]["usage_source"] == "estimated"
