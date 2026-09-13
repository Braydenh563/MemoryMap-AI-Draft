# Left by the three-dialogs agent, 2026-09-13

INBOX 123 (the quick sketch pad) and both of INBOX 126's dialog bullets (the
popup agent, the meeting recorder) are built, measured in both themes at 1440
and 1024, and pushed: `99cdde1`, `7002cd9`, `0eb515f`.

## Nothing is half-built

- **Quick sketch** (`99cdde1`): `frontend/index.html` `#sketch-toolbar` (six
  `.wb-tool-section` groups), `#sketch-foot`; `frontend/css/02-chat-graph.css`
  from `.sketch-toolbar` to `.sketch-foot`; `openSketch` and
  `syncSketchSizeReadout` in `frontend/app.js` (those two landed inside
  `b6294f2`, which swept the shared worktree). New recipe row in
  `docs/DESIGN.md` (a palette of many tools) with its lint,
  `tests/test_ui_recipes.py::test_a_tool_palette_is_all_sections_or_none`.
- **Popup agent** (`7002cd9`): `frontend/index.html`
  `.command-palette-head` and `#command-palette-close`;
  `frontend/css/07-whiteboard-misc.css` `.command-palette-*`; the close
  binding beside `cmdPaletteOverlay`'s backdrop handler in `frontend/app.js`.
- **Meeting recorder** (`0eb515f`): `frontend/index.html` `.meeting-stage`,
  `#meeting-help`, `.meeting-discard`; `frontend/css/02-chat-graph.css`
  `.meeting-stage`, `#meeting-controls > button`, `#meeting-save-row > button`.
- **The sweep** all three were measured with:
  `scratchpad/ui-sweeps/popupdialogs.js`. It reports rows (clustered by each
  control's vertical centre, so a 16px slider beside a 36px button is not
  read as a wrap), distinct control heights, insets and corners per bar, every
  field's border width, and a contrast pass that labels a translucent chain
  rather than failing it.

## The second pass on the sketch bar

Reported again after the first pass ("the quick sketch top dock still needs a
better redesign", with a screenshot of Paper alone on a second row and the
right half of the first row empty). It did not reproduce at 1440 or 1024 with
the default appearance settings, and `scratchpad/ui-sweeps/sketchbar.js` is
what found it: the card is `min(900px, 96vw)` and everything inside it is
sized in rem, so Large text (18px root) or Spacious density (a 1.35x spacing
scale) gives the contents width the card never gets. Measured before: 938px of
content in a 796px bar at both settings together, 821 in 831 at the defaults,
which is 10px of slack and the reason one machine saw a tidy bar and another
saw a wrap.

Now: controls on `--target-min` rather than `--control-h-lg`, Edit and Paper
merged into one Canvas group, the separator's fixed margin given back to the
grow, and `flex: 1 0 auto` on the sections so the leftover is shared between
the groups instead of left in a heap at the right-hand end. One row at 1440 and
1024 on all four settings; 820 still wraps on Large text, and that is the touch
step (`--target-min` is 2.75rem below 820) rather than a layout fault.

## Found, not fixed

- **A filled button is 2px shorter than every tonal button beside it, app
  wide.** `button` carries `border: none` (01-forms-settings.css) and `.ghost`
  a 1px edge, so a filled control measures 40px in a row of 42px ones: seen in
  the meeting save row and in every other dialog action row in the app. Both
  dialogs this agent touched pin their own rows to `--control-h-lg` instead.
  The one-line fix is `border: 1px solid transparent` on the base `button`,
  and it moves every filled button in the app by 2px, so it needs its own
  measurement pass (docks pin their heights and would not move; the chat
  composer, the note toolbars and the dashboard widgets would).
- **The meeting dialog's head row holds two heights**, a 28px `.ghost.small`
  Close beside the 32px `.graph-help-toggle`. Both are app-wide recipes
  ("every '?' in the app is this button", 03-dashboard-widgets.css), so this
  is a question about the two recipes rather than about this dialog.
- **`--radius-inner` had no users before this work.** DESIGN.md rule 3 and
  INBOX 101 declared the token in `10-responsive.css` and nothing reached for
  it; the sketch pad's toolbar, canvas and foot and the meeting stage are the
  first four. Every other surface inside a `.card` still draws `--radius-lg`,
  which is the concentric rule half-applied.
- **A colour swatch is 1rem and never grows for a finger.** `.sketch-color`
  is a fixed size at every width, so on a phone the seven ink dots are 16px
  targets inside a bar whose buttons step up to 44. `touch.js` does not look
  at this dialog, which is why it has never been reported. The fix is a step
  on the swatch under 820px and a re-measure of the bar at that width, where
  it already wraps into two rows on Large text.
- **The popup agent's results pane is unmeasured with a conversation in it.**
  Everything here was measured on the empty state: this sandbox has no model,
  so no turn could be rendered. `.command-palette-results` keeps its own
  `--card-pad-x` inset, and that is reasoned, not observed.

## Not done, and whose it is

- **INBOX 123 and 126 are not marked or moved.** `docs/roadmap/INBOX.md` was
  dirty with another session's work in the shared worktree every time this
  agent reached a step boundary, and `git add` on it would have taken their
  half-written edit. 123 is fully resolved by `99cdde1`; 126's second and
  third bullets by `7002cd9` and `0eb515f`; 126's first bullet (the Ask
  sub-tab's answer head) belongs to the agent that left `ask-head-ocr.md`.
