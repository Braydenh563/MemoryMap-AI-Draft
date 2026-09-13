# Documents: the owner's evening batch (DOCUMENTS_PLAN, "Placed from INBOX, 2026-09-09")

**Worktree** `agent-ad5696bf1be5660c3`, branch
`worktree-agent-ad5696bf1be5660c3`, cut from `claude/epic-ramanujan-8xocc0`
at `edb6aae`, then merged up to `2af5332`. Fourteen commits in the batch and
five in the follow-up pass; all five items of the batch and all four of the
follow-up are done, nothing half-finished and nothing uncommitted. Never
pushed; that is the orchestrator's job.

**A trap for whoever cuts the next worktree.** This one arrived checked out
at `28a8911`, **423 commits behind the branch** it was supposed to be cut
from: no `DOCUMENTS_PLAN.md`, no `INBOX.md`, no `agent-remaining/`, and a
`CLAUDE.md` from an earlier era that still described `frontend/app.js` as one
file. `git reset --hard claude/epic-ramanujan-8xocc0` fixed it (HEAD was an
ancestor, so nothing was lost), but a session that had not checked would have
built the whole batch against a codebase without CodeMirror in it. There is
also no `.venv` in a fresh worktree; `scripts/gate.sh` reads `$ROOT/.venv`
and fails both the lints and ruff with "No such file or directory", which
reads like a broken gate rather than a missing symlink. One
`ln -s /home/user/MemoryMap-AI/.venv .venv` in the worktree, or `PY=…`.

## What is done, with its numbers

Every number below was read out of a running app, never off a screenshot.

**1. Click an underlined word, see a popover** (`0fbfe87`). **No editor code
changed: it already worked.** The plan's entry said "the click target and its
popover never landed", and that entry was written without a browser; Phase 2
turned the findings into mark decorations and the click, double-click,
right-click and Alt+Enter routes all reach `openDocSuggest`.
`scratchpad/ui-sweeps/docsuggest.js` is the check that should have existed
before the reading did: in Live *and* Source, four marks of three kinds, all
with `cursor: pointer` and a real underline; one plain click opens
`.doc-suggest-menu` at left 470.6 against the mark's own left and top 172.8
against its bottom of 168.8, inside the viewport on all four including one
against the right edge; the first item rewrites the document; Alt+Enter opens
the same menu. `long-sentence` draws no underline, which is `DOC_FINDING_SKIP`
doing what its comment says.

**2. Markdown markers go invisible unless the selection is in them**
(`f9e053f`). The cursor-in-range test was already there and works through all
three of the owner's gestures. What was missing was found by inventory, not
by reading the plugin again: `---` drew its border **and** its three dashes,
and `> [!warning]` hid its `>` and kept its `[!warning]`. Both fixed; the
callout now shows its kind's own label from `CALLOUT_KINDS` where the marker
was ("⚠️ Warning"). The same inventory then found a third: a setext heading
(`Title` over `=====`) hid its underline, because that underline is a
`HeaderMark` like any other, while the heading branch matched `ATXHeading`
only, so the whole thing rendered as body text. One regex.
`scratchpad/ui-sweeps/cm-reveal.js` holds eight constructs against their
expected render, plus the setext pair, the callout label and the three
gestures.

**3. Three views, line numbers, and a real code editor** (`d396e0c`).
- **Plain** is new: the language compartment emptied (`docCmViewLanguage`).
  Measured on a markdown file, Source colours 2 kinds of token and Plain 0,
  same text, same engine. Offered for code files too, unlike Live and Split.
- **Line numbers** already worked and were unreachable behind the collapsed
  formatting strip. A second door in the view menu (`#doc-view-gutter`), same
  remembered preference. Measured: markdown 0 numbers, 7 after one press, 0
  again; `.py` 7 unasked from a fresh profile.
- **Code syntax** existed for twenty-one languages and was close to invisible
  in dark, because without a highlight style of its own the bundle falls back
  to `defaultHighlightStyle`, a fixed light-page palette with no dark
  variant. Every token was byte-identical in both themes; against the dark
  ground sampled at `rgb(27, 31, 44)`, `def` read **1.76:1** and a variable
  name **1.91:1**. `docCmHighlight` maps six roles onto the app's tokens:
  light 4.56 to 14.62, dark 6.47 to 13.52, all above 4.5.

**4. The Edit / Read toggle overflows** (`8769590`). Confirmed at 1440 and
1280, and the cause is **not** the `padding-block: 0` the plan's partial
reading guessed at. `.doc-dock .seg` is `height: var(--control-h)` (36px)
with the base `.seg`'s 4px padding, so a 28px content box, and
08-consistency.css pinned each button to `--control-h-lg` as well: a 36px box
4px down a 36px pill. Before: segment `scrollHeight` 40 / `clientHeight` 36,
buttons 36px with their bottoms 4px below the segment's. After: 36/36,
buttons 28px, 4px inside at both ends, neither clipping its label.

**5. The Outline sidebar** (`84a9c56`). All five reported problems, each with
its own assertion in `scratchpad/ui-sweeps/docoutline.js`. Centre-alignment
was `justify-content` from the bare `button` rule, not `text-align` (which
read `left` throughout). The indent was 4/16/24/38.4px, steps of 12, 8 and
14.4; now 4/16.8/29.6, a constant 12.8. The Outline section no longer hides
itself, and says what fills it. References is one row (link and ✕ 6.4px
apart, same line) and its picker replaces the button that opened it. The
storage help is its own content width (224.9px box, 225px of text) at the
column's left edge, muted, underlined only on hover. A sixth was found by
looking at the finished panel rather than at the report list: the outline
matched `#` headings only, so it read "2" over a document with three, the
missing one being the setext heading the editor had just started rendering.

## Gates at the head

`scripts/gate.sh --sweeps` with a server on 8833:

    ran:     lints node-check ruff sweep-errors sweep-docks sweep-contrast sweep-touch
    passed:  lints node-check ruff sweep-errors sweep-docks sweep-contrast sweep-touch
    failed:  none

errors.js 0 errors and 0 layout findings at 1440, 1024, 820 and 390;
contrast ok on all thirteen surfaces it walks; touch 0 findings at 390x844;
`doctype.js` Live p50 24 ms against its 30 ms gate. The batch's own sweeps
(`docseg`, `docsuggest`, `cm-reveal`, `docviews`, `docoutline`) and the
engine's (`cm-engine`, `cm-live`, `cm-editor`, `cm-layout`, `cm-search`) all
pass.

The full suite: **one failure, and it is not this batch's.**
`tests/test_debug_health.py::test_renders_fast_on_an_empty_notebook` came in
at a **median of 20.28 ms against a 20 ms budget**, 0.28 ms over, while three
other agents' suites were running on the same box. It is a wall-clock
assertion, this batch changes no Python at all (a diff of the branch limited
to `*.py` is empty), and the file passes on its own in under a second with
the load gone. Not fixed and not papered over: if it starts failing on a
quiet machine, the budget or the endpoint is the thing to look at, not this
branch.

## The exact next step

**DOCUMENTS_PLAN Phase 3, item 1: tables as a real editor.** It is the
largest thing still between this editor and the ones the instruction names,
it is the one construct `cm-reveal.js` asserts as *unchanged* (a table's `|`
markers stay visible because nothing renders them yet), and Phase 3's own
gate is already written: `/table`, Tab between cells, a cell menu, rendered
in Live, byte-exact round trip through Source (PLAN D4's gate). Start at
`docLivePlugin`'s `build`, which is where every other construct is handled,
and at `frontend/vendor/codemirror/`'s `markdownLanguage` (GFM), which
already parses `Table`, `TableHeader`, `TableRow` and `TableCell` nodes, so
the tree work is done.

## Not verified

- **Everything above is Chromium only.** No other browser was available.
- **The contrast ratios use one sampled ground.** `--page` is a gradient, so
  it has no `background-color` to read; the dark figure `rgb(27, 31, 44)`
  comes from `scratchpad/pngpixel.py` on a screenshot of the editor at three
  points (28,31,45 / 26,29,42 / 27,31,44), and light is the token value. A
  token sitting over a card rather than the page has a slightly different
  ground, and none was measured.
- **The callout label with a fold marker.** `> [!note]-` and `> [!note]+`
  are matched by the regex and are believed to hide with the marker, but only
  the bare `[!warning]` form was driven in a browser.
- **Plain view with the fallback textarea.** `docCmViewLanguage` is only
  consulted where the engine is mounted; with `docCmBroken` set, Plain and
  Source are the same thing, which is correct but was never run.
- **A server that dies under you is the sandbox, not the app.** The uvicorn
  behind these sweeps was killed twice mid-run by something outside this
  worktree (`pkill -f uvicorn` from another agent is the likely cause;
  CLAUDE.md warns about it from the other side). It cost one whole
  `gate.sh --sweeps --full` run, whose four sweeps all "failed" with
  `ERR_CONNECTION_REFUSED` and read exactly like a regression. If a sweep
  fails, `curl -s -o /dev/null -w "%{http_code}" $BASE` before believing it.

## The follow-up pass (the coordinator's four, 2026-09-09)

All four of the found-not-fixed list below are now done, in the order asked.

**1. `select.focus()` and select-level `keydown` are dead code app-wide.**
`enhanceSelect` takes the native control out of the tab order, so the direct
call focuses nothing or focuses an `aria-hidden` element. Measured across
seven tabs with every disclosure opened: **all thirteen reachable selects
would have focused the hidden native control**, not one would have reached
its opener. `focusSelect(select)` (app.js, beside `enhanceSelect`) is the one
way to do it; four call sites now use it, three of which were found by the
sweep rather than known (the note's bookmark picker, the chat skills panel,
the note-to-document picker).
**There is no lint and the reason is in the code**: the lints read source as
text and what decides is what a variable holds at runtime, so a name-based
rule would miss `box.focus()` on a select and fire on `picker.focus()` for a
text input. The guard is the helper plus its comment, the check is
`scratchpad/ui-sweeps/selectfocus.js`, and DESIGN.md's recipe index carries
the row. The sweep also corrected the helper twice: it read the opener off
`parentElement` (three selects have something between them and their shell,
so `closest(".select-shell")` is what works), and six selects live inside a
shut `<details>` where nothing is focusable by design, so the sweep opens the
disclosures rather than asserting the browser is wrong.

**2. The caret jumped 28.4px right on a leftward keystroke.** Fixed by
revealing a marker when the caret is on its **line** rather than inside its
range (`rangeRevealed`). `atomicRanges` was correctly ruled out: it steps over
the marker instead of into it. The line is what holds still, so horizontal
movement inside one causes no reflow at all; the one reflow left is on
*arriving* at a line, which is a click or a vertical move and relocates the
caret anyway. Measured after: fourteen steps left, x 642.2 down to 529.4,
strictly decreasing. `cm-reveal.js` asserts the monotonic walk. This
supersedes the phrase "when the caret enters the range" in Phase 2 item 3 and
is recorded in the plan as a decision.

**3. The empty column above References.** Both `.doc-outline-wrap` sections
carried `flex: 1 1 auto`: with a two-heading document the outline was 312.4px
of box around 68.3px of content and References 296.5px around 46px, leaving
**243.1px of nothing** between them. `flex: 0 1 auto` on both; now 85.3px and
69.4px, References 16px under the last entry. A long outline still scrolls
inside its own `max-height` rather than pushing References off (259px of box
around 242px). `docoutline.js` fails on any section more than 40px taller than
its content.
Found while measuring it: **`.linklike` never cancelled the filled button's
`box-shadow`**, so every text link in the app drew an accent halo behind its
words. Measured on the storage help as a transparent background with
`0 2px 10px color-mix(in srgb, var(--accent) 25%, transparent)` still
painting. One line, and the sweep now fails on any visible `.linklike` whose
computed shadow is not `none`.

**4. The missing language modes, costed before adding any.** The bundle was
built four ways with esbuild against the pinned versions; the baseline
reproduces the committed bundle to within its licence banner.
Baseline 787,401 raw / 269,374 gz.
- **swift, r, ini added**: +7,658 raw, **+2,476 gz**, under 1%. Measured in
  the app: Swift 3 colours over 17 styled tokens, R 3 over 6, INI 1 over 5
  (bold sections, 600 keys, muted italic comments, plain values).
- **php refused**: `@codemirror/lang-php` is a full Lezer grammar that also
  pulls in lang-html, **+98,144 raw and +28,563 gz on its own, 10.6% of the
  bundle for one language**.
- **csv refused permanently**: it has no syntax; what it wants is a table.
- A correction to my own earlier note: `r` *does* have a CodeMirror mode. I
  wrote otherwise from memory rather than from the package.
`docviews.js` asserts all five, php and csv included, so adding a mode later
has to come with an update to the decision.

## Gates after the follow-up

`scripts/gate.sh --changed` green at every step. All sweeps green at the head:
`selectfocus`, `docoutline`, `docseg`, `docsuggest`, `docviews` (both themes),
`cm-reveal`, `cm-live`, `cm-editor`, `cm-layout`, `cm-search`, `cm-notes`,
`cm-engine` (0 CSP violations, 0 style tags, 2 adopted sheets on the rebuilt
bundle), `doctype` Live p50 24 ms against 30 ms. And
`scripts/gate.sh --changed --sweeps` at the head:

    ran:     lints node-check ruff changed-tests sweep-errors sweep-docks sweep-contrast sweep-touch
    passed:  lints node-check ruff changed-tests sweep-errors sweep-docks sweep-contrast sweep-touch
    failed:  none

errors.js 0 errors and 0 layout findings at 1440, 1024, 820 and 390; contrast
ok on all seventeen surfaces; touch 0 findings at 390x844.

## Found and not fixed (what is left after the follow-up pass)

- **`scratchpad/ui-sweeps/editor.js` still describes the retired editor**,
  as `documents-engine.md` §2 says. Untouched here.
- **The INI mode does not tokenise values.** `port = 8080` colours the key
  and leaves `8080` plain, because that is what CodeMirror's `properties`
  mode does. Correct enough for an INI file; noted so it is not read as the
  mode failing to load.
