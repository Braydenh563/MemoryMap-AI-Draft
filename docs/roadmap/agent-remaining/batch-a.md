# INBOX batch A (31-38): what is done, what is left

> Companions: [INBOX.md](../INBOX.md) · [HANDOVER.md](../HANDOVER.md)
>
> One session's pass over INBOX.md items 31, 32, 33, 34, 35, 36, 37 and 38
> (chip and capture label part only), in that order. Every item was
> reproduced in a real Chromium (`bash scratchpad/ui-sweeps/serve.sh 8851
> /tmp/mm-batch-a`, Playwright through `scratchpad/ui-sweeps/lib.js`) with a
> number before anything was changed, then measured again after, per
> CLAUDE.md's own rule. INBOX.md itself now carries a `(fixed)` line per
> item with the before/after numbers; this file is the short version plus
> what is still open. One commit per item, all with before/after numbers in
> the message; nothing pushed.

## Done this session

- **Item 31** (dock menus clip/don't scroll): `details.dock-menu`'s toggle
  handler (app.js) now recomputes `max-height` from the list's own top on
  every open, position-aware, instead of the flat `calc(100vh -
  space-9*2)` the stylesheet had; `escapeMenuIfClipped` (written for
  `.action-menu`) extended to cover `.doc-dock-menu-list` too, for a menu
  whose scrolling ancestor clips it regardless of the cap. Reminders' Quick
  set at 1024x560: 172px past the viewport with no scroll before, inside
  and scrollable after. `kebab-viewport.js` extended with a `runDockMenus`
  sweep across all five of these menus at two viewports (900 and a forced
  300px); all ten cases OK.
- **Item 32** (dashboard toolbar touching its neighbours): `margin-block:
  var(--space-5)` plus a "Your dashboard" identity label, deliberately kept
  off the dock grammar (it has no find/arrange zone). 0px/0px gap before,
  13px/13px after.
- **Item 33** (too much scroll room): `--scroll-top-clearance` shrunk to
  the button's own height plus one gap (was also carrying the button's
  full viewport offset, `--status-bar-h` included, double-counting the
  page's own gutter) and moved behind a new `body.scroll-top-visible`
  class the button's `update()` toggles in the same place it shows itself,
  so a short page with the button nowhere near visible carries none of it.
  Notes > Ask at 1440x600: 151px of scroll room (100 of it padding with
  nothing under it) before, 51px (all real content) after.
- **Item 34** (two chat scroll controls / stale on new chat):
  `syncChatJumpLatest` re-derives "scrolled away" from the live rect
  instead of trusting a `dataset.stuck` cache that goes stale the moment
  `newChatConversation`'s `replaceChildren()` fires no scroll event; chat
  joined `NO_SCROLL_TOP_TABS` per the item's own decision ("one control,
  the pill"), so the reused down-arrow never shows there again regardless.
  Reproduced with a synthetic 40-message transcript, scrolled away, then
  "+ New": pill and arrow both wrongly visible on the resulting empty pane
  before, both correctly hidden after.
- **Item 35** (chips show raw Markdown / centred): `cmdPaletteTouchedRow`
  and `renderRelatedElsewhere` route `item.label` through `noteLabel` now
  (`cmdPaletteResultRow` already did; these two didn't). `# CAB432` and
  `**Ice Breakers:**...` reproduced verbatim by building each row directly
  with those two exact examples, both clean after. `.answer-related-chip`
  is a `<button>` that never set `text-align`, so the browser default
  (`center`) won over its own left-aligned intent; fixed alongside.
- **Item 36** (streaming indicator doesn't animate): `getAnimations()`
  confirmed the "always" default runs `dot-bounce` in every combination
  tried, including under OS reduced motion (by design). The "auto" +
  reduced-motion / "still" fallback was a class-toggle with no Web
  Animation at all (`typing-dots-stepped span.is-on`, a colour swap);
  replaced with a phase-labelled word ("Thinking"/"Writing") and a slow
  `typing-word-pulse` opacity animation, per the item's own decision.
  `test_style_scale.py`'s indefinite-animation check flagged the new
  keyframe correctly (it never turns off under reduced motion, on
  purpose); declared explicitly inside its own `@media` block with a
  comment explaining why, rather than silently exempted.
- **Item 37** (Magic add textarea taller than its button): reproduced the
  drift (not the raw symptom, headless Chromium's bundled font showed
  44/44 here too) by swapping the field's font to simulate a different
  engine's line-box metrics: 45px vs the button's fixed 44px.
  `autoGrow()` now reads `getComputedStyle(el).minHeight` for an empty
  field instead of measuring `scrollHeight`, which cannot drift with the
  textarea's own font the way a line-box measurement can. 44/44 in light
  and dark, normal and drifted font, all four. Growth once text wraps
  (44 -> 66) and the shrink back to 44 on clearing both still work.
- **Item 38, chip and label only** (space visibility): `EntryOut` gained
  `workspace_id` (the row had it all along; nothing sent it to the
  frontend). Note cards show a left-aligned, clickable space chip whenever
  the space picker doesn't already say it (every card in "All spaces", or
  a card whose own space differs from the one picked); the capture form
  says "Filing into `<space>`." above "File under", including the "All
  spaces" case, which files into Default Space (`database.py`'s insert
  hook only stamps a workspace when one is actually selected) and says so
  explicitly rather than leaving that a surprise. Verified live: created a
  "Work" space, captured into it, confirmed the label and the chip's
  presence/absence rules in both "All spaces" and "Work" directly.

## Fixed since (INBOX batch C, 2026-09-08)

- **`loadChatSuggestions()`'s null-deref on `#chat-suggest`, root cause
  found and fixed, not just guarded.** The real sequence needs no synthetic
  race: `#chat-suggest` is on loan to `.chat-empty` whenever suggestions
  have already loaded for the current empty chat (open the chat tab, let
  them load once, `#chat-suggest` ends up inside `.chat-empty`), and
  `newChatConversation`'s `$("chat-messages").replaceChildren()` wiped
  `.chat-empty` -- and the loaned element inside it -- without sending it
  home first the way `clearChatEmptyState` already knows how to.
  `newChatConversation` calls `clearChatEmptyState()` before wiping now (a
  no-op when there is no `.chat-empty` to rescue anything from);
  `loadChatSuggestions` also guards `box` with `?.` as the belt to that
  brace. `scratchpad/ui-sweeps/chatsuggestbug.js` reproduces the exact
  sequence and confirmed both the crash against the pre-fix code (a
  `PAGEERROR` and `#chat-suggest` gone from the document) and the fix.

## Left open

- **Item 38's bulk-move action is D2's, not this batch's**, per the
  item's own "Owner" line. The chip and label are the visibility fix that
  lets a person tell which space a survivor is actually in; moving a
  batch of them is still to build.
- **Whiteboard's own View menu** (`.wb-board-menu`, the screenshot INBOX
  31 opened with) was not touched: it already has its own
  max-height-on-open logic (whiteboard.js, `wb-board-menu-wrap` toggle
  listener) unrelated to the `details.dock-menu` family this item's fix
  targeted, and was not reproduced as broken in this session. Worth a
  Chromium check in its own right if it is still reported.
