# visual-c: three visual redesigns, what is left

Worktree `agent-a39e62953a9e53b63`, branch `worktree-agent-a39e62953a9e53b63`,
cut from `claude/epic-ramanujan-8xocc0` at `ab7f7f4`. Five commits, not
pushed. Server `:8788`, data dir `/tmp/mm-8788`.

## Done

| Item | Where the numbers are |
| --- | --- |
| GRAPH_PLAN Phase 6, the node panel (INBOX 59) | GRAPH_PLAN.md, "Built, Phase 6" |
| Library image cards (INBOX 56) | INBOX.md entry 56, marked fixed |
| Whiteboard bottom bar, zoom pill and properties panel (INBOX 52, 64, 65) | WHITEBOARD_PLAN.md, "Built, 2026-09-09" |

## Left for the orchestrator

1. **INBOX 64 and 65 have no "fixed" mark**, and that is a merge hazard
   rather than an oversight: both entries were added to `INBOX.md` after
   this worktree was cut (`ab7f7f4`), so they do not exist in the copy this
   branch edits, and writing them here would conflict with the branch's own
   version of the file. The work is done and measured; the numbers are in
   WHITEBOARD_PLAN.md's Built block, ready to paste onto both entries.
   Entry 52 *is* marked fixed, because it predates the cut.

## The two suite failures are not this pass's

Checked against the base commit rather than assumed:

- `test_doc_dock.py::test_the_name_and_the_type_share_a_row` wants
  `id="doc-file-type"` inside `class="doc-dock-identity"`. That section of
  `index.html` is byte-identical to `ab7f7f4` and does not contain it in
  either version, so the select moved and its lint did not. Documents is
  being rewritten by another agent in parallel and was out of bounds here.
- `test_docs_site.py::test_the_mirrored_docs_match_the_originals[CHANGELOG.md]`
  wants `docs/CHANGELOG.md` to match the root copy. Neither file is in this
  branch's diff; the mirror is stale on the branch (`cp CHANGELOG.md
  docs/CHANGELOG.md` is what the test itself suggests).

Everything else in the suite passes.

## Not verified, said plainly

- **A real touch device.** The graph node panel's 390 sheet and the
  whiteboard's panels were measured in a 390px Chromium viewport, which is
  a viewport, not a phone.
- **The align and distribute actions themselves.** Their markup changed
  (labels to icons); their handlers were not touched and were not driven.
- **A real vision model.** The Library card fixture writes the description
  and both readings through the API, so what a model would actually produce
  (length, line breaks) is not what was measured against the three-line
  clamp.
- **The Files rows** share the image tile's builder and were checked with
  one hand-made PDF (`scratchpad/ui-sweeps/seed-file.js`), not with a real
  scanned document.

## Found, not fixed

- **A tile's Rename and Delete buttons are never in the DOM.** They are
  detached `<button>` objects the kebab's rows `.click()`
  (`renderLibraryImagesGallery`, library.js). That is deliberate and works,
  but it means `.library-image-edit` and `.library-image-delete` match
  nothing in a running page, so the `[data-glass="off"]` rules naming them
  (03-dashboard-widgets.css) style nothing at all. Either the rules are
  dead and should go, or the buttons should be in the row and the menu
  should be the overflow. Not touched here: it is a behaviour question, not
  a visual one, and this pass was told to leave those two controls where
  they are. **Half of it is already gone** (checked 2026-09-12 on the image
  cards pass): that glass-off list now names `.library-image-tile`, its
  `.library-image-menu-btn` and `.library-image-menu-list` only, and no rule
  in `frontend/css/` mentions `.library-image-edit` or
  `.library-image-delete` any more. The detached buttons themselves are
  still detached, and that is still a behaviour question.
- **The graph node panel is reachable while the graph is in fullscreen**,
  and INBOX 66 says the lightbox it can open is not. Same phase, not in
  this brief.

---

# visual-c, second pass: the owner's second design batch + INBOX 107c/d

2026-09-12, in the shared worktree on `claude/epic-ramanujan-8xocc0`, server
`:8801`, data dir `/tmp/mm-design2`. Eight commits, not pushed. Every number
below was taken from the running app, not reasoned.

## Fixed, with the measurement

| Item | What it actually was | Numbers |
| --- | --- | --- |
| Boards & maps widget "is ugly" | A square thumbnail drawing its own frame with the board letterboxed inside a second one | 40.5x40.5 box, board 38.5x25.3, 7.6px band top and bottom, 59% fill → 72x40, one frame, 85%. Also "5 images" → "5 items" for text boxes |
| "Square tab corners" | Only the Documents sidebar's tab strip; its hover painted a square grey rectangle with no horizontal padding | radius 0 → 8.4px on the top corners, 49.2px → 62px wide with `--space-2` of room. Everything else tab-like on ten tabs is 8.4/11.2/4.2px |
| "Chat panel shadow" | `.chat-dock:focus-within`'s accent ring, lit by `switchTab`'s own autofocus | `rgba(79,109,245,0.14) 0 0 0 3px` on arrival → none; still 3px on the first key, first press, or a return to the tab |
| "Light vs dark glass" | Three token bugs, all in dark | `--shadow-sm` had no dark value (blue-violet on #0e1017); shadow-strength and sheen-strength sliders both byte-identical at 5% and 40% in dark. Default look unchanged |
| 107c whiteboard menu heights | Capped from the opener's bottom after `placeEscapedMenu` had moved the menu higher | 1440x700 View: top 96, room 604, cap 507, scrolling 594 through 505 → cap 596, no scroll. At 600: 407 → 536 of 544. Nothing within 8px of the window edge at 900/700/600 |
| 107c Ctrl+S in settings | The settings-aware branch had never run: a `shortcuts` binding on the same keys answers first and calls `saveEntry()` | 15 of 17 sections have no Save button on screen, so they now ring the nav button; the ring composes with `#prefs-save`'s resting `rgba(70,100,240,0.25) 0 2px 10px` instead of replacing it; Notes saves again (8 entries → 9) and Documents still saves |
| 107c "the dashboard band" | Nothing had changed there; one real defect in it | Continue pill `flex: 2 1 0` holding 68.7px of text in 535.1px, because its note line was passed as a hint and `.quick-pill` hides hints → 249.4px of note in the same pill |
| 107d segmented mini bars | The app's segmented control with a different set of numbers | track 8.4/2.4/1.6 vs 15.4/4/2.4; segment 26px at 12px type vs 28px at 16px; selected `rgba(79,109,245,0.14)` + drop shadow vs solid accent. Bar 686px → 209px |

## Not reproduced, said plainly

- **"The containers of all the ui in each tab page have hard corner
  rectangular edges so I want that fixed because the shadows make the cut off
  pretty obvious."** Swept every visible element on all ten tabs for a
  `border-radius: 0` carrying a shadow, or a border plus a background
  (`scratchpad/ui-sweeps/squarecorners.js`). The only hit on any tab was
  `footer#status-bar`, which runs edge to edge and is right to be square. At
  1440x900, light mode, one viewport. Not swept at other widths or in dark.
- **"The main chat panel shadow actually reaches all the way down on the
  gap."** Measured: `#chat-main` ends 60.8px above the window bottom and its
  drop shadow is `0 2px 8px`, so it reaches about 10px into that gap, not
  across it. Either this is the accent ring above under another name, or it is
  something this sweep could not see.
- **107c "the pckage headers, badges and buttons still get displaced onto
  separate rows".** Not attempted: it needs Packages populated, and the
  scratch profile has none.

## Found, not fixed

- ~~**`.seg button` draws its label at 16px**~~ **closed by `9586542`**, a
  later pass the same day, which measured it at three sizes rather than two
  and put every choice control on `--text-md` while leaving the tab strips
  where they are. Re-measured after it landed: all nine segments across
  `#doc-ai-verb`, `#doc-view-seg` and `#graph-layout` read 13.6px.
- **The dark shadow sliders saturate earlier than the light ones.** The dark
  alphas are 7 to 11 times the light ones at the same setting (they have to
  be, over a dark ground), so scaling them proportionally means the ambient
  layer reaches opaque around 14% of a 0-50% slider. Light's own
  `--shadow-lg` clamps at 33%, so both clamp and the structure now matches;
  spreading either across its full range is a separate decision about what the
  slider means.
- **The Boards & maps widget mixes a map chip with a plain title.** A map's
  row draws `mapChip` (a bordered pill) where a whiteboard's draws bold text,
  so two rows of one list are two shapes. That is a recorded decision
  (MINDMAP_PLAN §5 item 12, "a map says it is one, in the row") and standing
  order 3 says it is not remade here; noting it because the thumbnail and the
  meta line now say "map" twice over anyway.
- **`#doc-ai-verb` and `#graph-layout` still differ in segment radius**
  (6px against 4.2px) because `--radius-inner` resolves differently under the
  graph toolbar. Small, and not chased.

## Not verified

- **Dark mode, beyond two screenshots.** The glass work is measured in
  computed values (tokens, alphas, the card's own `box-shadow` string). Two
  dark captures were taken afterwards (`scratchpad/ui-sweeps/darkglassshot.js`,
  the dashboard band and the chat dock) and both read correctly: surfaces
  separate from the page, no ring on the composer on arrival. That is two
  surfaces of many, and it is a look, not a measurement: the luminance column
  `glassdepth.js` takes was not re-run after the shadow tokens changed.
- **A real touch device**, and anything below 390px.
- **The two suite failures in the shared worktree are not this pass's**:
  `test_whiteboard.py::test_a_text_object_round_trips_with_its_own_style` and,
  earlier, `test_ui_recipes.py::test_a_dialog_opts_out_of_the_page_column`,
  both from the other agent's uncommitted `routes_whiteboard.py` and
  `index.html` edits, checked by `git status` at the time.

---

# visual-c, third pass: INBOX 114's five design reports

2026-09-12, in the shared worktree on `claude/epic-ramanujan-8xocc0`, server
`:8853`, data dir `/tmp/mm-ui3`. Five commits, not pushed. Every number below
was taken from the running app.

## Fixed, with the measurement

| Item | What it actually was | Numbers |
| --- | --- | --- |
| "Fix the look of the mindmap item radial" | A fixed 68px circle around the node's *centre*, which covers any node wider than the ring is round | Default topic 200x44 on screen: slots over the topic 2 → 0, nearest gap -36px → 8px, slots on the edit strip 2 → 0, radius 68 → 122, spread 0 throughout. `mapstrip.js` 39/39, corner clamp included (`radialfit.js`) |
| "The view dropdown menu ... is still broken" | `escapeAndCapMenu` cleared its own cap before measuring and got the *stylesheet's* cap instead, so the placer measured an already-cut menu | Map View menu, 714px of content: 1440x760 top 56 → 36, cap 696 → 716, scrolling → not; 1280x640 visible content 574 → 622; 1024x500 434 → 482 (`viewmenu.js`) |
| "The new from a template popup buttons" | `button.ghost` rows with nothing taking the tonal fill off, and a `class="row right"` matching no rule in the app | Outlined rows 6 → 0, row type 16px → 13.6px, row height 61 → 55, dialog 559 → 526, ten action rows `normal` → `flex-end` (`tpldialog.js`) |
| "The height of the cature a thought taskbar and note edit form" | `.doc-toolbar[data-toolbar-mode="row"]` (0,2,0) beating `.note-toolbar`, and the edit form's clone built without `note-toolbar` | Composer strip row mode 58 → 50px; edit form row mode 58px with 339px of overflow → 86px with none; edit form wrap 91 → 88px; document strip untouched at 91/58 (`toolbarh.js`) |
| "I dont think you have redesigned the popup agent yet" | A step counter sharing a slot that may wrap, so it wrapped | Rows 78 → 60px, three runs fit the 200px list; dead `.monitor-title` font-size out (12px before and after); `prefers-reduced-motion` branch added (`agentpanel.js`) |

## Found, not fixed

- **The View menu is 714px of content on a map.** Under about a 730px-tall
  window it still scrolls, which is correct behaviour and may still read as
  the report. If it comes back, the fix is the menu's own length (four groups,
  sixteen rows), not its placement: that is now measured and right at every
  size from 500 to 1000px tall.
- **`.monitor-runs` overflows its 200px cap by 4px with three runs.** Rows are
  60px plus an 8px gap plus 8px of padding. The cap is a recorded decision
  ("the same max-height as the log it replaces"), so it was left; a fourth run
  scrolls either way.
- **The agent panel does not close on Escape.** Every other floating surface
  does. Not added here because it is a behaviour change on a non-modal panel
  that never takes focus, and Escape is already crowded.
- **The panel's empty line is a `<p class="muted">`, not `.empty-state`.** The
  recipe index names `.empty-state` for this; its 2rem padding and centred
  block would be wrong in a 384px glance panel. Worth a recipe row for "an
  empty line in a small panel" rather than a conversion.
- **`scratchpad/ui-sweeps/menus.js` times out** on the chat tab's
  `.select-opener` click, on this head and unrelated to any of the above (the
  change in this batch touches `escapeAndCapMenu`'s callers only, which are
  the whiteboard's five menus and `details.dock-menu`). Not chased.

## Not verified

- **The owner's own window size.** Every number here is 1440x900 unless the
  row says otherwise; the View menu was swept from 1440x1000 down to 1024x500.
- **The radial on a resized topic.** The radius is capped at 2.5 times its
  base and at what the canvas can hold; a topic wider than ~300px keeps its
  slots on its own margin. Measured only on default 200x44 topics.
- **Dark mode**, beyond one capture of the agent panel, which read correctly.
- **A real touch device**, and the desktop window (the browser tab is what was
  driven throughout).
