# Brief 13, the skill harness and its verifier: what is left

> Companions: [CHAT_PLAN.md](../CHAT_PLAN.md) (Phase 4, decisions 10 and 10a
> to 10f) · [SESSION_BRIEFS.md](../SESSION_BRIEFS.md) (Brief 13) ·
> [HISTORY.md](../HISTORY.md) ("Moved from the plans, 2026-09-12") ·
> `tests/test_harness_verifier_spec.py` (the spec, all markers now off) ·
> `tests/test_harness_verifier.py` (the behaviour around it)

## Done

Paging inside a step, the per-run token and time budget, the verification
result, the `verify` block, and the filing corrections. All four spec tests
pass with no xfail markers left in that file. The detail is in HISTORY.md;
this file is only what is still open.

## Left

1. **The `evals` marker and its fixture set.** Brief 13's done-when is
   `pytest -m evals`: at least 80% of the built-in skills complete with zero
   invalid tool calls under small-model mode, and a loose-ends fixture of 70
   notes with eight planted loose ends, all eight found. Not built, and
   deliberately not built against the fake transport: a fake calls whatever
   its script says, so "80% of skills complete" measured against one would be
   a measurement of the script. It wants the dev-only llama.cpp runner
   (WORLD_CLASS_PLAN 9); the suite must never depend on it, so the marker
   should be registered in `pyproject.toml` and the eval module skipped
   unless the dev model is reachable.
   - File: a new `tests/test_skill_evals.py`, marker `evals`.
   - Next step: land WORLD_CLASS_PLAN 9's runner first, then write the
     fixtures against it. Until then the unit tests in
     `tests/test_harness_verifier.py` are what the mechanism has.

2. **Nothing in the app reads a `verify` block from a skill's Markdown yet
   except `skills.normalise`.** The saved-skill editor in Settings and
   `save_skill` both round-trip it (normalise is the one door), but neither
   offers a control for it, so only the built-ins and a skill written by hand
   through the tool can declare one.
   - File: `frontend/index.html` (the skill editor), `frontend/app.js`
     (`renderSkillEditor`), `src/memorymap/ai/tools/__init__.py`
     (`save_skill`'s schema, so the model can write one).
   - Next step: one row in the editor, tool select plus predicate select plus
     a number, and the same three fields on `save_skill`'s schema.

3. **Two built-ins still have no `verify` block that they could have.**
   "Notebook health check", "Tidy suggestions" and "Find loose ends" now
   declare `{"tool": "count_notes", "expect": {"unchanged": true}}`, which is
   the claim their own prompts make. "Audit link reasons" declares only
   `audit_link_reasons` and "Find where I disagreed with myself" only
   `find_contradictions` and `link_notes`, so neither can verify with
   `count_notes` without widening its allowlist, which is a real change to
   what those runs may call and was not made on a guess. The *write* skills
   want a different shape entirely ("Auto-tag my notes" wants
   `count_notes(untagged) max 0`), which `count_notes` cannot express: it has
   no `untagged` argument, `list_notes` does.
   - File: `src/memorymap/ai/skills.py`, `_AUDIT_SKILLS` and the list after
     it; `src/memorymap/ai/tools/__init__.py` for `_count_notes`.
   - Next step: give `count_notes` the filters `list_notes` already takes,
     then the write skills can declare a postcondition and the two read-only
     ones can verify with a tool they already declare.

4. **The page cap and a large notebook.** `MAX_PAGES_PER_STEP` is 6 and
   `MAX_LIST_LIMIT` is 25, so one step can see at most 150 notes. A notebook
   larger than that gets an honest `truncated` report rather than a silent
   partial pass, which is the right failure, but "Find loose ends" over a
   thousand notes now reports seeing a sixth of them. Not fixed because
   raising the cap trades one wrong answer for another (a run that spends its
   whole budget paging), and the right answer is probably a filtered read
   rather than more pages.
   - Next step: decide it in CHAT_PLAN rather than in the constant.

5. **`filing_state = "auto"` is set on the two create paths only.** The
   recategorise-on-add-context path (`routes_entries.py`, the
   `exclude_entry_id` call into `janitor.categorise`) files with the AI and
   does not set it, so moving one of those notes by hand records no
   correction.
   - File: `src/memorymap/api/routes_entries.py`.
   - Next step: grep `categorise(` and set `manager.AUTO_FILED` wherever
     `janitor.is_ai_method` holds, the same two lines as the create paths.

## Not verified

Every provider test here runs against a fake transport (CLAUDE.md section 4).
Whether a real small model, handed the paging nudge with an offset written
into it, then calls the tool again is not tested anywhere and is not claimed.
The token figures the budget is charged are whatever the provider reports.
The `paging` step state, the verification line under a run and the Settings
controls are reasoned, not observed: no browser was driven this session.
