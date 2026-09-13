# The design system

Everything visual in this app is built from the tokens below. This document is
the contract: **new features use these, and `tests/test_style_scale.py` fails
the build if they don't.**

## Why this exists

Reported, after a round of real use:

> *"the way spacing, alignment and margins of all the ui features in each tab
> aren't consistent and it changes each tab. I want the UI across the
> application to be very professional, consistent and clean. not to look like
> it is just a bunch of ai generated slop features joined together."*

That was accurate, and the cause was structural rather than cosmetic. Each tab
was built in its own session, reaching for whatever value looked right at the
time, and `style.css` grew past 5,000 lines with nothing shared underneath it.
Measured before any of this was fixed:

| | Before | After |
| --- | ---: | ---: |
| Distinct spacing values | 25+ | 9 |
| Distinct font sizes | 37 | 10 (+3 hero one-offs) |
| Distinct corner radii | 12 hard-coded px | 3 tiers, all derived |
| Page gutter treatments | 4 across 7 tabs | 1 |

**None of those numbers is the point on its own.** Seven values between 0.3rem
and 0.6rem all mean "a small gap"; nine font sizes between 0.74rem and 0.85rem
all mean "slightly smaller than body text". Two things that are *almost* the
same size, next to each other, is exactly what reads as unconsidered, nothing
lines up, and no value means anything because every one is slightly its own.

---

## The tokens

All defined in `:root` in `frontend/css/00-tokens-shell.css`: the first of
the eight files `style.css` was split into (ROADMAP.md Priority 0 item 2), so
every later file's `var()` calls have it loaded before they need it.

### Spacing: `--space-1` … `--space-9`

```
--space-1: 0.25rem    --space-4: 0.6rem     --space-7: 1.25rem
--space-2: 0.4rem     --space-5: 0.8rem     --space-8: 1.5rem
--space-3: 0.5rem     --space-6: 1rem       --space-9: 2rem
```

Use for every `margin`, `padding`, `gap`, `row-gap` and `column-gap`.

Every step is wrapped in `calc(… * var(--density))`, so the density setting
(Settings → Appearance: compact / comfortable / spacious) tightens or loosens
the **whole interface** with one multiplier. It used to be nine rules in two
places, each re-stating literal paddings for the four components somebody
remembered, `.card`, `.layout`, `.dash-hero`, `.entry-list li`: so "compact"
tightened those four and left every dialog, chip row, toolbar and settings pane
at comfortable. **A density rule that names a component is that regression
coming back**, and the lint says so.

The scale was **extracted, not invented**: the nine steps are the modes of the
distribution that was already in the file, which is why adopting it moved 311
values by no more than 0.1rem each. It is deliberately denser at the small end,
because that is where interface spacing actually lives.

### Type: `--text-xs` … `--text-display`

```
--text-xs:      0.7rem    badges, counters
--text-sm:      0.75rem   dense metadata, small caps labels
--text-base:    0.8rem    secondary UI text
--text-md:      0.85rem   the workhorse, chips, list rows, controls
--text-lg:      0.92rem   form labels, settings copy
--text-body:    1rem      prose, card titles
--text-h3:      1.15rem   panel headings
--text-h2:      1.3rem
--text-h1:      1.7rem
--text-display: 2.2rem
```

Sizes above `--text-display` exist for three single hero elements and are
allow-listed individually in the lint. **A display size is a one-off, not a step
other components may reach for**: if a fourth thing wants 2.4rem, that is a
sign it should be using `--text-display` instead.

### Corners: derived from the user's setting

```
--radius-sm:   calc(var(--radius) * 0.3)   chips, inputs, small controls
--radius-md:   calc(var(--radius) * 0.6)   buttons, inner panels
--radius-lg:   calc(var(--radius) * 0.8)   cards, dialogs
--radius-pill: 999px                       pills, round buttons
```

`--radius` is a **user preference** (Settings → Appearance, 2–16px across the
built-in themes). Before this, ~90 declarations used literal pixels, so choosing
square corners squared the cards and left every chip, popup and button rounded.
Deriving the tiers makes the whole interface respond to one setting, which is a
behaviour fix as much as a consistency one.

The multipliers are chosen so each tier lands within a pixel of the value it
replaced at the default 14px. **Never pin a tier to a constant**: the lint
checks for this, because doing so silently disconnects the slider again.

### The page shell: `--page-gutter`, `--page-top`, `--page-bottom`

```
--page-gutter: var(--space-9)   /* 2rem */
--page-top:    var(--space-6)
--page-bottom: var(--space-9)
```

Applied once, by `.tab-page`. Seven tabs previously drew four different
gutters: the side inset was 2rem in five separate rules, but the space above
the first element was 1rem on Notes and Chat, 0 on Documents, and 0.8rem on
the Dashboard, Reminders and Graph, **each on top of `.tab-page`'s own
0.8rem**, so content began 1.8rem down one tab and 0.8rem down the next.

> **The rule:** a page's own container sets its internal `gap` and nothing
> else. The distance from the window belongs to the shell.

The narrow-screen tightening happens once, in a single media query on `:root`.
Per-page media queries shrinking to different numbers is how the desktop drift
got faithfully reproduced on mobile.

### Colour

The palette is already tokenised and theme-aware, every one of these has a
light and a dark value, and the lint enforces that:

```
--ink   --muted   --border   --card   --accent   --accent-soft   --chip-bg
--ok / --ok-soft      --warn / --warn-soft      --error / --error-soft
```

**Never write `var(--token, #fallback)` for a colour.** That pattern looks like
a safety net and is the opposite of one:

- If the token *doesn't* exist, the fallback is what renders, silently, in
  both themes. `var(--danger, #e2534b)` appeared in six rules and `--danger` was
  declared nowhere, so all six ignored dark mode entirely while looking
  perfectly correct in the stylesheet. The theme-aware `--error` had existed
  the whole time and is a different red in dark mode.
- If the token *does* exist, the fallback is dead code that would let a rename
  keep working while quietly showing the wrong colour.

`var(--text-muted, inherit)` was the same bug, quieter: the token was never
declared, so the text simply inherited and was never muted at all.

Fallbacks are allowed for font stacks and numeric defaults (`--mono`,
`--ui-font`, `--bg-art-opacity`) and for two tokens that legitimately fall back
to another token. Everything else is caught.

Literal colours are still correct in exactly one place: the sketch palette,
where the hex value *is* the data, and the accent presets, which are
definitions.

### Elevation: `--shadow-sm`, `--shadow-md`, `--shadow-lg`

```
--shadow-sm   resting cards, list-row hover, message bubbles
--shadow-md   floating panels, dropdowns, active/lifted tabs (= --glass-shadow)
--shadow-lg   a dragged card, a dialog's own depth, the "off the surface" tier
```

Added by the apple-design audit (ROADMAP §35L) after finding twelve
hand-written `box-shadow` values, six-plus different blur radii, opacities
from 0.05 to 0.5, one tinted family (`rgba(31, 38, 135, …)`, matching
`--glass-shadow`) and one flat-black family living side by side. Most of the
flat-black ones never adapted in dark mode the way `--glass-shadow` already
did, because they weren't built from it. All three tiers are dark-mode-aware
(`--shadow-sm`/`--shadow-lg` scale off `--shadow-intensity`, the same knob
Settings → Appearance already drives; `--shadow-md` is `--glass-shadow`,
already themed). Two literal shadows remain on purpose: the lightbox image's
(its backdrop is always near-black regardless of theme, so a themed shadow
would be wrong there) and the accent-glow on the CTA button family, which
carries the user's chosen accent colour via `color-mix()` rather than the
neutral elevation scale, a coloured glow, not a depth cue.

### Motion: `--motion-fast`, `--motion-base`, `--motion-slow`

```
--motion-fast: 0.12s   hover/press feedback, checkbox/toggle state
--motion-base: 0.16s   the default: colour, background, border, opacity
--motion-slow: 0.2s    a bigger move, panel/sidebar open, card lift
```

Same extraction method as the spacing/type scales: ten distinct transition
durations in the wild (0.08s-0.25s, one written as `120ms`) collapsed to the
three that were actually the modes of that distribution. Applied to every
`transition:` duration in `frontend/css/*.css`; `animation:` keyframe timings
(entrance/exit effects tuned to their own motion, not interactive feedback)
were deliberately left alone rather than mechanically swept, since a
keyframe's duration is part of what makes that specific effect read right,
not a value drifting for no reason.

**Not done, said plainly:** motion is a user setting (`prefers-reduced-motion`)
that only some components still honour, each with its own `@media` block,
see "What is not done yet" below. There is no gesture-driven motion anywhere
in the app yet (drag/resize move the DOM directly; nothing hands off release
velocity into a spring), so nothing here contradicts the apple-design skill's
"avoid fixed-duration transitions for anything gesture-driven", that rule
doesn't apply until something *is* gesture-driven.

---

## Glass & materials

Every floating or resting surface in the app commits to one of two opacity
tiers, this was itself the subject of a full audit (a user-supplied
checklist's Part B) that found and fixed real drift, so the rule below is
enforced, not aspirational.

```
--card          55% opaque: a page surface, meant to be seen *through*
--modal-bg      96-98% opaque: floats over arbitrary content, must stay legible
--glass-blur    18px: the one blur radius; do not hand-pick a px value
--glass-shadow  the one popup/floating shadow (= --shadow-md)
--glass-border  the one glass-surface border colour
```

**The rule:** anything that floats *over* other content, a popup, a
dropdown menu, a folded-away options panel, a toolbar strip drawn on top of
a canvas, declares all four together: `background: var(--modal-bg)`,
`backdrop-filter: blur(var(--glass-blur)) saturate(150%)` (+ `-webkit-`
mirror), `box-shadow: var(--glass-shadow)`, `border: 1px solid
var(--glass-border)`. A page-level surface that content scrolls *inside*,
a card, a sidebar, uses `--card` instead. Mixing the two, or picking a
one-off blur radius or shadow, is the bug this section exists to prevent:
found live in `.whiteboard-floating-panel`, `.graph-trace`/`.graph-options`,
and `.timeline-band` (three different blur radii, 8px, 12px, and the
18px token, across three tabs was the most visible version of the
problem), all fixed by conforming to the rule above rather than by
inventing a third option.

### Surface tiers, and the border budget

Measured before this existed, on Settings → Tools it can use: the modal drew
a hairline, the group inside it drew a hairline, and all 54 rows inside the
group drew one more, three nested boxes, each saying "this is a thing" with
the same 1px line, so none of them said anything. Skills, Personas, Templates
and the Notes list had the same shape at two deep.

```
--surface-1  the pane: .card, .modal-card, a popover. Glass, and the only
             tier that may carry a hairline or a rim.
--surface-2  a group inside a pane (.settings-group, .entry-list li). A faint
             ink tint, no border.
--surface-3  a row inside a group, or a hover (.provider-option, a list
             inside a settings group). One step deeper.
--divider    the line *between* rows in a list (.setting-row, .extras-row).
             Lighter than --border: a separator, not an edge.
```

**The rule:** a line on the outermost surface only; everything inside it is
grouped by tone and whitespace. Inner rows keep a `1px solid transparent`
border so their geometry does not move and so `[data-contrast="on"]` can
colour the line back in (`02-chat-graph.css`). A selected row is a fill
(`--accent-soft`), never a fill plus an accent edge, the edge was the
innermost of the three lines above. `--surface-2` is tinted with ink rather
than white on purpose: a white tint (`--inner`) is invisible on the
near-white modal, which is where most groups live.

A sticky row inside a tinted group (`.tool-filter-row`) has to composite the
tint over the opaque modal colour, not paint the modal colour alone,
otherwise it shows as a lighter slab inside the group.

### Where the blur is allowed to be

Measured at 1366x768 (`scratchpad/ui-sweeps/weight.js`, INBOX 49): with
every `.card` blurred, the blurred area at rest was 32% of the viewport on
the dashboard and over 80% on the notes, chat and graph tabs, a full-screen
filter pass per scroll on an integrated GPU, and all it blurred was the
page art, which is already a soft gradient. So a content panel (`.card`,
`.dash-hero`, `.sidebar-panel`, the status bar) keeps the fill, the border
and the rim and has **no `backdrop-filter`**. Blur belongs where something
scrolls under a surface or where the surface floats over content: the top
bar, the sticky sub-tab strips, `.card.glass`, the dialogs, popovers,
docks, the graph's zoom pill, `.scroll-top`. With the animated background
on, the cards frost it again (`:root[data-bg-art="on"] .card`): that is
the one place a card blur shows something, and the owner asked for it. The gate, kept by
`tests/test_perf_mode.py` and the sweep: under 10% of the viewport blurred
at rest on every tab (measured 6 to 10% after).

**Performance mode** (Settings, Effects & accessibility; the `perf`
preference, `auto | on | off`) takes the rest off: `data-glass="off"`,
`data-motion="reduced"` and the graph worker resting twice as long between
ticks, without rewriting the person's own glass and motion choices. "Auto"
turns it on for a machine reporting 2 cores or 4 GB or fewer, or an OS
`prefers-reduced-transparency` setting, and says so once in a toast.
`theme-boot.js` resolves the same rule before first paint.

### Turning it off

`:root[data-glass="off"]` is a standing user preference (Settings →
Appearance), not a special case to special-case around. It swaps `--card`
to `--modal-bg`'s opaque value and zeroes `backdrop-filter` on an explicit
selector list, currently 35+ selectors covering every popup, toolbar and
floating panel named above. **Adding a new glass surface means adding it to
that list too**: a panel missing from it stays glassy even with the
setting switched off, which is how three of the Part B violations were
found (the fix and the fallback drifted independently because they lived in
different rules).

### Palettes

Eight curated palettes, each with an explicit light and dark pair,
`:root[data-palette="X"]` / `:root[data-palette="X"][data-mode="dark"]`:
**Aurora** (default, no attribute needed), **Parchment**, **Sage**,
**Ocean**, **Lagoon**, **Ember**, **Plum**, **Carbon**. Carbon is the
"quiet, non-glassy" option some users want, it does not override
`--glass-opacity`/`--glass-blur` itself (it is still built from the same
glass system as the other seven), so reaching that quiet, flat look is
**Carbon palette + the Glass-off toggle together**, not a hard-coded
exception baked into one palette. Composing two orthogonal settings this
way is deliberate: a palette-specific override would be a second, competing
mechanism for the same effect the toggle already provides everywhere else.

---

## The recipe index: use these, nothing else

The owner, after a run of "the menu is crushed", "the panel clips", "the
buttons feel separate": every one of those came from a surface built by
hand instead of from the recipe the rest of the app uses. A new piece of
UI starts here. If the need is not in this table, the recipe is added to
this table and its lint in the same commit as the feature, never after.

| You need | Use | Guarded by |
| --- | --- | --- |
| A tab or sub-tab's control bar | `.dock` with `.dock-identity`, `.dock-group`, `.dock-actions`; seven controls at most, one filled | `tests/test_dock_grammar.py`, `scratchpad/ui-sweeps/docks.js` |
| A palette of many tools (a drawing bar, where every control is a tool rather than one of seven choices) | `.wb-tool-section` around one `.wb-tool-section-label` and one `.wb-tool-section-row`, all of them in one bar; the group boundary is the hairline `.wb-tool-section + .wb-tool-section` draws in `--divider`, and nothing sits in the bar outside a section. Used by the whiteboard rail and the sketch pad's toolbar | `tests/test_ui_recipes.py` |
| A menu behind a button | `kebabMenu(items, ariaLabel)` in app.js (positions, clamps, escapes clipping, closes on outside click) or `details.dock-menu` in markup | `tests/test_ui_recipes.py` (hand-built menus may not multiply) |
| A menu item | `makeMenuItem("ph:icon Label", title, run)` | same |
| A dropdown of values | a plain `<select>`; `enhanceSelect` restyles every one at boot | `tests/test_frontend_handlers.py` |
| Focus on a `<select>` | `focusSelect(select)` in app.js. **Never `select.focus()`**: `enhanceSelect` takes the native control out of the tab order (`tabindex="-1"`, `aria-hidden`), so the direct call focuses an aria-hidden element or nothing at all, silently. Measured across seven tabs: all thirteen reachable selects would have taken the focus onto the hidden control. The same goes for a `keydown` bound to a select, which never fires. | `scratchpad/ui-sweeps/selectfocus.js` (it cannot be a lint: what decides is what the variable holds at runtime, not what the source says) |
| Help longer than one line | one line in place, the rest behind a `data-help-for` '?' button and a `.help-body` popover | `tests/test_ui_signatures.py` |
| An on/off setting | `label.setting-check` with the switch first | `scratchpad/ui-sweeps/switches.js` |
| Two to four exclusive choices | `.seg` with `aria-pressed` | `tests/test_ui_signatures.py` |
| A brief confirmation | `toast(text)`; with one action, `toastAction(text, label, fn)` | |
| A dialog | `.card.modal-card` (settings-sized) or `.card.space-dialog` (small), opened through the app's modal helpers, never a bare `<dialog>` with its own chrome | `tests/test_ui_signatures.py` |
| A floating panel over a canvas | `.card.glass` plus the panel on the `[data-glass="off"]` list | `tests/test_ui_recipes.py` |
| A ring of actions around a canvas item (a radial) | `.wb-map-radial` with `.wb-map-radial-slot` children: `role="toolbar"` (a ring is not a list you walk with the arrows), no surface behind the ring so the item it acts on stays visible, each slot placed with `left`/`top` from `--wb-radial-r` and **never** with `translate`, which the press cue owns | `tests/test_ui_recipes.py` |
| Any surface that blurs | on the `[data-glass="off"]` list, radius from `--glass-blur`, never a px | `tests/test_ui_recipes.py`, `tests/test_style_scale.py` |
| A button | the ramp below: filled (one per surface), ghost, icon-only with `aria-label` | `tests/test_dock_grammar.py` |
| A chip | `.chip`; a chip is a fact, never an action (an action is a button) | |
| A panel head inside a card (a title with something to do beside it) | `h3.panel-head`: identity, then **at most one** chip, then an all-icon `aria-label`led action group; the row is `nowrap` and the chip is the only zone that may shrink (it ellipsises, with the whole phrase on its `title`). Every ancestor between the chip and the card needs `min-width: 0` or the head simply grows past its column | `tests/test_ui_recipes.py`, `scratchpad/ui-sweeps/askhead.js` |
| A list that says where you are in something (an outline, a page strip) | the row you are on takes `aria-current` (`"location"` inside a document) and is painted **from that attribute**, `--accent-soft` plus a weight step, never colour alone and never a fill plus an accent edge; if the list scrolls, the marked row is brought into view by adjusting that box's own `scrollTop`, never `scrollIntoView` (it walks every scrolling ancestor, the page included) | `tests/test_ui_recipes.py` |
| A row in a list | `.timeline-row`'s shape, on `--row-h` and `--row-gap`: a grid of mark, content and actions, the content column the only one that grows, a transparent 1px border so the hairline it gains under the pointer moves nothing, and the ground arriving with the pointer rather than an edge drawn around every row | `tests/test_ui_recipes.py` |
| One line of facts about the thing a row or card names | `.library-file-meta` plus a handle of its own: short statements, dot separators, `--text-xs`, `--muted`, one rank. Never a block per fact, which is what all three of the Library's "this needs a redesign" reports turned out to be | `tests/test_ui_recipes.py` |
| Empty state | `.empty-state` with one sentence and one action | |
| Spacing, type, radius, shadow, motion | the tokens above; a px in a stylesheet is a lint failure | `tests/test_style_scale.py` |
| Copy | sentence case, no em-dashes, no exclamation marks, one line per section | `tests/test_no_em_dashes.py` |

The sweeps that say whether a new surface matches the rest are
`errors.js`, `contrast.js`, `docks.js`, `touch.js`, `menus.js` and
`kebab-viewport.js` under `scratchpad/ui-sweeps/`; a UI change is not
done until they are green and its numbers are in the commit message.

## Taken from Liquid Glass and the Human Interface Guidelines (2026-09-09)

Read from Apple's own pages (the Liquid Glass overview, "Adopting Liquid
Glass", and the HIG's materials, layout, toolbars, menus, sheets,
popovers, typography, colour, motion, buttons, tab bars, sidebars, search
and accessibility pages). What transfers to a web app with its own tokens,
what we already do, and what we deliberately leave.

### The one idea worth the most

Liquid Glass "forms a distinct functional layer for controls and
navigation elements that floats above the content layer". "Don't use
Liquid Glass in the content layer." "Use Liquid Glass effects sparingly ...
limit these effects to the most important functional elements." That is
INBOX 49's decision word for word: blur on the top bar, the sub-tab
strips, docks, menus, popovers and dialogs; never on a content card. The
one exception Apple names is ours too: "controls in the content layer with
a transient interactive element like sliders and toggles ... take on a
Liquid Glass appearance when a person activates it" (the switch knob and
the slider thumb light up on drag, nothing else in a card blurs).

### Rules adopted, with the token or recipe they land on

1. **Two glass variants.** Regular: "blurs and adjusts the luminosity of
   background content to maintain legibility of text"; use it "when
   components have a significant amount of text, such as alerts, sidebars,
   or popovers". Clear: "highly translucent ... for components that float
   above media backgrounds", with "a dark dimming layer of 35% opacity"
   when the content behind is bright. Ours: `--glass-filter` is the regular
   variant (blur plus saturate plus a luminosity lift); a `.glass-clear`
   modifier (blur only, `--card` at 30%) is for panels over the animated
   background or an image, and it always pairs with `--glass-scrim`
   (35% ink) when the surface is light. Never a third variant.
2. **Scroll edge effect.** "Optimize for legibility when content scrolls
   beneath controls": the bar over a scroll region fades a soft edge under
   itself as content passes. Ours: `.dock`, `.notes-subtabs`,
   `.library-subtabs` and `header#top-bar` take a 16px `box-shadow` in
   `--scroll-edge`, shown only while the region is scrolled
   (`data-scrolled="1"`, set by one listener in app.js on the single bar
   whose bottom edge is against the top of the region that scrolled: it
   picks by measuring, because three bars can be stacked over one list and
   only the last of them has anything passing behind it). **A shadow, not
   the `::after` gradient this rule was first written as**: an absolutely
   positioned pseudo-element extends its bar's scrollable overflow, which
   turned `#notes-subtabs` into a 60/44 vertical scroller, and clipping it
   back hides the gradient with it. Built, INBOX 100.
3. **Concentric corners.** "Rounded shapes that are concentric to their
   containers": an inner radius is the outer radius minus the padding
   between them. Ours: `--radius-inner: calc(var(--radius) - var(--space-3))`
   and a lint that a `.card` child with its own radius uses it. INBOX 101.
4. **Vibrant colour on glass.** "Use vibrant colors on top of materials";
   "Use color sparingly, especially on glass"; "Avoid applying a similar
   color to toolbar item labels and content layer backgrounds". Ours:
   `--text-on-glass` (one step higher contrast than `--text`) for text on
   any blurred surface; accent only on the one filled control per surface.
5. **Toolbars group by function, icons over text.** "Group items that
   perform similar actions ... maintain consistent groupings"; "don't mix
   text and icons across items that share a background"; "Provide an
   accessibility label for every icon"; "Use the prominent style for key
   actions such as Done or Submit" (one). Ours: the dock grammar (three
   zones, hairline dividers, seven controls, one filled) is this rule; the
   lint holds it; a group is all icons or all text, never mixed.
6. **Menus.** "Prefer listing important or frequently used menu items
   first"; "Use menu item icons sparingly and with purpose"; "Consider
   using a checkmark to show that an attribute is currently in effect";
   "Show people when a menu item is unavailable"; "Prefer displaying a menu
   near the content it controls"; and, new: "an action sheet originates
   from the element that initiates the action". Ours: `kebabMenu` orders
   by frequency, the check mark on-state exists, disabled items stay
   visible and dimmed, and every menu anchors to its opener (never the
   screen edge).
7. **Buttons.** "Keep the number of prominent buttons to one or two per
   view"; "Use style, not size, to distinguish the preferred choice";
   "Don't assign the primary role to a button that performs a destructive
   action"; help buttons are "circular, consistently sized buttons that
   contain a question mark" and "avoid displaying text that introduces a
   help button". Ours: the ramp, Bin is never filled, the `data-help-for`
   '?' is round and unlabelled.
8. **Sheets and popovers.** "Show one popover at a time"; "Make a popover
   only big enough to display its contents"; "Avoid displaying popovers in
   compact views" (a sheet on a phone instead); half sheets are "inset
   from the edge of the display to allow content to peek through" and go
   opaque at full height. Ours: one popover open at a time (the outside
   click closes the rest), popovers become bottom sheets under 640px, a
   sheet has `--space-3` inset and the regular glass until it fills the
   height, then `--modal-bg`.
9. **Lists breathe.** "Organizational components like lists, tables, and
   forms have a larger row height and padding. Sections have an increased
   corner radius to match the curvature of controls." Ours: `--row-h`
   steps up one token at comfortable density; `.settings-group` radius is
   `--radius-lg`. (Apple also moved section headers to title case; we keep
   sentence case, the owner's rule.)
10. **Tab bar and sidebar.** "Use a tab bar to support navigation, not to
    provide actions"; "Don't disable or hide tab bar buttons"; "Consider
    automatically hiding and revealing a sidebar when its container window
    resizes"; tab bars can "recede when a person scrolls". Ours: the phone
    tab bar shrinks to icons on scroll down and returns on scroll up
    (UI Phase 9); the sidebar auto-hides under 1100px and is never hidden
    by default on desktop.
11. **Search.** "Place search at the top when there's no bottom toolbar";
    "Use tokens to filter by common search terms"; "Consider showing
    suggested search terms". Ours: INBOX 99e's operators become tokens in
    the Notes search box, suggestions under it.
12. **Motion.** "Don't add motion for the sake of adding motion";
    "Consider using fades when you need to relocate an object"; controls
    "fluidly morph into menus and popovers". Ours: a button that opens a
    menu scales the menu from the button's rect (`--motion-base`, spring
    easing), a fade for anything that moves more than its own width, and
    every one of these is off under Reduce motion and Performance mode
    except the progress indicators.
13. **Accessibility settings are inputs, not exceptions.** "People can ...
    turn on accessibility settings that reduce transparency or motion";
    "Make sure all your app's colors work well in light, dark, and
    increased contrast contexts"; "Let people use the keyboard alone".
    Ours: `prefers-reduced-transparency` turns Performance mode on,
    `prefers-contrast` sets `data-contrast`, every menu and dialog walks
    by keyboard (contrast.js and touch.js are the gates).
14. **Extra-large controls.** Controls "feature an option for an
    extra-large size, allowing more space for labels". Ours:
    `--control-h-xl` for the primary action on a phone sheet and the
    capture Save.

### Deliberately not taken

Refraction and lensing (a displacement filter on every glass surface is
the one effect measured as too costly on an integrated GPU; the lit rim
stands in for it), layered app icons, the background extension effect
under sidebars (our sidebar is a content panel, not glass), title-case
section headers.

### Where this goes next

INBOX 100 (scroll edge effect), 101 (concentric radius token and lint),
102 (clear variant with the scrim, the text-on-glass token), 103 (menus
morph from their opener; sheets inset and opaque at full height), 104
(phone tab bar recedes on scroll); UI Phase 9 carries 104. Each is a
half-day for Opus with the measurement named on its INBOX line.

## Buttons: the ramp

Three tiers, and a view should be readable from them alone:

| Tier | Recipe | Use |
| --- | --- | --- |
| **Filled** | `button`: accent fill, `--on-accent` text, the accent glow | The one action a surface is *for*. One per card or dialog, a dashboard of widgets has one per widget (Save, Start), not one for the page. |
| **Tonal** | `button.ghost`, and any `.icon-only` button, `--ghost-btn-bg` fill, a 1px `--ghost-btn-border` edge, no shadow | Every other action that stands on its own: a card's one-off control, a panel, a popover, a dialog. |
| **Quiet** | the same button inside something that already frames it, a dock, a card's `.entry-actions` run, a floating whiteboard panel: no fill, no edge, no shadow, a tint and an edge under the pointer | A *run* of actions. The container is the affordance; the tint is the state. |
| **Plain** | tab-bar buttons, `.linklike`, `.status-item`: no fill at rest, a tint on hover | Navigation and inline actions that sit in running text or a strip that is already a well. |

**The tonal/quiet split is the answer to one report made three times**, most
recently "all the buttons need to actually look like buttons with affordance,
not just shapes with text in them". The edge was tried, then removed on a
real measurement (22 outlined-and-shadowed buttons in one Notes toolbar,
beside outlined inputs and an outlined card, is three lines of texture), then
asked for again, because removing it left every button in the app a flat tint:
a silhouette with no rim, which is precisely a shape with text in it.

Both measurements are right and they are about different buttons. So the
split is not what the button is, it is **whether anything already frames
it**. On its own, a button draws its own edge and its own small lift. In a
dock, a whiteboard panel, or a run of row actions on a card, the frame is
already drawn and the button stays quiet until the pointer arrives. Measured
after the split: the 52 outlined boxes a note list put on screen went to 0,
and the largest remaining run of tonal buttons anywhere is 5.
`[data-contrast="on"]` puts an edge on the quiet tier too.
`tests/test_ui_recipes.py` pins the tonal recipe so a fourth pass cannot
flatten it again.

**The tonal tier draws no shadow, and the reason is dark mode.**
`--shadow-sm` is seven times heavier in dark than in light, because a shadow
over a #0e1017 page has almost no contrast to work with, and it was sized
for a panel. Under a 28px control it measures `rgba(0, 0, 0, 0.35)`, and
eight of those in one strip is a row of dark rims: reported as "the border
shadow on elements like these are too strong". The hairline is what makes a
tonal button read as pressable; a lift is what made it read as heavy. The
filled tier keeps its glow, and there is one of those per surface.

A selected toggle (`.active`) is the filled recipe: on is the accent, not a
darker tonal.

**Segmented controls are two things, and they are drawn differently on
purpose.** A *tab strip* (`[role="tablist"]`: the tab bar, the Notes and
Library sub-tabs) sits on the surface, the tab bar is a `--field-inset`
well, the sub-tab strips are their own card. A *choice control* (`.seg`,
`.segmented-control`: view toggles, sort, Ask/Agent) is a `--chip-bg` well
with no edge, whatever else it is inside. Measured: 28 `.seg` groups were
already that, and the Graph's layout/colour pickers plus the chat dock's
mode switch were the three drawn as cards, now conformed, not given a
third recipe.

**A choice control's selected segment is `--accent-surface` behind
`--on-accent`, with no shadow, whichever of the two forms it is.** The
radio-backed form (`.segmented-control`: `#doc-ai-verb`, `#graph-layout`) is
the same object as the button-backed one (`.seg`) and the recipe index has no
room for a second reading of it. Reported as INBOX 107d, "I want to get rid of
and redesign these mini menu bars ... they desperately need a modern redesign
or alternative". Measured beside `#doc-view-seg` on one screen before
(`scratchpad/ui-sweeps/segbars.js`): track radius 8.4px against 15.4px,
padding 2.4px against 4px, segments 26px tall at 12px type against 28px at
16px, and a selected state of `rgba(79,109,245,0.14)` behind `--ink` plus a
`0 2px 8px` drop shadow, against a solid accent behind white. A 14% tint
behind body-coloured text is not a selected state you can see across a popup,
and a segment inset in a well does not cast a shadow out of it. The answer to
"redesign or alternative" was neither: it was `.seg`'s numbers. What stays
particular to the radio form is only the plumbing, the visually hidden
`input[type="radio"]` that gives the group its native arrow-key navigation.

**Form rows share a label column.** `--form-label-col` (9rem; `-wide`, 11rem,
for Search relevance) is the width every `.setting-label` reserves, so the
controls in adjacent rows start on one edge.

## Icons

Phosphor (`<i class="ph ph-*">`) is the default for every icon in the app.
One deliberate, narrower exception: **download/export actions use a plain
Unicode arrow glyph** (`⬇`, `⭳`) instead, chat export, both document
export buttons, the whiteboard export button, and the settings support-
bundle download all do this consistently. It reads as inconsistent seen in
isolation; checked across all five call sites before touching any of them,
it is the app's actual (if quiet) convention for this one action family,
not drift, leave it alone rather than "fixing" it to Phosphor.

---

## Hierarchy

Levels must be **visibly ordered**, and they were not: `h2` ranged 0.92–1.15rem
depending on where it sat while `h3` was a flat 0.92rem, so in the sidebar a
section title was the same size as the subsections beneath it.

| Level | Size | Treatment |
| --- | --- | --- |
| `.card h2` | `--text-body` | weight 650, tight tracking, **a heading: names a thing** |
| `.card h3`, `.eyebrow`, `.nav-group-label`, `.launch-label` | `--text-sm` | weight 600, muted, uppercase, 0.04em, **an eyebrow: labels a section of controls** |
| `h4.setting-subhead` | `--text-md` | weight 600, sentence case, a subdivision inside an eyebrow's group |
| `.dash-getting-started h2` | `--text-h3` | titles a whole panel, not a card |

**Eyebrow vs heading.** An eyebrow labels a *section of controls* (THEMES,
WHICH ONES IT MAY USE, THE AI, START SOMETHING); a heading names a *thing*
(All notes, Recently added, a note's title). They are never both capitals,
a subdivision under an eyebrow is `h4.setting-subhead` in sentence case, not
a second run of caps (About → Updates was two stacked caps labels of the
same weight before this, and read as rivals). There is one eyebrow recipe,
measured: the app had two (12px/600/0.04em on cards, 11.2px/700/0.06em at
75% opacity on the Settings nav and the dashboard launch rows) doing the
same job in two voices. The one place caps sit directly over a title is the
dashboard hero's wordmark kicker, which is branding, not a section label.

Note that `h3` is **smaller** than `h2`, not one step down from it. Small caps
carry the distinction, which frees the size to drop, two sizes 0.08rem apart
cannot signal a level change on their own, and trying to make them was what
made the old hierarchy invisible.

**Use weight, colour and case before reaching for another size step.** The type
scale has ten steps because an interface needs ten *sizes*, not ten *levels*.

---

## Adding a feature

1. **Reach for a token first.** If you are typing a rem value into a `margin`,
   `padding`, `gap`, `font-size` or `border-radius`, stop, there is almost
   certainly a step for it.
2. **A page goes in `.tab-page`** and sets only its internal `gap`.
3. **A panel is a `.card`.** It brings its own padding, radius and shadow. Do
   not re-specify them.
4. **A group of choices is `.check-row`**, not bare labels, each option gets a
   hit area, a hover and a selected state, so the group is scannable without
   hunting for a filled dot.
5. **Confirming something destructive is `confirmDialog(...)`**, never
   `window.confirm`: the desktop shell does not reliably implement it, and a
   button gated behind one that returns `undefined` silently does nothing.
6. **Run the lint.** `pytest tests/test_style_scale.py`.

### When a token genuinely doesn't fit

Add the value to the relevant `ALLOWED` set in `tests/test_style_scale.py`
**with the reason**. There are three entries there today, two indent steps for
the document outline, which must stay evenly spaced relative to each other
rather than land on a scale built for gaps between unrelated things, and a
negative pull-back that cancels a list's own indent exactly.

Being made to write the reason is the entire mechanism. An entry with a vague
reason is a value that should have been snapped to the scale.

---

## Why the lint matters more than the conversion

The conversion is a one-off. Without something that fails, the next tab built
in the next session reaches for whatever looks right at the time, and the drift
starts again, which is exactly how it got here, over six tabs and as many
sessions.

`tests/test_style_scale.py` checks:

- every spacing value is on the scale;
- every font size is on the scale;
- no corner radius is hard-coded in pixels;
- the corner tiers stay expressed in terms of `--radius`;
- no page container draws its own outer gutter;
- the page shell is declared once and used;
- no colour token is used with a fallback;
- every semantic colour has a dark-mode value.

It strips CSS comments before scanning, because the comments in this file
explain layout decisions and therefore quote lengths, `test_frontend_ids.py`
had to learn the same lesson about markup comments quoting ids.

---

## Surfaces, tiles, chips and the popover shell (UI modernisation, Phases 1-3)

Added by the modernisation pass; every rule here was measured before and
after in Chromium (`scratchpad/ui-sweeps/`), and `tests/test_ui_signatures.py`
ratchets the counts so they cannot drift back.

- **Two card sizes, as tokens.** `.card` sets `--card-pad-y`/`--card-pad-x`
  (panel: `--space-7`/`--space-8`); `.card.compact`, `.sidebar-panel` and
  `.dash-widget` set both to `--space-6`. Anything that has to cancel the
  padding to reach the card edge (the sidebar head row) references the token,
  never a step. The 720px block tightens the tokens, not `padding`.
- **A card inside a card is a tone** (`--surface-2`, transparent edge, no
  shadow, no blur), never a second bordered pane.
- **One head row.** `.card > .row:has(> h2)` is `--control-h-lg` tall with
  `--space-5` under it, and the `h2` drops its own bottom margin. The sidebar
  collapse toggle is `--control-h-lg` square, so the sidebar head, the
  Library head and a widget head are one height.
- **The shell's inset is `--page-gutter` everywhere**: the top bar, the
  status bar and the page share one x for the logo, the first card and the
  first status item.
- **Rows have two gaps.** `--space-3` inside a control group, `--space-4`
  between groups. The two 60-control formatting strips (`.doc-toolbar`,
  `.note-toolbar`) are the one `--space-1` exception.
- **One button radius**: `--radius-md`, from the base `button` rule. Tiles
  (`.quick-link`, `.stat-tile`, `.start-step`) are one recipe: `--card` fill,
  `--glass-border`, `--radius-md`, no shadow, `--accent-soft` on hover; a tile
  inside a card is `--surface-2`.
- **The interactive filter chip** (`.library-chip`, the chat composer's
  Skills/Web/Plan): `--chip-bg` tint, transparent 1px edge, pill radius;
  active is the filled recipe. Not an outlined pill.
- **The floating control** (`.scroll-top`, `.graph-zoom`): `--card` fill,
  `--glass-border`, `--glass-shadow`, `--radius-md`; the buttons inside a
  strip are plain. **The help dot** is the one round icon button, on purpose
  (every "?" in the app is it).
- **One popover shell.** `.action-menu`, `.select-menu`, the toolbar menus,
  the nav-history menu, the chat model panel, the help popover, the
  notifications panel and the AI status popup share one rule at the end of
  `07-whiteboard-misc.css`: `--modal-bg-opaque`, `--border`, `--radius-lg`,
  `--glass-shadow`, no blur. Opaque because CLAUDE.md records the ghost-text
  bug the 96% tint caused over the note editor. A new floating surface joins
  that selector list; it does not declare its own shell.
- **Glass is material, not effect.** `backdrop-filter` stays on the top bar,
  status bar, sidebars, sub-tab strips, panels and floating controls, and is
  off on dashboard widgets and library cards (measured 28 → 4 blurred layers
  on the Dashboard, 25 → 5 on the Library). Background art defaults to 45%.
- **One control size.** Text fields and selects read `--text-md` from the
  base rule; a textarea is a writing surface and reads `--text-body`.
- **Hover changes tone, never position.** No `translateY`/`scale` on hover;
  no transitions on `left/top/width/height` except a progress bar filling.
- **One focus ring**: the base `:focus-visible` (2px `--accent`, 2px offset).

## Control height

One more thing has to match for a row of controls to read as a strip rather
than as a pile: **their height.** The chat dock declares `--control-h` and
every select, button and segmented control in it is that tall.

It is deliberately *not* a spacing token. A hit target is a control's own size
(the role `--radius` plays for corners), and snapping it to a gap step would
make it move with the density setting, which is not what density is for.

The failure it prevents is the one this whole document is about: the segmented
control brought its own padding and stood four pixels taller than the selects
beside it. Nothing lines up, no edge agrees with another, and the row reads as
assembled rather than designed, the "slop features joined together" complaint
in miniature, at four pixels.

### And zero the margins, not just the heights

Reported after the first attempt, which had matched the heights and looked
fine in the stylesheet: *"some are higher or lower than each other and
different heights."*

**A margin on a flex item is centred with the item.** `.seg` carries
`margin-bottom: 0.5rem` from the stacked forms it was built for, and under
`align-items: center` those 8px do not become a gap, they sit the control 4px
*above* its neighbours and make its group 8px taller, which pushes the next
group 4px down in turn. Two visible offsets, from one declaration in a rule
three thousand lines away.

> **The rule:** a row of controls neutralises the outside spacing its controls
> arrive with (`margin: 0`), and the row's own `gap` is the only thing between
> them. Anything else means every control added later has to be checked
> against every base rule that might have given it a margin.

The same applies to a control's own vertical padding: keep it horizontally,
give it up vertically, and let the declared height decide.

Where a row's box grows (a chat composer with an autogrowing textarea), align
to `end` rather than `center`, so the buttons stay level with the line the
caret is on instead of drifting up the side of it.

### Where this is applied

Not every toolbar has been through this yet, treat a row that hasn't as a
gap, not as a deliberate exception, and give it its own `--control-h` before
adding a control to it:

- `.chat-dock-controls` (`04-chat-dock-appearance.css`), the original.
- `.graph-toolbar` (`03-dashboard-widgets.css`), shared by the Graph and
  Timeline tabs' primary rows. Added after measuring a real ~15px gap
  between the search/select controls (45px, from the global form-field rule)
  and the buttons beside them (~30px), close enough to pass a glance, wrong
  enough to fail a ruler. Covers `select`, `input[type=text|search]`,
  `button`, and `.segmented-control` so a text input, a select, a button and
  a segmented radio group can all sit in the same row and read as one strip.
- `.graph-options` / `#timeline-options` (`03-dashboard-widgets.css`), the
  folded-away "tuned once" panels behind each tab's Options button. Only
  `button` is height-locked here; sliders and switches are deliberately their
  own native size rather than stretched to match, since forcing a slider
  thumb to a button's hit-box height would misrepresent it as clickable
  chrome rather than a drag control.
- `.library-toolbar` (`00-tokens-shell.css`), shared by the Library tab and
  the Notes tab's "All entries" row (`#browse` in `index.html`; same class,
  reused markup). The rule covered `.library-search`, `select`, `.seg` and
  `.seg button`, but Notes' own toolbar adds two plain `<button class="ghost
  small">`s (`#select-btn`, `#search-help`) that Library's own toolbar
  doesn't have, not inside a `.seg`, so the selector list missed them.
  Measured at 30.39px against the row's 36.8px (`2.3rem`) `--control-h`,
  the same failure shape as `.graph-toolbar`, just the buttons short instead
  of the inputs tall. Fixed by widening `.seg button` to plain `button`,
  which covers both without duplicating a rule.
- `.capture-field-row` (`07-whiteboard-misc.css`), `.draft-controls`
  (`04-chat-dock-appearance.css`) and `.ask-query-row`
  (`07-whiteboard-misc.css`), the Notes tab's Capture, Write-with-AI and
  Ask panels, none audited before this round. All three had the same
  three-heights-on-one-row shape: a `select`/`input` at the global 45.19px
  form-field height, a plain `button` at 40px, and a `.ghost` button at 42px
  (the border, under `box-sizing: border-box`). `2.5rem` (40px) rather than
  the toolbars' `2.3rem`, since these rows carry full-size `Save`/`Draft it`
  actions, not a `.small` toolbar strip.
- `#batch-bar` (`02-chat-graph.css`), the Notes tab's select-mode batch
  action row (`Move to…` / Move / Tag / Delete / Done). The category select
  (45.19px), `.small` `Move` (28.39px) and `.ghost.small` `Tag`/`Delete`/
  `Done` (30.39px) were three more heights on one row. `2rem` here, since
  every control is already `.small`.
- `#reminder-magic-row` (`05-sidebars-themes.css`), the Reminders tab's
  natural-language add row. Smaller than the others (44px `textarea.autogrow`
  against a 42px `.ghost` `Add` button, 2px) but the same shape, fixed by
  matching the button's height to the textarea's own `min-height: 2.75rem`.
  The tab's main `.reminder-form` row and the filter `.seg` were already
  correct, checked, not assumed, before moving on.

`.doc-toolbar`'s two rows (`04-chat-dock-appearance.css`), the Documents
editor's metadata/actions row and its formatting-button row, named as an
open question in an earlier HANDOVER entry, were measured and are
**already correct**, not a missed instance. The formatting row's buttons are
uniform 29.19px. The metadata row's title input (45.19px) sits beside a
`row space-between`-justified stats/actions group, not edge-to-edge with
it, a `space-between` title-left/actions-right header, not a strip of
controls sharing one boundary, so a height difference there doesn't read as
misalignment the way it does within `.doc-actions` itself (which is
internally uniform, all `.ghost.small`).

---

## What is not done yet

Recorded honestly, because this document should not read as further along than
it is. See ROADMAP §35L.

- **Most of this has still not been checked in a browser**, but it now *can*
  be, and the parts that were are marked as such. Chromium and Playwright are
  in the sandbox and the app runs on localhost (CLAUDE.md has the recipe). The
  chat header and dock were measured and screenshotted in both themes; the tab
  bar was measured at five widths. Everything else here was reasoned from the
  stylesheet and bounded so no single value moved more than 0.1rem, which is
  not the same as verified. **Look at what you change; it costs a minute.**
- **Motion** is a user setting a few components still ignore. Density is done,
  it is a multiplier over the spacing scale now. Duration is done as of this
  pass (the `--motion-*` scale above); *honouring* `prefers-reduced-motion`
  everywhere is not, still per-component `@media` blocks, not a single rule.
- **The tab bar** is at the width where another tab hurts, which matters for
  the unbuilt Library tab (§4), decide whether it absorbs existing tabs or the
  bar gains an overflow *before* building it.
- **The timeline's line/branch view needs more than this pass gave it**,
  screenshotted live (9 seeded notes, populated, not empty): the SVG canvas
  reserves a fixed height regardless of content, so a normal note count
  leaves most of the card blank below the spine; the active band has no
  visible label painted on the canvas itself (only in the "N notes · N
  bands" line above it); and notes sharing a bucket stack vertically with no
  jitter or connecting structure, which reads as a pile, not a branch. None
  of this is a token or colour problem, it's `renderTimelineBranch`'s own
  layout math (`app.js`, §10C) sizing the canvas and placing dots without
  regard to how much content is actually in it. A real fix is a layout
  change, not a CSS pass, and risked being a half-implementation attempted
  under this pass's own budget, scoped here instead of guessed at. See
  ROADMAP item 10.
- **The document editor was screenshotted live and looks fine**: title
  field, outline, word count, toolbar, AI edit/extract-notes actions all
  present and visually consistent with the rest of the app. Its real gap is
  the one BACKLOG.md §5 already names (wiki-links, a slash menu,
  live-preview editing, sub-pages), a feature/product question, not a
  design one, and correctly out of this pass's scope.


---

## The principles this system is an implementation of

Added after a direct instruction: *"I shouldnt be having to tell you to
consider all these ui/ux principles, they should be part of design.md and
you should be sticking to them throughout development."*

That is correct, and the four sections above (spacing, type, corners,
control height) are already three of the four classical CARP principles
wearing implementation names. Naming them, adding the fourth, and, where
possible, giving each a **number a session can measure itself against** is
what this section is for. A principle with no measurement is a preference;
a principle with one is a check.

### C: Contrast

Contrast is what makes a thing look like what it is. The palette carries it
(`--ink` vs `--muted`, `--accent` vs `--chip-bg`), and the failure mode here
has never been "not enough colour", it is **two things that differ slightly
for no reason**, which reads as an accident rather than a distinction.

> **The rule:** if two things are different, make them clearly different. If
> they are the same kind of thing, make them identical. Nothing in between.

Text contrast is 4.5:1 minimum for body copy (WCAG AA), 3:1 for large text
and for the boundary of a control you are meant to find. `--muted` on
`--card` is the pair to check when adding a theme.

### A: Alignment

**The weakest part of this app, measured.** Count the distinct left edges of
every visible element wider than 120px on a screen; a composed layout has
two to four. Measured at 1440×900:

| Screen | Distinct left edges |
| --- | ---: |
| Dashboard | **37** |
| Graph | **35** |
| Notes | **32** |
| Library | **25** |
| Reminders | **16** |
| Chat | 13 |
| Timeline | 9 |

Thirty-seven means essentially nothing lines up with anything, and it is the
most likely single cause of *"it feels fake and unprofessional but I cant
place it"*, misalignment is felt long before it is seen.

> **The rule:** every element sits on an edge something else already
> established. A new element that needs a new left edge is a sign the layout
> wants a grid, not that the element wants a margin.

This is the acceptance criterion for the shell work in
[roadmap/REDESIGN.md](roadmap/REDESIGN.md) §R6 item 6: **if a change does not
reduce that count, it did not fix the thing it was for.**

### R: Repetition

The token scales *are* repetition, and `tests/test_style_scale.py` enforces
them. The gap they did not cover was **control size**, because a class can
be consistent in its declarations and still render at five heights.

Measured before `--target-min` existed: `button.small` (the most-used
control class in the app) rendered at **19, 24, 25, 26 and 30px**, decided
entirely by whether a given button held an icon, a word, or both. Five
heights for one class.

> **The rule:** a control class declares a height (or a floor). Content never
> decides how tall a control is.

### P: Proximity

Related things sit together; unrelated things get a gap. The failure here is
the one the Library screen had: six stat tiles and, directly beneath them,
the same six filters as chips, *adjacent* but not related, because they
were the same control twice.

> **The rule:** before adding a control, find the one that already does it.
> Proximity is meaningless if the neighbours are duplicates.

---

## Voice

One voice, so labels do not read as three people's work (UI modernisation,
Phase 6). Measured before this was written: "No saved chats yet, ask
something!" beside "Nothing of this kind yet." beside "Your notebook is
empty, capture a thought to begin": three tones for one situation.

- **Sentence case** everywhere except eyebrows (`.card h3`, the nav group
  labels), which are the one uppercase recipe.
- **Verbs on buttons**: "Save current look", "Reset to default", "Add",
  "Move to bin". Never "OK", never a noun on its own where a verb fits.
- **No exclamation marks.** Nothing in this app is that exciting.
- **An empty state is one component**: `.empty-state` with an `.empty-icon`,
  an `.empty-title` that says what *would* be here, one sentence saying how
  to get it, and, where a single action exists, one button. Not a grey
  line.
- **Errors say what to do next**, inline under the control that failed;
  toasts are for background work finishing. "Ollama isn't reachable: check
  Settings → Models and try again." (the exact string `skill_runner.py`
  raises), not "Error".
- **Say the thing, not the mechanism.** "Reading the model's own
  specification…" is fine; "Fetching /models/spec" is not.
- **The notebook is "your notebook"; the model is "the AI" or "the model",
  never "I".** The app narrates; the model speaks in the chat and nowhere
  else.

## Hit targets: `--target-min`

```
--target-min: 1.75rem   /* 28px, the floor under every interactive thing */
```

Distinct from `--control-h`, and the difference matters: `--control-h` is a
**strip's** declared height, scoped per toolbar, and exists so a row reads as
one strip. `--target-min` is a **global floor** that applies to a control
wherever it sits, including the many that belong to no strip.

WCAG 2.2 AA ("Target Size (Minimum)", 2.5.8) sets 24×24 CSS px. 28px clears
it with room for a border. Measured violations before this token existed:

- `#semantic-search-toggle`, `#library-semantic-toggle`,
  `#library-show-binned`: **32×18**.
- The reminder rows' checkboxes, **13×13**, barely half the floor and
  genuinely fiddly with a trackpad.

A `min-height`, never a `height`, so a strip declaring a taller
`--control-h` still wins and a control that wraps to two lines still grows.
**Not a spacing token**, for the reason the control-height section already
gives: a hit target must not move with the density setting.

The one deliberate exception is a control drawn by a sibling, the switch
pattern, where the input is clipped to nothing and the switch is the real
target. Those are excepted by name in `01-forms-settings.css`, not by
accident.

**The painted switches are still 32×18.4, and that is honest rather than a
gap** (MODERNISATION_AUDIT.md Brief 8 measured the three ids above at
32×18.4 after this section first claimed them fixed). The pill's paint must
stay that size, a `min-height` on the input made it a 32×28 slab with the
knob adrift, reported within the hour, so the *target* is a transparent
`::before` on the input that overhangs the pill by 6.4px above and below
(`07-whiteboard-misc.css`): `elementFromPoint` 4px outside the pill returns
the input, and the pill looks exactly as it did.

---

## Motion: and the one rule that is not optional

Durations come from the `--motion-*` scale. Beyond that:

> **Every indefinite animation needs a `prefers-reduced-motion` branch, and
> the branch keeps the information.** Stopping a spinner is right; removing
> the thing it was telling you is not.

Both animations added in this pass follow it: the "Filing…" chip keeps its
label and drops the spin, and the streaming caret stays visible and stops
blinking. Someone who asked for less motion is the person least able to
infer "this is still loading" from text quietly appearing.
