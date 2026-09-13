# Inbox: things the owner dropped in while work was in flight

**How this file is used (the interrupt rule).** Anything the owner sends
while a step is in progress (a bug, a screenshot, a request, an opinion,
a usage figure) is appended here verbatim with the time, and NOT acted on
until the step in hand has passed its gate and is committed. Then, at that
boundary only, the inbox is triaged in one pass:

1. A bug in something built this session goes next (it is cheaper now).
2. A bug elsewhere goes into the relevant `agent-remaining/*.md` or
   BACKLOG row with the owner's words, and is scheduled by impact.
3. A feature or design request becomes a brief row (SESSION_BRIEFS or the
   plan it belongs to); it is not built ad hoc.
4. An opinion or a decision is recorded in the plan it affects and
   followed from then on.
5. "X% usage" means commit and push now, then continue more tersely.

Each item is moved out of this file when it has a home, with one line in
the report saying where it went. The point: the owner's pile after a usage
reset is processed as a batch at a boundary, the step that was in flight is
finished to standard first, and the goals in HANDOVER's "Now" line are
never lost to the smaller stuff.

## What is actually open, 2026-09-13

The owner asked how many items are in here and whether they need fixing or
clearing. Nine numbered entries, but that count is misleading: five of them are
batches from earlier sessions where most sub-reports carry a `Fixed <commit>`
marker mid-paragraph and were never filed out. Reading the numbers rather than
the contents overstates the work by about three times, which is what happened
the first time this was audited today.

**The genuinely open work, gathered from inside those entries:**

- The whiteboard is laggy to drag and pan (114). Unattributed after three
  passes. The one item here that is a real investigation rather than a fix.
- The graph suggested-links panel: spacing and padding inconsistent with the
  rest of the app (110, 111).
- The AI skills sidebar does not reach full height (110).
- The Files sub-tab text needs indenting, and "describe with AI" and the OCR
  passes should show as background processes (111, not investigated).
- Dragging the chat bar's height makes it snap back (111, not investigated).
- The AI edit-history popover still does not centre (111, carried from 107a).
- The per-model context window setting, so the token badge's window is
  manageable rather than assumed (77; the badge itself is done).
- 107c (whiteboard View and Arrange, Ctrl+S feedback, the dashboard band) and
  107d (the segmented mini-bar redesign): not started.
- The spelling popup's "wide gap" (128), which measures flush with the word
  here and is NOT reproduced; `scratchpad/ui-sweeps/spellanchor.js` is the
  probe for the next report.
- With agents as this was written: the settings logs dock (131), the command
  palette and Tools catalog audit (134), the README screenshots (138).

**What needs clearing rather than fixing:** 114's other seven reports, and
110's boards widget, square tab corners, chat panel shadow and glass tokens,
are all done and marked; they are sitting in the tray because nobody moved them
when they were closed. 107 also contains a question from the owner rather than
a task ("should I leave this pr open until we can finish the rest of the still
open and half finished stuff?"), which is a decision, not work.

## Open items

149. **Mid-work drop, 2026-09-13, verbatim (the owner), the graph.** "can you
    make graph nodes temporarily expand to fill their glow bubble when I hover
    over them or smth?? I feel like the graph nodes could look slightly nicer,
    cooler, more professional and more modern. visually". A visual ask, not a
    bug: the node's hit area already carries a soft halo larger than the dot,
    and the dot does not use it. Belongs in GRAPH_PLAN.md.

148. **Mid-work drop, 2026-09-13, verbatim (the owner), the New board dialog,
    one screenshot.** "also redesign that whiteboard and mindmap toggle in the
    popup, its ugly". The screenshot shows the Board / Mind map segmented
    control as a full-width pill with both options crowded into its left end
    and the right half of the track empty, and nothing naming what the choice
    is for.

147. **Mid-work drop, 2026-09-13, verbatim (the owner), the whiteboard and
    mindmap canvas.** "there's no way to delete a board while in that board on
    the whiteboard and mindmap." Deleting a board existed only on the gallery
    card's kebab menu.


146. **Mid-work drop, 2026-09-13, verbatim (the owner), the timeline feed, two
    screenshots (one full-width, one zoomed on the card's left edge).** "when i
    expand timeline items, the top text and stuff gets pushed up slightly and
    the vertical line on the right clashes with the other text and elements".
    The screenshots show an expanded note card: the title row and its tag
    chips sit hard against the card's top edge with a hairline rule directly
    under them, and a vertical rule (the timeline spine) runs down *inside*
    the card's left edge, crossing the title, the body line and the "Open in
    editor" button. Two separate faults: the expanded card loses the top
    padding the collapsed one has, and the spine is drawn over the card
    rather than beside it. A timeline agent (TIMELINE Phases 1 to 4) was in
    flight when this landed; it is sent there.


145. **Mid-work drop, 2026-09-13, verbatim (the owner), the Library images
    sub-tab, third report on these cards (two screenshots, one at rest and one
    with a fold open).** "The ui and ux and ux in the images cards needs
    improving"

    The two-rank rebuild has landed since the last report, and the screenshots
    are of that. What they show: the selection checkbox is a dark square
    floating over the top-left of every picture with no ground of its own,
    hardest to see on the dark thumbnails; the filename band sits on a grey
    strip across the bottom of the picture on some cards and over open sky on
    others, depending on the image; one card's caption is a wall of the
    picture's own OCR text rather than a description; and opening "Text" on
    one card grows it well past its neighbours, so the row's cards are 260px
    and 620px side by side.

144. **Mid-work drop, 2026-09-13, verbatim (the owner), the note edit form (one
    screenshot).** "when I open the edit form for a note and scroll down, only
    the bottom of the formatting bar sticks to the top of the screen and the
    bar is clear so it is hard to see"

    The screenshot shows the toolbar's icons overlapping a line of the note's
    own text, both legible through each other, with the Notes sub-tab strip
    above it: the bar has no ground of its own, so what sticks is a row of
    glyphs floating over the writing, and only part of the bar's height is
    held at the top.

142. **Mid-work drop, 2026-09-13, verbatim (the owner), the document editor's
    writing intelligence (two screenshots).** "the suggestions box at the
    bottom takes up a lot of my screen and it makes the text editor really
    small. also the popup edit suggestions menu screws upn the screen and
    make sit go out of bounds.and when I click on the issue from the
    suggestions thing, the box just appears right there in my face. the whole
    editor intelligence and auto correct and dictionary stuff needs a whole
    ux redesign and improvement"

    **This also settles INBOX 128**, which could not be reproduced: the first
    screenshot shows the word popup drawn at the far right of the window,
    clear of the document card altogether, while the flagged word sits at the
    end of line 4 inside it. So the "wide gap" is real; the probe
    (`scratchpad/ui-sweeps/spellanchor.js`) simply measured a case where the
    anchoring happens to be right, which means the bug is conditional and the
    condition is what has to be found.

    Four things in the report, and the last is the shape of the work:
    - the suggestions panel at the foot takes a large share of the window and
      shrinks the editor it is advising;
    - the word popup goes out of bounds;
    - opening a suggestion from the panel puts the popup over the text being
      discussed rather than beside it;
    - and taken together, the spelling, autocorrect, dictionary and suggestion
      surfaces want one redesign rather than four fixes.

141. **Mid-work drop, 2026-09-13, verbatim (the owner), the Write with AI
    sub-tab (four screenshots, two pairs of before and after a click).**
    "when I clcik on the text box in the \"write with ai\" subtab, the
    structure goes all funky. and also the bottom elements under the right
    text part need visual improvements and restructuring, aligning and
    spacing etc"

    Pair one: Undo, the hint "Optional: make it shorter, add a summary" and
    Draft it sit on one row; after a click they become three stacked rows,
    left-aligned, with the hint on its own line. Pair two: the Tags field
    shows its label and placeholder on one line, and after a click the label
    sits above the placeholder with the caret on the second line. So a click
    changes the layout rather than just the focus. The second half of the
    report is that this bottom area needs restructuring, alignment and
    spacing regardless of the bug.

138. **Mid-work drop, 2026-09-13, verbatim (the owner), the README.** "and
    also the screenshots on the readme page need updating and they need to
    show more parts of the application than what is there."

    The shots predate most of this session's surfaces (the docks, the
    documents editor, the mind maps, the timeline), and there are fewer of
    them than the app has places worth showing.

134. **Mid-work drop, 2026-09-13, verbatim (the owner), one screenshot of the
    Tools and features dialog.** "the tools and features popup content is
    poorly text aligned between the headers and the content, and make sure
    the command pallate and that tools and features popup are up to date"

    The screenshot shows the group header "CAPTURE & NOTES" left-aligned at
    the dialog's inset while every row under it (name and description both)
    is centred, so nothing lines up with anything. The second half is a
    coverage question: the dialog says "105 things MemoryMap can do", and a
    great deal has been built since that list was last touched.

131. **Mid-work drop, 2026-09-13, verbatim (the owner), one screenshot of
    the Settings logs page.** "can you also redesign the top dock at the top
    of the settings logs page to be more consistent with the rest of the
    application and modern??"

    The screenshot shows two rows of unrelated controls: a List/Terminal
    segmented control, two selects and a filter box on the first, and a
    Follow switch, a "live" dot, Copy all, Support bundle and Clear on the
    second, none of it on the `.dock` grammar every other tab head uses.

128. **Mid-work drop, 2026-09-13, verbatim (the owner), the spelling popup
    (one screenshot, a document in dark theme).** "I clicked on a flagged
    word and the popup didnt appear right next to it but off to the side
    with a wide gap, also I swear I added \"idk\" to the dictionary last
    night, make sure it is persistent."

    Two things. The popup is anchored several hundred pixels to the right of
    the flagged word (the word "idk" is at the left of the line and the popup
    sits against the right edge of the editor), and the popup itself offers
    "Add \"idk\" to dictionary" for a word the owner says they already
    added, so either the add does not persist across a restart or it persists
    somewhere the checker does not read. The persistence half is the more
    serious of the two: it is silent data loss.

114. **Mid-work drop, 2026-09-12 afternoon, verbatim (the owner), six
    reports across five screenshots.** In order as sent:
    - "I think the border shadow on elements like these are too strong"
      (three dark screenshots: the top bar, a Peek/Close bar, two icon
      buttons). **Fixed `69ae9cd`**: the tonal tier carried `--shadow-sm`,
      which is seven times heavier in dark and was sized for a panel;
      measured `rgba(0, 0, 0, 0.35)` on every button in the top bar.
    - "fix the look of the mindmap item radial" (two screenshots: eight
      circular slots scattered around and *over* a selected topic, some
      overlapping the node's own chevron and its text, one sitting on the
      node's edge; a second map where the ring's slots overlap a topic and
      a link). **Fixed `df988c4`**: the ring was a fixed 68px circle around
      the node's *centre*, which covers any node wider than the ring is
      round. The radius now clears the node's own measured box. Measured on
      a default topic (200 by 44 on screen): slots over the topic 2 to 0,
      nearest gap -36px to 8px, slots on the node's edit strip 2 to 0,
      radius 68 to 122, spread 0 both times; `mapstrip.js` 39/39.
    - "the view dropdown menu in the whiteboard and mindmap is still
      broken, fix it" (screenshot: the LOOK menu open, "Snap to grid" cut
      in half at the bottom edge, a scrollbar present, the menu far
      shorter than its content). This is INBOX 107c's menu-height item,
      reported again after `1096ee7` capped the menu from where it was
      actually placed, so that fix did not reach this menu. **Fixed
      `8b92164`**: `escapeAndCapMenu` cleared its own inline cap before
      measuring, which handed the menu back to the *stylesheet's* cap
      (`.wb-board-menu`, `calc(100vh - 9rem)`), so the placer measured a menu
      that had already been cut and left it lower than it needed to be.
      Measured on the map's View menu, 714px of content: at 1440x760 it was
      placed at top 56 and capped to 696 and scrolled, now placed at 36 and
      capped to 716 with no scroll; at 1280x640 the visible content goes 574
      to 622, at 1024x500 434 to 482.
    - "litterally everything isnt in the dictionary" (screenshot: 268
      suggestions on a 298-word document, with "Offline", "No",
      "internet", "connection", "handling" and "for" all listed as not in
      the dictionary). The word list went in at 92,972 words on
      2026-09-12 morning and `docs-spell.js` measured six findings over
      8,000 characters of README with no false positives, so something
      between that and a real document is not matching at all.
    - "the new from a template popup buttons need a look consistent with
      the rest of the application" (screenshot of the template dialog:
      six full-width rows drawn as heavy outlined boxes, and a Cancel
      that does not match the app's own dialog actions). **Fixed
      `f53132b`**: the rows were `button.ghost` with nothing taking the
      tonal fill and hairline off, and every `.space-dialog-actions` row is
      written `class="row right ..."` against a `.right` rule that does not
      exist anywhere in the app. Measured: outlined rows 6 to 0, row type
      16px to 13.6px, row height 61 to 55, dialog height 559 to 526, and all
      ten dialog action rows now report `justify-content: flex-end`.
    - "the height of the cature a thought taskbar and note edit form are
      really high compared to the one in the documents editor"
      (screenshot of the note toolbar, one tall row with a horizontal
      scrollbar under it). **Fixed `cce4dbf`**: `.note-toolbar` is written
      tighter than the document editor's strip on purpose, and two rules took
      that back, `.doc-toolbar[data-toolbar-mode="row"]` at (0,2,0) beating it
      in the scrolling mode, and the edit form's clone being built without
      `note-toolbar` at all. The same specificity gap also left the edit
      form's strip `nowrap` with `overflow-x: visible`, drawing 339px of
      controls outside its own box. Measured at 1440x900: composer strip in
      row mode 58px to 50px, edit form strip 58px with 339px of overflow to
      86px with none, edit form in wrap mode 91px to 88px; the document
      editor's own strip untouched at 91 and 58.
    - "the tree view on the graph is still broken" (screenshot: the graph
      drawn as a scatter with crossing dotted links, not a tree).
      **Fixed `ba892b0`**: a race, not the layout. A position update from
      the force worker delivered after the hierarchy had been laid out
      overwrote it by index (`{type:"stop"}` cannot unsend a tick already
      posted). Every worker message now carries the epoch of the `init` it
      belongs to and a stale one is dropped. Measured with
      `graphtreerace.js` at every 100ms of the cooling curve: depth-1
      spread 469.2px and depth-2 spread 962.3px at one of fifteen moments
      before, 30 of 30 moments at spread 0 after.
    - "The note node popups dont show on any of the graph views when I
      click on a node except for the force view. Also I dont think you
      have redesigned the popup agent yet" **The agent panel half is fixed
      `6b4e75e`** (the graph half is another agent's): a run's step counter
      shared a slot with the background-job detail sentence and wrapped under
      itself, so rows measured 78px and three runs overflowed the 200px list;
      counter marked as a counter, rows 60px, three runs fit. Also took out
      `.monitor-title`'s dead `font-size` (the `.card h3` eyebrow wins at
      (0,1,1); 12px before and after) and gave the 0.3s entrance the
      `prefers-reduced-motion` branch it had none of.. **The popups are fixed
      `f72eec8`**: a click on a node was handled by d3-drag's `end`, and
      tree, radial and arc deliberately have no drag, so the one path to
      the popup did not exist in three of the four views. Measured with
      `graphtree.js`, a trusted click on the node nearest the centre of
      the viewport: popup 448x338 in force and closed in the other three
      before, 448x338 in all four after. **The popup redesign is not
      this**: GRAPH_PLAN Phase 6 and the three evening rows under "Placed
      from INBOX, 2026-09-09" hold the node panel, and the agent popup is
      a different surface again. Left open.
    - "the whiteboard is still laggy to drag and pan around, it isnt
      perfextly smooth and uniform like it should be on a professional
      application" (third report; two measured passes have failed to
      attribute it, and this sandbox is vsync-bound at ~16.7ms in every
      condition tried, so the next attempt needs *drag* profiled, not
      pan, and needs a real machine to confirm)
    - "what does left off mean?? should it be something else??"
      (screenshot of the dashboard's Continue pill, tooltip "Continue
      where you left off"). **Fixed**: the tooltip now states the rule,
      "Opens the note you edited most recently".
    - And a question that is a feature request, recorded here rather than
      answered ad hoc: "there also needs to be more integration and
      merging between features. like if a document references a note, can
      you see in that note on the notes page that it is referenced by
      that document?? If I make a new reference or link in the text
      editor like in obsidian, can I click on that new link and create it
      into a new note, document or smth else??"


111. **End-of-session drop, 2026-09-09 evening, verbatim (the owner), fixed
    this pass in parentheses.** "the documents formatting toolbar still
    gets clipped, and can you change the editor window background for
    when on the plain text view to be like vs code??" (fixed: stale
    `doc-toolbar-mode` "row" localStorage value from before the
    2026-09-09 wrap-default change migrated once to "wrap"; Plain view
    now paints a literal black/white ground behind CodeMirror's own
    transparent editor, `49d78c1`) · "also the show line numbers button
    on the documents formatting toolbar doesnt work" (not investigated:
    `applyDocGutter`/`docCmGutter` read `docGutterWanted`, wiring not yet
    traced live) · "I dragged a note from the library dropdown onto the
    board but the note appeared in the top left, not in the centre where
    I placed it" (fixed: the drop handler measured against
    `#wb-html-layer`'s own rect, which already carries the pan/zoom as a
    CSS transform, then applied that same transform again on top;
    switched to the untransformed `#whiteboard-container`, `49d78c1`) ·
    "can you make the 'm' navigation kinda like alt tab... if I hold it
    down the popup stays up", refined to "press m again to close it or
    an x close button" (fixed: the guide no longer auto-hides on a fixed
    900ms timer; a second "m" or a new X button closes it, `49d78c1`) ·
    "and fix the whiteboard dropdown menu heights, make sure they arent
    too short but also not clipped off the bottom" (**not verified**: a
    live probe found no open board in the scratch data dir to measure
    against; the two CSS `max-height` rules on `.wb-board-menu`
    (07-whiteboard-misc.css ~7330 and ~7601) already disagree, the later
    one, `calc(100vh - var(--space-9) * 2)`, wins and is the more
    generous of the two, so the "too short" report may already be stale
    or may be a real bug this session could not reproduce) · "when I
    pressed the jump to latest button in the chat, it jumped to the
    right for a second. same with a lot of dropdown menus and tooltips,
    they flicker into the top corner for a second then appear in the
    right place" (**investigated 2026-09-12, not
    reproduced**, and the sweep that looked is now
    `scratchpad/ui-sweeps/flicker.js`: a MutationObserver installed before
    any page script runs samples every element that goes from not-rendered
    to rendered on the next animation frame and again four frames later, so
    a surface painted before it was positioned is caught by the move between
    the two rather than by a screenshot. 50 floating surfaces opened across
    all seven tabs plus the header's four, at 1440x900: 0 moved more than
    24px. What that run did **not** cover, and where the report may still
    live: the chat's own jump-to-latest pill, which needs a long streaming
    transcript to appear at all, and the documents AI popovers, which need a
    document open. The earlier guess, a shared "measure at 0,0 then
    reposition" recipe, is not supported by anything measured:
    `wireEscapedActionMenu`'s `place()` is synchronous inside one
    MutationObserver callback and the sweep agrees it does not move.) · "this text in
    the files sub tab needs indenting, and the describe with ai feature
    needs to show in background process, same for all ocr processes"
    (not investigated) · "when I try to manually change the height of
    the chat bar, it snaps back to what it was with or without text in
    it" (not investigated) · "the ai edit history popover still not
    centering" (carried from 107a, still found-not-fixed) · "fix the ui
    spacing and padding in the graph suggested links tab, make it
    consistent with the rest of the app" (not investigated). 107c
    (whiteboard View/Arrange, Ctrl+S feedback, the dashboard band) and
    107d (the segmented mini-bar redesign) remain not started. The
    second batch's own remaining items (boards & maps widget visual
    design, AI skills sidebar not reaching full height, square tab
    corners, chat panel shadow, light-vs-dark glass difference) remain
    not reproduced live, not fixed. Two background agents (a dashboard
    hero MSN-style redesign, a bugs-batch covering the whiteboard menus
    and the AI history popover) were dispatched this session and both
    hit the weekly agent rate limit before landing any commits; nothing
    from either survives to merge.

110. **A second batch, mid-work, 2026-09-09, verbatim (the owner).**
    "These requests in the photos and in the following also werent
    fixed: the boards and maps dashboard widget is ugly and needs
    fixing, and the graph suggested links panel is poorly designed and
    not consistent with the rest of the app ui style. the documents edit
    and read toggle options dont fit in the toggle and go out of it at
    the bottom and I want to be able to use the documents tab as a plain
    text editor like before as a view option (not the defauklt though)
    and also if I select a txt document, and/or other code file
    document, and these can have line numbers as well. Im assuming this
    will all be done when you continue the documents and graph plan when
    my usage resets, but also i still cant click on a grammar or
    misspeled underlined word and see a popup like in a realworld editor
    like obsidian, word, notion, vs code. also for code files, include
    code syntax and make it a proper code editor like vs code. the files
    description needs to be an actual description or summary of what
    the file is about and includes, not a transcription. also the
    panels and sidebars in windows actually go quite far down below
    where the scroll should stop, and the ai skill sidebar isnt 100%
    height. also the containers of all the ui in each tab page have
    hard corner rectangular edges so I want that fixed because the
    shadows make the cut off pretty obvious. and in the chat tab, the
    main chat panel shadow actually reaches all the way down on the
    gap. also no back to top button appears on the dashboard?? and
    glass looks better on light mode and not dark but idk if thats an
    actual thing or if the values are different." Screenshots: a Files
    row's title/kind/size row misaligned (repeat of an earlier report,
    now closed once, live again); the links editor Save/Cancel pair
    (repeat, already closed once, live again); the `m` quick-nav guide
    rendered as an overlapping card, not a full-screen hint; the
    Edit/Read toggle (repeat, already closed once); the suggested-links
    panel's plain unstyled rows.
    **Triaged 2026-09-12, with numbers against the running app.** Fixed this
    session: the suggested-links panel (an inset and one scrollbar instead of
    none and two), the boards and maps widget and the glass difference
    between themes (both by agent), the AI skills sidebar (measured full
    already, see below), "no back to top button on the dashboard" (measured
    present), "the panels and sidebars go far below where the scroll should
    stop" (measured 16 to 40px of page gutter on every scrolling tab), the
    hard corners (by agent), the chat panel shadow (the composer was ringing
    itself on arrival), the files description (the prompt now rules out a
    transcription in as many words), and the click-an-underline popup plus
    line numbers for code files (both by the documents pass, with a real
    92,972-word dictionary behind the underline).
    **Measured and not reproducible**, at 1440, 1280, 1024, 820 and 390:
    "the documents edit and read toggle options dont fit in the toggle and go
    out of it at the bottom". The segment is 36px with 4px of padding and its
    two buttons are 28px sitting exactly 4px inside it at every width, with
    no text clipped and nothing overflowing its own box
    (`scratchpad/ui-sweeps/docsegfit.js`). This was closed once before, so
    the earlier fix is holding and the screenshot in this entry is stale.
    **Triage.**
    - Plain view, Line numbers: **already correct**, see 107a's commit
      `9a2ddf1`, no change needed.
    - Files row alignment, links Save/Cancel, Edit/Read pill: reported
      fixed earlier in HANDOVER's done-when items 3 and 5; **live again**
      means either a regression since or, per today's pattern, a stale
      build. Not re-chased without a live reproduction.
    - Real code editing (VS Code-grade syntax highlighting, a spell/
      grammar-check popover): this is DOCUMENTS_PLAN Phase 3 scope, not
      a bug fix; the owner's own words scope it to "when you continue
      the documents and graph plan when my usage resets". Left for that
      phase, not attempted piecemeal here.
    - The `m`-guide as a full-screen hint: a design change (WORLD_CLASS_
      PLAN quick-nav item), not a fix; needs its own pass against
      DESIGN.md's recipe index (standing order 11).
    - Files description as summary not transcription: built this
      session (`docreader.py`, `captioning.py` DOCUMENT_PROMPT); if
      still a transcription live, needs reproduction with a real file,
      not assumed broken.
    - Boards & maps widget, suggested-links panel style, panel/sidebar
      overflow, AI skill sidebar height, square corners app-wide, chat
      panel shadow, dashboard back-to-top, light-vs-dark glass: each is
      its own visual judgement call, none reproduced live this pass.
      Placed here rather than fixed blind.
    **Reproduced and fixed, 2026-09-12** (measurements in the commits and in
    `agent-remaining/visual-c.md`):
    - **Boards & maps widget: fixed.** The thumbnail was a 40.5 by 40.5 square
      drawing its own border and fill with the board letterboxed inside it, so
      a 100x65.7 board came out 38.5 by 25.3 with 7.6px of empty band above and
      below, inside a second border 1px outside the first; 59% of the box was
      the picture. Now 72 by 40, one frame, 85%. A board's meta also called its
      objects "images" and reads "items".
    - **Square tab corners: fixed, and it was one control.** Swept every
      visible element's radius on all ten tabs; the main strip is not square,
      and the only tab-like control computing 0px was the Documents sidebar's
      Documents/Outline strip, whose hover painted a hard-edged grey rectangle
      clamped to the word. The wider "all the containers have hard corner
      rectangular edges" half did not reproduce at 1440x900: no framed square
      container on any tab but the full-width status bar.
    - **Chat panel shadow: fixed.** It was `.chat-dock:focus-within`'s accent
      ring, lit by `switchTab`'s own focus, so every arrival on Chat opened
      with a blue halo round the composer. The caret still lands there; the
      ring waits for the reader.
    - **Light vs dark glass: three token bugs fixed.** `--shadow-sm` had no
      dark value at all (a blue-violet ink on a near-black page), and neither
      the shadow-strength nor the sheen-strength slider reached dark mode.
    - **Still open from this entry**: the graph suggested-links panel, the
      panel/sidebar overflow, the AI skills sidebar height, the dashboard's
      back-to-top button, the files description, and the documents code editor
      (DOCUMENTS_PLAN Phase 3).

107. **The 0.3.0 blocker list (the owner, 2026-09-09 23:25, verbatim).**
    "should I leave this pr open until we can finish the rest of the still
    open and half finished stuff?? otherwise I need to to absolutely make
    sure that finishing this list of unfinished items and half finishe
    items in the number one priority, I need them finished, this pr is
    v0.3.0 and I dont want to merge it if things arent complete... work
    through these bugs really fast: can you make the live view on
    documents the default if it isnt already?? also when I click on the
    plain and line numbers view nothing happens and they dont do anything.
    note in the redesign documents and where it is supposed to that I want
    to get rid of and redesign these mini menu bars as they are in a couple
    popups around the place and they desperately need a modern redesign or
    alternative, the ai assistant popup blurred background in the documents
    doesnt reach the full height of the scree, leaving a clear strip at the
    top and bottom, and the ai history popup goes to the left of the
    screen, should it be in the middle?? I put in a link to a note in the
    document, but when I clicked it, it didnt take me to the note and
    instead a notification showed saying no document by that name exists
    yet. fix the formatting bar in the documents tab, it is crushed
    bertically and has a vertical scrollbar. I cant open the reader ai
    dropdown combobox at the top of the ocr workspace. I scroll to the
    bottom of the ocr text in the files row in the files subtab, and the
    whole \"extracted text from this file\" dropdown closes. the same
    happens when I scroll to the bottom and expand, and click see more the
    \"text in this image\" dropdown in the images tab. I cant click on the
    file name header in the files subtab file rows to open the file up in
    the lightbox or ocr workspace. the view dropdown in the whiteboard
    opens on top of the top bar, not under it, and it is overly short, the
    arrange dropdown is also very short, there's no visula feedback when I
    press ctrl + s in settings. the pckage headers, badges and buttons
    still get displaced onto separate rows did you make changes to the
    section between the hero section and the widgets on the dashboard? they
    look the same..."
    Screenshots: a bolded run showing literal `**` markers in a document; the
    Edit/Write/Remove segmented bar; the AI assistant dialog with its
    backdrop; the AI edit history popover at the left edge; a document with
    an `Act I, Scene I` link and two identical "No document called ... yet"
    toasts.
    **Split, 2026-09-09**: 107a documents (live default, the plain and
    line-number views, the assistant backdrop, the history popover
    placement, the note link, the formatting bar) · 107b files and images
    (the reader combobox, the two dropdowns closing on scroll, the file
    title click) · 107c the rest (whiteboard View and Arrange, Ctrl+S
    feedback, the packages row, the dashboard band) · 107d the segmented
    mini bars, a redesign recorded in DOCUMENTS_PLAN and DESIGN.md.
    **Status, 2026-09-09 evening.** 107a: five of six closed (`9a2ddf1`),
    the AI history popover still found-not-fixed. 107b: **done, merged
    and pushed (`b24836d`)**, all four items closed plus two bonus finds
    (a select offering a hidden option; focusing a menu's first row
    scrolling the page enough to close the menu itself).
    **Status, 2026-09-12.** 107c: three of four closed. The whiteboard View
    and Arrange menus were capped from the opener's bottom while
    `placeEscapedMenu` had already moved them higher up the window, so at
    1440x700 the View menu scrolled 594px of content through a 505px port
    with 89px of window to spare; it now takes the room under where it
    actually sits. Ctrl+S in settings never reached the settings-aware code
    written for it at all, because `shortcuts` carries a `save` binding on the
    same keys that answers first; it does now, it rings the section's own Save
    button or the nav button for a section that saves as you change it, and
    the ring composes with the control's resting shadow instead of replacing
    it. The dashboard band had not in fact been changed (the redesign
    dispatched for it landed no commits); its one measurable defect, a
    Continue pill holding double width for a note line a later rule hid, is
    fixed. **Left: the packages row** (headers, badges and buttons displaced
    onto separate rows), not reproduced this pass.
    107d: **done**, recorded in `docs/DESIGN.md` and pointed at from
    DOCUMENTS_PLAN.md.
    **The owner's live error, confirmed as this exact fix.** A console
    trace at `library.js:3291` ("Cannot set properties of null (setting
    'src')", from `openThisRow`/`ocrOpenSibling`) matched the pre-fix
    line for line at the previous head. `git pull` plus a server restart
    is what picks this up; the boot-token cache fix (`dd2d843`) stops the
    *browser* from serving old code once the server has new code on
    disk, it does not substitute for actually pulling the branch.

77. **Half done, 2026-09-09: the badge is fixed.** It reads "1.2k / 20k"
    instead of "6% of window", is 20px tall at every width from 420 to 1440
    (it stretched to 44px below 820 before), and is centred against the chat
    subline. What is left is the second half below, the per-model context
    size, which the entry already assigns to the next session.
    **Token window badge: not centred, text wrong; the window itself
    should be manageable by the user and auto when set** (screenshots:
    "6% of window" pill off-centre in the chat header, and the header wraps
    at width). Owner: CHAT_PLAN header (Fable, now for the badge; the
    window setting next session): a `num_ctx` preference per model in
    Settings > Models with Auto (the model file's value) or a number, sent
    on every request; the badge shows "used / window".
## Placed (last 20, newest first)

- 2026-09-08: dashboard hero preference, New note tile colours, sub-tab
  arrow keys, Files reading, sidebar toggle, mindmap bugs, line numbers,
  docks as one bar, timeline redesign, responsive design, em-dashes,
  paragraphs to popovers, security review: all placed (HANDOVER "flagged
  list") and most built.
