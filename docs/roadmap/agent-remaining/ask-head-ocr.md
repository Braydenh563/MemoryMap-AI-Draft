# Left by the Ask-head / page-reader agent, 2026-09-13

Both of the owner's reports from INBOX 125 and INBOX 126's first bullet are
built, measured and pushed. What follows is what a next session would need.

## Nothing is half-built

- **The answer head** (INBOX 126, first bullet): `frontend/index.html`
  `h3.panel-head.answer-head`, `#answered-by`, `#retry-btn`, `#copy-btn`,
  `#speak-btn`; `frontend/css/08-consistency.css` family 8;
  `renderChatMeta`/`setAnsweredBy` in `frontend/app.js`. Sweep:
  `scratchpad/ui-sweeps/askhead.js` and `askheadcontrast.js`. Lint:
  `tests/test_ui_recipes.py::test_a_panel_head_is_identity_one_fact_and_actions_that_do_not_wrap`.
- **The lightbox / reader stacking bug** (INBOX 125, first half): the
  `readWithAiBtn` handler in `frontend/app.js` inside `openLightbox`. Lint:
  `tests/test_lightbox.py::test_the_lightbox_leaves_before_the_workspace_arrives`.
- **The reader's second door** (INBOX 125, second half): `openPageReader` in
  `frontend/library.js`, the palette row in `paletteCommands` (`app.js`) and
  the "Page reader" row in `featureCatalog` (`dashboard.js`). Decision:
  UI_MODERNISATION_PLAN.md, "Decided, 2026-09-13, how the page reader is
  reached". Sweep: `scratchpad/ui-sweeps/pagereader.js`.

## Found, not fixed

- **`.answer-actions` lost its words, and one other head may want the same
  pass.** `#chat-results`'s second half (`Matching records` + `#search-mode`)
  is now the only `.panel-head` in the page with no actions, so the lint has
  one real subject. The next head that wants a control beside its title should
  take family 8 rather than inventing a fourth arrangement, and that is what
  the lint is there to insist on.
- **The Ask results grid is two columns down to 900px.** At 1024 each half is
  356px, which is why the badge has to ellipsise a long model id at all. The
  breakpoint (`@media (max-width: 900px)` on `.chat-grid`,
  01-forms-settings.css) is arguably too low for a panel that holds an answer,
  but moving it is a layout decision the owner has not asked for, so it was
  left alone and is written here instead.
- **Nothing measures a real reading.** `pypdfium2` + `Pillow` were installed
  into `.venv` in this sandbox so a PDF would render pages in the lightbox at
  all; no vision model or Tesseract ran, so "the reader reads" is still
  unverified by this session. `tests/test_pdfpages.py` and friends skip
  without that extra, so a machine without it sees fewer tests, not failures.
- **The shared worktree swallowed three of this work's file edits.** Another
  agent committing with a whole-tree stage carried `frontend/index.html`,
  `docs/roadmap/INBOX.md` and this session's `app.js` palette entry into
  `7c4ce50` and `3dc125b`. The content is on the branch and correct; only the
  commit messages are wrong about what they contain. Nothing is missing.
