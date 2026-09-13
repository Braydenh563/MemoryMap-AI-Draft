# Paging the list endpoints (INBOX 117)

Two commits on `claude/epic-ramanujan-8xocc0`, both gated with
`scripts/gate.sh --changed` (lints, node-check, ruff, changed-tests: green):

- `e38dffa` the backend. `/documents`, `/reminders` and `/media` take
  `limit` and `offset` and set `X-Total-Count`, the shape `GET /entries`
  was given after the same finding. Page sizes: documents 200 (max 1000),
  reminders 200 (max 1000), media 200 (max 500, lower because a row carries
  `ocr_text`, `caption` and `vision_ocr_text`, so a row count is a poor
  proxy for bytes). Each list is ordered with the id as a tiebreaker, or two
  rows sharing a timestamp could swap places between pages and hide one.
- `dd0caa5` the frontends that must not lose a row. `apiPagedList` in
  documents.js loops until `X-Total-Count` is satisfied; `loadDocuments`,
  `renderLibraryDocuments`, `renderLibraryImagesGallery`, `ocrLoadSiblings`,
  `editorLoadFiles` and the editor's `[[` document cache all use it.

Measured with 300 rows of each seeded through the models:

| endpoint | before | after, no params | after `?limit=10&offset=295` |
| --- | --- | --- | --- |
| `/documents` | 300 rows, 119,483 B (116.7 KB) | 200 rows, 79,801 B (77.9 KB) | 5 rows, 1,976 B |
| `/reminders` | 300 rows, 53,783 B (52.5 KB) | 200 rows, 35,783 B (34.9 KB) | 5 rows, 901 B |
| `/media` | 300 rows, 120,383 B (117.6 KB) | 200 rows, 80,401 B (78.5 KB) | 5 rows, 1,991 B |

## Closed by the orchestrator, 2026-09-12 evening

Both sections below are done. `app.js` and `dashboard.js` freed up when the
Notes agent reported, and all nine call sites read to the end through
`apiPagedList`: `loadReminders`, `clearDoneReminders`, `openPalette`'s
`paletteReminders`, `loadCaptureDocuments`, `renderAttachToDocument`,
`notePickerRows` (documents, files and images), `resolveMediaUploadByUrl`,
and dashboard.js's three reminder reads.

The Reminders decision the section below asks for was taken the second way
it offers, reading to the end rather than adding a pager: it is four lines,
loses nothing, and leaves the grouping alone. The `due_at` caveat is what
decided it, and each site now carries it as a comment: the first page is
the *oldest* rows with the ticked-off ones among them, so a notebook whose
oldest two hundred are all done would have pushed everything upcoming off
the list. A real pager is still the better answer at thousands and is left
here as the next step.

Measured on a seeded notebook of 260 documents and 260 reminders, past the
server's 200-row page: `apiPagedList` returns 260 and 260, a single
unpaged read returns 200 and 200. `resolveMediaUploadByUrl` was found while
doing this and is not in the list below: it resolves one url to its upload
row, so an upload past the first page simply did not resolve.

The original entries, for the record:

## 1. The Reminders tab still reads one page (app.js, held elsewhere)

`frontend/app.js` and `frontend/index.html` were held by another agent while
this was built, so the Reminders frontend was not touched. The backend is
paged; these five call sites are not, and each takes the first 200 rows:

- `loadReminders` draws the Reminders tab from `GET /reminders` and groups
  what it gets. **This is the one that needs a decision**, and the decision
  is not "loop like the others": the list is ordered `due_at` ascending, so
  the first page is the *oldest* rows, ticked-off ones included. A notebook
  whose oldest two hundred reminders are all done would push everything
  upcoming off the page, which is the silent loss this whole item exists to
  prevent. Two honest options: page in the UI (the Library's own pager is
  the recipe: `library-docs-pagination` in index.html, `libraryDocsPageSize`
  in library.js), or read to the end with `apiPagedList("/reminders", 200)`
  the way the other three surfaces do and leave the grouping alone. The
  second is four lines and loses nothing; the first is the better answer for
  a notebook that really has thousands.
- `clearDoneReminders` deletes the done ones it can see, so on a paged
  response it clears the first page's done rows and reports that count.
  Reading to the end fixes it exactly.
- `checkDueReminders` and `openNotifications` filter for overdue rows.
  `due_at` ascending means the overdue ones are at the front, so these two
  are correct on the first page today; they stay correct only while the
  ordering does.
- `openPalette` preloads `paletteReminders` for the command palette's
  search: first page only, so a reminder past it is unfindable there.

`index.html` is needed only for the pager option (a `.dock` row beside the
existing filter controls, `data-help-for` for the help text); the loop
option needs no markup at all.

## 2. Other first-page-only callers, all outside this agent's files

Each of these takes the first page and shows no sign that there is more.
None is wrong today at a realistic notebook size (200 documents, 200
uploads); all are wrong at some size, and the fix is one call each:

- `app.js` `loadCaptureDocuments` and `renderAttachToDocument`: the "file
  this note under a document" pickers.
- `app.js` `notePickerRows`, for its `documents` and `images` sources.
- `dashboard.js` `renderDocumentsWidget` (documents, newest-first, slices
  six: correct on page one by construction) and its three reminder reads
  (`/reminders` twice in the widget pair plus the "next four" list), which
  have the same `due_at`-ordering caveat as `checkDueReminders` above.

`apiPagedList(path, pageSize, options)` in documents.js is already global
and already used by three files; none of these needs anything new.

## 3. Not verified

- No real notebook has 200 documents or 200 uploads here; every number above
  is from rows seeded through the models (300 for the endpoint measurements,
  230 for the browser run at `127.0.0.1:8899`).
- The reminders surface was not opened in a browser at all this session,
  because the file that draws it was held.
- The full suite was not run for this work; `scripts/gate.sh --changed` was,
  after each step.

## 4. Found, not fixed: the AI's own reminder tool is unbounded

**Closed by the orchestrator, same evening.** `_list_reminders` pages like
its sibling now, with the `done` filter moved into SQL (filtering a page
after limiting it is how "show me ten" quietly returns two) and the total
travelling with the page so the model can say "ten of three hundred"
rather than implying it has seen everything. Pinned by
`test_listing_reminders_hands_the_model_a_page_not_the_table`. The
original entry, for the record:

`_list_reminders` in `src/memorymap/ai/tools/__init__.py` reads every
reminder row and hands the lot to the model. It is not one of the three
endpoints INBOX 117 names (it is a tool result, not an HTTP list), so it was
left alone deliberately, but it is the same shape: its sibling
`_list_documents` in `ai/tools/documents.py` already takes `limit` and
`offset` and counts its own filtered set, which is the pattern to copy. The
cost here is prompt tokens rather than bytes over the wire, and
`agent.PROSE_BUDGET_CHARS` does not bound a tool result.
