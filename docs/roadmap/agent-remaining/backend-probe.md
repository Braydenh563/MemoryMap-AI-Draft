# The backend hole-poking pass, 2026-09-12 evening

What the orchestrator probed while agents worked the surfaces, what it
found, and, just as usefully, what came back clean. Written so the next
session spends its probes somewhere new.

## Found and fixed

| What | Measured | Commit |
| --- | --- | --- |
| `GET /entries` was an N+1 | 32 statements at 25 notes, 107 at 100; one attachments SELECT per note. 67 to 8 on a 60-note page | notes list attachments |
| Five missing indexes | `entry_links` had none on either of its two columns, the link table of a linked-notes app: SCAN from either end on 2,000 notes with 6,000 links. `whiteboard_objects.board_id` SCAN, 34.38 ms for one board of 3,000. `conversations` and `reminders` sorted their whole table per load | index the link table |
| `_related_elsewhere` ran 3 queries per word | 18 round trips for a six-word question, each an unindexable `ILIKE '%word%'` over the two widest text columns. 145.3 to 118.8 ms; 109.8 to 85.3 when nothing matches | three scans not three per word |
| Three unbounded list endpoints | `/documents` 116.7 KB, `/reminders` 52.5 KB, `/media` 117.6 KB at 300 rows | INBOX 117, agent |
| Nine first-page-only readers | `apiPagedList` returns 260 of 260 where a plain read returns 200 | read to the end |
| `_list_reminders` gave the model every reminder | Everything a tool returns is spent from the context window | a page not the table |
| A concurrent capture lost notes | Six writers, twelve notes each: **5 of 72 saves died** on a category race; 0 after | category race |
| `store_for_entry` was a bare insert | Second call for one note raised `UNIQUE constraint failed` | idempotent vector |
| **Three of four parents could not be deleted** | A document with a note attached, a note with a saved link, a bookmark attached to either: FOREIGN KEY constraint failed, 500, the thing still there | three delete commits |
| The guard that should have caught the last one | `test_a_note_with_every_kind_of_attached_row...` builds rows **by hand**; written when 7 tables pointed at an entry, there are 10 | schema-driven check |

## Probed and clean, so do not spend a session here again

- **Auth surface.** With a password set, exactly two routes answer without a
  token: `/changelog` and `/health`. Both are meant to.
- **Error contract.** Every parameterised route driven with a non-existent
  id, a non-numeric id and an empty body: **0 endpoints returned 5xx or
  raised**.
- **Path traversal.** Seven encodings of `../../../../etc/passwd` and its
  Windows twin against `/media`, `/media/meta`, `/media/text` and
  `/media/pdf-info`: nothing escaped, nothing 5xx'd.
- **Private notes.** Twelve read endpoints with the vault locked return no
  plaintext, retrieval does not carry one into the model's context, and the
  text is in none of `entries.content`, `search_index.body` or
  `entries_fts.content`. Now pinned by a test, which carries the trap that
  produced a false alarm: `/search` echoes the query back, so grepping its
  response for the secret word finds it every time.
- **Search cost.** 4 statements at every size; 8.4 ms at 200 notes, 10.5 at
  1,000, 14.2 at 3,000, against the plan's 200 ms target.
- **Capture cost.** 16 statements and 9.0 ms at 1,206 notes, the same as at
  56. The app does not get worse at the one thing it is for.
- **Backup and restore.** Already covered properly: `test_backups_api.py`
  asserts the content actually rolls back and that a pre-restore safety
  snapshot is taken.
- **Restore from the bin.** A note comes back with its document link intact.
- **Rename paths.** The other half of the delete class: renaming a category
  moves its notes and leaves one category behind (`renamed, merged: false,
  moved: 0`, the note reads `Projects`), and renaming a tag rewrites it on
  every note that had it (`changed: 2`, both notes updated, the other tag
  untouched). Nothing stores a category or tag by name where an id was
  meant, so nothing goes stale.
- **Every other short write field.** After capping notes and tags, the rest
  were driven with 100,000 characters: a space's name and icon, a category
  rename, a bookmark's title and url, a reminder's text and a conversation's
  title. All refused (422, or 400 for the two space fields). Capture was the
  only unbounded one.

## Not verified

- Everything here is this sandbox, SQLite, one process, seeded rows. No real
  notebook, no real model (every provider test runs against a fake
  transport, CLAUDE.md section 4), nothing at ten thousand notes.
- The concurrency probe used six threads against one TestClient app. Real
  contention between the desktop window, a browser tab and the night shift
  is the same shape but not the same timing.
- ~~Large-input handling was measured and not acted on~~ **acted on the same
  evening, and the reasoning is worth keeping because it changed.** It was
  first written down as a product decision to leave alone: capping how long
  a note may be is a judgement about someone pasting a long article. On a
  second look that framing was wrong. The question was never "how long may a
  note be": `routes_documents` already answered it with `MAX_CONTENT =
  500_000`, and capture simply never grew the same limit, so the same app
  said yes and no to the same paste depending on which box it went in. Using
  the document's own number is removing an inconsistency, not making a new
  rule. A note is now capped at the same 500,000 characters, a tag is
  clipped to 60 (twice what `librarian.py` allows itself when it suggests
  one) rather than refused, because a save that fails over one long tag
  throws the note away, and a tag list past 200 is a paste rather than a set
  of labels.
