"""A plan for an open-ended request, worked through a step at a time (§35K).

Reported directly: *"I will say fix my categories and it will only merge two
categories and leave it at that, ignoring the rest."*

That is §21's finding again, from outside a skill: a model given one broad
instruction does the first part and reports success. The skill runner already
solves it: each step is its own bounded turn, so "the model did step 2" is
something the app *knows* rather than hopes for, but only for jobs somebody
had saved as a skill. An open-ended request got one turn and a model's good
intentions.

`make_plan` closes that, and like `run_skill` before it, it is deliberately
built out of mechanisms that already exist rather than a third one:

- **`ends_turn`**, built for `ask_user`. The model plans, its turn stops, and
  the runner takes over. Not nesting an agent loop inside an agent loop is both
  the simpler code and the honest thing to show: the run *is* the rest of the
  work, not a tool result to reason about.
- **the step runner**, built for skills. A plan is a skill nobody saved, so it
  gets the plan card, the ticked steps, the change list and an Undo on each,
  with no second implementation to keep in step.

The property most of these tests are about: **a plan run is indistinguishable
from a skill run**, because it is the same code reached by the client sending
the steps back down `/chat/stream`.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import skills, tools


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


# --- what counts as a plan --------------------------------------------------


def test_a_plan_needs_a_goal_and_steps():
    event = tools.validate_make_plan(
        {"goal": "Fix my categories", "steps": ["List them", "Merge duplicates"]}
    )
    assert event["type"] == "run_plan"
    assert event["goal"] == "Fix my categories"
    assert event["steps"] == ["List them", "Merge duplicates"]


def test_one_step_is_not_a_plan():
    """Planning a single action costs a whole model round to say what the model
    could have done in that round."""
    with pytest.raises(tools.ToolError, match="just call the tool"):
        tools.validate_make_plan({"goal": "Tag note 4", "steps": ["Tag note 4"]})


def test_too_many_steps_is_refused_rather_than_truncated():
    """Silently keeping the first six would drop the end of the job, which is
    precisely the failure this tool exists to prevent, arriving from the other
    direction."""
    with pytest.raises(tools.ToolError, match="at most"):
        tools.validate_make_plan(
            {"goal": "Do everything", "steps": [f"step {n}" for n in range(9)]}
        )


def test_the_models_own_numbering_is_stripped():
    """It has just been asked for an ordered list, so "1." on the front is a
    natural thing for it to write, and the card numbers the steps itself."""
    event = tools.validate_make_plan(
        {"goal": "Tidy up", "steps": ["1. Find untagged notes", "2) Tag them", "- Report"]}
    )
    assert event["steps"] == ["Find untagged notes", "Tag them", "Report"]


def test_steps_sent_as_one_string_are_recovered():
    """Same recovery as `validate_ask` makes for options sent as "yes, no": a
    quoting mistake should not cost a round."""
    event = tools.validate_make_plan(
        {"goal": "Tidy up", "steps": "Find untagged notes\nTag them\nReport back"}
    )
    assert len(event["steps"]) == 3


def test_steps_sent_as_objects_are_recovered():
    event = tools.validate_make_plan(
        {"goal": "Tidy up", "steps": [{"step": "Find them"}, {"text": "Tag them"}]}
    )
    assert event["steps"] == ["Find them", "Tag them"]


def test_a_repeated_step_is_dropped():
    """Padding to reach a count it imagined. A repeated step runs the same turn
    twice, on a machine where every turn is seconds of generation."""
    event = tools.validate_make_plan(
        {"goal": "Tidy", "steps": ["Find them", "find them", "Tag them"]}
    )
    assert event["steps"] == ["Find them", "Tag them"]


def test_the_label_says_what_is_about_to_happen():
    event = tools.validate_make_plan(
        {"goal": "Fix my categories", "steps": ["List", "Merge"]}
    )
    assert "2 steps" in event["label"]
    assert "Fix my categories" in event["label"]


# --- it cannot be run like an ordinary tool ---------------------------------


def test_the_tool_ends_the_turn():
    assert tools.TOOLS["make_plan"].ends_turn is True


def test_running_it_directly_fails_loudly(session, app_state):
    """Returning a plausible result here would hand the model a JSON list of
    steps, which it would summarise in the past tense, a job reported as done
    that nothing ever started (§35B by another route)."""
    with pytest.raises(tools.ToolError, match="cannot"):
        tools.TOOLS["make_plan"].handler(session, {"goal": "x", "steps": ["a", "b"]})


def test_the_confirm_endpoint_will_not_run_it(ai_client):
    response = ai_client.post(
        "/chat/tools/execute",
        json={"name": "make_plan", "arguments": {"goal": "x", "steps": ["a", "b"]}},
    )
    assert response.status_code >= 400


# --- end to end through the agent loop --------------------------------------


def test_the_agent_ends_its_turn_with_a_run_plan_event(ai_client, fake_ollama, app_state):
    """The whole point in one assertion: the model plans, the turn stops there,
    and the client is handed the steps to start."""
    fake_ollama.tool_script = [
        [
            {
                "name": "make_plan",
                "arguments": {
                    "goal": "Fix my categories",
                    "steps": ["List the categories", "Merge the duplicates"],
                },
            }
        ]
    ]
    events = _events(ai_client, "fix my categories", use_tools=True)
    handover = [e for e in events if e["type"] == "run_plan"]
    assert len(handover) == 1
    assert handover[0]["steps"] == ["List the categories", "Merge the duplicates"]


def test_nothing_after_the_handover_runs(ai_client, fake_ollama, app_state):
    """`ends_turn` means the run replaces the rest of the turn. A stray write
    beside it would be work outside the plan the user is watching."""
    fake_ollama.tool_script = [
        [
            {
                "name": "make_plan",
                "arguments": {"goal": "Tidy", "steps": ["Find them", "Tag them"]},
            },
            {"name": "create_note", "arguments": {"content": "should never exist"}},
        ]
    ]
    events = _events(ai_client, "tidy my notebook up", use_tools=True)
    assert any(e["type"] == "run_plan" for e in events)
    assert ai_client.get("/entries").json() == []


def test_a_malformed_plan_is_recoverable_within_the_turn(ai_client, fake_ollama, app_state):
    """A one-step plan is a mistake the model can fix in the same turn, so the
    loop hands back the reason instead of ending on a tool meant to end it."""
    fake_ollama.tool_script = [
        [{"name": "make_plan", "arguments": {"goal": "Tag note 1", "steps": ["Tag it"]}}]
    ]
    events = _events(ai_client, "tag that note", use_tools=True)
    assert not any(e["type"] == "run_plan" for e in events)
    failed = [e for e in events if e["type"] == "tool" and not e.get("ok")]
    assert failed and "steps" in failed[0]["error"]
    assert any(e["type"] == "answer" for e in events)


# --- running the plan the model made ----------------------------------------


def test_a_plan_run_ticks_off_its_steps(ai_client, fake_ollama, app_state):
    """Indistinguishable from a skill run, because it is the same runner: a
    plan card, then a step at a time, each one its own turn."""
    events = _events(
        ai_client,
        "ph:compass Fix my categories",
        plan={"goal": "Fix my categories", "steps": ["List them", "Merge duplicates"]},
        use_tools=True,
    )
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["kind"] == "plan"
    assert plan["steps"] == ["List them", "Merge duplicates"]
    states = {e["index"]: e["state"] for e in events if e["type"] == "step"}
    assert states == {0: "done", 1: "done"}


def test_each_step_is_its_own_turn(ai_client, fake_ollama, app_state):
    """The mechanism, stated as a measurement: two steps means two calls to the
    model, not one call carrying a numbered list it is free to ignore."""
    _events(
        ai_client,
        "ph:compass Tidy up",
        plan={"goal": "Tidy up", "steps": ["Find them", "Tag them", "Report"]},
        use_tools=True,
    )
    assert len(fake_ollama.tool_rounds) == 3


def test_a_step_is_told_which_step_it_is(ai_client, fake_ollama, app_state):
    """And told it is *its own plan*, not a saved skill. Told it is "running
    the skill 'Tidy up'", a small model looks for a skill by that name and
    reports that there isn't one."""
    _events(
        ai_client,
        "ph:compass Tidy up",
        plan={"goal": "Tidy up", "steps": ["Find them", "Tag them"]},
        use_tools=True,
    )
    first = fake_ollama.tool_rounds[0][-1]["content"]
    assert "step 1 of 2" in first
    assert "plan you made" in first
    assert "saved skill" not in first


def test_a_plan_run_cannot_start_another_run(ai_client, fake_ollama, app_state):
    """Each run brings its own fresh rounds, so nesting them means the bound on
    a turn stops meaning anything, and the plan on screen stops describing
    what is happening."""
    fake_ollama.tool_script = [
        [
            {
                "name": "make_plan",
                "arguments": {"goal": "Deeper", "steps": ["More", "Even more"]},
            }
        ]
    ]
    events = _events(
        ai_client,
        "ph:compass Tidy up",
        plan={"goal": "Tidy up", "steps": ["Find them", "Tag them"]},
        use_tools=True,
    )
    assert not any(e["type"] == "run_plan" for e in events)
    refused = [e for e in events if e["type"] == "tool" and not e.get("ok")]
    assert refused and "inside a run" in refused[0]["error"]


def test_a_skill_may_not_declare_the_planning_tool(app_state):
    """The same rule at save time that `RUN_STARTERS` enforces at execution: 
    an allowlist holding it would let a run start a run."""
    with pytest.raises(skills.SkillError, match="never have to stop"):
        skills.normalise(
            {"name": "Loop", "prompt": "Plan forever.", "tools": ["make_plan"]},
            set(tools.TOOLS),
        )


# --- what arrives over HTTP is not trusted ----------------------------------


def test_a_hand_made_plan_is_validated_too(ai_client, app_state):
    """The client echoes back what the server produced, but nothing makes that
    true of a request somebody wrote by hand, and the run it starts writes."""
    response = ai_client.post(
        "/chat/stream",
        json={"question": "go", "plan": {"goal": "x", "steps": ["only one"]}},
    )
    assert response.status_code == 422


def test_a_plan_longer_than_the_cap_is_refused_over_http(ai_client, app_state):
    response = ai_client.post(
        "/chat/stream",
        json={
            "question": "go",
            "plan": {"goal": "x", "steps": [f"step {n}" for n in range(9)]},
        },
    )
    assert response.status_code == 422
