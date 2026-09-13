# Wrap and alignment sweep: what is left

Agent: worktree `agent-a6db54045f3f6f144` on `claude/epic-ramanujan-8xocc0`.
Seven reports assigned, plus INBOX 77 (the token window badge) added
mid-task by the coordinator. All seven reports done: six fixed and
measured directly, one found already fixed upstream by a concurrent
session. INBOX 77's badge half fixed and measured; its other half (a
per-model context-size preference) is explicitly next session's, not this
one.

**Mid-task correction, worth restating for whoever reads this next:** this
worktree was cut from a base one merge behind
`origin/claude/epic-ramanujan-8xocc0`'s tip, which is why `scripts/gate.sh`
and several lints (`test_no_em_dashes.py` among them) were missing for the
first four commits below, and why report 6's feature was not there at all.
`git merge origin/claude/epic-ramanujan-8xocc0` (clean, no conflicts) fixed
both. Six em-dashes in the first four commits' comments were rewritten by
the coordinator directly on the branch; every commit from `a63b75f` onward
was gated with `scripts/gate.sh --changed` (lints, node-check, ruff) before
committing, which now includes `test_no_em_dashes.py`.

## Done, with numbers

1. **Chat answer header wrap** (`frontend/index.html`, `frontend/css/01-forms-settings.css`).
   Grouped the icon + "AI answer" text + `#answered-by` badge into one
   `.answer-title` flex item (`min-width: 0; flex: 1 1 auto`) so the badge
   can never separate from the title onto its own line the way
   `.answer-actions` does. Before: at 1280px with a realistic model id
   ("answered by llama3.1:8b-instruct-q4_K_M") the row fragmented into
   three lines (title / badge flush left / actions flush right, top values
   296.5 / 320.9 / 348.5). After: badge stays within 2.3px of the title's
   own top at 1024-1460px with two model-id lengths tested; worst case is
   two rows (title, then actions), never three. Commit `8fb0ae2`.

2. **Skills button width** (`frontend/css/04-chat-dock-appearance.css`).
   `--composer-h` moved from `.chat-dock .chat-composer` up to `.chat-dock`
   itself (the shared ancestor) so `.chat-dock-controls`, a sibling of
   `.chat-composer`, can read it too. `#chat-skills-btn` gets
   `min-width: calc(var(--composer-h) * 2 + var(--space-2))`. Measured:
   button now spans 362-456.4px at 1440px, exactly matching the note-picker
   + attach-image pair above it, at every width from 600 to 1440px. Commit
   `af55ba6`.

3. **Chat dock bottom row gap** (`frontend/index.html`,
   `frontend/css/04-chat-dock-appearance.css`). Replaced
   `.chat-tool-group-mode`'s unbounded `margin-left: auto` with an explicit
   `.chat-dock-controls-spacer` (`flex: 1 1 auto; max-width: var(--space-9)`)
   between the two clusters. A capped container max-width was tried first
   and rejected: Skills can reach 18rem and the mode group ~23rem at wide
   viewports, so a cap generous enough for both worst cases barely shrank
   the gap. The spacer bounds the *gap*, not the row, so it carries no new
   wrap case at any content length. Measured: gap now a constant 48px at
   1920/1440/1024/900px (was 766/548/197/113px), narrow-viewport wrap to a
   left-aligned second line still works at 768/640/600px. Commit `4bdec8b`.

4. **Packages rows** (`frontend/app.js`'s `renderExtras`,
   `frontend/css/00-tokens-shell.css`). Same defect shape as #1: title, its
   "Installed"/"Not ready yet" chip, and the actions were three independent
   flex children of `.entry-meta`. Wrapped name + chip into `.entry-title`
   (`min-width: 0; flex: 1 1 auto`), scoped to `.extras-row` so the many
   other `.entry-meta` consumers (notes, reminders, tasks, conversations)
   are untouched. Reproduced with Tesseract's real label forced into its
   installed state (a fresh dev profile has it uninstalled, so this needed
   simulating rather than a real install); title and chip now stay within
   2.3px of the same top at 800-1440px, actions wrap to their own
   right-aligned line as before. `renderEmbedModels`, which shares the same
   classes, was checked and left alone: it already builds its badge inside
   `.entry-actions` rather than beside the title, so it never had this
   failure mode. Commit `34357f0`.

   Note for whoever reads this next: the brief named `frontend/settings.js`;
   the actual code is `renderExtras`/`renderEmbedModels` in `frontend/app.js`.

6. **Boards and maps dock** (`frontend/css/08-consistency.css`, after the
   merge brought the real markup in). This dock's `.dock-actions` has four
   full-text buttons before its icon utilities (New board, New mind map,
   Map from notes, Import outline), 730-850px depending on width, and no
   `.dock-more` menu to fold any into, unlike every other `.dock` this
   recipe serves. The generic `.dock-actions { margin-left: auto }` pins it
   to the row's right edge only while it fits beside identity/find/arrange;
   once `.dock-find`'s own growth leaves too little room, `.dock-actions`
   wraps onto its own line and the auto margin still fires there, landing
   its left edge wherever that line's leftover width happens to put it.
   Measured at 1700px: actions started at x=918 on a 1659px-wide dock,
   under the middle of the search box above it. Fixed by dropping the auto
   margin for this one dock (`[data-dock-name="library-boards"]
   .dock-actions { margin-left: 0 }`, higher specificity than the generic
   rule so every other dock is unaffected). Re-measured: 1440-2000px
   (fits, no wrap) pixel-identical to before; at 1300px (wraps) the second
   row now starts at x=51.2, exactly matching `.dock-identity`'s own
   x=51.2, so it lands under the title and search box instead of under
   empty space. Commit `a63b75f`.

   The coordinator's specificity hint (`.card > .row.space-between {
   flex-wrap: wrap }` outranking a declared `nowrap` elsewhere) was
   checked and does not apply here: this dock is `<div class="dock"
   data-dock-name="library-boards">` directly inside `<section
   class="card glass">`, never `.row.space-between`, and its wrap is the
   base `.dock { flex-wrap: wrap }` rule working as designed, not a
   `nowrap` being silently defeated. The bug was in where the wrapped
   group landed, not whether it wrapped.

7. **Links Save/Cancel** (`frontend/library.js`, `bookmarkRow`'s in-place
   edit form). Cancel was built as `class="ghost small icon-only"` with the
   text "Cancel" as its content, one function using its own hand-rolled
   buttons instead of the `smallButton()` helper that sizes `icon-only`
   automatically from content length. `icon-only` forces `aspect-ratio: 1`,
   which is right for a bare glyph and wrong for a word. Measured before:
   Save 62.6x28px, Cancel 56.2x56.2px. Fixed by dropping `icon-only`
   (plain `.ghost.small`, matching Save's `.small`). Measured after: both
   28px tall, both 9.8px radius, both `0 12.8px` padding, only the fill
   differs. Checked the other three hand-built Save/Cancel pairs in the app
   (`msg-edit-actions` and the message-edit cancel in app.js, the graph
   link-creation dialog in graph.js) for the same mistake and found none:
   this bookmark row was the only instance. Commit `b41a7c0`.

**INBOX 77** (added mid-task): the token window badge (`renderChatContextMeter`
in app.js, `.chat-context-pill` in `frontend/css/07-whiteboard-misc.css`).
Two fixes:
- *Wording*: the pill now reads `${compactTokens(used)} / ${compactTokens(window)}`
  (e.g. "1.2k / 20k") instead of a raw percentage, matching the entry's own
  "the badge shows 'used / window'".
- *Centring*: measured at 700/550/420px (the same band the entry's "header
  wraps at width" half names) that the pill was stretched from 20px to
  44px tall by "every control in a dock takes the touch floor below
  819.98px", a rule meant for real controls that this metadata badge
  (a `<button>` only so it can also open Compress, same shape as
  `#chat-turns`) was never meant to be caught by. Its own `align-items:
  center` still centred its text correctly inside the stretched box, which
  is why this read as the badge looking wrong rather than as a height
  change. Excluded `.dock .chat-context-pill` from the touch floor
  (`min-height: auto`) in the same media-query block, alongside the
  existing `.graph-help-toggle` exception it already carries a comment
  for. Re-measured: 20px tall at 1440/1024/700/550/420px alike, vertically
  centred against `.chat-subline`'s own height at each width. Commit
  `3b9ed99`.

  Not done, per the coordinator, explicitly next session's: the num_ctx
  preference (Settings -> Models, Auto or a number, sent on every request)
  that is the other half of this INBOX entry. I did not touch
  `docs/roadmap/INBOX.md` or move this item to a plan's "Placed from
  INBOX" section: only half of it is done, `scratchpad/inbox_resolve.py`
  moves an item whole, and updating the shared planning docs on a merge
  read as the orchestrator's step in the standing recipe (section 2, rule
  10) rather than a per-worktree one, done once per merge rather than
  once per contributing agent.

## Found already fixed, not by me

5. **Quick-nav hint wrap** ("m" and "then" wrapping onto two lines beside
   the key chips, `showTabJumpHint` in `frontend/app.js`). At the time this
   was checked, this function did not exist anywhere in this worktree's
   (then unmerged) checkout. Read-only, on `origin/claude/epic-ramanujan-8xocc0`,
   a concurrent session had already replaced the small popup with the
   full-screen "chord guide" the owner separately asked for (commit
   `409f044`, "The quick-nav chord is a full-screen guide, and it has
   three more keys"). Its `frontend/css/10-responsive.css` carries a
   comment naming this exact bug as the reason for the rebuild: *"...ten
   key-and-label pairs in a row that wrapped mid-pair, which is why 'm'
   and 'then' ended up on separate lines beside the chips"* and
   *".chord-guide-row: one pair per chip, so a key and its destination can
   never be split across a line break: the exact fault in the
   screenshot."* Confirmed present after the merge
   (`frontend/app.js`'s `showTabJumpHint`/`chordGuideEl`/`chordGuideGroup`,
   `frontend/css/10-responsive.css`'s `.chord-guide*` rules). Made no
   changes here: the code this report names is gone, its replacement
   already carries a fix for the same defect, and touching it further
   would be the redesign the brief explicitly told me to leave alone.

## Not verified

- Real-browser text metrics: everything above was measured against
  Chromium (headless, via Playwright, `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`)
  at 420-2200px and the app's own `--zoom` appearance setting at 95%. Font
  rendering in a different browser or OS could shift an exact wrap
  breakpoint by a few pixels; none of the fixes above depend on an exact
  breakpoint holding, only on removing the fragmentation/mislanding
  failure mode, so this should not matter, but it was not itself checked
  against a non-Chromium engine.
- Did not run the full pytest suite (standing order 5a: routine local gate
  is `scripts/gate.sh --changed`, the full suite is for a session's end or
  a backend move). Ran `scripts/gate.sh --changed` before every commit
  from the merge onward, plus a handful of specific test files by name
  (`test_dock_grammar.py`, `test_ui_recipes.py`, `test_css_braces.py`,
  `test_ui_signatures.py`) after the boards-and-maps fix since it touches
  dock CSS directly.
- Did not push. Nine commits on this branch, in order: `8fb0ae2` (report
  1), `af55ba6` (report 2), `4bdec8b` (report 3), `34357f0` (report 4),
  `b41a7c0` (report 7), `7e54cab` (this file, first version), `1643181`
  (merge of `origin/claude/epic-ramanujan-8xocc0`), `a63b75f` (report 6),
  `3b9ed99` (INBOX 77's badge half).
