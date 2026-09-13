# The attach picker, the two catalogues, the README tour: what is left

> One agent's three items, all three landed. This file is what a session
> picking the area up next needs: what was measured, what was deliberately not
> done, and the one bug found on the way that belongs to somebody else.

## How to pick this up

```bash
bash scratchpad/ui-sweeps/serve.sh 8934 /tmp/mm-shots            # its own port and data dir
cd /home/user/MemoryMap-AI
BASE=http://127.0.0.1:8934 SCRATCH=/tmp/claude-0 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  node scratchpad/ui-sweeps/pickerimages.js    # seeds five captioned images, then measures the rows
  #   NOSEED=1 re-measures a data dir that has already been seeded
  node scratchpad/ui-sweeps/catalogs.js        # runs every catalogue row's own closure
```

Gates: `bash scripts/gate.sh --changed`, plus
`.venv/bin/python -m pytest -q tests/test_feature_catalog.py tests/test_readme_freshness.py`.

## Done, with the numbers

1. **The attach picker's Images tab** (`frontend/app.js`, `notePickerShape`
   and `renderNotePickerOtherSource`; CSS at the end of
   `frontend/css/07-whiteboard-misc.css`). Every image row has a thumbnail and
   its caption. Measured over seventeen seeded images: 17/17 decoded
   (`naturalWidth` 96), 17/17 with a caption line, one row height (52.8px),
   0 console errors, caption contrast 7.4:1 light and 7.9:1 dark.
2. **Both catalogues** (`featureCatalog()` in `frontend/dashboard.js`,
   `paletteCommands()` in `frontend/app.js`). 110 rows in nine groups and 57
   commands; the dialog's heading counts what it rendered (168 with the AI's
   own tools). `tests/test_feature_catalog.py` fails on a row naming a tab,
   section, id or function that does not exist. `catalogs.js` ran every row:
   0 threw.
3. **The README tour** (`README.md`, `docs/screenshots/`,
   `scratchpad/ui-sweeps/readmeshots.js`). Thirteen captures, five of them new
   (a board, a concept map, Tools & features, the command palette, Appearance).
   `tests/test_readme_freshness.py` now also fails on a README image with no
   file, and on a file no README image shows.

## Left, with the file and the next step

- **A caption for an image that has none.** The picker's second line falls back
  to the note the picture is used in, then to "No caption yet". The Library can
  write one (`POST /media/{id}/caption`), and the row is the place a person
  notices it is missing: an "Ask the model for one" action on that line is the
  obvious next step, and was not built because it puts a model call behind a
  row in a picker, which is a decision, not a tidy-up.
  File: `frontend/app.js`, the `caption` entry of the images shape.
- **The other four picker sources have no thumbnail.** Documents, files and
  maps all have something to show (a first page, a file glyph, a map preview:
  `mapPreview` already draws the last of these for the boards gallery). The
  renderer is ready for them, `shape.thumb` is optional and per source. Only
  images were asked for.
  File: `frontend/app.js`, `notePickerShape`.
- **The chat screenshot shows an empty conversation.** There is no model in the
  sandbox, so the honest capture is the composer and its suggestions, and the
  caption was rewritten to say that rather than to promise an answer. A machine
  with Ollama running should retake `docs/screenshots/chat.png` with a real
  exchange in it.
  File: `scratchpad/ui-sweeps/readmeshots.js`, the `chat` entry.
- **The page reader has no README shot.** It wants a multi-page PDF and an OCR
  binary, and this sandbox has neither (`tesseract` is absent), so the reader
  would have photographed an empty reading panel. It is the one large surface
  the tour still does not show.

## Found, not fixed

- **`<rect> attribute x: Expected length, "NaN"` on the console**, dozens of
  them, while `catalogs.js` switches tabs quickly. Almost certainly a chart or
  heatmap laying out against a container that has no size yet (the shape
  CLAUDE.md warns about: a value invalid where it is used, not where it is
  set). Not reproduced at human speed, so not attributed to a surface; the
  quickest route is `catalogs.js` with the per-row wait raised until it stops,
  then bisecting by group.
- **The timeline's band label sits over the cards scrolled under it.** Visible
  in `docs/screenshots/timeline.png`: the sticky left column ("Uncategorised
  12") is translucent, so the cards of the columns scrolled behind it show
  through as ghost text. Left alone deliberately: the Timeline is being
  rewritten in the shared worktree (TIMELINE_PLAN Phase 1) and the band rail is
  part of what is changing. Whoever lands that should check it at a scrolled
  position, not only at `scrollLeft` 0, where it cannot be seen.
- **`tests/test_frontend_ids.py` fails on `timeline-view`** in the shared
  worktree: the Timeline rewrite in flight there has taken the element out of
  `index.html` while `app.js` still looks it up. Not this agent's change, and
  not touched; it belongs to whoever is mid-way through that plan.

## Closed by the orchestrator, 2026-09-13: the `<rect> ... "NaN"` errors

Left here as "not reproduced at human speed, so not attributed". Checked on
the head carrying every commit of this session, against a seeded notebook:

- all seven tabs at human speed (900ms apart): **0 console errors**;
- then three rounds of all seven at 40ms apart, which is what produced them in
  the catalogue sweep: **0 new**;
- and a walk of every element's every attribute afterwards looking for the
  string `NaN`, which is the trap this app has hit before (two missing
  appearance defaults once wrote `NaN` into CSS and flattened every card):
  **none**.

So it is an artifact of that sweep's own driving, not a fault in the app.
Nothing to fix; recorded so the next reader does not spend a session on it.
