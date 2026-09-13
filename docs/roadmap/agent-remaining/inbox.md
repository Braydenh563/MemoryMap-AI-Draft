# INBOX "Open items" run: what is done, what is left

> Companions: [INBOX.md](../INBOX.md) · [HANDOVER.md](../HANDOVER.md)
>
> One session's pass over INBOX.md "Open items" 2, 7, 9, 11, 12 (caps part
> only), 14, 18, 19, in that order. Every report below was reproduced in a
> real Chromium (`bash scratchpad/ui-sweeps/serve.sh 8820 /tmp/mm-inbox`,
> Playwright through `scratchpad/ui-sweeps/lib.js`) before anything was
> changed, per CLAUDE.md's own rule. INBOX.md itself now carries a `(fixed)`
> or `(checked, already correct)` line per item with the detail; this file
> is the short version plus what is still open.

## Done this session

- **Item 2** (kebab submenus / outside-close / bottom-of-list clip):
  `buildMenuGroupButton`'s three flyouts (AI actions/Connect/Add) now
  escape to `<body>` and clamp on both axes; outside-close moved to a
  capture-phase `pointerdown`. Found and fixed a real, separate bug while
  writing the sweep: the last row of a scrolled Notes/Library list sat
  directly under the fixed `.scroll-top` button with zero clearance
  (`--scroll-top-clearance`, 00-tokens-shell.css). New sweep:
  `scratchpad/ui-sweeps/kebab-viewport.js`.
- **Item 7** (jump-to-latest pill takes a row): `.chat-transcript` wrapper,
  pill is `position: absolute` inside it instead of `sticky` as a flex
  sibling. Measured 0px composer shift.
- **Item 9** (streaming indicator / step order): checked, not touched.
  `typingDots()` already renders as a tidy row honouring
  `data-progress-motion`, and a simulated multi-step timeline confirmed
  tool rows land inside their own step group, in order. Neither half of
  the original report reproduced live.
- **Item 11** (mind map root placement / edge-follow on bulk drag): both
  root-placement call sites now use `wbCenterOn` against the rendered
  root instead of a guessed coordinate (measured `{dx:0,dy:0}`).
  `wbApplyBulkMove` now updates every bulk-moved item's own linked
  sketches, not only the card the pointer is on (reproduced the frozen
  edge before the fix, confirmed it tracks after). Two new checks in
  `scratchpad/ui-sweeps/mindmap.js` (51/51 passing).
- **Item 12, caps part only**: `wbDetectArrowStyle` no longer double-counts
  the shaft's own leading `M` as a start-cap marker. The rest of item 12
  (export-selection popover placement, missing align-centre/
  distribute-gaps, the arrange panel's icon/text overlap) is **untouched**
 : out of the scope I was given ("12 only the caps part").
- **Item 14** (icon/text alignment): measured all three named surfaces
  before touching anything. The bottom bar and the spaces switcher were
  already within a fraction of a pixel; only the popup agent's own row was
  actually off (a real 4px), fixed with two changes in
  07-whiteboard-misc.css (the icon's own flex-centring, and a stray
  inherited `margin-bottom` on the textarea). Verified 0.00px diff live.
- **Item 18** (pinned toolbar group radius/opacity/squashed): radius
  fixed (`.doc-toolbar-tools` had none at all). The "opaque only on the
  note form" half was already fixed by an earlier commit, verified
  byte-identical CSS on both toolbars. "Squashed at 1440" **not
  reproduced**: see below.
- **Item 19** (Ctrl+Shift+S strikethrough): added to all three editors,
  wider than the literal ask, since Ctrl+B/I never actually worked from
  the keyboard in the note capture box or the note edit form (only
  `#doc-content` had any keyboard shortcuts at all: the toolbar's own
  "(Ctrl+B)" tooltips were aspirational on two of the three surfaces).
  `wireMdFormatShortcuts` (documents.js) is the one place all three now
  share. Help text updated.

## Found, not fixed

- **Item 18, "documents toolbar squashed at 1440"**: measured `gap`,
  `row-gap` and the space around every `.doc-toolbar-sep` on both
  `#note-toolbar`'s clone and `#doc-toolbar` at 1440px: byte-identical
  (both `gap: 4px`, both `8px` around every separator). A screenshot of an
  open document at 1440 (`/tmp/mm-inbox/shots/doc-toolbar-1440.png` this
  session, not preserved) shows one comfortable row with clear group gaps,
  not wrapped, not squashed. Left alone rather than changing shared CSS
  that also drives the note editors' own toolbar on a report that would
  not reproduce. If this is still seen live, it is worth checking at a
  *narrower* width than 1440 (a sidebar or the Outline panel open would
  shrink the editor column) or with a document open whose own title is
  long enough to compete with the toolbar for the head row's width: that
  combination was not tried.
- **Item 12, the rest**: export-selection popover placement, missing
  align-centre/distribute-gaps on the whiteboard's arrange panel, and its
  buttons' icon/text overlap. All still open, owner WHITEBOARD_PLAN.md,
  unstarted this session.

## Traps worth recording for the next session

- **The Notes list appends a `.list-window-sentinel` li** after the real
  rows (a lazy-load/windowing marker): `li:last-child` finds it, not a
  note. Filter to `li[data-id]` and take the last one.
- **`#entry-list` itself never scrolls.** The real scroll container is
  `#tab-notes .layout > main`, one level up. Setting `#entry-list`'s own
  `scrollTop` is a silent no-op; `scrollIntoView({block:'end'})` on a row
  aligns to the *visible* edge of the real container regardless of any
  trailing padding past it, so neither reproduces "scrolled all the way
  down" the way `main.scrollTop = main.scrollHeight` does.
- **Scroll the container and read the target row in the *same*
  `page.evaluate` call.** Splitting them across two round-trips let a
  background poll's re-render land in between at least once this session,
  handing back a row id that no longer matched what was actually at the
  bottom by the time the next call ran.
- **The mind map's "Mind map" board type and the free-canvas "concept
  map"** (Library's own "New concept map" entry) are two separate creation
  paths (`createNewBoard("map")` vs `createConceptMap()`), each with its
  own root-placement code. A fix to one is not a fix to the other; both
  needed the same `wbCenterOn` change this session.
- **A note's kebab menu (`entryOverflowMenu`) is a different builder from
  every other kebab in the app (`kebabMenu()`)**: only the note-card one
  has the grouped AI actions/Connect/Add submenus. `kebabMenu()` itself is
  flat and already escapes every caller automatically via
  `wireEscapedActionMenu`.
- **The "popup agent" is `#command-palette-overlay`** (Ctrl+Shift+A,
  `toggleAgentPalette`), not `#palette-overlay` (a plain `<input>`, the
  global Ctrl+K command palette): two different overlays with similarly
  named ids, easy to conflate.

## INBOX 115, four of the six lines (2026-09-12, agent)

Each reproduced with a measurement before anything was changed, against
`serve.sh 8857 /tmp/mm-batch3`.

- **The splash's loading bar** (`7c43889`). Instrumented rather than read:
  the status file captured while `start.sh` ran in a scratch copy. Five
  steps are written, four ever reach `done`; the fifth is the step the
  app's own process owns and nothing finished it. Desktop: 4 ticks and
  80% to 98.4%, now 5 ticks and 100% at the instant the server answers,
  before the swap. Browser mode ticks it at the handoff instead.
- **Per-tool cursors on the board and the map** (`8594023`). 32 item/tool
  pairs answered `grab` under a tool that does not drag, and bucket,
  sticky and text had no cursor of their own. 0 and 0 after.
  `scratchpad/ui-sweeps/toolcursor.js`.
- **The boards selector** (`bedff0c`). `#wb-board-select` said nothing
  about kind; grouped by kind now, the recipe from MINDMAP_PLAN §5 item 12.
  `scratchpad/ui-sweeps/boardsel.js`.
- **The Files rows** (`210a607`). 257px a row of five one-string blocks,
  now 176px in two ranks, plus "Save a copy". The decision about what a
  Files row is for is in UI_MODERNISATION_PLAN, "Decided, 2026-09-12".
  `scratchpad/ui-sweeps/filesrow2.js`, `filesave.js`.

### Left of 115

- **"the bottom of the image cards in the library images subsaection needs
  a desperate redesign and funection"**: four stacked controls and the
  model name twice. Untouched. The Files decision above is the shape to
  apply: two ranks, and a fact is not a control.
- **"the documents page sidebar needs redesigning as well, both for
  outline and documents but mostly outline."** Untouched.

### Not verified

- **Windows.** The splash the owner is reading the "3/5" off is
  `scripts/splash.ps1`, which draws "N of M steps done"; PowerShell cannot
  run here, so the launcher half is verified through the status file both
  renderers parse and through the desktop loading window in Chromium. In
  browser mode the launcher now ticks the last step immediately before
  deleting the status file, so whether the splash paints `4 of 4` before it
  closes depends on where its 250ms poll lands; the terminal and the log
  narration are complete either way.
- **A real download dialog.** The Playwright download event fires with the
  right filename; no OS save dialog was driven.
- **Touch.** Every cursor claim here is a pointer claim.
