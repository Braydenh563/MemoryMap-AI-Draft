# Phase 8, the dock grammar: what is left

> Companion to [`../UI_MODERNISATION_PLAN.md`](../UI_MODERNISATION_PLAN.md)
> Phase 8. Six of this file's seven sections are now closed with measurements;
> what remains is below, each with the file, the id and the next step.

## How to pick this up

```bash
bash scratchpad/ui-sweeps/serve.sh 8799 /tmp/mm-docks           # its own port and data dir
cd scratchpad/ui-sweeps
BASE=http://127.0.0.1:8799 SCRATCH=/tmp/mm-docks PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node seed.js
#   docksurface.js  per dock: fills, radii, borders, control heights, wraps   (W=, THEME=)
#   dockodd.js      names the outliers docksurface.js counts                  (DOCKS=)
#   heads2.js       every [data-dock-name] plus the Dashboard toolbar
#   keys.js         tab stops per dock, and whether arrows move focus
#   setindent.js    every Settings heading's content-edge left
#   touch.js        44px targets on a real touch context
#   errors.js       must be 0 at 1440/1024/390
```

Gates after every surface: `node --check` on any touched JS;
`.venv/bin/python -m pytest -q tests/test_dock_grammar.py tests/test_frontend_ids.py
tests/test_frontend_handlers.py tests/test_style_scale.py tests/test_ui_signatures.py
tests/test_icon_only_buttons.py tests/test_icon_label_gap.py`; `errors.js` 0 at
all widths. Add each finished surface's `data-dock-name` to `ON_THE_GRAMMAR` in
`tests/test_dock_grammar.py`.

---

## Closed, with the numbers, so nobody re-opens them

- **The keyboard pass (was section 1).** `keys.js` exists. Baseline: 3 to 8 tab
  stops per dock, no roving tabindex anywhere, arrows moved focus in none.
  **The decision is recorded: `role="group"`, not a roving toolbar.** Four of
  the six docks contain a text field, where arrow keys already mean "move the
  caret", so a roving toolbar with inputs excluded would honour its promise on
  some controls of a strip and break it on others. The ARIA toolbar pattern
  requires arrow navigation over a roving tabindex; declaring it without either
  announced a contract the app did not honour. The twelve `.dock` surfaces are
  `role="group"` now. The five genuine tool strips (note and document
  formatting bars, whiteboard tool group and selection bar, OCR reading tools)
  keep `role="toolbar"`.
- **Seven visible controls per row (was section 2).** notes 8 to 7
  (`#select-btn` into `#notes-more-menu`), graph 9 to 7
  (`#graph-trace-toggle` into `#graph-view-menu`). `#graph-concept-maps` is
  settled as **not** a control on the bar: it is a `.dock-link` in the identity
  zone pointing at a sibling surface. Both moved controls are driven in
  `moved.js`, not just relocated.
- **The 44px touch target (was in section 6).** Measured at 720, 719, 600 and
  390: every dock control is 44px and each dock reports a single control height
  at every one of those widths. `touch.js` on a real touch context finds 0
  under 44px, 0 covered, 0 overlapping taps. Phase 9's `--target-min` resolved
  it. Nothing is capped.
- **Settings heading indents (was in section 6).** 54 of 55 headings now share
  one left edge (546px), measured at the content edge.
- **`#library-media-refresh` (was in section 6)** is `#library-boards-refresh`,
  and its title and aria-label now say what it reloads.

---

## 1. The Dashboard hero

**Deferred by the owner, not by judgement.** The owner prefers the
banner-style hero (wordmark eyebrow, large greeting, large accent clock).
**Do not touch** `.dash-hero`, `.dash-wordmark`, `.dash-greeting`,
`.dash-clock*` in `frontend/css/03-dashboard-widgets.css`, the hero markup in
`frontend/index.html` (`#dash-hero`, around line 489), or `dashboard.js`'s
`renderEmblem($("dash-hero-emblem"), …)` call.

`.dash-toolbar` beneath it **is** done: it was transparent with two 28px
controls loose between the stats strip and the grid, and it is now the bar
surface at h=54 with 36px controls. `tests/test_style_scale.py`'s
`PURE_WRAPPERS` lost it as a consequence, because that list's membership test
is "has no background of its own" and the toolbar now paints.

What was checked and is fine, so nobody re-checks it: the 24 dashboard widget
head rows are one shape, `h2` at 16px/650, `gap: 9.6px`,
`justify-content: space-between`, no controls in any of them.

## 2. `.sidebar-head`, and why it was left

**Files:** `frontend/index.html` (three rows: `#chat-sidebar` line ~1134,
`#sidebar` line ~523, the documents sidebar ~2172),
`frontend/css/05-sidebars-themes.css` line 17.

Not converted, and this is the reason: `.sidebar-head` carries
`min-height: var(--sidebar-toggle-size)`, a negative
`margin-top: calc(var(--sidebar-toggle-inset) - var(--card-pad-y))` that
brings the row up to meet the absolutely positioned collapse toggle, and
`padding-right: var(--sidebar-toggle-lane)` reserving that toggle's lane.
Two of those three exist because of reports: the three sidebar headings
rendering misaligned, and New-chat clashing with the collapse button.
Converting one of the three sidebars would reintroduce both.

Measured: the Chats head is already 36px, the same height the Chat
conversation header now is, which is what "one height" was asking for.

**If a future session does want them on the grammar,** the only safe route is
all three at once, with `.dock` gaining the three sidebar properties behind a
`.dock.is-sidebar` modifier, and `heads.js` run before and after to prove the
three headings still share one y.

## 3. Smaller things found, measured, and not fixed

- **"Advanced response settings"** sits 20.8px right of its siblings because it
  is inside a `<summary>` (`#sampling-box`, `frontend/index.html` ~line 5326)
  and the disclosure marker is in front of it. Fixing it means hiding the
  native marker, and hiding it without drawing a replacement trades a visible
  affordance for an alignment. It is the last of 55 Settings headings off the
  common edge.
- **The Chat head's second control height** is `#chat-active-model` at 28px
  against the row's 36. It is meta, not a control: it sits in `.chat-subline`
  with the turn count, the context pill and the usage figure, all
  `.chat-usage`. A model name drawn as quiet meta is what the contract asks
  for. Left alone deliberately.
- **`--field-inset` and the segmented track are one tone in light and two in
  dark.** A token-pair question rather than a dock one; see consistency.md.

## 4. Things a later session should know about

- `enhanceSelect` (`frontend/app.js`) mirrors a `<select>`'s `hidden` class and
  attribute onto the shell it wraps it in.
- `tests/test_dock_grammar.py` counts a filled button only when it is a
  **direct child of a zone**, matching `.dock > * > button` in the stylesheet.
  Keep the two definitions together.
- The quiet-control rule in 08 now also carries `.dock .menu-wrap > button.ghost`
  as a **descendant**, not a child: the chat head's kebab is two wrappers deep
  (`.dock > .dock-actions > #chat-actions-menu > .menu-wrap > button`) and the
  child version missed it. `scratchpad/ui-sweeps/dompath.js` prints that path.
- Moving a control into a menu can reintroduce a fill the menu recipe removed.
  `#select-btn.active` (02-chat-graph.css) is 1,1,0 and beat the flat-menu rule
  at 0,2,0. 08 restates it at 1,2,0. **Measure a moved control's rest state.**
