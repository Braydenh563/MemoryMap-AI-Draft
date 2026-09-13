# Left by the logs, cards and links agent, 2026-09-13

Three surfaces the owner reported that day, all built, measured in both themes
at 1440 / 1024 / 820, and pushed: `6e5db00`, `3209be1`, `b7c1c02`, `a34867b`.

## Nothing is half-built

- **The Settings → Logs head** (`6e5db00`): `frontend/index.html`
  `.dock[data-dock-name="settings-logs"]`; `frontend/css/06-timeline-dialogs.css`
  (the rules the dock recipe now owns, and this dock's own `--dock-find` basis);
  `frontend/settings.js` `renderCopyLogsLabel` and `downloadSupportBundle`;
  `tests/test_dock_grammar.py` `ON_THE_GRAMMAR`. Sweep:
  `scratchpad/ui-sweeps/logsdock.js` (docks.js walks the seven tabs and never
  opens the settings modal, so this is the same reading for the one dock inside
  it). Two rows to one, nine controls at four heights to six at one.
- **The picture card's foot** (`3209be1`): `frontend/library.js` (the facts
  line, the fold's one-word label on a card);
  `frontend/css/00-tokens-shell.css` (`.library-image-caption`'s rank and its
  reserved second line); `frontend/css/07-whiteboard-misc.css`
  (`.library-image-meta`). Sweep: `scratchpad/ui-sweeps/imagecardfoot.js`.
- **The saved link rows** (`b7c1c02`): `frontend/library.js` `bookmarkRow`,
  `metaLine`, `bookmarkAddress`; `frontend/css/01-forms-settings.css`
  `.bookmark-list` through `.bookmark-pinned`. Sweep:
  `scratchpad/ui-sweeps/linkrows.js`. Two row heights to one, six controls to
  two, five type sizes to two.
- **The two recipes** (`a34867b`): DESIGN.md's index gained "a row in a list"
  and "one line of facts", each with its lint in `tests/test_ui_recipes.py`.

## Found, not fixed

- **The Files rows' description grew 5.1px.** `.library-image-caption` is
  shared by the picture cards and the Files rows, and its size moved from
  `--text-sm` to `--text-md` so a card would have two type ranks rather than
  three. That is right for a Files row too (its own prose against its own
  facts line), but it is arithmetic from the card's measurement, not a Files
  measurement: this sandbox's seeded media are all images, so the Files
  sub-tab renders nothing and the rows were never on screen. Seed a PDF
  (`/media/upload`) and run `imagecardfoot.js` against the Files sub-tab if
  the rows are ever reported.
- **Two pictures in a gallery row are still different sizes when one card has
  nothing to say.** UI_MODERNISATION_PLAN's decision block now records why (a
  subgrid was built and measured: it equalises everything and puts 75px of
  hole under the shortest card). The remaining variance is cards with no
  caption and no facts, which take a taller photograph instead of a hole.
- **A filled button is still 2px shorter than a tonal one beside it**, the
  finding `popup-redesigns.md` left. Untouched here; it moves every filled
  button in the app and wants its own measurement pass.
- **The app's own working tree was broken for about an hour mid-session**:
  `frontend/app.js` bound a handler to `#timeline-feed` while `index.html` had
  no such element, so every page load threw and everything after that listener
  never ran. Another agent's in-flight work, and green again on HEAD by the
  end. It is the exact failure `scripts/gate.sh --staged` exists for. Measuring
  around it needed `git archive HEAD | tar -x -C <dir>` plus a copy of this
  agent's own uncommitted files, served from there: worth knowing, because the
  worktree is shared and this will happen again.

## Not verified

- **A real log stream under load.** The live pill reads `● live` in green and
  the filters hide the right count (275 records on the seeded server), but
  nothing here produced a burst of records, so Follow's own scroll-pinning was
  not exercised beyond toggling it.
- **The Files sub-tab and the "Attach from Library" picker**, both of which
  build the same tile as a picture card without a frame. The rules changed
  here are all scoped by `:has(> .library-image-frame)` or by a class only the
  card carries, but only the gallery was on screen.
- **Anything below 820.** The three surfaces were measured at 1440, 1024 and
  820. Phase 9's phone band (< 600) was not swept.

## Next step, if this comes back

The one thing that would settle the picture-card complaint for good is a
gallery whose cards are all captioned, which is what the owner's own notebook
looks like and what the seeded six are not: in that case every card is already
pixel-identical (240.7px, a 144px picture, a 95.7px foot). If it is reported a
fourth time, seed six captioned images, measure, and the answer will be about
the *filename on the photograph* or the picture's aspect, not about the foot.

## INBOX 145 overlaps this work, and is not covered by it

Filed while this agent was building (`18ec138`), on the same cards: the
selection tick floating over the picture with no ground, the filename band
sitting on grey on some cards and on open sky on others, a caption that is the
picture's own OCR text rather than a description, and an opened fold growing
its card to 620px beside a 260px neighbour. None of those is the foot, and
none of them is fixed here.

One number for whoever takes it: an opened fold adds up to 288px, because
`.library-image-card-fold > .library-image-reading-body` caps its scroller at
18rem, and every card in the *same grid row* grows with it (measured at 1440:
six cards 240.7px, all six 390.7px with one fold open, the opened card's body
159px wide inside a 180px tile). A 620px card beside a 260px one is therefore
two cards in different rows, not a card that failed to line up, and the lever
if that reads badly is the 18rem cap rather than the layout.
