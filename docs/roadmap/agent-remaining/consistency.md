# Consistency sweep: what is left

The brief behind this file is the owner's report, in his words:

> "in a lot of the application areas, each of the menu items and elements feel
> very disconnected and separate, maybe due to their backgrounds or obviousness
> as separate elements", "the dropdown menus and elements in them need to not
> feel disconnected", "the notes top dock feels very squished and the title
> feels like it has no room, I feel like all these top docks need a unified bar
> where the buttons and dropdowns and comboboxes feel a part of that and not
> just separated buttons chucked together at the top of the panel", "there are
> areas where the icons and accompanying text dont align", "consistent design,
> things flowing and feeling connected".

Eight numbered items came out of that. **Seven are closed with measurements.**
Everything below is what a next session can still pick up.

All CSS from this work is in **`frontend/css/08-consistency.css`**, linked last
in `index.html` and registered in `tests/_css_paths.py`. `00-07` are untouched
by design: their concatenation order is load-bearing, and a cross-cutting
decision has no single section it belongs in. **Keep adding to 08 rather than
reopening the earlier files.**

```bash
bash scratchpad/ui-sweeps/serve.sh 8821 /tmp/mm-consist
cd scratchpad/ui-sweeps
BASE=http://127.0.0.1:8821 SCRATCH=/tmp/mm-consist PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  node seed.js && node seed-images.js       # once per data dir
# then any of: wbmenus.js menurows.js imagechips.js imagebadges.js docksurface.js
#              dockodd.js heads2.js wraps.js capturebtns.js setindent.js
#              dialogs.js widgetdrive.js promptdrive.js iconalign.js gapwhy.js
#              keys.js wbtopbar.js whichrule.js dompath.js selcheck.js
```

---

## Status by numbered item

| # | Item | State |
| --- | --- | --- |
| 1 | One menu recipe, no fill at rest | **Done**, all five whiteboard menus now measured too |
| 2 | `details > summary` in a card is a flat header | **Done** |
| 3 | Top docks as one bar | **Done** for all twelve docks plus the Dashboard toolbar and the whiteboard top bar's controls |
| 4 | Icon and text alignment | **Done**, 2 gap families left and both are deliberate |
| 5 | Form footers as one action bar, FAB clearance | **Done**, including the two 1024 wraps |
| 6 | One toggle-row recipe | **Done** |
| 7 | Meta looks like meta | **Done**, image chips now measured on a seeded gallery |
| 8 | No em-dashes in new copy or comments | **Held**, 0 in `08-consistency.css` |

---

## What is actually left

### 1. The documents editor toolbar (`.doc-toolbar`)

**The one surface in item 3's list still off the recipe.** It has had the bar
surface since the "fix the toolbar" round, so only its *controls* are open:
apply the `.dock > * > button.ghost` half of the recipe scoped to
`.doc-toolbar` and re-measure fills, radii and heights the way
`scratchpad/ui-sweeps/heads2.js` does.

Not done here because another agent owns the documents toolbar this round. Do
not start it until that work has landed, then compare its controls against
`.dock`'s and reconcile in 08.

### 2. The OCR workspace head

Not in the original brief, but it is the same shape and
`05-sidebars-themes.css:1269` names it alongside `.doc-toolbar` and
`.library-head` as having had the same fault.

**Could not be measured**: `.ocr-toolbar` only exists once a file is open in
the OCR workspace, and the seeded notebook has no path to one without a real
scan. `wbtopbar.js` already has a probe pointed at it; the missing piece is a
way to get a scanned file into the sweep's notebook. Nothing is assumed about
it either way.

### 3. Two icon-gap outliers, both judged deliberate

- **10 meta chips at 3.6px** (`.chip.when`, `.map-chip`) against the app's
  242 controls at 6.4px. `--space-1` for a 12px chip is a size relationship,
  not drift. Revisit only if the owner reads them as inconsistent.
- **`#conv-browse-all` at 17.7px, at 1024 only.** It is `width: 100%` with
  `justify-content: center`, so its visible gap is a function of the sidebar's
  width rather than a gap declaration that drifted. One control.

### 4. "Advanced response settings" sits 20.8px right of its siblings

54 of the 55 Settings headings now share one left edge (546px). The one left
is inside a `<summary>` (`#sampling-box`) and the disclosure marker precedes
it. Fixing it means hiding the native marker, and hiding it without drawing a
replacement trades a visible affordance for an alignment. Decide that
trade-off before touching it.

### 5. One cross-theme difference, in a token pair rather than a surface

In light, `--field-inset` and the segmented track are both
`rgba(31, 36, 48, 0.07)`, so a search field and a segment track are one tone.
In dark they are `rgba(0, 0, 0, 0.28)` and `rgba(255, 255, 255, 0.08)`, two
tones. Light flattens a distinction dark makes. Found while re-measuring the
docks in both themes; it belongs to whoever owns the token file, not to a dock.

---

## The measurement lessons worth keeping

These cost a round each here and will cost the next session the same.

- **Park the pointer before measuring a rest state.** The first whiteboard-menu
  run reported a row filled at rest that was only under the virtual mouse.
  Hover is not rest. `wbmenus.js` does `page.mouse.move(1430, 890)` first.
- **`--control-h` has no root value.** It is declared fourteen times in scoped
  blocks at 1.875rem, 2rem, 2.25rem and 2.5rem, so a rule that can land
  anywhere resolves to whichever surface it happens to sit inside. Using it in
  the menu recipe returned 34/33/35.17/22.39px in one popover.
  **`--control-h-lg` is declared once, at the root.**
- **Ask the browser which rule wins, and ask for the shorthand.**
  `scratchpad/ui-sweeps/whichrule.js` lists every rule matching an element and
  declaring a property, in cascade order, which grep cannot do: it cannot see
  specificity and it cannot see that a selector matches nothing. Ask it for
  `background`, not `background-color`: a `var()` inside a shorthand is stored
  as a pending substitution, so the longhand reads empty and the winning rule
  looks absent.
- **A selector written from the feature rather than from the markup matches
  nothing, silently.** `.library-image-model-chip` was in 08 for a whole round
  and `document.querySelectorAll` for it returns 0.
- **`getBoundingClientRect().left` does not move when something is indented
  with padding.** A landed fix measured as no change at all until the sweep
  read the content edge instead.
- **Count the way the grammar counts.** A segmented control is one control, not
  its track plus its items, and the visually hidden native `<select>` behind an
  enhanced one is not a control at all. Counting them reports four of five
  docks at two heights and the Timeline at three, which is a fact about the
  counter.

## The one bug shape worth carrying forward

Three of the eight items turned out to be the *same* rule doing damage in three
places:

```css
/* 07-whiteboard-misc.css:3640 */
summary:not(.icon-only):not(.icon-button) {
  background: var(--ghost-btn-bg);
  border: 1px solid var(--ghost-btn-border);
  padding: var(--space-2) var(--space-3);
}
```

It gives every `<summary>` in the app a resting tonal fill, an edge and button
padding. Six hundred lines earlier, `07-whiteboard-misc.css:3053` sets a hover
tint on the same selector and its comment says a resting fill was *deliberately
refused* because it "would turn every collapsed section into a button-looking
slab and compete with the real buttons inside them". The later rule wins on
order, so what ships is the thing the first comment predicted.

**If a fourth `<summary>` is reported as "looking like a button", this is why.**
The split 08 makes is: a summary in a dock or a toolbar *is* a control in a row
of controls and keeps the fill; a summary that heads a folded section, or that
is marked up as a chip, does not. Add the new case to the flat list in 08 at
(0,3,1) or better so it wins on weight rather than on file order.
