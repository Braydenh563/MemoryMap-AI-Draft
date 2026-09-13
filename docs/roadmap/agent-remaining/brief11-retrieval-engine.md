# Brief 11, the retrieval engine (WORLD_CLASS_PLAN B3): what is left

> Companions: [HISTORY.md](../HISTORY.md) ("From WORLD_CLASS_PLAN.md B3 and
> SESSION_BRIEFS Brief 11") · [SESSION_BRIEFS.md](../SESSION_BRIEFS.md)
> Brief 11 · the spec, `tests/test_search_engine_spec.py` · the measurement,
> `scratchpad/search/measure_engine.py`

Built this session: `src/memorymap/search/index.py` (one FTS5 index over six
kinds, an `after_flush` write path, a source registry that raises on an
unregistered kind), `src/memorymap/search/engine.py` (`search()`, `Hit` with
bm25/cosine/graph, the vector matrix, `related()`, `vectors_by_id()`),
`src/memorymap/api/routes_search.py` (`GET /search`, `GET /search/stats`),
the operators of §5.1 in `search/query.py`, the Notes list's "why this
result" line in `frontend/app.js`, and the removal of three per-request
scans of every stored vector in `routes_entries.py`. All five strict-xfail
markers in `tests/test_search_engine_spec.py` removed; thirty-three tests
added in `tests/test_search_engine.py`.

## Open, with the file and the next step

1. **The other search surfaces still do their own thing.** `file:
   frontend/app.js`, `id: search-one-surface`. The Notes list still filters
   client-side with its own `parseNoteQuery` (which knows `tag:`,
   `category:`, `is:` and phrases, but not `kind:`, `in:`, `before:`,
   `after:` or `has:`), the Library filters its own arrays, and
   `/entries?semantic=true` is a second ranking path. The engine only
   *annotates* that list today. **Next step:** make the Notes filter call
   `GET /search` when the query carries an operator the client parser does
   not know, and render the returned order; then the Library, then the
   command palette. One surface per commit, each with a sweep.

2. **No FTS index rebuild job.** `file: src/memorymap/search/index.py`,
   `id: search-reindex-job`. `rebuild()` exists and runs once, at the
   startup that first creates the table. On a large notebook that is
   seconds of startup, and there is no way to ask for a rebuild after a
   restore, an import or a bug. **Next step:** a `reindex` job kind once
   Brief 9's runtime lands, with `/search/stats` showing the row counts it
   is working towards. Do not add a route that rebuilds inline.

3. **A bulk write can leave the index stale.** `file:
   src/memorymap/search/index.py`, `id: search-bulk-writes`. The hook sees
   the ORM's unit of work; `session.execute(update(Entry)...)` or raw SQL
   bypasses it. `touch(session, source, ref_id)` is the manual path and
   nothing calls it yet. **Next step:** grep for bulk `update(`/`delete(`
   over the six indexed models (the importer and the space reassignment in
   `routes_spaces.py` are the likely two) and call `touch` there, or add a
   lint that fails on a bulk statement against an indexed model.

4. **The matrix forgets by zeroing a row.** `file:
   src/memorymap/search/engine.py`, `id: search-matrix-compaction`. A
   deleted vector's row is zeroed rather than removed, so a notebook that
   churns vectors for a long uptime keeps dead rows in the array (they
   score zero, so they are never returned). **Next step:** rebuild when
   dead rows pass some fraction of the whole, counted rather than guessed.

5. **`has:` only knows `file`.** `file: src/memorymap/search/engine.py`,
   `id: search-has-vocabulary`. `has:file` is answered with one query over
   the candidates; `has:image`, `has:link`, `has:reminder` parse and match
   nothing. **Next step:** decide each one's source (an attachment mime for
   image, `EntryLink` for link, `Reminder.entry_id` for reminder) and
   answer them the same way, over the candidates, never with a join on
   every save.

6. **Nothing here ran against a real embedding backend.** `id:
   search-real-embeddings`. Every cosine number in the report came from the
   4-dimensional fake; a real backend is 384-dimensional, anisotropic, and
   its `embed_text` per query is the cost this engine does not measure.
   **Next step:** WORLD_CLASS_PLAN §9's dev-only llama.cpp script, then
   re-run `scratchpad/search/measure_engine.py` against it.

7. **The graph signal needs an open note, and the Notes list rarely has
   one.** `file: frontend/app.js`, `id: search-open-note`. The list passes
   `entry_id` when exactly one row is opened out (rows view) or one is being
   edited; in card view there is no such thing, so the third signal is zero
   there. **Next step:** decide what "open" means on that surface (the last
   note clicked, per the app's own focus model) rather than leaving a
   signal that only appears in one view.
