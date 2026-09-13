"""The harness verifier, budget and corrections (WORLD_CLASS_PLAN 4 B5;
SESSION_BRIEFS Brief 13; CHAT_PLAN decision 10): the spec.

Built by Brief 13; every marker is off. Specified: a skill step loops its
tool until the step's contract is met (paging included), within a per-run
token and time budget; each run ends with a verification result; a moved
auto-filed note records a correction that the next filing prompt for that
category includes; a skill's Markdown may declare a `verify` block.

The behaviour around these lives in `tests/test_harness_verifier.py`, which
also says what a fake transport cannot prove about any of it.
"""
from __future__ import annotations


def test_a_skill_may_declare_a_verify_block():
    from memorymap.ai import skills

    raw = {
        "name": "t", "description": "d",
        "steps": ["List every note with count_notes"],
        "verify": {"tool": "count_notes", "expect": {"min": 1}},
    }
    norm = skills.normalise(raw, known_tools={"count_notes", "list_notes"})
    assert norm["verify"]["tool"] == "count_notes"


def test_a_step_pages_until_its_contract_is_met(fake_model_with_paged_list):
    """70 notes, list_notes pages 20 at a time: the step that must see every
    note calls the tool four times and the run's state holds 70 ids."""
    from memorymap.ai import skill_runner

    run = skill_runner.run_for_test(fake_model_with_paged_list, skill="find_loose_ends", notes=70)
    step = run.steps[0]
    assert step.tool_calls >= 4
    assert len(run.state["seen_ids"]) == 70
    assert run.verification.ok


def test_the_budget_stops_a_runaway_run(fake_model_that_loops):
    from memorymap.ai import skill_runner

    run = skill_runner.run_for_test(fake_model_that_loops, skill="tidy_suggestions", budget={"tokens": 2000, "seconds": 5})
    assert run.stopped_by == "budget"
    assert run.verification.ok is False
    assert run.undo_available


def test_a_moved_auto_filed_note_records_a_correction(session):
    from memorymap.core.database import AuditLog
    from memorymap.entry import manager
    from memorymap.ai import librarian

    entry = manager.create_entry(session, "x", category_name="A", tags=[])
    entry.filing_state = "auto"
    session.commit()
    manager.update_entry(session, entry, category_name="B")
    session.commit()
    cat_b = manager.get_or_create_category(session, "B")
    last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert last.action == "correction"
    prompt = librarian.filing_prompt_for_test(session, category=cat_b)
    assert "x" in prompt and "A" in prompt, "the last corrections for the category ride in the prompt"
