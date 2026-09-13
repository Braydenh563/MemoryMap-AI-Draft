# image-cards: the bottom of a Library picture card, what is left

Shared worktree on `claude/epic-ramanujan-8xocc0` (no worktree of its own, by
the brief: one other agent was editing `frontend/index.html`, `frontend/app.js`
and the Notes CSS at the same time). Server `:8897` and `:8898`/`:8899` for the
clean-data runs, data dirs `/tmp/mm-cards2`, `/tmp/mm-cards2b`,
`/tmp/mm-cards2c`. Not pushed.

## Done

| Item | Where the numbers are |
| --- | --- |
| INBOX 115's image-card line and INBOX 118, the card's foot | INBOX.md, both entries marked; UI_MODERNISATION_PLAN "Decided, 2026-09-12 — what the bottom of a picture card is" |
| The fold's ground and its label's contrast | commit `65cf876`, and `pixelcontrast.py`'s header |
| The menu half ("and funection"), run rather than assumed | `scratchpad/ui-sweeps/imagecardmenu.js` |

Probes: `imagecardfoot.js` (every block under the picture, the gap below the
last one, contrast off the rendered pixels via `pixelcontrast.py`),
`imagecardmenu.js` (opens a card's kebab and works three of its rows),
`imagecardrow.js` (the previous pass's, still current).

## Left

1. **`75a1d62` is not the commit its message describes.** The foot redesign
   was staged file by file and another agent committed the whole index a
   second later, so the image-card work is inside a commit titled "The Capture
   rows run on two control heights". Nothing is lost and nothing is broken;
   the history is just wrong about which change is which, and INBOX and the
   plan both point at `75a1d62` deliberately so the trail still leads
   somewhere. HANDOVER's staging-trap note covers staging a *file* someone
   else is mid-edit in; this is the other half, staging at all while another
   agent may run `git commit -a`. Worth a line there.

2. **The six descriptions start at six different heights** (1440, six seeded
   cards: the picture runs 144 to 249.9px so the text under it starts wherever
   the picture ends). This is the accepted cost of equal card heights with
   optional rows, and it is written into the plan's decision as such, but if
   the owner reads the row as ragged, the two other places to put the
   difference are both things they have already reported: a hole under the
   short cards, or reserved empty rows.

3. **The fold chip is 128.8px of a 156.3px content column at 1440** (82%), so
   on the narrowest tile it still reads as nearly a bar; at the owner's own
   card width, about 330px, it is 39%. If it needs to be smaller on a narrow
   tile the label is the only place left to cut, and "Text in this image" is
   the shortest true thing it can say.

4. **Not swept:** the Files sub-tab rows, which share `library-image-*`
   classes and take the *unchanged* full-width fold by design. The
   `.library-image-usage` chips and `.library-image-usage-lead` still belong
   to those rows only. Nothing in this pass touched them, and nothing
   re-measured them.

5. **The dead glass-off rules the brief asked about are already gone.** No
   rule in `frontend/css/` names `.library-image-edit` or
   `.library-image-delete`; the glass-off list names the tile, its menu button
   and its menu list, all of which are real. `visual-c.md`'s found-not-fixed
   entry has been corrected rather than left to send the next session looking
   for them. The two buttons are still detached objects the kebab clicks,
   which is the behaviour question that entry actually raises.

6. **`tests/test_learned_spec.py::test_boosts_are_bounded_and_decay` XPASSes
   strictly** and fails `scripts/gate.sh --changed` for anyone whose changed
   set selects it. It is a backend spec, untouched by this work, and its
   marker is someone's to remove with the plan line that goes with it.
