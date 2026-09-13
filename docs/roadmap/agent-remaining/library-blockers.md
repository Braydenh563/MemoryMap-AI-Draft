# INBOX 107b, the Library half of the 0.3.0 blocker list

> Companions: [INBOX.md](../INBOX.md) · [HANDOVER.md](../HANDOVER.md)

One agent's pass over the four Library and OCR workspace items in INBOX 107b.
Every one was reproduced in a real Chromium before anything was changed
(`bash scratchpad/ui-sweeps/serve.sh 8793 /tmp/mm-8793`, Playwright through
`scratchpad/ui-sweeps/lib.js`) and measured again after. Four commits, one per
finding, each carrying its own before and after numbers. Nothing pushed;
INBOX.md untouched, per the brief.

The probes are `scratchpad/ui-sweeps/libblockers.js` (the seed: a note with a
markdown attachment carrying sixty lines of reading, plus an image upload with
both readings) and `libprobe.js` through `libprobe9.js`.

## Done

- **Item 1, the reader picker would not open.** `openActionMenu` unhid the
  menu, the chosen row took focus, the browser scrolled `.ocr-toolbar`
  (`overflow-x: auto`) to reveal it, and `closeActionMenusOnScroll` shut the
  menu the click had just opened. Before: 0x0, `display: none`,
  `aria-expanded="false"`, 3 rows built. After: 203x123 at (441,159),
  `position: fixed`, `z-index: 1020`, `aria-expanded="true"`, the topmost
  element at its centre its own chosen option. `focusMenuItem` (app.js)
  focuses with `preventScroll` and scrolls the menu itself when the row is
  below its own fold, so a long select still brings its chosen row into view.
  Every enhanced select and kebab inside a scrolling panel inherits the fix.
- **A second finding on the same control:** the stand-in listbox offered
  `<option value="ocr" hidden>`, which `ocrLoadReaders` unhides only on a
  machine with two readers. 3 rows against 2 unhidden options before, 2 after.
- **Items 2 and 3, the reading folds closing themselves.** The poll's
  signature check only ever covered "nothing changed". With one caption
  written in the background between polls: before, Files fold open
  true to false and the reading scrolled to 792 back to 0 over 24 rebuilds,
  Images fold true to false over 12. After, both stay open, the reading stays
  at 792. `openRowReadings` and `readingScrollTops` (library.js) remember
  them, keyed by `mediaRowKey`, and the three clamp sets are keyed that way
  now too (an `Attachment` and a `MediaUpload` share an id space here).
- **Item 4, the file name in a Files row.** The click was never the problem:
  all four routes in (attachment or upload, preview view or type view) open
  the workspace on the right file, and an image row still opens the lightbox.
  What was broken was the workspace after a text file had been through it:
  `replaceMissingMedia` deleted `#ocr-image` from the document when the .md's
  url failed to decode as an image, so every later open threw "Cannot set
  properties of null (setting 'src')" and showed the previous file's text
  under the new file's name. Before: `#ocr-image` absent from open 1 onward,
  a page error on every open after. After: present on all three opens,
  regions 2 / 0 / 2, no page error.

## Not verified

- **A PDF's page picture was never seen drawn.** This sandbox has no PDF
  render extra (`pdfpages.available()` is false, `/media/pdf-page/...`
  answers 404), so the workspace's stage stayed empty for a PDF. That same
  404 is what proved item 4's deletion, and it is now hidden rather than
  fatal, but "the page renders" is untested here.
- **Choosing a reader was not exercised end to end.** On this machine all
  three options are `disabled` (no model, no Tesseract), so the option row's
  click handler correctly returns without changing the value. The opening,
  the row count and the closing are measured; the value change is not.

## Found, not fixed

- **`scratchpad/ui-sweeps/selectfocus.js` fails twice on a notebook with
  content**, and it is not from this work: `graph/graph-view-picker`, "its
  opener cannot take focus" and "focusSelect landed on SELECT.ghost, not on
  its opener". Measured both ways to be sure: the branch's own code passes on
  an empty data dir (port 8851) and fails on the used one (8793), and the
  base checkout fails identically on that same data dir. So it is
  pre-existing and depends on notebook state. Worth an INBOX line: something
  about the graph's view picker on a populated notebook leaves its opener
  unfocusable, which is the shape `focusSelect`'s own comment was written for.
