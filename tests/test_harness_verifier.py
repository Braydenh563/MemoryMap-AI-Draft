"""The skill harness: paging inside a step, the run budget, the verifier and
the filing corrections (SESSION_BRIEFS Brief 13, CHAT_PLAN decision 10).

`tests/test_harness_verifier_spec.py` is the executable spec; this is the
behaviour around it, in the shape the rest of the suite uses (a fake model
driving the real `/chat/stream` route, so what is tested is the thing the app
runs rather than a rehearsal of it).

**What these cannot prove**, and the standing caveat in CLAUDE.md is why:
every provider here talks to a fake transport. That a *real* small model,
handed the paging nudge with an offset in it, then calls the tool again is not
verified anywhere and is not claimed. What is verified is the mechanism: that
the app knows a page is outstanding, that it re-prompts instead of ticking the
step off, that it stops at the cap and says so, and that the run is charged
for what it spent.
"""

from __future__ import annotations

import json
import time

from memorymap.ai import budget, skill_runner, skills, tools
from memorymap.core import deps
from memorymap.entry import manager


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _save(skill: dict) -> None:
    config = deps.get_config()
    config.set_preference("skills", [*skills.stored(config), skill])


def _seed(session, count: int) -> None:
    for index in range(count):
        manager.create_entry(session, f"note {index}: chase up the invoice", "Work", [])


PAGING_SKILL = {
    "name": "Read them all",
    "prompt": "Go through every note.",
    "steps": [
        {
            "text": "Page through every note with list_notes.",
            "expects": "tool_called",
            "tools": ["list_notes"],
        }
    ],
    "tools": ["list_notes", "count_notes"],
}


def _page_script(pages: int, size: int = 20) -> list[list[dict]]:
    """A model that fetches one page per turn and then stops talking.

    Exactly the behaviour decision 10 is about: the small model does the first
    page, narrates, and considers the step done. Each pair here is one agent
    turn (a round with a call, then a round with none, which is the final
    answer).
    """
    script: list[list[dict]] = []
    for page in range(pages):
        script.append(
            [{"name": "list_notes", "arguments": {"offset": page * size, "limit": size}}]
        )
        script.append([])
    return script


# --- paging inside a step ----------------------------------------------------


def test_a_step_is_not_done_while_its_read_has_more_pages(
    ai_client, fake_ollama, app_state, session
):
    """The reported shape, one level up from the contract: the tool *was*
    called, so the old contract passed, and the step had seen a fifth of the
    notebook."""
    _seed(session, 70)
    _save(PAGING_SKILL)
    fake_ollama.tool_script = _page_script(4)
    events = _events(ai_client, "run", skill="Read them all")
    steps = [e for e in events if e["type"] == "step"]

    assert [s["state"] for s in steps] == ["running", "paging", "paging", "paging", "done"]
    # Four pages of twenty over seventy notes: the fourth comes back with ten
    # and `has_more` false, which is what ends the step.
    assert [s["page"] for s in steps if s["state"] == "paging"] == [2, 3, 4]
    result = next(e for e in events if e["type"] == "result")
    assert len(result["state"]["seen_ids"]) == 70
    assert result["truncated"] is False


def test_the_paging_nudge_carries_the_next_offset(ai_client, fake_ollama, app_state, session):
    """A small model acts on a call it can copy, not on the idea of one."""
    _seed(session, 70)
    _save(PAGING_SKILL)
    fake_ollama.tool_script = _page_script(4)
    _events(ai_client, "run", skill="Read them all")
    sent = [
        str(message.get("content", ""))
        for round_messages in fake_ollama.tool_rounds
        for message in round_messages
        if message.get("role") == "user"
    ]
    # Deduplicated: the user message stays in `messages` for every round of
    # the turn it opened, so each nudge is seen once per round, not once.
    nudges = list(dict.fromkeys(t for t in sent if "You have not seen all of them yet" in t))
    assert len(nudges) == 3
    assert "offset=20" in nudges[0]
    assert "offset=60" in nudges[2]


def test_a_step_that_runs_out_of_pages_says_so_rather_than_claiming_the_lot(
    ai_client, fake_ollama, app_state, session, monkeypatch
):
    """The cap has to be loud. A silent stop is the same lie as the silent
    tick this whole mechanism replaced."""
    monkeypatch.setattr(skill_runner, "MAX_PAGES_PER_STEP", 2)
    _seed(session, 70)
    _save(PAGING_SKILL)
    fake_ollama.tool_script = _page_script(4)
    events = _events(ai_client, "run", skill="Read them all")
    done = next(e for e in events if e["type"] == "step" and e["state"] == "done")
    assert done["truncated"] is True
    assert "with more left to read" in done["reason"]
    assert next(e for e in events if e["type"] == "result")["truncated"] is True


def test_a_step_that_names_no_tool_is_never_held_open_by_paging(
    ai_client, fake_ollama, app_state, session
):
    """A step with no contract has always advanced unchecked, and a skill
    saved before any of this existed must keep working exactly as it did."""
    _seed(session, 70)
    _save({"name": "Loose", "prompt": "Look around.", "steps": ["Have a look."],
           "tools": ["list_notes"]})
    fake_ollama.tool_script = _page_script(1)
    events = _events(ai_client, "run", skill="Loose")
    assert [e["state"] for e in events if e["type"] == "step"] == ["running", "done"]


def test_the_state_line_says_how_many_notes_a_run_has_read():
    """Twelve ids is not an answer to "have I seen them all"; a count is."""
    line = skills.state_line({"note_ids": [1, 2], "seen_ids": list(range(70))})
    assert "notes read so far: 70" in line
    assert skills.state_line({"note_ids": [1], "seen_ids": [1]}).count("read so far") == 0


# --- the budget --------------------------------------------------------------


def test_a_budget_charges_what_the_provider_reports():
    spend = budget.RunBudget(tokens=1000, seconds=999)
    spend.charge({"prompt_tokens": 300, "output_tokens": 100})
    assert spend.spent_tokens == 400
    assert spend.exceeded() == ""
    spend.charge({"prompt_tokens": 500, "output_tokens": 200})
    assert "1,000 tokens" in spend.exceeded()


def test_a_round_with_no_reported_tokens_still_costs_something():
    """A transport that reports nothing must not make the budget a no-op."""
    spend = budget.RunBudget(tokens=1000, seconds=999)
    for _ in range(3):
        spend.charge(None)
    assert spend.spent_tokens == 3 * budget.ASSUMED_ROUND_TOKENS
    assert "tokens" in spend.exceeded()


def test_a_time_budget_stops_a_run_that_is_not_spending_tokens():
    """Wall time, not tokens: a run whose rounds are cheap and slow (a large
    model on modest hardware) is the case this half exists for. The clock is
    wound back rather than slept through, so the test costs nothing."""
    spend = budget.RunBudget(tokens=0, seconds=5, started_at=time.monotonic() - 9)
    spend.charge({"prompt_tokens": 1})
    assert "time budget" in spend.exceeded()


def test_the_reason_a_run_stopped_survives_later_checks():
    """`stopped` is read several turns after it is set; it must not un-set."""
    spend = budget.RunBudget(tokens=10, seconds=999)
    spend.charge({"prompt_tokens": 20})
    first = spend.exceeded()
    spend.tokens = 10_000
    assert spend.exceeded() == first


def test_a_budget_scope_does_not_nest(app_state):
    outer = budget.RunBudget()
    inner = budget.RunBudget()
    with budget.spending(outer):
        with budget.spending(inner):
            assert budget.current() is outer
    assert budget.current() is None


def test_the_budget_comes_from_settings(app_state):
    config = deps.get_config()
    config.set_preference("run_budget_tokens", 1234)
    config.set_preference("run_budget_seconds", 12)
    spend = budget.from_settings(config)
    assert (spend.tokens, spend.seconds) == (1234, 12.0)


def test_nonsense_in_the_settings_falls_back_rather_than_failing_the_run(app_state):
    config = deps.get_config()
    config.set_preference("run_budget_tokens", "lots")
    assert budget.from_settings(config).tokens == budget.DEFAULT_TOKENS


# --- the verifier ------------------------------------------------------------


def test_every_predicate_in_the_vocabulary_has_an_evaluator():
    """The `core/events.py` driver trick in miniature.

    A predicate name added to `skills.VERIFY_PREDICATES` without a function to
    evaluate it would be accepted at save time, stored, and then pass silently
    on every run that used it, which is the worst of the three possible
    outcomes. The enumeration is what makes forgetting fail the build instead.
    """
    assert set(skills.VERIFY_PREDICATES) == set(skill_runner.PREDICATES)


COUNTING_SKILL = {
    "name": "Count them",
    "prompt": "Count my notes.",
    "steps": [
        {"text": "Count my notes.", "expects": "tool_called", "tools": ["count_notes"]}
    ],
    "tools": ["count_notes"],
    "verify": {"tool": "count_notes", "expect": {"min": 3}},
}


def _counting_script() -> list[list[dict]]:
    return [[{"name": "count_notes", "arguments": {}}], []]


def test_a_postcondition_that_holds_verifies(app_state, fake_ollama, fake_embeddings, session):
    for index in range(4):
        manager.create_entry(session, f"note {index}", "Work", [])
    _save(COUNTING_SKILL)
    fake_ollama.tool_script = _counting_script()
    run = skill_runner.run_for_test(fake_ollama, skill="count_them")
    assert run.verification.ok
    assert run.verification.got == 4
    assert run.stopped_by == ""


def test_a_postcondition_that_does_not_hold_fails_the_run(
    app_state, fake_ollama, fake_embeddings, session
):
    """The whole point: the model reported success and the notebook disagrees."""
    manager.create_entry(session, "the only note", "Work", [])
    _save(COUNTING_SKILL)
    fake_ollama.tool_script = _counting_script()
    run = skill_runner.run_for_test(fake_ollama, skill="count_them")
    assert run.verification.ok is False
    assert "came back 1" in run.verification.reason
    assert [s.state for s in run.steps] == ["done"], (
        "the steps still passed: a verification is about the notebook, not "
        "about whether the model did as it was told"
    )


def test_unchanged_is_read_against_the_reading_taken_before_the_run(
    app_state, fake_ollama, fake_embeddings, session
):
    """`Find loose ends` promises a report. This is what makes that checkable."""
    for index in range(3):
        manager.create_entry(session, f"note {index}: chase up the invoice", "Work", [])
    fake_ollama.tool_script = [
        [{"name": "list_notes", "arguments": {"limit": 25}}],
        [],
        [{"name": "get_note", "arguments": {"note_id": 1}}],
        [],
    ]
    run = skill_runner.run_for_test(fake_ollama, skill="find_loose_ends")
    assert run.verification.ok, run.verification.reason
    assert (run.verification.before, run.verification.got) == (3, 3)


def test_a_run_that_stopped_is_never_reported_as_verified(
    app_state, fake_ollama, fake_embeddings, session
):
    """A `min` that happens to hold over a run that stopped at step one is a
    pass nobody should be shown."""
    for index in range(4):
        manager.create_entry(session, f"note {index}", "Work", [])
    _save(COUNTING_SKILL)
    fake_ollama.tool_script = [[]]  # narrates, never calls the tool
    run = skill_runner.run_for_test(fake_ollama, skill="count_them")
    assert run.stopped_by == "step"
    assert run.verification.ok is False
    assert "stopped at step 1" in run.verification.reason


def test_a_skill_with_no_verify_block_is_verified_by_finishing(
    app_state, fake_ollama, fake_embeddings, session
):
    _save({**COUNTING_SKILL, "name": "No promise", "verify": None})
    fake_ollama.tool_script = _counting_script()
    run = skill_runner.run_for_test(fake_ollama, skill="no_promise")
    assert run.verification.ok
    assert run.verification.reason == "every step finished"


# --- filing corrections ------------------------------------------------------


def _correct(session, text: str, frm: str, to: str):
    entry = manager.create_entry(session, text, frm, [])
    entry.filing_state = manager.AUTO_FILED
    session.commit()
    manager.update_entry(session, entry, category_name=to)
    session.commit()
    return entry


def test_an_edit_that_is_not_a_move_is_not_a_correction(app_state, session):
    """Retagging an auto-filed note says nothing about where it belongs."""
    entry = manager.create_entry(session, "x", "A", [])
    entry.filing_state = manager.AUTO_FILED
    session.commit()
    manager.update_entry(session, entry, tags=["work"])
    session.commit()
    assert _actions(session) == ["edited", "created"]


def test_a_move_the_user_filed_themselves_is_not_a_correction(app_state, session):
    """Nothing was corrected: the AI never chose in the first place, and a
    rule learned from this would be learned from the user's own filing."""
    entry = manager.create_entry(session, "x", "A", [])
    session.commit()
    manager.update_entry(session, entry, category_name="B")
    session.commit()
    assert "correction" not in _actions(session)


def test_a_second_move_is_not_a_second_correction(app_state, session):
    """Once corrected, the note is the user's. The AI's guess is what a
    correction is about, and there is only ever one of those."""
    entry = _correct(session, "x", "A", "B")
    manager.update_entry(session, entry, category_name="C")
    session.commit()
    assert _actions(session).count("correction") == 1


def _actions(session) -> list[str]:
    from memorymap.core.database import AuditLog

    return [row.action for row in session.query(AuditLog).order_by(AuditLog.id.desc()).all()]


def test_the_correction_carries_both_categories_and_the_note(app_state, session):
    from memorymap.core.database import AuditLog

    _correct(session, "ring the landlord back", "Work", "House")
    row = (
        session.query(AuditLog)
        .filter(AuditLog.action == "correction")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row.payload["from"] == "Work"
    assert row.payload["to"] == "House"
    assert row.payload["excerpt"] == "ring the landlord back"


def test_the_filing_prompt_carries_the_corrections_for_that_category(app_state, session):
    from memorymap.ai import librarian

    _correct(session, "ring the landlord back", "Work", "House")
    prompt = librarian.filing_prompt(session, "call the plumber", ["House", "Work"])
    assert "ring the landlord back" in prompt
    assert "moved from Work to House" in prompt
    assert prompt.index("corrected") < prompt.index("Note: call the plumber"), (
        "the corrections come before the note, the same placement the contract "
        "nudge uses and for the same reason"
    )


def test_a_category_with_no_corrections_adds_nothing_to_the_prompt(app_state, session):
    from memorymap.ai import librarian

    _correct(session, "ring the landlord back", "Work", "House")
    assert librarian.corrections_note(session, ["Ideas"]) == ""
    assert "corrected" not in librarian.filing_prompt(session, "a note", ["Ideas"])


def test_only_the_last_few_corrections_ride_in_the_prompt(app_state, session):
    """A prompt made of examples has no room left for the note being filed."""
    from memorymap.ai import librarian

    for index in range(librarian.CORRECTIONS_REMEMBERED + 4):
        _correct(session, f"note {index}", "Work", "House")
    found = librarian.filing_corrections(session, ["House"])
    assert len(found) == librarian.CORRECTIONS_REMEMBERED
    assert found[0]["excerpt"].endswith("8"), "newest first"


# --- the budget in Settings --------------------------------------------------


def test_the_run_budget_round_trips_through_preferences(ai_client):
    """A setting the backend reads and nothing can change is a switch that
    never saves: the shape `small_model_mode` was in before it got a control.
    """
    assert ai_client.get("/preferences").json()["run_budget_tokens"] == budget.DEFAULT_TOKENS
    ai_client.put("/preferences", json={"run_budget_tokens": 5000, "run_budget_seconds": 30})
    prefs = ai_client.get("/preferences").json()
    assert (prefs["run_budget_tokens"], prefs["run_budget_seconds"]) == (5000, 30)


def test_a_negative_budget_is_refused_rather_than_stored(ai_client):
    assert ai_client.put("/preferences", json={"run_budget_seconds": -1}).status_code == 422


def test_a_verifier_may_not_write(app_state, fake_ollama, fake_embeddings, session):
    """The one thing a check must never do is change what it is checking.

    `verify` names any known tool and the runner calls it with no arguments
    twice per run, so a block naming a write tool would write twice on every
    run of that skill as part of "verifying" it. Refused where the call is
    made, not only at save time: a skill stored before the block existed
    reaches the runner without passing `normalise` again.
    """
    manager.create_entry(session, "a note", "Work", [])
    _save(
        {
            **COUNTING_SKILL,
            "name": "Sneaky",
            "tools": ["count_notes", "delete_note"],
            "verify": {"tool": "delete_note", "expect": {"min": 0}},
        }
    )
    fake_ollama.tool_script = _counting_script()
    run = skill_runner.run_for_test(fake_ollama, skill="sneaky")
    assert run.verification.ok is False
    assert "cannot check anything" in run.verification.reason
    assert manager.count_entries(session) == 1


def test_the_read_only_built_ins_say_they_change_nothing_and_are_checked():
    """Three of them promise it in their own prompt or description; a promise
    the app checks is worth more than one it repeats."""
    catalog = {skill["name"]: skill for skill in skills.builtins(set(tools.TOOLS))}
    for name in ("Notebook health check", "Tidy suggestions", "Find loose ends"):
        assert catalog[name]["verify"]["expect"] == {"unchanged": True}, name
