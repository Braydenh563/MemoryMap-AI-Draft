# HANDOVER

## 2026-09-08, the third night: read this block first, whoever you are

**If you are the Opus continuation of the Fable session** (same session,
same branch, the owner's Fable window closed): the standard is the one
in `SESSION_BRIEFS.md` §0 and it does not drop. Measure before claiming,
tests first, one commit per step, push after every merged batch, no
em-dashes, report in five lines. When unsure, the decision is already
written in `WORLD_CLASS_PLAN.md` or a plan file; find it, do not remake
it.

### If Opus is the orchestrator (no Fable available)

This is the expected case for most of the week. Everything Opus needs is
already written; the rule is to work it, not to redesign it.

1. **Open with:** read `CLAUDE.md`, this block, `ROADMAP.md`'s opening
   table, the "Now" line below, `INBOX.md`, then the file the Now line
   names. Nothing else before the first commit.
2. **Order of work** is the standing orders' order: INBOX bugs (Sonnet
   for the named-fix ones, Opus for the design ones), `agent-remaining/*.md`
   (Opus), `SESSION_BRIEFS.md` Briefs 2 to 15 (by the specialty split),
   then the plan phases in ROADMAP order (TIMELINE, WHITEBOARD, CHAT,
   DOCUMENTS, GRAPH, MINDMAP), each against its plan's gates and, for the
   backend, its spec tests (remove a strict-xfail marker only when the
   test passes on its own).
3. **Decisions are not remade.** Every plan carries a "Decisions made"
   section; a session that finds itself choosing between two designs
   looks there first, and if the answer is missing, records the question
   in `INBOX.md` under "Design and feature requests" with a one-line
   recommendation and takes the recommendation. Fable's next window
   reviews those entries.
4. **Review is Opus's job too.** Before merging any agent branch: read
   the diff for the four failure shapes in `CLAUDE.md` (a working thing
   rewritten riskier; a feature that never ran; a guard removed; a policy
   silently refusing), run the lint set and the sweep the brief names,
   and refuse a merge whose report has no numbers.
5. **No new plan documents.** There are eleven; a new need becomes a brief
   row in the plan it belongs to, or an INBOX entry. `HANDOVER.md`'s Now
   line and this table are the only status surfaces; keep them true.
6. **Agents:** at most two, by the specialty split below, each with its
   own worktree, port and data dir, committing per step and writing its
   remaining list before it stops.
7. **The hourly check-in** (`send_later`) is re-armed at the end of every
   turn; it carries the standing orders in its prompt, so a session that
   went idle resumes itself.

The opening prompt that does all of this: "Read CLAUDE.md, then the top
of docs/roadmap/HANDOVER.md, and continue."

### PR 144 is done when (the owner's checklist, 2026-09-09 05:30 UTC)

Tick these in order; the PR merges on the last tick. Everything added to
the plans this session (DOCUMENTS Phase 8, MINDMAP §12, GRAPH 6b, INBOX
100 to 104, CHAT and TIMELINE in full) is the next session's, not this
PR's.

- [x] 1. Documents Phase 2 steps 2 to 4 merged (2026-09-09;
      `tests/test_doc_surface.py` carries no xfail marker): the CodeMirror surface is
      the editor, Live as decorations, findings, undo, search, folding;
      `tests/test_doc_surface.py` has no xfail markers left; doctype.js
      under 30 ms; the vendor bundle absent at boot.
- [x] 2. Graph Phase 6 merged: the node panel on the new recipe, measured
      at 1440, 1024 and 390; graph4b.js passes. (Panel 416x439 to 448x348 at
      1440 and 1024, three groups of three to nine buttons in one row,
      shortest control 28 to 36px, no page scroll, and a 362x442 sheet at
      390. Its header and its action footer were fixed later the same day:
      close button back at 0,0 with an ellipsised title, and the actions as
      a centred band 446px wide in a 448px panel.)
- [x] 3. Library image cards and the whiteboard bottom bar and properties
      panel merged (INBOX 52, 56, 64, 65), with their numbers. (Card 651.6
      to 371.8px, font sizes 4 to 3, usage lines 2 to 1, scrim 3.6:1 to
      6.8:1; whiteboard own backgrounds 16 to 1 and 15 to 3, overlapping
      pairs 4 to 0, bar and pill both 46px, surface 0.549 to 0.96 opaque.
      The Arrange group was restructured later the same day into three
      named rows, 192px wide in a 200px panel.)
- [x] 4. The owner's section-A bugs closed or ruled out at head: INBOX 66,
      69, 70, 73, 77, 81, 83, 84, 86, 88, 89, 96 (each fixed and moved to
      HISTORY, or marked "not reproduced" with the measurement). Eleven of
      the twelve are in HISTORY with their numbers. 77 is the exception and
      is half done on purpose: the badge is fixed and measured, the
      per-model context size is the half the entry itself assigns to the
      next session, and INBOX says so. It is the only item left in there.
- [x] 5. The three "not verified in a browser" fixes measured: INBOX 75
      (kebab first click), 82 (settings rows), 91 (chat header), plus
      Ctrl+S and the profile group; errors.js, contrast.js, docks.js,
      touch.js and weight.js green on the head.
      **Where this stands, 2026-09-09.** Ctrl+S is measured and fixed (the
      visible section had no reachable Save button, all six in the document
      laid out at zero height). errors, contrast, docks and touch all passed
      on the merged head. 82 is clean as far as it was checked: two settings
      rows carrying both a field and a button, zero height mismatches, which
      is thin coverage rather than a result. 91 is measured by the wrap
      sweep, which took the answer header from three fragmented lines at
      1280px to two clean rows. 75 is measured now
      (`scratchpad/ui-sweeps/kebabfirst.js`): 58 kebab wraps on the Notes
      tab, the first click opens exactly one menu at 375px tall, the second
      closes it. The earlier probe reported "no kebab found" because it
      looked for `[aria-haspopup]`; the recipe is `kebabMenu()`, which builds
      a `.menu-wrap` around a `.action-menu` and a `smallButton`, so the wrap
      is what to look for. Worth writing down: the same wrong selector would
      fail the same way next time.
      A note on the metric, so the next attempt does not repeat it: counting
      distinct `top` values among a row's children does **not** detect
      wrapping. A `nowrap` row whose children are baseline- or
      centre-aligned reports several distinct tops and has not wrapped. Test
      whether a child's `top` is at or below the first child's `bottom`.
- [x] 5b. The README's screenshots recaptured, last of all. The owner:
      "I think the screen shots on the readme need an update from all the ui
      changes." Eight of them in `docs/images/` (chat, dashboard, documents,
      graph, library, notes, reminders, timeline). Capture them only once
      every UI batch has merged: taken mid-session they are stale within the
      hour, which is how they got stale in the first place.
- [x] 6. Mind map previews (INBOX 68) acceptable in the dashboard widget
      and the Library gallery (the board's real shapes at its aspect, no
      inner scrollbar). (Whiteboard card 5 blocks at one size to 5 at four
      sizes with 5 of 5 labels inside their shapes; map card 0 of 6 labels
      inside to 6 of 6, worst contrast 3.82:1 to 4.77:1; dashboard
      thumbnail 293.2 square to 40.5 square with the widget's body no
      longer scrolling, where it was 602 against 320.)
- [x] 7. The full suite green on the final head (the one local run this
      PR gets; CI covers every push in between); ruff and CodeQL green;
      **Run, 2026-09-09:** `PYTHONPATH=src .venv/bin/python -m pytest
      tests/` on the head, exit code 0, no F or E in the progress line, the
      xfails still xfail. Worth knowing before the next reader thinks the
      run was cut short: with `addopts = -q` from `pytest.ini`, the totals
      line does not survive being read out of a redirect on a run this
      long, while a single-file run prints it normally. The exit code is
      the result. All sixteen CodeQL review threads on the PR are resolved,
      the sweeps (errors, docks, contrast, touch) pass on the head, and
      the branch is mergeable.
      **Note, 2026-09-09:** `.github/workflows/ci.yml` runs `python -m
      pytest` with no selection, so CI *is* the full suite, on every push,
      and it has reported no failing suite on every head today. CodeQL has
      come back green on each one it has finished. The local run this item
      asks for is therefore a second opinion rather than the only evidence,
      which is exactly why the owner's "not as routine" rule costs nothing.
      no open CodeQL threads; the branch mergeable.
- [x] 8. Documentation: every Built block of the merged phases in
      HISTORY (the lint holds it), INBOX holding open items only, the
      README's numbers passing `test_readme_freshness.py`, CHANGELOG's
      "Since 0.2.2" carrying one line per merged item, this Now line
      rewritten as "PR 144 merged; next: Brief 18 section A onward".
- [ ] 9. The owner has run the updated build once: `start-desktop.bat`
      launches, the splash reads right, the glass frosts the art.

Then: tag the release (`__version__` is already 0.3.0, a minor bump by
RELEASING.md's rule: new features, not fixes; rename "## [Unreleased]" to
"## [0.3.0] - <date>" in both CHANGELOG copies, `git tag v0.3.0`, push the
tag, watch the release workflow), merge PR 144, restart the branch from main for the next session
(the branch rule at the top of the session prompt), and open with "Read
CLAUDE.md, then the top of docs/roadmap/HANDOVER.md, and continue".

### Fable's working notes for Opus (2026-09-09 05:10 UTC)

What made this session's fixes land first time, written down so the method
survives the model change. Use it verbatim.

**The method, per report.** (1) Find the code by grep before reading any
file whole; the sites below are already found. (2) Write a 20-line
Playwright probe (`scratchpad/ui-sweeps/lib.js` `boot()`, then
`page.evaluate` returning numbers: rects, computed styles, counts) and run
it against `serve.sh 8784 /tmp/mm-8784`; never screenshot-and-look. (3)
Fix the cause, not the symptom (the shape that recurs here: a handler
re-renders over what it just opened; a rule set on the wrong class; a
value measured while hidden). (4) Re-run the probe, then the lint set,
`node --check`, ruff; errors.js in the background. (5) One commit per
report with the measured numbers in the message, the INBOX line marked
"Fixed" with the numbers, push. (6) Say "not verified" when a browser did
not confirm it. Never widen a lint; a failing lint found something.

**Where each open section-A item lives** (INBOX number: file, area,
diagnosis):
- 66 lightbox in graph fullscreen: `frontend/app.js` lightbox mount (grep
  `lightbox`), `#graph-card` is the fullscreen element; mount the dialog
  inside `document.fullscreenElement` while it is set.
- 69 agent panel rows: `frontend/app.js` ~35850 (`agent-run-summary`,
  `agent-run-name`); the caret's toggle handler is per-row and lost on
  re-render; delegate it on the panel.
- 70 notifications combobox: the panel's outside-click guard closes on a
  click inside `.select-menu` (enhanceSelect at `app.js` ~18359); exclude
  it.
- 73 mute toggle resets: `frontend/settings.js`, grep `mute`; write the
  value into `prefsCache` before the save round-trip, not after.
- 74 profile panels and Ctrl+S: `frontend/index.html` "About you
  (optional)" group; a `keydown` on `#settings-modal` for Ctrl/Cmd+S that
  clicks the visible section's Save.
- 77 token badge: `frontend/index.html` ~1238 `.chat-subline`; the pill's
  padding is asymmetric and its text is `x% of window`; centre with
  `inline-flex; align-items:center; line-height:1`.
- 81 web links: the answer renderer's link rule (grep `renderMarkdown` in
  `app.js`), accept `<https://...>` autolinks; number web sources after
  the notes in the Sources list.
- 83 Tools paragraphs: `frontend/index.html` Settings > Tools, "How many
  are offered at once" and "Small model mode"; one line each, the rest
  behind `data-help-for` (pattern at index.html ~5321).
- 84 marquee behind objects: `frontend/whiteboard.js`, the selection
  rectangle is drawn on the object canvas; draw it on the overlay canvas
  (the one the guides use).
- 86 zoom popup under dialogs: the zoom indicator's z-index (grep
  `zoom-indicator` in CSS) is below `.modal-overlay`'s; raise it.
- 88 fullscreen graph glass: `:fullscreen .graph-card` paints over
  `--page` with nothing behind it; give it `--modal-bg` on purpose and a
  comment.
- 89 glass sliders: measure `--glass-blur` on `header#top-bar`'s computed
  backdrop-filter, `--glass-opacity` on `.card` background alpha (palette
  override order in `00-tokens-shell.css` 131/628/677), sheen on
  `:root[data-glass-sheen="on"] .card` (3389); the card blur is off unless
  `data-bg-art="on"` (INBOX 49), which is why "blur does nothing" on a
  still page.
- 96 drag without pin: `frontend/graph-canvas.js` drag end (grep `fx =`
  and `gcTogglePin`); on drop set `x/y`, clear `fx/fy`, reheat at
  alpha 0.1; pin only on Shift+drag or the menu.
- 67 gravity: `frontend/graph-worker.js` `tuning()`; `pull` is 0.25x to
  3.25x; if still spread at 100 on the owner's build, raise to 5x and add
  the component ring.

**The two agent briefs**, verbatim, are SESSION_BRIEFS Briefs 19 and 20 so
an agent that dies can be relaunched by anyone with the same words.

**What Opus should not do:** redesign what a plan decided; touch
`documents.js`/`editor.js` while the documents agent runs; merge a report
without numbers; run pkill on uvicorn; install torch; use inline
`style=`; add a glass surface without the `[data-glass="off"]` list.

### Standing orders for this session (whoever the model is)

The owner will say "continue", or paste a batch of issues, possibly
after a usage reset. Either way, without asking anything:

1. **"Continue"** means, now and after every brief is done: read
   `CLAUDE.md`, this block, `ROADMAP.md`'s opening table and `DESIGN.md`
   (token-efficiently: first screens, then only what the next item
   needs); merge any agent worktree that has commits not on the branch
   (table below, recipe below); then take the next unfinished item in
   this order: the owner's flagged items (this block and
   `agent-remaining/*.md`, deferred not dropped), `SESSION_BRIEFS.md`
   Briefs 1 to 15 in order, WORLD_CLASS_PLAN §11's quarter, then
   `ROADMAP.md`'s live list and `BACKLOG.md` top-down by impact and
   quality. Scan for bugs, flaws and stale docs on the way and fix or
   record them. Keep `HANDOVER.md`, `ROADMAP.md` and `BACKLOG.md` true as
   you go. Commit per step, push per batch, five-line reports. Never
   wait for a prompt; never ask permission for work inside the plans.
1a. **The "Now" line.** The first line under "State of the branch" below
   always says what is in flight and what its gate is. Update it when a
   step starts and when it ends. A session that resumes after a pile-up
   reads it before the pile.
1b. **Things the owner drops in mid-work** (a screenshot, a complaint, a
   feature, "X% usage") are not a change of task: finish the step in
   hand, add the new item to the task list with the owner's words, place
   it by impact (a bug in something just built goes next; a new feature
   goes into the relevant plan or BACKLOG with a brief row), and say in
   one line where it landed. The mechanism is `INBOX.md`: append
   verbatim on arrival, triage only at a step boundary, in one pass. A
   usage figure means: commit and push now, then continue more tersely.
   Never finish a step early, never drop quality, never lose the "Now"
   line to the pile: the owner has said this is the recurring failure.
2. **A batch of issues** means: for each one, reproduce it in the running
   app first (Chromium, `scratchpad/ui-sweeps/lib.js`), fix it to the
   standard (measured, a sweep check added where one exists), commit it
   on its own with the owner's words in the message, and push the batch.
   One that cannot be reproduced gets a line saying exactly what was
   driven and what was seen, never "works for me". One that is bigger
   than a fix gets a row in the relevant `agent-remaining` file or a
   SESSION_BRIEFS brief, and the owner is told which.
3. **Agents, by specialty, at most two at once** (the owner's rule):
   **Sonnet** takes the mechanical and the verifiable: lints (Brief 2),
   copy moves and popovers (Brief 4), docs condensation (Brief 14), test
   fixture edits, sweeps, and bugs whose fix is already named in
   `INBOX.md`; **Opus** takes anything with a design judgement in it:
   frontend layout and visual fixes, the one-bar and alignment work, plan
   phases (DOCUMENTS, GRAPH, TIMELINE, WHITEBOARD, CHAT, MINDMAP) and the
   backend moves (Briefs 6 to 13), each against its spec tests
   (`tests/test_events.py`, `test_search_engine_spec.py`,
   `test_harness_verifier_spec.py`: strict-xfail, remove the marker as
   each passes); **Fable**, when available, writes plans and specs,
   reviews merges line by line and root-causes the invisible bugs. Each
   agent works in its own worktree cut from the branch with its own port
   and data dir, commits per step, and writes its remaining list before
   stopping. The orchestrator merges, gates, pushes.
4. **Never stop on a red**: CI, CodeQL and review comments are fixed the
   same hour; the hourly check-in re-arms itself (`send_later`), and the
   subscription on PR #144 stays.
5. **Quality does not drop with the model.** Tests first, measure before
   claiming, no em-dashes, no scope creep, the four failure shapes checked
   in every diff. If a decision seems needed, it is already written in a
   plan file; find it.

### How far each plan actually is (honest, as of 2026-09-08 late)

The owner: "many of the plan and ui redesign and modernisation documents
are only just begun or half done." True; this table is the state.

| Plan | Done | Left |
| --- | --- | --- |
| UI_MODERNISATION_PLAN | Phases 0 to 10 (tooling, mass, components, type and glass, motion, per-surface, states, dock grammar, responsive, the Liquid Glass adoptions) | Phase 11, the phone done properly; the items in `agent-remaining/responsive.md`, `consistency.md` and `docks.md` |
| GRAPH_PLAN | Phases 1 to 6 (canvas and drag, the space, colour rules and groups, utility part one, backend, the node panel) | Phase 4 part two, 6b the minimap, the local pane |
| DOCUMENTS_PLAN | Phases 0, 1 and 2 in full (the chrome, then CodeMirror 6 as the surface: Live as decorations, findings, undo, search, folding) | Phases 3 to 8; `agent-remaining/documents-engine.md` and `documents-batch.md` |
| MINDMAP_PLAN | Phases 1 to 5 and the previews | §12, Coggle-level controls (INBOX 93) |
| AGENT_SKILLS_REFORM | Phases A to C | Phase D (recovery); the verifier and paging inside a step (CHAT_PLAN Phase 4) |
| WHITEBOARD_PLAN | One surface per panel, the Arrange section, the marquee and the export fixes | Phases 1 to 4: the rail and keys, the context bar, the export dialog and handles, the mind map regressions and Tidy |
| CHAT_PLAN | The header and badge, citation numbering, the Sources panel, angle-bracket links (as bug fixes, not phases) | Phases 1 to 4 |
| TIMELINE_PLAN | Audit and plan only | Phases 1 to 4 |
| WORLD_CLASS_PLAN / SESSION_BRIEFS | Brief 1; parts of 3 and 10; Brief 18 section A | Briefs 2 to 15; Brief 18 sections B onward |

### State of the branch (`claude/epic-ramanujan-8xocc0`, PR #144)

**A trap this session paid for, keep it.** In the shared worktree,
`git add <file>` stages the *whole* file, including whatever an agent has
half-written in it. Doing that to `frontend/index.html` committed an
agent's mid-step removal of `#entry-document` without the matching handler
removal in `app.js`, so a top-level `addEventListener` on a null element
aborted the whole of `app.js`: `initAuth` never ran, the lock overlay never
came out of `.hidden`, and the E2E suite failed on
`waitForSelector("#lock-password")` with the element present but hidden 35
times over 15 seconds. The app did not boot at all on that head. Stage by
hunk, or commit only files no agent holds, and run `scripts/gate.sh
--staged`, which exists because of this: it runs the lint set against the
index rather than the working tree. `test_frontend_ids.py` was already in
the lint set and already checks that every `$("id")` exists in the markup;
it passed, because the gate was reading the working tree, where the pair
was still whole. Proven on the same shape afterwards, with the break staged
and the working tree clean: `lints` passed and `staged-lints` failed,
naming the missing id.

**And its twin, learned the same hour, in the other direction.** A staged
file is not yours either: `git add` leaves it in the index, and the next
agent to run a plain `git commit` in the shared worktree takes it. The
`--staged` change above landed inside an agent's commit `3ef6b9b` ("The
line numbers go away with the box they number") for exactly that reason,
which is why that commit also carries `scripts/gate.sh`, `CLAUDE.md` and
this file. The content is right and the attribution is not; rewriting a
shared branch's history to fix that would cost more than it is worth.
**Stage and commit in one step, and never leave the index populated.**
In practice that means `git commit -m ... -- <paths>`, which commits
those paths directly and leaves the index alone, rather than `git add`
followed by `git commit`. It happened three times in one evening before
the habit changed, each time putting the orchestrator's work inside an
agent's unrelated commit: `scripts/gate.sh` went in with a preview
gutter fix, and `ai/learning.py` with a picture-card note. Nothing was
lost either time, and the history now says things it does not mean,
which is its own slow cost when the next session reads it. The same three symptoms in the
console are the signature: one real error, then `X is not defined` and
`Cannot access Y before initialization` from everything declared after it.

**Now (2026-09-13, Opus orchestrating, the owner awake and flagging reports
live, the order "file and log all my requests so you dont miss anything ...
fix them all and then finish the rest of the pr").** Three agents have been
through their first briefs; one is on a second pass. What the owner flagged
today is INBOX 124 to 140, and most of it is closed: the capture panel's 3px
border, the Dictate label, the writing dictionary (which was overwriting the
whole saved list on the first add after any reload), the `#` leaking into
`[[wiki link]]` labels, the `apiPagedList` crash that killed the Notes tab at
boot, the Continue pill, the whiteboard View menu (714px of content in a 272px
column, now two columns at 453px), board kinds, the selection kebab (a flip
class collapsing an escaped menu from 303px to 15px), the Tools and features
alignment, the splash bar's two separate causes, the chat on a phone (dock 38%
to 20% of the window), and the chord guide's pills becoming real buttons.

**Still open from that batch:** the spelling popup's "wide gap", which measures
flush with the word here (0px horizontal, 4px below) and is therefore NOT
reproduced, with `scratchpad/ui-sweeps/spellanchor.js` committed so the next
report starts from a number.

**The trap this session found, and it matters for the PR:** every CI run on
this branch is coming back `cancelled`, not `failed` and not `success`. Four
writers (the orchestrator and three agents) push often enough that each push
cancels the run in flight, so **the test suite has not completed on any head
since the failure at `0a7c2ab`**, which was fixed but never confirmed by a
finished run. CodeQL completes and passes. Before this PR closes, the pushes
have to stop long enough for one CI run to finish, or the suite has to be run
locally end to end (HANDOVER done-when item 7 already says the latter).

**The container restarted mid-session** (2026-09-12 ~20:00). Both agents were
killed with their work committed, and were relaunched with continuation
briefs; nothing was lost, but their `agent-remaining/*.md` files were a round
stale at that point, which is why both briefs start by reconciling them with
`git log`.

Queue after them, in the owner's stated order: (1) Brief 24, the derived
facts pipeline (I9, the ten markers left in `test_learned_spec.py`), written
this session and ready to hand to an agent; (2) GRAPH Phase 4b and 6b and
`agent-remaining/graph.md`; (3) UI Phase 11, the phone, whose first item is
now measured and written down (the status bar at 320); (4) TIMELINE_PLAN and
CHAT_PLAN Phases 2 and 3, untouched this session, last.

Landed by the orchestrator since the previous Now line, each measured: the
phone band (touch.js from 3 surfaces to 16, which found 33 findings the old
sweep could not see; the header 7px wider than a 390 screen on every tab; the
dashboard's Edit layout half off the edge; the small-phone band at 360 and
320); the security pass (13 LIKE sites escaping user text, a walk that asks
every route to refuse a stranger and found `/changelog` open, and the updater
that downloaded and ran whatever URL a release row named); a hidden tab's two
one-second clocks, stopped; a flicker sweep that opened 50 popovers and found
none painted before it was placed (INBOX 111, measured and not reproduced);
and resurfacing given a surface at last (I4: the Rediscover widget now shows
the three most faded notes with the reason on each, and Notes has a
"Forgotten first" sort).

Carried, found and not fixed: `touch.js` covers sixteen surfaces but not the
documents editor or the whiteboard, which need a document and a board open;
the note edit form's toolbar is a clone taken at open time; the whiteboard
drag lag (with the whiteboard agent now); four owner reports measured and not
reproduced are in INBOX 114. The hourly check-in re-arms itself.

**After the plans (the owner, 2026-09-12 evening): "just repeat, improve ui,
improve ux, fix bugs, fix security flaws, poke holes in the application for
fixing."** That loop is the standing order once the queue is empty: a sweep
pass (errors, contrast, docks, touch, idle, flicker, finalqa), a security
pass (WORLD_CLASS_PLAN section 12 and the CodeQL categories), a hole-poking
pass (the flaw classes in WORLD_CLASS_PLAN section 10 with their commands),
each finding fixed and measured, then again.

### The agents (worktrees under `.claude/worktrees/agent-<id>`)

Each is cut from main and merged with the branch; each has its own
server port and data dir. Their committed heads are merged as of
`dca50c6`; anything they commit after that is merged with
`git merge worktree-agent-<id>`, then the lints, then push. If one is
dead (usage limit, container restart), its worktree keeps its commits:
merge those and re-brief the rest from its brief.

| Worktree id | Brief | Port | State at hand-off |
| --- | --- | --- | --- |
| `a9ca1fcf2f7eb318b` | Phase 8 docks: Chat, Dashboard, Library sub-tabs | 8799 | 7 commits merged; finishing |
| `a7b3e667c203e7caf` | Documents Phase 0 | 8800 | **Done**, 8 commits merged; editor.js sweep 89/89; six bugs found by measuring (report in its transcript) |
| `a1fb06af7bc117427` | Phase 9 responsive by device | 8801 | 5 commits merged (one column below 820, sidebars as sheets); working |
| `a97f8374639e599f8` | Graph Phase 1 canvas renderer | 8802 | 3 commits merged (worker, fixture, Canvas 2D renderer); working |
| `a01201cb4507e3030` | Menus, summaries, one-bar docks, icon alignment, footers, toggle rows, meta chips (`08-consistency.css`) | 8815 | 3 commits merged; working |
| `a12f6d594c4b9c730` | Mindmap bugs (selection box, text selection, map-as-note, node picker, dangling edges), previews, boards widget, Phases 4 to 5 | 8816 | 2 commits merged (a map is no longer a note); working |
| `abcdedfb8d9f9f2bf` | Timeline redesign | 8817 | **Paused** to save usage after the audit; resume with SESSION_BRIEFS Brief 5 |
| `a228ba0fe38c417dc` | Paragraphs to '?' popovers | 8818 | **Paused**; 54 paragraphs left; resume with Brief 4 |

### The whole-app visual pass and the section 6 review, 2026-09-09

Both moved whole to [`HISTORY.md`](HISTORY.md) ("Moved from the plans,
2026-09-12") at the 600-line ceiling. In one line each: the visual pass
found zero console, JavaScript and HTTP errors across four full passes
(1440 and 1024, both themes) and one real finding, the Library's Contents
dock wrapping to two lines at 1024, which should take the kebab the boards
dock took; the section 6 review found nothing dead, no CSP-refused inline
styles, and one deliberate rewrite (the graph's drag), recorded in
GRAPH_PLAN with its reason.

### Two traps an agent worktree sets (2026-09-09)

Moved to [`HISTORY.md`](HISTORY.md) ("Moved from the plans, 2026-09-12")
at the 600-line ceiling. Both still bite: a worktree can be cut from an
older base than you think, so every brief says merge the branch before
starting and "that lint does not exist here" means merge rather than
substitute a weaker check; and `scripts/gate.sh` resolves python and ruff
from the main checkout, found through `git rev-parse --git-common-dir`,
because a linked worktree has no `.venv` of its own.

### Merge recipe (every time, no shortcuts)

The whole recipe below is `scripts/gate.sh --changed` plus
`BASE=<port> scripts/gate.sh --sweeps` against a fresh server; the steps
are listed so a failure can be read. The full suite is not part of a
merge: CI runs it on the push; locally it runs once before a large
agent task's final report and once before the PR closes (done-when
item 7), never per step or per merge.

1. `git merge --no-edit worktree-agent-<id>`; on a conflict in
   `07-whiteboard-misc.css` keep BOTH sides (both append), then run
   `tests/test_css_braces.py`: the last merge left one block unclosed and
   only that test saw it.
2. `for f in frontend/*.js; do node --check $f; done`, `.venv/bin/ruff check .`,
   the lint set in `SESSION_BRIEFS.md` §0 step 6.
3. Restart the 8781 server (`setsid`, never `pkill`), run
   `scratchpad/ui-sweeps/errors.js` (takes over two minutes: run it in
   the background) and the sweep the brief names.
4. Commit the merge, push, read the CI result when it arrives; CodeQL
   comments are bug reports: fix, push, resolve the thread.

### The owner's flagged list, and where each stands

- Em-dashes everywhere: sweep script ready (`scratchpad/emdash.py`), run
  it LAST, after every agent has merged (Brief 1). Not run yet.
- Paragraphs to '?' buttons: wiring merged; 54 left (Brief 4).
- Sub-tab arrow keys: done. Sub-tabs stay left-aligned (decision).
- Mindmap: selection box, text selection, "test" map as a note (fixed),
  node picker rows, dangling edge: with the mindmap agent.
- Line numbers drifting: fixed (Documents Phase 0, measured 0.0px).
- Docks as one bar, menus not stacks of buttons, icon alignment, capture
  footer with the FAB over Save, toggle rows, meta chips: with the menus
  agent.
- Timeline line and table views: audited, paused (Brief 5).
- Responsive by device: with the Phase 9 agent.
- Graph fullscreen square corners: with the graph agent (Phase 2 item).
- Files reading only first line: done.
- New note tile colours: done. Hero: restored and refined (owner's call).
- Sidebar toggle clash when collapsed: done.
- llama.cpp in the project: no; dev-only script planned (WORLD_CLASS §9).

### After the agents: the order

`SESSION_BRIEFS.md` Briefs 1 to 14 in order. Brief 1 (the em-dash sweep)
only after every agent above has merged, or their diffs conflict on every
line that carried a dash.

### Traps found this night

- A merge of two appended CSS sections can drop a `}`; the braces test is
  the only guard.
- `kill $(pgrep ...)` in the same shell line as a `setsid` start kills the
  shell; separate the commands.
- The Bash tool times out at 120s; `errors.js` needs the background flag.
- CodeQL reads `scratchpad/` too: lazy `.*?` regexes over argv paths,
  unclosed `open()`, and case-sensitive tag filters were all flagged there.
- **A CSS or JS file changed on disk is not re-served to the next sweep
  until the server process restarts.** Local assets are stamped
  `?v=<version>-<boot token>` and served as immutable for that stamp, and
  the boot token is fixed once per uvicorn process, so a second browser run
  against the same server can be handed the bytes the first run fetched.
  Cost an hour here: a fix measured correct, then reverted to check the new
  guard, and the guard stayed green because the browser was still being
  served the fixed file. Restart the server between a CSS change and the
  sweep that judges it, exactly as a Python change already requires.
- **Three pytest runs in one worktree collide.** With two agents and the
  orchestrator all running `scripts/gate.sh` in the shared checkout, a gate
  can fail on a test that passes on its own seconds later: seen here on
  `TestTheDesktopShortcut`, which writes a real desktop entry and then asks
  the uninstaller to list it. Re-run the failing file alone before believing
  a gate failure that names one of the file-writing suites, and say which of
  the two you saw.
- A sweep only knows about what it is pointed at. `touch.js` reported
  "PASS, 0 findings" for a month over three surfaces out of sixteen, and
  the thirteen it had never opened were holding 33 findings, one of them
  the whole page sliding 7px sideways on every tab at 390.
- `elementFromPoint` at a point outside the viewport returns null, so a hit
  test that does not scroll the control into view first reports every
  control below the fold, and every one in a sideways-scrolling strip, as
  "covered". Fifteen such lines in one run were all this.

---

# Handover

**Next: [`PLAN.md`](PLAN.md)** — the scoped professional-grade plan (whiteboard, documents, backend, agent harness, performance), in ship order with measurements. Written by direct instruction; start there.

## Earlier sessions

The session-by-session record that used to follow here (12k lines) is in HISTORY.md under "HANDOVER archive, 2026-09-09". This file is the current state only.
