# The Documents sidebar redesign (INBOX 115)

**Worktree** `agent-adf2ab02ab01bdacf`, branch
`worktree-agent-adf2ab02ab01bdacf`, cut from `claude/epic-ramanujan-8xocc0`.
All five outcomes in the brief are **done**: built, measured in a browser in
both themes, documented in HISTORY.md ("Moved from the plans, 2026-09-12",
"From DOCUMENTS_PLAN.md: the Documents sidebar, both tabs"), and committed.
Nothing is half-finished and nothing is uncommitted. Merged and pushed by the
orchestrator, not here.

Six commits, `e457ba4` through `cb776a7`. Gates at the head:
`scripts/gate.sh --changed` green after every one of them;
`BASE=... scripts/gate.sh --sweeps` green (errors, docks, contrast, touch);
`docoutline.js` passes every assertion it had before this work (it did before
too, so it is a guard, not a scoreboard); `docsidebarshape.js` is new, 14
failures before the first commit and all checks passing after the last, in
light and with `THEME=dark`.

**The trap worth writing down.** This worktree was cut 778 commits behind the
branch head, so the first thing that had to happen was `git reset --hard
claude/epic-ramanujan-8xocc0`, and `scratchpad/ui-sweeps/` had to be topped
up from the main checkout (most of those 238 files are untracked there).
`docsidebar.js`, the file the brief said was "already on your branch", is
untracked in the main checkout and is left that way here rather than
committed from under the orchestrator.

What follows is what this session did **not** do, in the order a next session
should weigh it.

## 1. Outline rows are 24 to 25.2px, under the app's own 28px floor

`frontend/css/05-sidebars-themes.css`, `.outline-link`. DESIGN.md declares
`--target-min: 1.75rem` as "the floor under every interactive thing", and
these rows sit under it (`padding: 0.15rem 0.25rem` plus a 0.85rem line).
Deliberately left: a table of contents is a dense list you scan, 21 rows of
it in a 767px column, and 24px is WCAG 2.2 AA's own floor for a pointer
target, so raising it costs three headings' worth of visible outline for one
step of comfort. The honest answer is probably a density-aware rule (compact
keeps 24, comfortable and spacious take 28) or a touch layout for the whole
sidebar, which is UI Phase 9's territory rather than this one's.

## 2. `contrast.js` never visits the Documents tab

`scratchpad/ui-sweeps/contrast.js`, the `TABS` constant: seven tabs, and
documents, whiteboard and mindmap are not among them. So the merge gate's
contrast step has never measured any of this tab's text, and the numbers in
HISTORY for this work came from a probe written by hand for the purpose.
Adding the three missing tabs is a two-line change to that array, but it will
almost certainly find pre-existing findings on surfaces nobody has looked at
that way, which is a session of its own rather than a line in this one.

## 3. The outline is headings only, and it does not fold

Two things every editor it is measured against has and this does not:
- No folding. A 21-heading document is fine; a 120-heading one wants its h2s
  collapsible, with the state kept per document.
- No filter box. Obsidian's outline has one, and past two screens of headings
  it is how you use it at all.
Both belong in DOCUMENTS_PLAN rather than in a bug list; neither was asked
for by the report this session answered.

## 4. The scroll-spy follows the viewport, not the caret

`frontend/documents.js`, `docVisibleTopLine`. The mark follows the top of the
visible area, which is what a scroll-spy is and what the brief asked for. It
does **not** move when the caret moves inside an already-visible screen, so
typing in a section further down the page than the one at the top of the view
marks the wrong heading until the view scrolls. Fixing it means listening to
selection changes as well (`docSurface().onChange` is not enough: it fires on
edits, not on arrow keys) and deciding which of the two wins when they
disagree. Measured cost of the current shape: one hit test per animation
frame while scrolling.

## 5. Not verified

- Every number in this work is from Chromium at 1440x900 through Playwright.
  Narrow widths were not re-measured: `#doc-sidebar` becomes a sheet under
  the responsive rules in `07-whiteboard-misc.css` (around line 9413) and the
  new row tints, the `:has` empty state and the indent guides were reasoned
  about there, not observed. `touch.js` at its own widths passes, which is
  not the same thing.
- The textarea branch of `docVisibleTopLine` (the fallback when CodeMirror's
  bundle does not load) was never exercised: every sweep run had the engine
  under the editor. It is a scroll-fraction estimate, so the failure mode if
  it is wrong is a mark one heading out, not an error.
- No screen reader was run against `aria-current="location"`.
