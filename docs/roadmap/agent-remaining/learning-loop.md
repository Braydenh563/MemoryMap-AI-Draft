# The learning loop: what is built, and what I9 actually is

Brief 23 (`docs/roadmap/SESSION_BRIEFS.md`). Written by the orchestrator on
2026-09-12 after building steps 1 to 3, so the next pass starts from what is
there rather than from the spec's own picture of it.

## Built, and green

| What | Where | Specs |
| --- | --- | --- |
| The corrections store and its boosts | `src/memorymap/ai/learning.py` | `tests/test_learned_spec.py`, the five I7 tests |
| The three consumers: filing, search, link suggestions | `librarian` reads `learning`; `search_manager._learned_order`; `routes_entries.link_suggestions` | same file |
| `POST`/`GET /learned/corrections` | `src/memorymap/api/routes_learned.py` | same file |
| Resurfacing | `src/memorymap/ai/resurface.py`, `src/memorymap/api/routes_resurface.py`, the `note_scores` table and `ix_note_scores_rank` | `tests/test_resurface_spec.py`, all six, markers removed |

Eleven of Brief 23's twenty-two strict-xfail markers are gone. The decision
the brief asked for first is recorded in `learning.py`'s module docstring:
corrections stay in `AuditLog` as `action="correction"` rows and `learning`
is the layer over them, because one store already existed, works, and has
the index, retention, compaction and feed a second table would need again.

## What is left, and it is not a Settings section

The ten remaining markers are I9, and reading them against the code says
plainly that **I9 is a feature, not a screen**. Every one of them drives a
derived-facts pipeline that does not exist:

- `POST /night/run` with a `budget`, and `force` to re-derive.
- `GET /learned?kind=question|claim`, returning rows with the text, the
  **source span**, the model that produced it and the time.
- `GET /learned/{id}`, `DELETE /learned/{id}`, `POST /learned/{id}/reset`,
  with "edited is never overwritten" and "deleted is never re-derived"
  surviving a re-run.
- `PUT /learned/switches` per runner plus a master switch, each yielding no
  rows and a paused reply.
- "Forget everything" leaving notes and revisions **byte-identical** (the
  spec hashes the tables), a private note's facts never listed, and a
  readable JSON export of the lot.

So the shape is: a night pass that reads notes and writes derived rows, a
table for those rows carrying provenance, an edit/delete/reset lifecycle
with tombstones, a switch per runner, and only then a Settings section over
it. That is a brief of its own, not the tail of this one.

**Where to start, because it is not nothing.** `src/memorymap/ai/autonomous.py`
is already the night shift: it has a scheduler, a cancel and snooze
protocol, `_enabled_tasks` reading a preference per task (auto-tag,
auto-link, auto-dedupe), and it records everything it does as
`system:librarian` so "who did this" is answerable. A fourth task that
derives facts, and a route that runs one pass on demand with a budget, fit
that frame rather than needing a new one. `ai/extractor.py` and
`ai/tensions.py` are the two places that already pull statements out of a
note's text.

## Not verified

- No real model touched any of this: every provider test in this project
  runs against a fake transport (CLAUDE.md section 4). What a small model
  actually derives as a "claim" or a "question", and whether the source
  spans it returns line up with the note, is untested and is the main risk
  in I9.
- The resurfacing numbers are this sandbox's: read 6.7 ms at 800 notes,
  compute 50 to 230 ms. Nothing was measured at ten thousand notes.
- `for_context` degrades to the plain ranking without an embedding backend.
  That path is exercised; a real vision of "near this note" with a real
  embedding model is not.
