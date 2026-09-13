"""Plan → execute → verify, with a visible plan (PLAN.md §4, item A2).

PLAN.md's acceptance for A2 is one line: *"tests/test_agent_plan.py with the
fake transport: a 3-step ask produces 3 ticks."* This is that file, and it
covers the whole clause the line is the acceptance for, *"the agent posts a
checklist, ticks steps as tools return, and re-plans on a failed step (max
2)"*:

- the checklist is posted **before** anything runs (the `plan` event), which
  is what makes it a plan rather than a report;
- a step ticks only after its own turn is over, and a turn that called a tool
  is ticked after that tool's event, not before it;
- a step that **failed** is rewritten and run again rather than ending the
  run, at most twice, `skill_runner.MAX_REPLANS`.

Everything here runs against the fake transport, which is the standing caveat
in CLAUDE.md: it proves the machinery is wired and says nothing about whether
a real 4B model responds to a rewritten step.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import skill_runner, skills
from memorymap.core import deps


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _save(skill: dict) -> None:
    config = deps.get_config()
    config.set_preference("skills", [*skills.stored(config), skill])


def _one_call_then_prose(fake, tool="list_tags"):
    """Make every step take exactly two rounds: a tool call, then an answer.

    The `tool_script` queue cannot express this on its own, it is drained
    across the whole run, so three scripted calls all land inside step one.
    Wrapping `chat_tools` is how the existing contract tests steer a run
    per-round, and this is the same lever.
    """
    original = fake.chat_tools
    state = {"round": 0}

    def scripted(model, messages, tools, mode=None):
        state["round"] += 1
        if state["round"] % 2 == 1:
            fake.tool_script = [[{"name": tool, "arguments": {}}]]
        return original(model, messages, tools, mode)

    fake.chat_tools = scripted


# --- the checklist -----------------------------------------------------------


def test_a_three_step_ask_produces_three_ticks(ai_client, fake_ollama, app_state):
    """PLAN.md §4 A2's acceptance criterion, verbatim."""
    _one_call_then_prose(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={
            "goal": "Tidy my notebook",
            "steps": ["List my tags", "Find the untagged notes", "Report what you found"],
        },
        use_tools=True,
    )
    ticks = [e for e in events if e["type"] == "step" and e["state"] == "done"]
    assert [e["index"] for e in ticks] == [0, 1, 2]


def test_the_checklist_is_posted_before_any_step_runs(ai_client, fake_ollama, app_state):
    """A plan drawn after the work is a report. The `plan` event is what the
    chat's plan card is built from, and it arrives first."""
    _one_call_then_prose(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["One", "Two", "Three"]},
        use_tools=True,
    )
    kinds = [e["type"] for e in events]
    assert "plan" in kinds
    plan = events[kinds.index("plan")]
    assert plan["steps"] == ["One", "Two", "Three"]
    assert kinds.index("plan") < min(i for i, k in enumerate(kinds) if k == "step")


def test_a_step_is_ticked_after_its_tool_returns_not_before(ai_client, fake_ollama, app_state):
    """"Ticks steps as tools return" is an ordering claim, so it is measured
    as one: within a step, the tool event comes before the tick."""
    _one_call_then_prose(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["List my tags", "Report"]},
        use_tools=True,
    )
    order = [
        e["type"] if e["type"] != "step" else f"step:{e['index']}:{e['state']}"
        for e in events
        if e["type"] in ("tool", "step")
    ]
    assert order.index("tool") < order.index("step:0:done")


# --- re-planning a failed step ------------------------------------------------


#: A model that answers with nothing at all and calls nothing. That is the
#: single most common way a small model ends a step (see `skill_runner`'s own
#: "the model didn't respond" branch), so it is what these drive the failure
#: with: and it makes the re-plan deterministic, because the same empty reply
#: comes back from the rewrite call and the fallback rewrite is used.
def _says_nothing(fake) -> None:
    fake.librarian_reply = ""
    fake.tool_script = []


def test_a_failed_step_is_replanned_rather_than_ending_the_run(
    ai_client, fake_ollama, app_state
):
    _says_nothing(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["List my tags", "Report"]},
        use_tools=True,
    )
    steps = [e for e in events if e["type"] == "step" and e["index"] == 0]
    states = [e["state"] for e in steps]
    assert "replanned" in states, "the run ended at the first bad step"
    # …and it was actually run again, rather than only announced.
    assert states.count("running") > 1


def test_the_rewritten_step_is_a_smaller_instruction_not_the_same_words(
    ai_client, fake_ollama, app_state
):
    _says_nothing(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["List my tags", "Report"]},
        use_tools=True,
    )
    replanned = [e for e in events if e["type"] == "step" and e["state"] == "replanned"]
    assert replanned
    assert replanned[0]["text"] != "List my tags"
    #: The fallback rewrite, which is what a model that cannot supply one
    #: gets. It is still a rewrite, it names what to do, rather than the
    #: same sentence sent twice.
    assert "Do one thing only." in replanned[0]["text"]
    assert replanned[0]["reason"], "a re-plan says what it is recovering from"


def test_replanning_stops_after_two_attempts(ai_client, fake_ollama, app_state):
    """Unbounded, this is a model rewriting its own instructions for ever over
    a notebook it cannot act on."""
    _says_nothing(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["List my tags", "Report"]},
        use_tools=True,
    )
    replanned = [e for e in events if e["type"] == "step" and e["state"] == "replanned"]
    assert len(replanned) == skill_runner.MAX_REPLANS == 2
    assert [e["attempt"] for e in replanned] == [1, 2]
    # The run still ends where it stopped, so Resume still has an index.
    result = next(e for e in events if e["type"] == "result")
    assert result["stopped_at"] == 0


def test_a_replanned_run_never_ticks_a_step_it_did_not_finish(
    ai_client, fake_ollama, app_state
):
    """The property the whole reform exists to protect: re-planning must not
    become a way for a step to end up green without having been done."""
    _says_nothing(fake_ollama)
    events = _events(
        ai_client,
        "ph:compass Tidy my notebook",
        plan={"goal": "Tidy my notebook", "steps": ["List my tags", "Report"]},
        use_tools=True,
    )
    assert not [e for e in events if e["type"] == "step" and e["state"] == "done"]


def test_a_step_cut_off_mid_job_is_not_replanned(ai_client, fake_ollama, app_state):
    """**The sharpest line in the mechanism, and it was drawn by a failing
    test** (`tests/test_long_runs.py`, which this must not be allowed to
    break).

    A step that ran out of rounds is unlike every other ending here: it was
    *doing the job* and got cut off, so work has happened and more is left.
    Rewrite it and run it again and the model, with none of the rounds'
    context about what it already tagged, answers in prose, and the step goes
    green over a job that is still half finished. That is the exact bug the
    runner exists to prevent, arriving through its own recovery. A cut-off
    step keeps the honest ending it already had: stop, and let Resume carry on
    against the notebook as it now stands.
    """
    _save(
        {
            "name": "Big tidy",
            "prompt": "Tidy the whole notebook.",
            "steps": ["Tag everything", "Report back"],
            "tools": ["search_notes", "tag_note"],
        }
    )
    note = ai_client.post("/entries", json={"content": "something to tag"}).json()
    rounds = skill_runner.STEP_ROUNDS + skill_runner.STEP_EARNED_ROUNDS + 2
    fake_ollama.tool_script = [
        [{"name": "tag_note", "arguments": {"note_id": note["id"], "tags": [f"t{n}"]}}]
        for n in range(rounds)
    ]
    events = _events(ai_client, "ph:lightning Big tidy", skill="Big tidy", use_tools=True)
    states = [e["state"] for e in events if e["type"] == "step" and e["index"] == 0]
    assert states[-1] == "stalled"
    assert "replanned" not in states
    assert "done" not in states
    assert next(e for e in events if e["type"] == "result")["stopped_at"] == 0


def test_the_model_supplies_the_rewrite_when_it_can(ai_client, fake_ollama, app_state):
    """The re-plan asks the model for one short instruction, and uses it."""
    _save(
        {
            "name": "Tag audit",
            "prompt": "Check my tags.",
            "steps": [{"text": "Look at my tags.", "expects": "tool_called", "tools": ["list_tags"]}],
            "tools": ["list_tags"],
        }
    )
    #: Prose and nothing else, enough to satisfy "the model said something",
    #: so the step ends `stalled` on its unmet contract rather than on an
    #: empty turn, and the same reply comes back as the rewrite.
    fake_ollama.librarian_reply = "Call list_tags exactly once and stop."
    events = _events(ai_client, "run", skill="Tag audit")
    replanned = [e for e in events if e["type"] == "step" and e["state"] == "replanned"]
    assert replanned
    assert replanned[0]["text"] == "Call list_tags exactly once and stop."


# --- the recovery itself, in isolation ----------------------------------------


class _Models:
    def utility_model(self) -> str:
        return "fake-model"


class _Reply:
    def __init__(self, content: str, running: bool = True) -> None:
        self.content = content
        self.running = running

    def is_running(self) -> bool:
        return self.running

    def chat(self, model, messages, mode=None) -> dict:
        return {"content": self.content}


SPEC = {"expects": "tool_called", "tools": ["list_tags"], "retries": 2}


def test_an_unreachable_model_still_yields_a_rewrite():
    """A run whose recovery cannot reach the model must not stop *because* of
    that: the mechanical rewrite is still an improvement on the same words."""
    text = skill_runner._replan_step(
        _Models(), _Reply("", running=False), {"prompt": "job"}, {}, "Do the thing", SPEC, "why"
    )
    assert text == "Do the thing. Call list_tags exactly once."


@pytest.mark.parametrize("reply", ["", "   ", "x" * (skills.MAX_STEP + 1)])
def test_an_unusable_reply_falls_back(reply):
    """Empty, whitespace, or a wall of prose, none of them is a step, and a
    "rewrite" that is a paragraph is the failure this file exists to stop."""
    text = skill_runner._replan_step(
        _Models(), _Reply(reply), {"prompt": "job"}, {}, "Do the thing", SPEC, "why"
    )
    assert text == "Do the thing. Call list_tags exactly once."


def test_a_transport_error_is_not_allowed_to_end_the_run():
    class Boom(_Reply):
        def chat(self, model, messages, mode=None):
            raise RuntimeError("socket closed")

    text = skill_runner._replan_step(
        _Models(), Boom(""), {"prompt": "job"}, {}, "Do the thing", SPEC, "why"
    )
    assert text.startswith("Do the thing.")


def test_a_step_with_no_named_tool_still_gets_a_narrower_instruction():
    text = skill_runner._replan_step(
        _Models(), _Reply("", running=False), {"prompt": "job"}, {}, "Do the thing", {}, "why"
    )
    assert text == "Do the thing. Do one thing only."
