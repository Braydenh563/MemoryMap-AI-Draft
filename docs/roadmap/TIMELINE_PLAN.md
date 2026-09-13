# The Timeline: a full redesign of the line view and the table view

**Status: written by direct instruction ("apply the same design and plan
process to the timeline line view and see if you can redesign the timeline
table view as well"), by Fable, after the measured audit in
`scratchpad/ui-sweeps/timeline-audit*.js`. Executed after GRAPH_PLAN.md
in ROADMAP.md order; SESSION_BRIEFS.md Brief 5 is its hand-off.**

Back to [../ROADMAP.md](../ROADMAP.md).

## 1. What exists (checked in the code)

`GET /timeline?days=&scale=day|week|month|year&group=category|tag|thread|none`
(`routes_timeline.py`) returns up to `MAX_NOTES` entries newest first with a
bucket label per entry and a band per group. The tab (`#tab-timeline`,
`renderTimelineBranch` in `app.js` ~22005) draws one of two views chosen by
the hidden `#timeline-view` select behind an icon segment: a **line** view
(a d3 SVG: bands as horizontal lanes, one dot per note, axis ticks, a
hover popup with Close and Open in editor) and a **grid** view (one column
per bucket, one card per note, called "table" in the dock). The dock holds
search, the options menu (scale, group, range, custom dates), Jump to
today and help. The Phase 9 pass gave the dock one height at four widths.

## 2. Why it disappoints (measured, 48 notes across six months, 1358px)

| Measure | Line view | Grid view |
| --- | --- | --- |
| Readable text without hover | 14 text nodes for 48 notes (6 band labels, 8 ticks); no titles | titles, but 122px cards regardless of content |
| Keyboard stops on notes | 0 (SVG circles carry no tabindex) | 67, but no arrow-key order |
| Width | forced 480px minimum, overflows at 390 | 8,800px against a 1,358px viewport, 40 columns, unchanged at 1024 and 390 |
| Empty area | dot collisions 0 / 2 / 6 at 1440 / 1024 / 390 | 186 of 234 cells empty (79% of cells and of area) |
| Colour | d3 `schemeTableau10` literals, not tokens | category tokens |
| Actions from a row | Close, Open in editor | open |
| Search | dims dots, reads `d.preview` | dims cards, reads `dot.textContent` |
| Recipes in the tab | 5 font sizes, 2 card recipes, 1 popup recipe not shared with the app | |

Reading the two views against the app's own reference points: the line
view is a chart, not a timeline (a chart of when notes were written, with
no way to read one); the grid view is a spreadsheet with the axis on the
wrong side (buckets as columns push time off-screen). Neither answers the
question a timeline exists to answer: *what was I doing then, and what
came before and after it.*

## 3. The target, in one paragraph

A timeline that reads top to bottom like a journal: a vertical spine with
sticky day, week, month or year headers; each note a compact row with its
kind icon, title, one-line snippet, time, tags and space, dense when the
bucket is a month and spacious when it is a day; the same rows in a real
table when a table is what is wanted (sortable columns, sticky header, row
focus, multi-select with the Notes list's own selection bar); one search
and one filter (the dock's) that *filter* rather than dim; a scrubber
along the edge that shows the density of writing over the whole range and
jumps on click; every row reachable by keyboard and openable in place; and
on a phone, one column with the scrubber folded into the dock. Nothing in
the tab draws a colour, a font or a card that the rest of the app does not.

## 4. Decisions made (do not re-decide)

1. **The grid view is removed, not tuned.** Its shape (time as columns)
   cannot be made to read; the table view replaces it.
2. **One row model, two renderers.** `timelineRow(entry)` returns
   `{id, kind, title, snippet, when, tags, category, space, words, links,
   pinned}`; the line view and the table render from it and from nothing
   else. Search, filter, sort and selection operate on the array, so the
   two views can never disagree.
3. **The line view is DOM, not SVG.** Rows are `<li>`s inside `<section>`s
   per bucket; the spine and the sticky headers are CSS. SVG is kept only
   for the density scrubber (one path). This is what gives keyboard stops,
   text selection, ellipsis and the app's chip recipe for free.
4. **Density follows the bucket.** Day: full row (title, snippet, tags,
   time). Week: title, time, tags. Month and year: title and date only,
   two columns above 1024. The scale select stays; "auto" is added and is
   the default (day under 60 notes in range, week under 400, else month).
5. **Bands become a filter, not lanes.** Grouping by category, tag or
   thread produced lanes that were mostly empty; the same choice now
   colours the row's kind marker and offers itself as a chip filter in the
   dock ("Show: Courses & Study"). Threads keep one affordance: a row that
   continues another shows a small link to it.
6. **The table is a `<table>`.** Sticky `<thead>`, columns date, title,
   kind, category, space, tags, words, links; click a header to sort;
   arrow keys move row focus, Enter opens, Space selects; the Notes
   selection bar (`#select-btn`'s code path) drives bulk actions. Below
   600px the table shows date and title only.
7. **The scrubber.** A 40px strip at the right edge (bottom, on a phone,
   inside the dock's "more" menu) with a density path for the whole
   loaded range and a window marker; click or drag jumps the list.
8. **Open in place.** A row's click opens the entry in the app's split
   panel (the same one Notes uses) rather than a bespoke popup; the
   bespoke popup and its media renderer are deleted.
9. **Backend.** `/timeline` gains `cursor`/`limit` (SESSION_BRIEFS Brief 6
   helper), `kind=note|document|board|reminder`, and returns `density`
   (counts per bucket for the whole range) so the scrubber needs no second
   call. `MAX_NOTES` goes; pagination replaces it.
10. **Tokens only.** Kind colours come from the category tokens the
    Library chips use; no `schemeTableau10`.

## 5. Phases

### Phase 1: the row model and the feed: **built 2026-09-13**, see
[HISTORY.md](HISTORY.md) "Moved from the plans, 2026-09-13". Gate green at
1440, 1024 and 390 (`scratchpad/ui-sweeps/timeline.js`).

### Phase 2: the table view: **built 2026-09-13**, see
[HISTORY.md](HISTORY.md) "Moved from the plans, 2026-09-13". Gate green
(`scratchpad/ui-sweeps/timelinetable.js`).

### Phase 3: the scrubber and pagination (half a session)
`density` from the backend, the SVG path, click and drag to jump,
`cursor` paging on scroll in both views; `MAX_NOTES` removed. **Gate:** a
2,000-note seed scrolls without a horizontal bar and without a > 100ms
frame during paging (Playwright `requestAnimationFrame` counter).

### Phase 4: kinds and the journal (half a session)
Documents, boards, reminders and daily notes as rows with their own kind
markers; the `kind=` filter chips in the dock; the daily-note row gets a
"Today" action when the day has none (WORLD_CLASS_PLAN D6).

## 6. Consistency rules

The dock stays on the Phase 8 grammar (no markup restructuring); rows use
the Notes list row tokens (`--row-h`, `--row-gap`); tags are
`.library-chip`; the row menu is the `.action-menu` recipe; the split
panel is the Notes one; keys are the app's (`/` search, arrows, Enter,
Space, Escape, `T` today). Copy: sentence case, no em-dashes, one line of
help behind the '?' popover.

## 7. Not verified until built

The density scrubber's usefulness under 200 notes (it may read as noise
and should hide below a threshold measured then); the "auto" scale
thresholds are a first guess to be tuned on a real notebook; the table's
column set on a tablet needs a measurement at 820.

## 8. Research: what the reference products do, and what it changes here

Written from working knowledge of the products, not a live teardown.

- **Apple Photos** and **Google Photos** solve "a lot of items over time"
  with a zoomable scale (years, months, days, all) and a scrubber at the
  edge showing months; density changes the tile size, not the layout.
  Implication: decisions 4 and 7 come from here; the "auto" scale should
  also respond to pinch or Ctrl+wheel.
- **Notion's timeline view** is a Gantt chart of date ranges, not a feed;
  the table view beside it is what people actually use for dated
  records. Implication: the table (decision 6) matters more than a Gantt;
  notes with date ranges (EntryDate) could later render as spans in the
  line view but that is not Phase 1 to 4.
- **Linear's activity feed, GitHub's timeline**: a vertical spine with
  sticky date headers, compact rows, kind icons on the spine. Implication:
  decision 3's shape.
- **Obsidian daily notes and the Calendar plugin**: the day is the unit;
  a heatmap of writing density per day is the overview. Implication: the
  density scrubber (decision 7) and the daily-note row (Phase 4).
- **Day One** (the journaling app closest to "what was I doing then"):
  a feed with a calendar and a "On this day" surface. Implication: an
  "On this day" chip in the dock is a cheap Phase 4 addition.
