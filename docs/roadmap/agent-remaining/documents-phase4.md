# Documents: Phase 3 is complete; Phase 4, the connected document

**Branch** `claude/epic-ramanujan-8xocc0`. Successor to
`documents-phase3.md`, which described items 4 and 5 as "not started": they
landed on 2026-09-12 in `8fd3603`, `a5ef6b1` and `041d0ce` and that file was
one round stale.

## 1. Phase 3: all five items built, re-measured on the branch head

Confirmed on `d0b6d35` rather than taken from the commits that built it, which
is the point of re-measuring: `scratchpad/ui-sweeps/docprops.js` **30/30**,
`doccols.js` **23/23**, `docembed.js` **14/14**, and
`tests/test_doc_frontmatter.py`, `test_doc_columns.py`, `test_doc_tables.py`,
`test_doc_math.py` green. The built record, with every decision, is in
HISTORY.md under "From DOCUMENTS_PLAN.md Phase 3" (two entries: items 1 to 3,
and items 4 and 5). The plan holds a one-line pointer and the syntax decision.

**The one half-item that is not built**, and it is item 4's second clause:
"searchable from the Library's filter". The frontmatter is parsed and the
fields are editable; nothing filters documents on a property. `library.js` was
outside the building agent's scope and is outside this one's too. A
client-side filter over the documents list is one function in `library.js` and
needs no migration or endpoint; a server-side one needs a column or a query
parameter in `routes_documents.py`. Recommendation, so the decision is not
re-derived: client-side, because the documents list is already loaded whole.

## 2. Phase 4, the connected document: where it stands

Not started as this file is first written (2026-09-12, the documentation pass
that closed Phase 3). This section is rewritten at the stopping point with
file, id and next step per plan item.

## 3. Found and not fixed, carried forward from Phase 3

- **`scratchpad/ui-sweeps/editor.js` still describes the retired editor**, as
  `documents-engine.md` §2 says. Untouched again.
- **The table cell menu is a `kebabMenu` with ten items and no grouping.**
  Rows, columns and alignment read as one list of ten. `kebabMenu` has no
  separator today; adding one is a change to the shared recipe and to
  DESIGN.md, which is why it was not done inside a phase item.
- **`enhanceSelect` (app.js ~18427)** rebuilds every `<select>` as a shell
  with a `<button>` opener and takes the native element out of the tab order,
  so `select.focus()` focuses nothing and a `keydown` bound to a select never
  fires. There is no lint for the class.

## 4. Not verified, carried forward from Phase 3

- **Chromium only**, at 1440 and 390. No other browser and no touch device;
  the table's cell menu in particular is a 28px target inside the text.
- **The fallback textarea path** (`docCmBroken`) for tables, embeds,
  properties and columns. The models are engine-independent and tested in
  node; nothing has been driven in a browser with the engine off.
- **Multi-line `$$…$$`** is deliberately not rendered (a replace decoration
  from a view plugin may not contain a line break). Single-line `$$…$$` is.
- **A table inside a callout or a list item.** `docTableParse` finds tables by
  pipe-bearing lines, so an indented table inside a `>` blockquote is not one
  as far as it is concerned. Nobody has asked; it is a real shape.
