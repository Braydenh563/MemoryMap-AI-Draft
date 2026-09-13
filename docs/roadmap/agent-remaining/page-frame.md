# The page frame and scroll batch: what is done, what is not

> Six reports about the shell rather than any one feature, each with an owner
> screenshot. Measured against a real Chromium, both themes, 1440x900 and
> 1280x720 unless noted. Server: `bash scratchpad/ui-sweeps/serve.sh <port>
> <data dir>`, seeded with `scratchpad/ui-sweeps/seed.js`.

## Fixed, with the numbers

### 3. AI skills sidebar not 100% height

Owner: *"the ai skill sidebar isnt 100% height."* True, but only once
scrolled. `#library-view-skills` is `#skills-sidebar`'s own `100cqh`
container-query ancestor, and container-query units follow the queried
element's **content** box. `body.scroll-top-visible` was adding
`--scroll-top-clearance` (53.6px measured) as `padding-bottom` to that same
element, so the back-to-top button appearing shrank the very size `100cqh`
reads, while the sidebar's `position: sticky; top: 0` did not move.

Measured at 1440x900, scrolled past 400px (button visible): sidebar
711.4px down to 657.8px, a 53.6px gap opening under its rounded bottom corner
while the scroll area's own border-box stayed 711.4px. Fix: moved the
clearance to `.skills-split > main` (07-whiteboard-misc.css), the column
that actually needs it, the same split `#tab-notes .layout > main` already
uses. After: sidebar stays exactly the scroller's own height (711.4px at
1440x900, 532.1px at 1280x720) at every scroll position tested (0, 450,
800). Screenshot in the commit shows the sidebar reaching the same bottom
edge as the message list beside it, both themes.

Commit: `cab1eac`.

### 5. Dashboard heatmap too small

Owner: *"the heatmap on the dashboard is a little small."* Measured: 2.72px
cells in a 306px-wide widget, since 53 weeks of 3px gaps alone (159px) outweighed
the room the cells themselves got. `--heat-cell-max`/`--heat-gap`
(03-dashboard-widgets.css) are now the one declaration of both numbers;
`dashboard.js` reads them back (`getComputedStyle`) instead of duplicating
them, measures the widget's real available width, and shows however many of
the *most recent* weeks fit at the real cell size, dropping older columns
rather than shrinking every column to fit a whole year. A `ResizeObserver`
repaints on resize, so the "wide" toggle (Edit layout) earns back more real
weeks instead of stretching the same set into bigger gaps.

Measured at 1440x900, default (narrow) widget: cell 2.72px up to 11.70px (the
12px cap), grid height 41px → 104px. Widened: cell 11.77px, 312 cells
(~44 weeks) vs 144 (~20 weeks) narrow. Screenshot in the commit: distinct
rounded squares filling the widget, the busiest-day cell clearly readable.

Commit: `8519ee2`.

### 6. Chat panel shadow reaches into the gap: partly fixed, real cause found

Owner: *"in the chat tab, the main chat panel shadow actually reaches all
the way down on the gap."* `#chat-main` is the one card in the app that is
`height: 100%` of its page, so only `--page-bottom` (24px, both themes, both
widths) ever sits under it. Diffing a shadow-off render against the default
found the standard `--glass-shadow` (12px offset + 32px blur) was still 16
RGB units darker than the bare background at the very last visible row:
real, but clipped mid-fade rather than faded out.

Fix: `#chat-main` now uses `--shadow-sm` (DESIGN.md's own smaller tier,
"resting cards") instead of the floating-panel tier, keeping `--glass-rim`
(the top specular lip is about reading as glass, not about shadow reach).
Not a one-off value: an existing documented tier, chosen because this is
the one card that never floats over a neighbour below it. Measured, dark
theme, x=880: diff peaked at -16 sustained through the last visible row
before; now peaks at -12 on the first row and is 0 by the third.

**Found, not fixed, said plainly why.** Most of what the owner's screenshot
shows is not this card's shadow. `html`'s own fixed background
(`radial-gradient(700px 500px at 85% 90%, var(--blob-b), …)`,
00-tokens-shell.css) sits at that exact screen position on *every* tab, both
themes: confirmed by hiding `#tab-chat .layout` entirely and re-screenshotting,
the identical teal patch, no card present. Chat is the one tab where nothing
sits in front of it (100% height, no neighbour below), so it is the one
place this always-present art is seen unbroken. That art is deliberate (the
owner, an earlier session: *"with the glass, I still want to be able to see
background animations"*), so repositioning or dimming `--blob-b`, or
deciding it should stay exactly as is, is a cross-tab aesthetic call, not a
page-frame fix. **Next step**: if the owner still sees this after the shadow
fix, take it to an Opus session as a `--blob-b` placement/opacity question,
with this file's screenshots as the starting evidence, rather than reopening
the shadow.

Commit: `6502f77`.

## Investigated at length, not reproduced: say plainly, don't invent a fix

### 1. Square page containers

Owner: *"the containers of all the ui in each tab page have hard corner
rectangular edges ... the shadows make the cut off pretty obvious."*

Swept every element (min 60x30px, on-screen) on all 7 tabs plus all 7
Library sub-tabs, for **any** element carrying a `box-shadow` while its own
`border-radius` computed to `0px` on any of its four corners: the exact
shape a rounded shadow "cutting off" against a square box would produce.
Checked at 420px, 1024px, 1280px and 1440px width, both themes, both an
empty profile and the seeded one (13 items): **zero matches, every run.**
Spot-checked the bottom-right corner of six cards individually
(`#chat-main`, `#graph-card`, `#reminder-list-card`, `.dash-hero`, the Notes
"browse" card, the Timeline card) with real screenshots, cropped to the
corner: all cleanly rounded, no artifact.

This branch already carries `de53d90` ("Concentric corners are a token, and
a lint keeps them one", INBOX 101) and the wider radius-tier work in
DESIGN.md section "Corners, derived from the user's setting", both merged into
this worktree from `origin/claude/epic-ramanujan-8xocc0` before this batch
started (this worktree was cut before that work landed, then fast-forwarded
here: see the merge at the top of this session's log). Reading the report
against what actually renders now: it does not reproduce. **Next step**: if
the owner has a fresh screenshot (post this branch's radius work), get the
exact tab and, ideally, the browser's viewport size from them: nothing in
this sweep found a candidate to fix blind.

### 2. Sidebars past the scroll end

Owner: *"the panels and sidebars in windows actually go quite far down below
where the scroll should stop."* Measured every sticky/height-constrained
panel's `getBoundingClientRect().bottom` against its own scroll container's
`bottom`, at 1440x900 and 1280x720:

| Panel | 1440x900 | 1280x720 |
| --- | --- | --- |
| `#sidebar` (Notes, Categories) | -24px (i.e. 24px short, never over) | -24px |
| `#chat-sidebar` | -24px | -24px |
| `#doc-sidebar` (open a document) | -24px | -24px |
| `#skills-sidebar` (Library › AI skills) | **+53.6px over, before the fix** | not separately measured, same mechanism |
| Settings modal's `#settings-nav` | 0px (exact) | 0px (exact) |

Every one of the panels/sidebars whose scroll container is the page itself
(Notes, Chat, Documents, Settings) sits *short* of the scroll end by exactly
`--page-bottom`, never past it, whether scrolled or not. The **one** real
overrun found anywhere in the app was `#skills-sidebar`, see report 3
above, already fixed in commit `cab1eac`. No second offender turned up after
checking every `position: sticky` selector with a height/max-height rule in
`frontend/css/*.css` (23 occurrences; the rest are sticky toolbar strips
with no bottom constraint to overrun). Reading this report against what
renders: report 2 and report 3 describe the same bug from two angles: it is
fixed. **Next step, if the owner still sees an overrun**: get the specific
tab and panel: this sweep did not miss a sidebar, so a fresh report likely
means a fresh regression, not this one recurring.

### 4. Dashboard back-to-top button

Owner: *"no back to top button appears on the dashboard??"* Extensively
tested and could not reproduce: the button correctly shows at scrollTop >
400 on the Dashboard tab in every scenario tried:

- Cold boot (no tab click at all, whatever the app lands on by default)
  and warm boot (explicit `#tab-btn-dashboard` click).
- Empty notebook and the seeded profile (13 items, full widget grid).
- Real mouse-wheel scroll (`page.mouse.wheel`) and programmatic
  `scrollTop` + dispatched `scroll` event.
- Light and dark theme.
- "Edit layout" mode on and off.
- 1440x900.

In every case: `.scroll-top` gets `class="scroll-top visible"`, `opacity:
1`, positioned correctly at the bottom-right of `#tab-dashboard`, not
covered by any element (`coversAFormPrimary` false), and a cropped
screenshot shows it rendered whole, un-clipped, sitting at the corner of the
last visible widget card. `scrollTopTargetEl()` resolves the Dashboard tab
to `scrollingPage()` (`.tab-page:not(.hidden)`, i.e. `#tab-dashboard`
itself) exactly as intended: there is no `NESTED_SCROLL_TABS` entry
diverting it to a different, non-scrolling element, which was the leading
hypothesis going in.

**Said plainly: not verified as broken.** This does not mean the owner
didn't see it: it means this session could not reproduce it after a wide
test matrix, so guessing at a fix would be exactly the "rebuilt without
checking" mistake this project's standing orders warn against. **Next
step**: ask for the viewport size and whether "Performance mode" or
`data-glass="off"` was active when it was seen (untested combination here),
and whether the notebook at the time was genuinely tall enough to need
400px of scroll on that specific window.

## Second batch: three INBOX items (73, 83, 89), fixed and resolved

Merged and pushed by the orchestrator between batches, then fast-forwarded
into this worktree before starting. All three fixed, gated, committed, and
moved out of `INBOX.md` into `HISTORY.md`'s "INBOX resolved, 2026-09-09"
section (`scratchpad/inbox_resolve.py 73 83 89`).

### INBOX 73: mute-notifications toggle disabling itself on close

Owner: *"'Mute notifications except reminders' toggle disables itself when
the settings close."* Reproduced with Playwright route interception rather
than guessed at, in two shapes: (1) check the box, Save, then anything that
re-shows Preferences (closing and reopening Settings does, via
`showSettingsSection` -> `renderPrefs`) fires a fresh GET while the PUT is
still in flight, and the GET can win, replacing `prefsCache` wholesale with
the pre-save value; (2) delaying the PUT leaving the browser at all (a slow
connection) makes a concurrent GET win outright, leaving the checkbox wrong
*forever*, not just mid-flight, since nothing re-reads it once the PUT
does succeed.

Fixed in `frontend/app.js`'s `savePrefs()`/`renderPrefs()`: the built
payload is written into `prefsCache` immediately, before the PUT's await
(closes case 1), and the PUT's own promise is held in
`prefsSaveInFlight`, which `renderPrefs()` awaits before doing its own GET
(closes case 2 outright, rather than narrowing the window). Measured with
the fix: both scenarios end checkbox/cache agreeing (true/true), where
case 2 previously ended false/true and stayed that way. Commit `1422575`.

### INBOX 83: Tools settings' two wall-of-prose paragraphs

Owner: *"Tools settings: the big paragraphs ('How many are offered at
once', 'Small model mode') become '?' popovers."* Done with the existing
`data-help-for` recipe (no JS needed, `initHelpToggles()` already wires
every `[data-help-for]` at boot): one line in place, the original
paragraph behind a "?" that opens a `.help-body` popover, verified live to
open/close correctly and to obey "one popover at a time". Commit `e6e48a9`.

**Other settings sections with the same pattern, not converted (the brief's
own instruction: list them, don't convert them all).** A sweep of every
`<p class="muted">` in the Settings modal at 35+ words, with its nearest
heading (approximate: a few of these may actually belong to the item after
the named heading, this is a start-here list, not a precise catalogue):

| Section | Near | Words |
| --- | --- | --- |
| Models | "Utility model (filing, digest & writing fixes)" | 46 |
| Models | "Reading text (OCR: scanned PDFs, and text in images)" | 35 |
| Skills | "Share" | 67 |
| Skills | "Add your own" | 42 |
| Templates | "Share" | 46 |
| What it remembers | "Add your own" | 40 |
| What it remembers | "Add your own" | 45 |
| Tools | "Add your own" | 39 |
| Appearance | "Status bar" | 40 |
| Packages | "Packages" | 41 |
| Packages | "Embedding models" | 39 |
| Web search | "Your SearXNG instance" | 89 |
| Web search | "Your SearXNG instance" | 35 |
| Background tasks | "Running now" | 39 |
| Data (backups) | "Backups" | 37 |
| Account & security | "If you forget your password" | 62 |

The Web search "Your SearXNG instance" one (89 words) is the longest
survivor and the most obvious next candidate if this list gets picked up.

### INBOX 89: glass sheen strength, opacity and blur

Owner: *"sheen strength, opacity and blur don't do anything."* Measured
all three with `getComputedStyle` against `#top-bar`, a dialog and a
`.card`, glass sheen and the animated background both switched on first
(the card's own blur is conditional on the art being on, INBOX 49, so
testing with it off reads as this bug even when it isn't):

- **Opacity: already correct.** `#top-bar`/`.card` background alpha
  scaled exactly with the slider (0.549 at 100%, 0.0275 at 5%, the same
  ratio); dialogs correctly did not move (`--modal-bg` is a fixed tier,
  never tied to this slider, by design).
- **Blur: correct on dialogs, wrong on the top bar.** Dialog blur measured
  14px -> 30px correctly. `#top-bar` stayed at a hard-coded `blur(18px)`
  the entire time, close enough to `--glass-blur`'s own 14px default that
  only moving the slider ever exposed it. The same literal 18px was on
  `.toast` and the mobile bottom-tabs bar too. All three now read
  `var(--glass-blur)`; top bar measured 14px -> 30px after the fix.
- **Sheen strength: drove nothing.** `--glass-sheen-strength` was
  declared and written by the slider, read by zero CSS: `--glass-catch`
  (the sheen's actual gradient) hard-coded its alpha, even though the
  comment on the sheen's own `.card` rule already claimed it was "scaled
  by `--glass-sheen-strength` through the same color-mix trick
  `--glass-opacity` uses" -- a real feature-never-ran gap between the
  comment and the code. Fixed by actually doing that: a card's own
  `background-image` now measures alpha 0.302 at 100%, 0.151 at 50%, 0 at
  0% in light; 0.0745 down to 0 in dark.

Commit `acb178a`.

## Third batch: two retests the coordinator could not reach

### INBOX 105 retest: the whiteboard View menu, on the real surface

Owner, twice: *"the view dropdown is still overly short"*, then *"on the
mindmap, the view dropdown is even more visually broken."* Today's
placement fix (`aee7a19`) was measured on a menu built for the purpose,
not the real one, and three prior attempts to open the real one failed:
`scratchpad/ui-sweeps/viewmenu.js` clicked `[data-tab="whiteboard"]`,
which does not exist (the whiteboard is Library's "Boards & maps"
sub-tab, and its canvas, `#wb-canvas-view`, stays `hidden` until a board
is actually open, not just the picker).

Fixed the script (created a board and a map via the API directly, opened
with the app's own `openWhiteboardBoard(id)`, sidestepping
`createNewBoard()`'s naming dialog) and measured the real `#wb-view-menu`
at 1440 and 820 wide, 900 and 640 tall, on both a plain board and a mind
map (8 configurations): `fitsOnScreen` true and 0 unreachable cut rows in
every one. Content height 594px (board), 674px (map, the extra "Map"
section a mind map adds); at 640px tall it correctly scrolls inside
itself (`maxHeight` 576px) with only the expected last-row-at-the-
scroll-boundary partial row, which is the documented affordance, not a
failure.

**Why it already worked, despite the fix landing on the wrong function.**
`aee7a19`'s comment claimed the whiteboard's View menu "shares this code"
with `wireEscapedActionMenu`'s `place()` (frontend/app.js). It does not:
that function is wired only to `enhanceSelect`'s dropdown shell and
`kebabMenu`'s wrap, and the whiteboard's `.wb-board-menu` goes through
its own separate implementation, `wbCapBoardMenu` in whiteboard.js (from
an earlier fix, `e1e395b` / INBOX 43), which the toolbar's fixed
top-of-window position makes correct in practice even though its
algorithm is less general (it does not compare "room above" vs "room
below" the way the newer `place()` does; it always tries below first,
which happens to be right here since the toolbar never sits anywhere
else). The misleading comment is corrected in commit `37eefe0` rather
than left to send the next session hunting for shared code that is not
there.

Resolved: closed as not reproduced, `scratchpad/inbox_resolve.py 105`.
Commits `37eefe0`, `c2d68f9`.

**Not touched, worth a look if the report ever DOES reproduce**: the two
implementations (`wireEscapedActionMenu`'s `place()` and whiteboard.js's
`wbCapBoardMenu`/`escapeMenuIfClipped`/`placeEscapedMenu`) solve the same
problem two different ways in two files. Neither is currently broken, so
consolidating them is a nice-to-have, not a bug fix, and out of scope
here.

### Documents Edit/Read toggle: already fixed, confirmed with numbers

Owner: *"the documents edit and read toggle options dont fit in the
toggle and go out of it at the bottom."* `DOCUMENTS_PLAN.md`'s own entry
had a partial reading (`.doc-dock .seg button` zeroing `padding-block`)
but no measurement, because the dock only exists with a document open
and three probe attempts never reached the editor.

**Already fixed by another agent's work, merged in before this retest.**
`08-consistency.css`'s `.doc-dock .seg button` rule (added since
DOCUMENTS_PLAN.md's entry was written) gives the buttons an explicit
centred box, `height: calc(var(--control-h) - 2 * var(--seg-pad))` with
`min-height: 0` and `place-items: center` on the segment, exactly the
"explicit centred box at a control-height token rather than zeroing
their padding" this retest was asked to apply if it were still needed.

Reached the real editor with `scratchpad/ui-sweeps/docopen.js` (written
by that same agent, to solve exactly the "probe never reaches the
editor" problem DOCUMENTS_PLAN.md recorded) and measured `#doc-view-seg`
and its two buttons at 1440 and 1280:

| Width | `.seg` height | Button height | Button top inset | Button bottom inset |
| --- | --- | --- | --- | --- |
| 1440 | 36px | 28px | 4px | 4px |
| 1280 | 36px | 28px | 4px | 4px |

Both buttons sit exactly 4px inside the segment's own top and bottom
(its padding) at both widths, `scrollHeight === clientHeight` (36 = 36,
no overflow) on the segment itself, and a screenshot shows both pills
cleanly inside the rounded edge. **Not reproduced; no overflow at
either width.**

Per the brief ("do not touch anything else in the Documents editor: that
agent owns it"), no code changed here, and `DOCUMENTS_PLAN.md`'s own
entry is left for that agent to close in their own file rather than
edited from here -- this is the confirmation measurement it was waiting
on, recorded so it does not get re-investigated blind. No commit: nothing
in the tree changed.

## Fourth batch: a whole-app visual QA pass before the PR closes

The coordinator's ask: every surface at once, at 1440 and 1024, both
themes, worst finding first, fix only what is small and unambiguous.

New tool: `scratchpad/ui-sweeps/finalqa.js`. Not built from scratch --
`errors.js` already does console/overflow/off-screen per top-level tab,
but its Library sub-tab clicks use `[data-section]`/`[data-view]`, which
Library's own sub-tabs never carry (they use `data-target`), so every
Library sub-tab past the default has gone unchecked by it since it was
written. `finalqa.js` walks all 7 tabs, Notes' 4 sub-tabs, Library's 8
sub-tabs by their real selectors (plus opening a real board and a real
document, not just their landing lists), and all 17 Settings sections,
at 1440 and 1024, in both themes: 4 full passes. Per surface: console
and page errors, HTTP 5xx, horizontal page scroll, clipped text,
off-screen controls, dock-row wrap, control-height mismatch (excluding a
dock's own `.dock-identity` label -- a short line of text centred beside
a taller button is not a height mismatch, and an early run of this
script had to learn that the hard way, see below), and a sticky panel
overrunning its own scroll container (the AI-skills-sidebar shape from
this file's own second batch).

**Worst first (there is only one real finding):**

1. **Library's Contents dock wraps to two lines at 1024px, both themes.**
   Measured: row 1 (top 162) holds the filter input and the four-way "By
   category / By tag / By month / By folder" segment (458px, full text
   labels); row 2 (top 206) holds "Collapse all", refresh and help,
   pushed down because the row's combined content does not fit 1024px's
   available width. Screenshot confirms it visually: the wrapped row
   sits oddly right-aligned under the segment rather than under the
   filter box. **Not fixed, written down instead**: `.dock`'s own
   `flex-wrap: wrap` is a deliberate recipe -- a dock wraps rather than
   crushing its heading or overflowing, per 08-consistency.css's own
   comment on `.dock-identity` -- so this is the designed fallback
   engaging on the one dock whose arrange zone is unusually wide, not a
   broken rule. Whether to narrow the segment's labels, move the
   trailing actions behind a kebab below some width, or accept the wrap
   is a design call, not a "wrong height" or a "missing `min-width: 0`",
   so per the brief it stays a finding, not a fix.

**Everything else came back clean.** 0 console/js/HTTP errors across all
four passes. 0 findings on: dashboard, notes (+ its 4 sub-tabs), chat,
graph, library's other 7 sub-tabs, an opened board, an opened document,
timeline, reminders, and all 17 Settings sections, at both widths, both
themes.

**Also checked, not part of the structural sweep, no findings:**
- Five menus (the notification panel, a note's kebab, the chat model
  picker, the Library sort select, Library's "..." menu) opened and
  measured fully on-screen at both 1440 and 1024 (10 checks).
- `docks.js`'s own control-height inventory (a complementary, pre-existing
  tool) flagged a "2px control" on Timeline: `#timeline-view`,
  `enhanceSelect`'s deliberately-hidden native `<select>` behind its
  styled replacement, not a bug -- the same shape repeats on every
  enhanced select in the app.
- Two items `notverified.js` (already in the repo, INBOX 75/91,
  explicitly flagged in its own header as "reasoned, never observed")
  had never actually been opened in a browser: a kebab opening on the
  first click, and the chat header not wrapping. Both now observed and
  both hold up -- the kebab opens correctly (confirmed via
  `aria-expanded`/visible height after one click; the script's own
  selector had gone stale, checking for `[aria-haspopup="true"]` when
  the real markup now uses `aria-haspopup="menu"`), and the chat header's
  two children sit 1-2px apart (sub-pixel rounding, not a second line),
  confirmed by a cropped screenshot showing "New chat llama3.2" on one
  line. Neither is this batch's to resolve (they belong to whichever
  session owns `notverified.js`'s own three items), so noted here rather
  than closed elsewhere.

**A false-positive trap for whoever extends this script**: the first
draft of the control-height/row-wrap check did not exclude
`.dock-identity`, and reported 13 "findings" -- every one was a text
heading sitting a few px off a 36px button's top because `align-items:
center` centres a 24px line of text differently than a 36px button, not
a real wrap or height mismatch. Fixed before the real sweep ran (see
`finalqa.js`'s own comment); recorded here so the next script does not
rediscover it the slow way.

Commit `669349b`.

## Gate status

Every commit across all four batches: `scripts/gate.sh --changed`
(lints, `node --check`, ruff, plus whichever changed-tests matched --
`test_dashboard_layout_cap.py`, then `test_style_scale`,
`test_svg_paint_attributes`, `test_whiteboard` once other agents' merged
work pulled them in) all green. Full suite not run (not routine per
standing order 5a; CI covers it on push). Not pushed: the orchestrator
merges.
