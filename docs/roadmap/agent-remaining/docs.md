# Brief 16, the documentation: done

The docs agent was cut off by a rate limit after six files (INSTALL.md,
TROUBLESHOOTING.md, MODELS.md, PRIVACY.md, SECURITY.md, CONTRIBUTING.md).
This file tracked the six left in the brief's order; all six are now done,
each in the README's voice and checked against the code, gated per file on
`tests/test_no_em_dashes.py`, `test_docs_layout.py`, `test_style_scale.py`
and `ruff check .`.

1. **docs/INSTALL.md**: voice pass over the launcher agent's flag-accurate
   version. All ten launcher flags and six uninstall flags kept, word for
   word; every em-dash and verb contraction removed.
2. **docs/ARCHITECTURE.md**: tightened and de-staled against the running
   code, not guessed. The tool registry was 50, documented and counted at
   58; the four mind-map tools and four others (`find_contradictions`,
   `notebook_overview`, `search_files`, `read_file`) were never listed. The
   directory map was missing `ai/tools/files.py` and said 8 CSS files
   where there are 9. The router table was missing `routes_update`,
   `routes_bookmarks` and `routes_debug`. The test count was 2,700+,
   measured at 3,500+. A quoted marker string did not match what
   `librarian.py` actually emits (a comma, not the dash claimed);
   corrected. Every em-dash removed (127).
3. **docs/DESIGN.md**: prose only, no token or lint-rule value changed;
   the "Hit targets" and "Motion" section names `test_style_scale.py`
   quotes by name still resolve. Two of three quoted "before" UI-copy
   examples under Voice were themselves stale against the current code
   (app.js, dashboard.js, skill_runner.py); corrected to the exact
   current strings. Found, not fixed here: `app.js:18597`'s empty-chat
   string still carries the exclamation mark the doc quotes as an example
   of the inconsistency the Voice rule exists to prevent. Every em-dash
   removed (127).
4. **CHANGELOG.md**: the "Unreleased" section had drifted below the
   already-released [0.2.2] (backward from the Keep a Changelog order
   this file names as its own format) and its own header still claimed
   version 0.2.1 against the real 0.2.2; both fixed. Added "Since 0.2.2,
   by surface", built from `git log --no-merges --oneline
   --since=2026-09-06` on the branch (366 non-merge commits), grouped by
   surface, one line each, no hashes, with pure roadmap bookkeeping
   commits excluded and pointed at `docs/roadmap/` instead of repeated.
5. **docs/index.html**: found, not a voice issue: the footer called the
   AGPL-3.0 codebase "MIT License". Fixed. The Chat pane said "nearly 50
   tools" against the real 58. All 11 `&mdash;` entities and 2 literal
   em-dashes removed; links and the mirrored-file set
   `tests/test_docs_site.py` checks (CHANGELOG.md, CONTRIBUTING.md,
   SECURITY.md) re-verified, and `docs/CHANGELOG.md` re-mirrored after
   item 4's edit.
6. **The two expansion files** (`memorymap-ai-expansion-gemini.docx`,
   `memorymap-ai-expansion-perplexity.md`): read in full, checked against
   the running code and BACKLOG.md. Neither model had actually fetched
   the repository (both say so in their own text), so most of both
   invents an architecture this app does not have or repeats an idea
   already in BACKLOG.md (the browser clipper, already credited to
   Gemini there) or already decided against (cross-device sync, the most
   discussed deferred item in that file). Folded into ANALYSIS.md §114 as
   a pointer paragraph explaining exactly this; both files deleted.

## Left open

Nothing. All six files in the brief are done.
