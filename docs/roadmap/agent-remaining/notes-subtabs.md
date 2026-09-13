# Brief 22, the three Notes sub-tabs: what is done, what is left

> Companions: [SESSION_BRIEFS.md](../SESSION_BRIEFS.md) Brief 22 ·
> [UI_MODERNISATION_PLAN.md](../UI_MODERNISATION_PLAN.md) ·
> [HISTORY.md](../HISTORY.md) "INBOX resolved" 116, 119, 120
>
> Two sittings. The first (`2d4b19b`, `728bd71`) turned the "Add to document"
> combobox into an adder and regrouped Capture's rows by family; it was cut
> off by a usage limit mid-step. The second is the rest of the brief. Every
> number below was measured on a real Chromium against a running app
> (`bash scratchpad/ui-sweeps/serve.sh 8895 /tmp/mm-notes2`, 1440x900, dark
> unless said otherwise), before and after.

## Done

- **Two control heights** (`75a1d62`). `--control-h-lg` (36px) for the head
  row and the formatting strip, `--control-h` (40px) for every field, picker
  and button you act on, textareas excepted. The last control off the pair
  was `#entry-tags` at 41.6px: the row's height rule covered `select` and
  `button` and never `input`.
- **The preview leaves no line numbers behind** (`3ef6b9b`, INBOX 119).
  Measured 27.2x21.2px above the preview panel in the capture composer and
  again in the note edit form; fixed on the wrap rather than on either
  preview button. The documents editor was already right.
- **A menu is placed by the height it is drawn at** (`6d456ea`, INBOX 119).
  The File under list opened 127.1px above its own opener on a nine-category
  notebook, `wants - drawn + 4` at every notebook size; now 3.8px, whole.
- **The two Ask rows stop repeating each other** (`9b8b4e8`, INBOX 120).
  Settled in `/chat/suggestions`, with reserves so the row keeps its length.
- **Write with AI is two of the same column** (`1472735`). Both columns
  472.6px, both boxes 330.3px, every row at the same y in both, no dead
  space; the instruction and the tags field ride the `.ask-composer` recipe.
- **The Ask card sits on one 9.6px step** (`554739d`), the step the capture
  rows already use, instead of 12.8, 8, 8 and 13.6.
- **The capture box is inside the composer's surface, not a box in a box**
  (`c5242b6`). `mountGutterFor` wraps the textarea, so every
  `.note-composer > …` rule had stopped reaching it: 89px tall with its own
  border, radius, ground and inset shadow against the title beside it with
  none of those. 176px now, and the same treatment as the title.

## The three cards, before and after

`scratchpad/ui-sweeps/notessubtabs.js`, :8895, 1440x900, dark. The before
column is where this sitting started (the two commits of the first sitting
already in), the after is the branch as it stands.

    capture, before   19 controls, 8 rows, heights [1, 36, 40, 41.6, 89]
      150  3  [36, 1]  help, template picker
      198  1  [40]     Optional title
      240  3  [36]     the formatting strip
      282  1  [89]     the note box
      414  1  [41.6]   Tags
      462  5  [40]     Attach, From library, Sketch, Dictate, Improve
      516  3  [40]     Filing: category, Add to document
      564  2  [40]     Save as draft, Save

    capture, after    19 controls, 8 rows, heights [1, 36, 40, 176]
      150  3  [36, 1]  help, template picker
      198  1  [40]     Optional title
      240  3  [36]     the formatting strip
      282  1  [176]    the note box, inside the composer's surface
      492  1  [40]     Tags
      546  5  [40]     Attach, From library, Sketch, Dictate, Improve
      594  3  [40]     Filing: category, Add to document
      642  2  [40]     Save as draft, Save

    writing room, before  10 controls, 4 rows, heights [36, 40, 189.2, 330.3]
      150  1  [36]              help
      228  2  [189.2, 330.3]    the two boxes, unequal
      432  3  [40]              Draft it, Undo, the instruction field
      576  4  [40]              Save as note, tags, Extract notes, Discard

    writing room, after   10 controls, 4 rows, heights [36, 40, 330.3]
      150  1  [36]      help
      228  2  [330.3]   the two boxes, equal
      582  4  [40]      the instruction field with Undo and Draft it, and the
                        tags field opposite it in the other column
      636  3  [40]      Extract notes, Discard, Save as note

    ask, before and after  6 controls, 2 rows, heights [36, 40]
      150  1  [36]   History
      204  5  [40]   the question, the length picker, tune, Ask

    What changed on Ask is the spacing, not the controls: the gaps down the
    card were 12.8, 8, 8 and 13.6 and are now 9.6 throughout, which is the
    step every row of the Capture card sits on.

The `1` in Capture's height set is the hidden native `<select>` the custom
picker stands in front of (absolute, 1px, clipped): invisible, and counted by
the sweep rather than by the eye.

## Open, with what is known about each

- **The Notes categories sidebar overflows at 390px**, on every sub-tab
  including Browse, which this brief did not touch: `errors.js` reports
  `aside#sidebar.card.sidebar-panel 976>706` five times, once per sub-tab
  page. Pre-existing, reproduced at every run this session, not this brief's
  work. The fix belongs with the phone pass (UI_MODERNISATION_PLAN Phase 9):
  the category list needs its own scroll or a collapse at that width.
- **`textarea.autogrow`'s `min-height: 2.75rem` is still shared** between the
  capture box and the Reminders "Magic add" row. It does no harm now (the
  capture box has its own 11rem floor and Reminders measures 44px across both
  its rows), but the sharing is what made the capture box 89px for a while,
  and DESIGN.md's control-height section still describes that row as 44px
  against a 42px button, which is out of date: both are 44.
- **The `.select-native-hidden` shadow selects report odd boxes**
  (`#entry-template` 24x1, `#entry-category` 1x40). They are invisible by
  construction (absolute, clipped) and no sweep should count them as
  controls; `notessubtabs.js` still does, which is why its height set reads
  `[1, 36, 40, 176]` rather than `[36, 40, 176]`. Cosmetic, in the sweep.
- **The note edit form's strip is a clone taken at open time**, so anything
  stateful in the capture strip is cloned with its state. The Preview button
  was fixed here (`3ef6b9b`); the collapse/expand state and the highlight
  colour pickers have not been checked for the same shape.
- **Nothing here was tested with the AI running.** Write with AI's layout
  was measured with the model off, so "Draft it" is disabled and the draft
  box is empty in every measurement; the column heights are the same either
  way (the boxes stretch), but an in-flight draft with its Stop button and a
  long status line has not been seen.
