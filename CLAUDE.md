# MemoryMap AI: read this first

A 100% offline, local-first notebook where a local AI files your notes and
answers questions about them. Python and FastAPI backend, vanilla JS
frontend, SQLite. No build step: `frontend/*.js` and `frontend/css/*.css`
are served as-is.

This file is the operating manual for any session, human or model. It is
short on purpose; the detail lives in the files it points at.

## 1. Before you build anything

**Check the running app first.** Three sessions have rebuilt something that
already existed; an audit of one roadmap section found four of its six
"quick wins" already done. Ten seconds of `grep` beats a session of rework.
The owner's words: "Three sessions rebuilt existing work. It's the single
most expensive recurring mistake in this project's history."

**"Already exists" is not "is good enough."** A thing the owner flags may be
present and still wrong: the wrong shape, a missing case, clumsy, visually
inconsistent. Finding it exists is the start of triage, not the end: read
the report against what actually renders or runs and say whether it meets
what was asked.

**You cannot see a browser, so say what you could not verify.** The owner's
words: "Everything visual I did this session is reasoned, not observed. A
session that forgets this will report UI work as done when it's untested."
Chromium and Playwright are in the sandbox (section 5); use them.

## 2. Standing orders on branch `claude/epic-ramanujan-8xocc0`

These are the owner's rules, collected from this project's sessions. The
full text, with the reasons, is the block at the top of
[`docs/roadmap/HANDOVER.md`](docs/roadmap/HANDOVER.md).

1. **"Continue"** (or the owner's usual prompt: review the docs, proceed
   with the top-priority, most impactful, qualitative work, autonomously,
   token-efficiently, scanning for bugs, keeping docs current) means: read
   this file, the HANDOVER block and its "Now" line, `docs/ROADMAP.md`'s
   opening table; merge any agent worktree with commits not on the branch;
   then work, in order, `docs/roadmap/INBOX.md`, `docs/roadmap/agent-remaining/*.md`,
   `docs/roadmap/SESSION_BRIEFS.md` Briefs in order, the plan phases in
   ROADMAP order, then ROADMAP's live list and BACKLOG by impact. Never
   wait for a prompt; never ask permission for work inside the plans.
2. **Mid-work drops** (a screenshot, a bug, a request, a usage figure) go
   into `INBOX.md` verbatim and are triaged at the next step boundary in
   one pass; the step in hand is finished to standard first; the "Now"
   line in HANDOVER is never lost to the pile. A usage figure means commit
   and push now, then continue more tersely. INBOX is a tray, not a
   backlog: under twenty items by lint; a triaged item is fixed now and
   moved to HISTORY, or placed in its plan's "Placed from INBOX" section.
3. **Decisions are not remade.** Every plan has a "Decisions made"
   section. A missing decision becomes an INBOX entry with a one-line
   recommendation, which is then taken.
4. **Agents, by specialty, at most two at once.** Sonnet: the mechanical
   and verifiable (lints, copy moves, fixture edits, sweeps, bugs whose fix
   is named). Opus: anything with a design judgement in it (frontend layout
   and visual work, plan phases, backend moves against their spec tests).
   Fable, when available: plans, specs, line-by-line review of merges, the
   invisible bugs. Each agent: own worktree cut from the branch, own port
   and data dir, commit per step, remaining list before stopping. The
   orchestrator merges, gates, pushes.
5. **Quality does not drop with the model.** Tests first, measure before
   claiming, one commit per step, push per batch, five-line reports
   (status, commits, numbers, not verified, found-not-fixed).
5a. **Speed without losing quality** (the owner's ask, 2026-09-08). Three
   rules, none of which trims a measurement:
   - An agent runs the targeted tests for the files it touched plus the
     lint set (`scripts/gate.sh --changed`) after each step. **The full
     suite is not routine** (the owner, 2026-09-09: it is ten to fifteen
     minutes now): CI runs it on every push; locally it runs only when
     absolutely needed, meaning once before a large agent task's final
     report (a backend move, a multi-file surface), once at the end of a
     session before the PR closes (HANDOVER done-when item 7), or when a
     change touches something the targeted tests cannot see (migrations,
     the event bus, conftest). Never per step, never per merge.
   - A brief names the files, selectors and line areas, the plan's
     measured numbers, and the sweep script to run, so the agent starts
     at the change, not at orientation. Most agent tokens otherwise go to
     re-reading the codebase.
   - Two agents that land close together are merged and gated in one
     pass (suite, sweeps, push once).
   What does not speed things up: a third agent (the cap, and merges
   start conflicting on the same CSS files) or skipping the sweeps (the
   "fixed again" rounds came from exactly that).
6. **Copy:** sentence case; no em-dashes anywhere (a lint fails the build);
   no "Oops", no exclamation marks; one line of description per section,
   longer help behind a `data-help-for` '?' popover.
7. **CI red is fixed the same hour.** CodeQL comments are bug reports: fix,
   push, resolve the thread. The hourly check-in (`send_later`) re-arms
   itself at the end of every turn with these orders in its prompt.
8. **No new plan documents.** Eleven exist. A new need is a brief row in
   the plan it belongs to or an INBOX entry.
10. **Documentation hygiene, enforced by a lint** (the owner, after the
   fourth time: "I keep having to ask you to clean up and move the
   documentation"). A plan holds open work only. When a phase or step is
   built, its "Built" block moves whole into `HISTORY.md` ("Moved from the
   plans") at that step boundary, leaving a one-line pointer;
   `tests/test_plan_hygiene.py` fails otherwise, and fails when
   `HANDOVER.md` passes 600 lines (the session record goes to HISTORY).
   `tests/test_readme_freshness.py` checks the README's tool count, skill
   count, version and mode names against the code, so a change that makes
   the README stale fails the build until the README says the same. Every
   merge ends with: CHANGELOG line, README if a number or name moved,
   INBOX entry marked and moved (`python scratchpad/inbox_resolve.py <n>`
   moves it to HISTORY's "INBOX resolved"; the lint fails on a "Fixed"
   item left in INBOX), the plan's Built block moved.
11. **New UI comes from DESIGN.md's recipe index**, never from scratch: a
   menu is `kebabMenu`, a bar is `.dock`, help is `data-help-for`, a
   blurred surface is on the glass-off list, spacing and radius are
   tokens. A need the index does not cover gets its recipe and its lint
   added in the same commit as the feature. `tests/test_ui_recipes.py`
   holds the ratchets (hand-built menus may not multiply, every blurred
   surface is listed). The owner's words: "all the ui issues ... happen
   when new features are added or changed because you don't follow
   design.md".
9. **Commit trailers** on every commit: the `Co-Authored-By` and
   `Claude-Session` lines the recent commits carry. No model identifiers in
   commits, PR bodies or code.

## 3. Where things are written down

Start with [`docs/ROADMAP.md`](docs/ROADMAP.md): its opening table says
which of the roadmap files are plans, which are reference, and which are
superseded. Then:

| File | What it answers |
| --- | --- |
| [`docs/roadmap/HANDOVER.md`](docs/roadmap/HANDOVER.md) | The standing orders in full, the Opus-as-orchestrator block, the "Now" line, how far each plan is, the agents table and merge recipe, the last session's traps. |
| [`docs/roadmap/INBOX.md`](docs/roadmap/INBOX.md) | The owner's mid-work findings, placed. Bugs first. |
| [`docs/roadmap/SESSION_BRIEFS.md`](docs/roadmap/SESSION_BRIEFS.md) | The operating protocol (section 0) and one complete brief per session: goal, done-when, decisions, files, tests first, steps, traps. |
| [`docs/roadmap/WORLD_CLASS_PLAN.md`](docs/roadmap/WORLD_CLASS_PLAN.md) | The consistency contract with a lint per rule, the competitor gap table, fifteen frontend dossiers, the backend moves, the security review, twelve flaw classes with commands, the execution order. |
| [`docs/roadmap/UI_MODERNISATION_PLAN.md`](docs/roadmap/UI_MODERNISATION_PLAN.md) | Phases 0 to 9 of the UI work; 8 and 9 partly open. |
| [`docs/roadmap/DOCUMENTS_PLAN.md`](docs/roadmap/DOCUMENTS_PLAN.md), [`GRAPH_PLAN.md`](docs/roadmap/GRAPH_PLAN.md), [`TIMELINE_PLAN.md`](docs/roadmap/TIMELINE_PLAN.md), [`WHITEBOARD_PLAN.md`](docs/roadmap/WHITEBOARD_PLAN.md), [`CHAT_PLAN.md`](docs/roadmap/CHAT_PLAN.md), [`MINDMAP_PLAN.md`](docs/roadmap/MINDMAP_PLAN.md), [`AGENT_SKILLS_REFORM.md`](docs/roadmap/AGENT_SKILLS_REFORM.md) | One plan per surface: what exists, why it disappoints (measured), the target, decisions made, gated phases, research, not verified. |
| [`docs/roadmap/agent-remaining/`](docs/roadmap/agent-remaining/) | What each agent left, with file, id and next step. |
| [`docs/roadmap/HISTORY.md`](docs/roadmap/HISTORY.md), [`BACKLOG.md`](docs/roadmap/BACKLOG.md), [`ANALYSIS.md`](docs/roadmap/ANALYSIS.md), [`MODERNISATION_AUDIT.md`](docs/roadmap/MODERNISATION_AUDIT.md) | What is built (with every retraction), the standing backlog, the judgements and competitor reads (including the licence constraint: this project is AGPL-3.0; odysseus's AGPL code may come in with its notices, nothing may go out to an MIT project), the measured audit. |
| [`docs/DESIGN.md`](docs/DESIGN.md) | The design system; `tests/test_style_scale.py` fails the build otherwise. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the pieces fit. |
| [`.claude/skills/README.md`](.claude/skills/README.md) | The vendored design skills; `docs/DESIGN.md` overrides them for anything in `frontend/`. |

Section numbers (`§21`) in code comments resolve through HISTORY.md's index;
`tests/test_docs_layout.py` enforces the cross-links.

## 4. The standing caveat

**Every provider test runs against a fake transport.** Plain SSE streaming
and one streamed tool call are verified against a real socket
(`scratchpad/fake_openai_server.py`); real inference, concurrent tool calls
at index 1+, Ollama's native tool-call dialect, and every claim about how a
real small model responds to a re-prompt are not. When something is
reported broken, reproduce it before theorising, and say plainly when you
could not. A dev-only llama.cpp script is planned (WORLD_CLASS_PLAN 9); the
suite must never depend on it.

## 5. Running and verifying the app

```bash
# setsid, not plain &: pkill -f uvicorn kills your own shell here (exit 144).
# One server per data dir; never put `kill $(pgrep ...)` and a setsid start
# on the same shell line.
bash scratchpad/ui-sweeps/serve.sh 8781 /tmp/mm-me
# or:
setsid env PYTHONPATH=src MEMORYMAP_DATA_DIR=<scratch>/appdata \
    .venv/bin/python -m uvicorn memorymap.api.app:create_app \
    --factory --port 8781 > <scratch>/server.log 2>&1 < /dev/null &
# then drive it: node script.js, requiring
# /opt/node22/lib/node_modules/playwright, with PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
```

Sweeps live in `scratchpad/ui-sweeps/` (`lib.js` boot, `errors.js`,
`contrast.js`, `docks.js`, `touch.js`, `chrome.js`, per-surface sweeps).
Password `testpassword123`; `THEME=dark` for dark.

**Traps, each worth an hour:**

- `waitUntil: "networkidle"` never settles (the app polls); use
  `domcontentloaded` plus `waitForTimeout`.
- The login is one field in two modes: fill `#lock-password`, click
  `#lock-submit`.
- A screenshot you look at is not a measurement. Use `getComputedStyle`,
  `getBoundingClientRect`, `scrollHeight` vs `clientHeight`, and
  `scratchpad/pngpixel.py` for colour. Never close a visual report as a
  capture artifact without a number.
- A value that is invalid where it is used, not where it is set, does its
  damage nowhere near the code that caused it (two missing appearance
  defaults once wrote `NaN` into CSS and flattened every card in the app).
- Two appended CSS sections merged can drop a `}`; only
  `tests/test_css_braces.py` sees it.
- The Bash tool times out at 120s; `errors.js` needs the background flag.
- Restart the server after any Python change: a stale uvicorn is why a
  correct fix "did not work" twice.
- Local `css`/`js` URLs are version-stamped (`?v=`), enforced by
  `tests/test_asset_cache_busting.py`; a report that keeps coming back while
  the code tests clean is a stale file or a bad interaction shape, not the
  handler.
- A test that runs a script able to delete things (the uninstallers, the
  launcher's `--reinstall`) runs it in a scratch copy, never with
  `cwd=ROOT`: one such test took the sandbox's own `.venv` mid-suite, and
  every later test that spawned Python died with "No such file".
  `tests/test_launcher_scripts.py` has the guard fixture.
- CodeQL reads `scratchpad/` too: lazy `.*?` over argv paths, unclosed
  `open()`, case-sensitive tag filters and wrong keyword arguments have
  all been flagged there.
- **The desktop window caches independently of every browser tab, for
  days.** `start-desktop.bat`/`.sh` launches `webview.start(...,
  private_mode=False, storage_path=<data dir>/webview)`
  (`src/memorymap/__main__.py`), a deliberately persistent profile so
  settings and theme survive between launches. It also keeps its cache.
  Cost one owner report of "basically all my bugs are still there" after
  a long stretch of fixes each individually measured correct against the
  branch: a browser tab opened fresh always fetches current files, the
  desktop window did not. **Fixed, not a manual step**: every local
  CSS/JS URL is stamped `?v=<__version__>`, and `RevalidatedStatic` in
  `src/memorymap/api/app.py` now splices a `_BOOT_TOKEN` (fixed once per
  server process) onto every one of those stamps inside `index.html`'s
  own served body, so a fresh launch of either script always gets its
  own stamp and can never reuse a previous launch's cache; `__version__`
  alone still governs what a *released* build caches for a year. If this
  report recurs anyway on a head after `dd2d843`, the bug is real, not a
  cache: reproduce it, do not repeat the deleted-`webview`-folder advice
  this replaced.

## 6. Reviewing work that came from somewhere else

Look for these four shapes first, in this order; they are cheap to check
and expensive to miss:

1. A working thing rewritten into a riskier thing, with no stated reason.
2. A feature that never ran once: grep the call site of anything new.
3. A guard removed while the shape around it was kept.
4. A policy silently refusing the work (inline `style=` is rejected by the
   CSP; use `el.style.x =` or a class).

Run the suite against the base branch first, so "everything else here is
new" is a fact rather than a guess.

## 7. Working here

- **Do not install torch or `sentence-transformers`.** Install by hand:
  `python3 -m venv .venv && .venv/bin/pip install fastapi "uvicorn[standard]" SQLAlchemy alembic python-dotenv requests numpy "fsspec[http]" bcrypt cryptography python-multipart pytest httpx ruff defusedxml`
- `python -m pytest tests/`: 2,800+ tests, ten to fifteen minutes, all
  green. Keep it that way, but run it locally only when absolutely
  needed (`scripts/gate.sh --full`: the end of a large agent task, the
  end of a session); CI runs it on every push. `PYTHONPATH=src` is
  needed to run the app.
- `.venv/bin/ruff check .` before pushing; CI runs it and CodeQL.
- `scripts/gate.sh` is the merge gate in one command: the lint set,
  `node --check`, ruff; `--changed` adds the tests that name the files
  changed since `origin/main` (the routine local gate); **`--staged` runs
  the lint set against the index rather than the working tree**, which is
  the only mode that catches a commit splitting a pair (2026-09-12: staging
  `index.html` while an agent was mid-way through removing an element took
  the id without its `app.js` handler, and the app stopped booting; the
  working tree was whole, so every other mode passed); `--full` adds
  the whole suite (only when absolutely needed, standing order 5a);
  `BASE=... --sweeps` adds errors,
  docks, contrast and touch against a running app. Run it before every
  push and paste its five lines into the report.
- `node --check frontend/<file>.js` after any JS edit; there is no bundler.
- The lints that exist because the suite cannot see the DOM:
  `test_style_scale.py`, `test_ui_signatures.py`, `test_css_braces.py`,
  `test_frontend_ids.py`, `test_frontend_handlers.py`, `test_dock_grammar.py`,
  `test_docs_layout.py`, `test_asset_cache_busting.py`, `test_no_em_dashes.py`,
  `test_no_innerhtml_interpolation.py`, `test_markdown_link_schemes.py`. If
  one fails it has found something real: fix the cause, never widen the
  rule.
- The executable specs for the backend moves are strict-xfail tests
  (`tests/test_events.py`, `test_search_engine_spec.py`,
  `test_harness_verifier_spec.py`, `test_learned_spec.py`,
  `test_resurface_spec.py`): remove a marker only when its test passes on
  its own.
- Comments explain why, at length; a comment that restates the code is
  noise. Prompt text is budgeted (`agent.PROSE_BUDGET_CHARS`).

## 8. Token budget (the owner's policy, condensed)

Quality first: never downgrade model or effort for quality-sensitive work
because usage is high. Compact proactively at natural boundaries. Subagents
report a status line plus results, never a transcript. When usage is low,
say so in one line and be terser rather than silently cutting corners.
