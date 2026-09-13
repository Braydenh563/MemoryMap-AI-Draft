# Timeline redesign: remaining (agent paused to save usage, nothing dropped)

Resume with SESSION_BRIEFS.md Brief 5. Worktree `agent-abcdedfb8d9f9f2bf`
(branch `worktree-agent-abcdedfb8d9f9f2bf`, port 8817, data `/tmp/mm-timeline`);
its commit `fd25a24` (seed and audit scripts) is merged into the branch.

## Done
- `scratchpad/ui-sweeps/seed-timeline.js` (48 notes, 6 categories, 10 tag
  sets) and `seed-timeline.py` (back-dates across 6 months, two dense days).
- `scratchpad/ui-sweeps/timeline-audit.js`, `timeline-audit2.js`,
  `timeline-audit3.js`: the measurement sweeps.

## Measured baseline (port 8817, 48 notes, Mar to Sep)
- Grid ("table") view: 234 cells, 186 empty (79% of cells and of area);
  8,800px wide against a 1,358px viewport, unchanged at 1024 and 390; 40
  columns; all 48 cards 122.1px regardless of content; 5 font sizes in the
  tab.
- Line view: 48 dots, 14 text nodes total (6 band labels, 8 ticks); nothing
  readable without hover; 0 keyboard stops for notes; d3 `schemeTableau10`
  hexes, not tokens; viewBox forced to a 480px minimum so it overflows at
  390; colliding dot pairs 0 / 2 / 6 at 1440 / 1024 / 390.
- A row offers two actions (a 416x220 popup with Close and Open in editor).
  Search dims instead of filtering and reads two different sources
  (`dot.textContent` in grid, `d.preview` in line).

## Next steps, in order
1. Write `docs/roadmap/TIMELINE_PLAN.md` in the GRAPH_PLAN.md shape from the
   numbers above; add its row to ROADMAP.md's opening table and CLAUDE.md.
2. Row model `timelineRow(entry)` beside `renderTimelineBranch` in
   `frontend/app.js` (~22005); both views render from it.
3. Line view (Phase 1), then table view (Phase 2), per Brief 5; the grid
   view is removed, not tuned.
4. `scratchpad/ui-sweeps/timeline.js` sweep; lints; `contrast.js` both
   themes; `errors.js` at 1440/1024/390.
