# Paragraphs to '?' popovers: remaining

Worktree `agent-a6db54045f3f6f144`. Not pushed; orchestrator merges.

## Done

- `initHelpToggles()` in `frontend/app.js`: any `[data-help-for="<id>"]`
  button plus a `.help-body.hidden` panel is wired with no JS (Escape,
  outside click, second click close; focus+Enter opens). Idempotent, so
  call it after a lazy render.
- `scratchpad/help-audit/count.py` (index.html) and `countjs.py` (JS
  strings): the counters. Baseline: index.html 55, JS 2.
- Sections converted, one commit each, `scripts/gate.sh --changed` clean,
  each popover opened live in Chromium at 1440x900 (`checkone.js` harness
  in scratchpad, or a standalone script for anything outside
  `#settings-modal`) and confirmed: opens on the "?", shows the full
  original text (inline `<em>`/`<strong>` preserved), closes on a second
  click. Running index.html count after each:
  - Model backend (2 paragraphs): 55 -> 53.
  - Background tasks' three groups, Templates, What it remembers,
    Appearance's Themes and Status bar: 53 -> 45.
  - Settings > Models (6 paragraphs), Skills (2), Packages (2 group
    intros), Appearance's Custom CSS, Keyboard shortcuts' own "Always
    available", Preferences' Notifications, Web search (3), Background
    tasks' Quit MemoryMap, Import & export (4): 45 -> 22. Commits
    `b5d685f 8431285 7f7f3c3 6f31b6b 29c680f bc78b72 f3b70b6 b40c0dc
    3d68668`.
  - Account & security's three groups (section intro, "Change your
    password or PIN", "Sessions"): 22 -> 19. Commit `9f32b22`.
  - Settings > Help's "Ask the guide" mini-chat group, and the standalone
    keyboard-shortcuts overlay's own "Always available" section (a
    different surface from Settings > Keyboard shortcuts, opened by the
    "?" key, not the settings nav): 19 -> 17. Commit `98f3f01`.
  - `#settings-tools` ("Tools it can use", "How many are offered at once",
    "Small model mode"): done by another agent, commit `e6e48a9`
    (INBOX 83). Its two sub-group paragraphs are converted; its own
    top-level section intro ("When Agent mode is on...") is NOT, still
    flagged by `count.py` at (roughly) line 5994 as of this writing. Left
    alone on purpose: the owner's most recent instruction said "skip
    `#settings-tools`, which is done", and re-opening a section another
    agent owns risks a collision. Flagging it here rather than silently
    leaving it off the list: `count.py` will keep reporting it until
    someone (the owning agent, or a future pass once it is confirmed free)
    adds the same treatment to that one paragraph.

## Decisions made (so no future pass re-litigates these)

1. **Section/group-level intros ("why does this area exist") convert.
   Field-level hints (attached to one specific control) and
   destructive/safety-critical warnings stay inline.** First stated in
   the Appearance/Custom CSS commit `6f31b6b`: hiding "what does turning
   this on do" behind a click, right where the control is, is worse than
   the extra line; hiding a section's own "why does this area exist" text
   is not, since nobody needs it to operate the section moment to moment.
   Governs every item below.

2. **The Tesseract OCR per-package caveat (Packages settings) stays
   inline, decided now.** It is a different shape from every other item
   on this list, and was left open deliberately in an earlier pass rather
   than converted blind: the caveat text is built by `renderExtras()` in
   `frontend/app.js`, one row at a time from server data (`caveat=` on the
   extra's own definition), not static markup in `index.html`, so
   `count.py` structurally cannot see it either way. Decision: leave it
   inline. It reads as a field-level warning attached to one specific
   row's Install/Reinstall/Remove action ("what happens if I click this"),
   not a section-level "why does Packages exist" aside, so decision 1
   already covers it; the different shape (JS-generated per row) is a
   reason the fix would look different, not a reason to weigh the
   question differently. A per-row `data-help-for` pair generated
   dynamically is possible if a future session wants the audit script to
   see it too, but is not needed for the copy rule itself: the caveat is
   already one or two sentences, not a wall of prose.

3. **Account & security's "If you forget your password" pair (the two
   paragraphs around `python -m memorymap --reset-password`) stays
   inline, decided in commit `9f32b22`.** Same reasoning as decision 2,
   applied to a destructive command instead of a per-row caveat: the text
   describes irrecoverable private-note loss right next to the command
   that triggers it, so it is a safety-critical warning attached to one
   action, not a section intro.

4. **Five more items decided the same way, this pass, once
   `count.py`'s remaining list was checked against what actually renders
   around each:**
   - Command palette intro (`#command-palette-intro`, ~line 315): the
     comment directly above it in the markup argues for keeping it
     visible ("What it can do, said out loud... These are real examples...
     they are replaced by the conversation the moment there is one"). The
     paragraph's whole purpose is to be seen before anything else is
     typed; a popover would undo that.
   - Documents' "Where are my documents kept?" dialog (`#doc-storage-dialog`,
     ~line 425), Tensions' "Where you disagreed with yourself" dialog
     (`#tensions-dialog`, ~line 477), Ask's idle screen
     (`#ask-idle`, ~line 956), the document history dialog
     (`#doc-history-dialog`, ~line 3049), and Meeting notes'
     (`#meeting-overlay`, ~line 8223) own intro: all five are already
     inside a `<dialog>` opened from a link-styled button, or (Ask's case)
     a one-time idle screen replaced the moment it is used. Each is
     already the progressive-disclosure step decision 1 asks for; putting
     a `data-help-for` popover inside a dialog that is itself the
     click-to-reveal step would hide the content twice.
   - About's hero tagline ("A 100% offline, local-first notebook...",
     `.about-hero`, ~line 7706): this is the app's own one-line identity
     statement directly under its name and emblem, the shortest and most
     essential text on the page, not an explanatory aside about why the
     About section exists. Converting an app's own tagline on its own
     About page into something the reader has to click to see would be
     backwards.

5. **Field-level hints already decided inline in earlier passes, listed
   here so nobody re-checks them:** the settings-tools sub-group hints
   (`tool-focus-help`/`small-model-help`, already popovers via `e6e48a9`),
   `#progress-motion-row`'s inline hint, the model-latency `<small>`
   under Diagnostics ("How long each kind of job has been taking...",
   ~line 6059 in the old numbering), the thinking-dots motion hint
   (~6439), `#log-terminal-hint`, `#desktop-console-hint`, and
   `#desktop-tray-hint`. Each sits directly beside, or is toggled by, the
   one control it explains.

6. **The two JS strings (`countjs.py`) checked this pass, both decided
   inline, for the same reason as decision 2 (Tesseract):** the
   dashboard's Tensions widget explain line
   (`frontend/dashboard.js:3156`, "Similar-notes search finds what
   belongs together...") and the Library skills panel's Background
   workers hint (`frontend/library.js:1649`, "Lets the AI work through
   your notebook on its own..."). Both are one or two sentences built
   with `document.createElement`, the same JS-generated shape as the
   Tesseract caveat, and both are short enough that they are not the
   wall-of-prose problem this task targeted. Converting either properly
   needs the trigger and panel created and inserted into the live DOM
   before `initHelpToggles(root)` runs against that subtree (it is only
   ever called once, at load, against the whole document today; no
   dynamic render anywhere in the app calls it a second time yet), which
   is a real behaviour change worth its own render-path regression check
   rather than a same-session, same-commit add. Left inline; `countjs.py`
   will keep reporting TOTAL 2 until a future pass does that properly.

## Found, not fixed (out of scope for this sweep)

- ~~**The standalone keyboard-shortcuts overlay**~~ **Fixed** (orchestrator,
  2026-09-09, `d8b9038`). The cause was one tier up from where this entry
  put it: `.modal-card` itself, not `#shortcuts-card`, capped every dialog
  at 88vh with `overflow-y: visible`, so any dialog filled from script lost
  what fell past the cap. `overflow: hidden auto` plus
  `overscroll-behavior: contain` on the class fixes all of them at once.
  Measured before: 1925px inside 790px, scrollTop stuck at 0, the heading
  at y=1444 below an 846px window. After: scrollTop reaches 1171, the last
  list ends at 762.7, Settings unchanged at 790 in 790 with no scrollbar.
  The original text follows for its diagnosis of what the static markup
  measurement misses.

- **The standalone keyboard-shortcuts overlay (`#shortcuts-overlay`,
  opened by the `?` key) has no scroll mechanism at 1440x900.** Its
  content (the full rebindable list plus "Always available") is taller
  than `.modal-card`'s `max-height: 88vh` cap; nothing clips or scrolls
  it (`card.scrollTop`, `document.body.scrollTop`,
  `document.documentElement.scrollTop`, and a real mouse-wheel event over
  the card all left every scroll position at 0 in Playwright). The
  "Always available" section and its new `shortcuts-overlay-always-help`
  popover trigger sit below the visible window at that size and cannot be
  reached. Confirmed pre-existing rather than caused by this session's
  edit: the new markup (one short line replacing a three-line paragraph)
  is net shorter than what it replaced, and the popover itself opens
  correctly, full text, in viewport, once tested at a 2000px-tall
  viewport where the surrounding content fits. Needs an `overflow-y:
  auto` (with a matching `max-height` or `min-height: 0` so the flex
  column actually shrinks) on `#shortcuts-card` or a wrapping content
  column; a job for the wrap-sweep style of pass, not this one. Worth an
  INBOX entry if the owner wants it prioritised, since anyone on a
  1440x900 or smaller display who opens the shortcuts overlay cannot see
  or use "Always available" today, independent of this session's changes.

## Next steps, in order

1. `count.py` on `frontend/index.html` currently reports 17, and
   `countjs.py` reports 2. Every one of those 19 is now a written
   decision to stay inline (decisions 3-6 above cover all of them by
   name) except `#settings-tools`'s own top-level intro, deliberately
   skipped pending the owning agent's status. So the list of *open,
   undecided* items is effectively zero; a fresh run of both counters is
   still worth doing before closing this file, in case another agent's
   merge introduced new paragraphs since this was written.
2. Toggle rows onto one recipe (no lavender-filled bars): not started.
3. `scratchpad/ui-sweeps/help-popovers.js`: open every '?' on Settings,
   assert each popover rect is inside the viewport at 1440 and 390. Not
   built; would also have caught the shortcuts-overlay overflow above if
   it covered that surface too.
4. Once `#settings-tools`'s status is confirmed and its intro (if still
   open) is converted: `count.py` should print a number matching only
   the decided-inline items, lints clean, `errors.js` 0. `countjs.py`
   stays at 2 (decision 6) unless a future session takes on the
   dynamic-DOM wiring question it describes.
