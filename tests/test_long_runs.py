"""Long jobs: earning rounds, stalling honestly, and resuming where it stopped.

Reported directly, and it is two failures in one sentence: *"the agent
struggles with long tasks like skills then cuts out half way through and has
to restart, or it hits a limit for tool calls which has happened quite a
bit."*

Both halves were real, and neither was a model problem.

1. **The round cap counted the wrong thing.** `MAX_ROUNDS` was a flat six for a
   turn and a flat four for a skill step, so "tag these eight notes", one
   search, a read and eight writes, ran out with the work half done. A cap
   that stops a runaway has to distinguish a model doing eight useful things
   from a model doing the same thing eight times, and counting rounds does not.
   Rounds are now *earned*: a round that made a successful call it had not
   already made buys another one, to a ceiling. A loop earns nothing and stops
   exactly where it always did.

2. **A step that ran out was ticked off as done.** The runner could only see
   that the step's turn produced text, and "I ran out of rounds" is text: so a
   step cut off mid-job was marked ✓ and the next step ran on top of
   half-finished work. The `limit` event is what separates the two, and a
   stalled step now stops the run and says where it stopped, so the user can
   resume from that step instead of re-running the ones that already wrote to
   their notebook.

The tests below are in that order: what earns a round, what does not, and what
the run does when it stops anyway.
"""

from __future__ import annotations

import json

from memorymap.ai import agent, skill_runner, skills
from memorymap.core import deps


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _save(skill: dict) -> None:
    config = deps.get_config()
    config.set_preference("skills", [*skills.stored(config), skill])


def _note(client, text: str) -> int:
    return client.post("/entries", json={"content": text}).json()["id"]


# --- rounds are earned, not granted -----------------------------------------


def test_a_turn_doing_new_work_runs_past_the_flat_cap(ai_client, fake_ollama):
    """The reported failure, in one test: more distinct successful calls than
    MAX_ROUNDS allows, and the turn is not cut off part-way."""
    ids = [_note(ai_client, f"note number {n}") for n in range(agent.MAX_ROUNDS + 3)]
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note_id, "tags": ["filed"]}}]
        for note_id in ids
    ]
    events = _events(ai_client, "tag every one of my notes", use_tools=True)
    tagged = [e for e in events if e["type"] == "tool" and e.get("ok")]
    assert len(tagged) == len(ids) > agent.MAX_ROUNDS
    # And it ended by answering rather than by running out.
    assert not any(e["type"] == "limit" for e in events)


def test_repeating_the_same_call_earns_nothing(ai_client, fake_ollama):
    """The other side of the same rule, and the reason the ceiling is safe: a
    model calling one thing over and over is the runaway the cap is for, and no
    length of script gets it near the ceiling.

    Exactly one round is earned, and it should be: the *first* of those calls
    was new work. Every one after it is the same call with the same arguments,
    whose result the model already has in front of it."""
    note_id = _note(ai_client, "a note to read again and again")
    fake_ollama.tool_script = [
        [{"name": "get_note", "arguments": {"note_id": note_id}}]
        for _ in range(agent.MAX_ROUNDS + agent.EARNED_ROUNDS + 5)
    ]
    events = _events(ai_client, "look at that note", use_tools=True)
    calls = [e for e in events if e["type"] == "tool"]
    assert len(calls) == agent.MAX_ROUNDS + 1
    assert any(e["type"] == "limit" for e in events)


def test_a_failing_call_earns_nothing(ai_client, fake_ollama):
    """A round that errored did not get anywhere, whatever the arguments. Each
    of these is a *different* call, so only the success rule keeps it bounded."""
    fake_ollama.tool_script = [
        [{"name": "get_note", "arguments": {"note_id": 9000 + n}}]
        for n in range(agent.MAX_ROUNDS + agent.EARNED_ROUNDS + 5)
    ]
    events = _events(ai_client, "read those notes", use_tools=True)
    calls = [e for e in events if e["type"] == "tool"]
    assert len(calls) == agent.MAX_ROUNDS
    assert all(not e.get("ok") for e in calls)


def test_the_ceiling_still_holds(ai_client, fake_ollama):
    """Earned rounds are bounded too, a notebook is not a licence to loop for
    as long as there are notes in it."""
    ids = [
        _note(ai_client, f"note {n}")
        for n in range(agent.MAX_ROUNDS + agent.EARNED_ROUNDS + 4)
    ]
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note_id, "tags": ["x"]}}]
        for note_id in ids
    ]
    events = _events(ai_client, "tag all of them", use_tools=True)
    calls = [e for e in events if e["type"] == "tool"]
    assert len(calls) == agent.MAX_ROUNDS + agent.EARNED_ROUNDS
    assert any(e["type"] == "limit" for e in events)


# --- what running out looks like --------------------------------------------


def test_running_out_says_so_as_its_own_event(ai_client, fake_ollama):
    """The `limit` event is what lets the UI offer Continue instead of a
    paragraph asking the user to type "carry on", and what lets the skill
    runner tell a stalled step from a finished one. It carries what was
    written, because "it stopped" and "it stopped having changed six notes"
    need different words."""
    note_id = _note(ai_client, "a note")
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note_id, "tags": [f"t{n}"]}}]
        for n in range(agent.MAX_ROUNDS + agent.EARNED_ROUNDS + 2)
    ]
    events = _events(ai_client, "keep tagging that note", use_tools=True)
    limits = [e for e in events if e["type"] == "limit"]
    assert len(limits) == 1
    assert limits[0]["reason"] == "rounds"
    assert limits[0]["rounds"] == agent.MAX_ROUNDS + agent.EARNED_ROUNDS
    assert "tag_note" in limits[0]["wrote"]
    # The answer after it is a stopping notice, and it offers to carry on.
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "Continue" in answer


def test_a_turn_that_finishes_normally_emits_no_limit(ai_client, fake_ollama):
    fake_ollama.tool_script = [[{"name": "count_notes", "arguments": {}}]]
    events = _events(ai_client, "how many notes do I have", use_tools=True)
    assert not any(e["type"] == "limit" for e in events)


# --- a skill step that stalls -----------------------------------------------


def _stalling_skill() -> None:
    _save(
        {
            "name": "Big tidy",
            "prompt": "Tidy the whole notebook.",
            "steps": ["Tag everything", "Link what belongs together", "Report back"],
            "tools": ["search_notes", "tag_note", "link_notes"],
        }
    )


def test_a_stalled_step_is_not_ticked_off(ai_client, fake_ollama):
    """The bug that made the other one invisible. The step's turn ends with
    "I couldn't finish step 1", which is text, which used to be enough to
    count as an answer, which marked it done."""
    _stalling_skill()
    note_id = _note(ai_client, "something to tag")
    rounds = skill_runner.STEP_ROUNDS + skill_runner.STEP_EARNED_ROUNDS + 2
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note_id, "tags": [f"t{n}"]}}]
        for n in range(rounds)
    ]
    events = _events(ai_client, "ph:lightning Big tidy", skill="Big tidy", use_tools=True)
    states = {e["index"]: e["state"] for e in events if e["type"] == "step"}
    assert states[0] == "stalled"
    assert 1 not in states  # and the run stopped rather than carrying on


def test_the_result_says_which_step_it_stopped_on(ai_client, fake_ollama):
    """`stopped_at` is what Resume is built on. Without it the only way to
    continue a six-step run that died at step four is to run all six again,
    and four of them write to the notebook."""
    _stalling_skill()
    note_id = _note(ai_client, "something to tag")
    rounds = skill_runner.STEP_ROUNDS + skill_runner.STEP_EARNED_ROUNDS + 2
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note_id, "tags": [f"t{n}"]}}]
        for n in range(rounds)
    ]
    events = _events(ai_client, "ph:lightning Big tidy", skill="Big tidy", use_tools=True)
    result = next(e for e in events if e["type"] == "result")
    assert result["stopped_at"] == 0
    assert result["steps"] == 3


def test_a_run_that_finishes_stopped_at_nothing(ai_client, fake_ollama):
    _stalling_skill()
    # No script: every step's turn answers in words on its first round.
    events = _events(ai_client, "ph:lightning Big tidy", skill="Big tidy", use_tools=True)
    result = next(e for e in events if e["type"] == "result")
    assert result["stopped_at"] is None
    states = {e["index"]: e["state"] for e in events if e["type"] == "step"}
    assert states == {0: "done", 1: "done", 2: "done"}


# --- resuming ---------------------------------------------------------------


def test_resuming_does_not_re_run_the_earlier_steps(ai_client, fake_ollama):
    """The point of the whole exercise: the steps that already ran are marked
    as done earlier and are not repeated. They are still *shown*, because a
    plan with the first two steps missing is not the plan the user watched."""
    _stalling_skill()
    events = _events(
        ai_client, "ph:lightning Big tidy", skill="Big tidy", skill_from_step=2, use_tools=True
    )
    states = {e["index"]: e["state"] for e in events if e["type"] == "step"}
    assert states[0] == "earlier"
    assert states[1] == "earlier"
    assert states[2] == "done"
    # The steps that were skipped cost no model round at all.
    asked = [m for m in fake_ollama.tool_rounds]
    assert len(asked) == 1


def test_the_plan_says_where_a_resumed_run_starts(ai_client, fake_ollama):
    _stalling_skill()
    events = _events(
        ai_client, "ph:lightning Big tidy", skill="Big tidy", skill_from_step=1, use_tools=True
    )
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["start_at"] == 1
    assert plan["steps"] == ["Tag everything", "Link what belongs together", "Report back"]


def test_an_out_of_range_resume_point_runs_nothing_rather_than_raising(
    ai_client, fake_ollama
):
    """A hand-made request, or a stale button on a conversation reopened after
    the skill was edited. Clamped, because the alternative is a 500 on a
    request that means something perfectly sensible."""
    _stalling_skill()
    events = _events(
        ai_client, "ph:lightning Big tidy", skill="Big tidy", skill_from_step=9, use_tools=True
    )
    states = {e["index"]: e["state"] for e in events if e["type"] == "step"}
    assert set(states.values()) == {"earlier"}
    result = next(e for e in events if e["type"] == "result")
    assert result["stopped_at"] is None
