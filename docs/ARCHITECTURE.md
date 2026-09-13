# MemoryMap AI: Architecture & Project Guide

> A single place to understand *what MemoryMap AI is, how it's built, and where
> everything lives.* Read this once and you'll be able to find your way around
> the whole codebase.

---

## 1. What it is, in one paragraph

MemoryMap AI is a **100% offline, local-first personal notebook**. You type a
thought; a local AI files it into a category automatically. Later you ask a
question in plain English and get back **both** a conversational answer **and**
the raw notes that matched. Everything (your notes, the search index, the AI
models) runs on your own machine. Nothing is ever sent to the cloud.

The core loop:

```
capture text → AI categorises it → store it → ask a question → chat answer + raw results
```

## 2. Design principles (the rules everything follows)

These are the constraints that shaped every decision. When in doubt, they win.

1. **Offline-first, always.** No feature may depend on a cloud service. The one
   opt-in exception is web search, which is off by default and clearly marked.
   When it *is* on it is built to reveal as little as possible: an ordinary
   browser User-Agent rather than one naming the app, no cookie jar, no
   Referer, DNT/Sec-GPC set, POST so queries stay out of request lines, and
   tracking parameters stripped from result URLs. It has its own settings
   screen (`settings-websearch`), not a corner of Preferences, because
   every message that has to explain it points there by name.
2. **Degrade gracefully.** If the AI (Ollama) is down, the app still works:
   new notes are filed as `Uncategorised`, search falls back to keywords, and a
   status dot in the header says what the AI is doing. **Saving a note must
   never fail because the AI is unavailable.**
3. **Your data is yours, in plain files.** SQLite + JSON on disk, in a folder
   you can back up, inspect, or delete. Full JSON/CSV/Markdown export built in.
4. **Additive schema migrations.** The database upgrades itself at startup by
   adding new columns in place. Users never delete their database to update.
   (Alembic is deliberately deferred until a column rename/removal is needed.)
5. **Single source of truth for shared state.** Exactly one `ConfigManager` and
   one `DatabaseManager` per process, created in `core/deps.py`. Nothing else
   constructs them.
6. **Destructive AI actions are always confirmed.** The chat agent can act on
   your notebook, but deletes (and similar) pause for a user confirmation
   instead of executing silently.
7. **Tests are fast and fully offline.** Every AI call is faked in `tests/`, so
   the suite needs no GPU, no models, and no network.

## 3. The big picture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (frontend/: vanilla HTML/CSS/JS, no framework)      │
│   capture · ask · graph · chat · settings · voice · PWA      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP (same origin, no CORS needed)
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI app (src/memorymap/api/)                            │
│   routes_* → everything behind a single-user unlock gate     │
└───────┬───────────────────┬───────────────────┬─────────────┘
        │                   │                   │
┌───────▼──────┐   ┌────────▼────────┐   ┌──────▼──────────────┐
│  entry/      │   │  ai/            │   │  search/            │
│  create/read │   │  janitor        │   │  keyword + semantic │
│  + audit log │   │  librarian      │   │  (falls back safely)│
│              │   │  agent + tools  │   │                     │
│              │   │  embeddings     │   └─────────────────────┘
│              │   │  voice          │
└───────┬──────┘   └────────┬────────┘
        │                   │
        │          ┌────────▼────────┐        ┌───────────────┐
        │          │ provider        │───────▶│  Ollama       │
        │          │  ├ ollama_client│        │  (localhost)  │
        │          │  └ openai_client│───────▶│  LM Studio /  │
        │          │ (local REST)    │        │  llama.cpp /  │
        │          └─────────────────┘        │  Jan / vLLM   │
        │                                     └───────────────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│  core/: config · database (SQLite) · deps (singletons) ·      │
│          backup · logbuffer                                   │
│  data/ (gitignored): memorymap.db · preferences.json ·        │
│                       uploads/ · backups/                     │
└───────────────────────────────────────────────────────────────┘
```

## 4. Request lifecycle (two examples)

**Capturing a note** (`POST /entries`):

1. The route hands the text to the **janitor** (`ai/janitor.py`).
2. The janitor tries the cheap path first: embed the note and compare it to each
   category's centroid. A clear match files it with no LLM call at all.
3. Borderline or unknown → **one** call to the chat model, which returns a JSON
   category decision.
4. No AI available → `Uncategorised`, confidence `0`. The note is always saved.
5. The entry is written to SQLite, its embedding is stored, and the action is
   recorded in the audit log.

**Asking a question** (`POST /chat/...`):

1. **Search** (`search/`) retrieves candidate notes, semantic when embeddings
   are available, keyword otherwise.
2. The **librarian** (`ai/librarian.py`, strictly read-only) feeds those notes
   to the chat model with a grounding instruction: *answer only from the notes.*
3. The user gets the conversational answer **and** the raw matched notes side by
   side. If the model is offline, they still get the raw notes plus a friendly
   note that the AI answer is unavailable.

**Agentic chat** (`ai/agent.py`) is a superset of the above: the chat model is
offered a tool registry (see §7) and can *act*: create, tag, pin, link notes,
set reminders, looping tool-call → result → repeat until it produces a final
answer. Destructive tools don't execute inline; they emit a `confirm` event to
the UI.

## 5. Directory map

```
MemoryMap-AI-v0/
├── src/memorymap/
│   ├── __main__.py          # entry point: `python -m memorymap [--desktop]`
│   ├── __init__.py          # __version__
│   ├── core/
│   │   ├── config.py        # paths + user preferences (ConfigManager)
│   │   ├── database.py      # SQLAlchemy models + additive auto-migrator
│   │   ├── deps.py          # THE singletons (config, db, ollama, embeddings…)
│   │   │                    #   + store_quietly(): best-effort embed, lives
│   │   │                    #   here because it needs the shared service
│   │   ├── backup.py        # daily local snapshot + restore
│   │   ├── docview.py       # any file -> its text (the viewer + import path)
│   │   ├── pdfpages.py      # a PDF page -> a PNG, so a model can read a scan.
│   │   │                    #   Optional (the `pdfpages` extra); returns []
│   │   │                    #   rather than raising when it is not installed
│   │   ├── filetypes.py     # the one table of document types: comment
│   │   │                    #   markers, indent, whether it renders
│   │   ├── extras.py        # the ALLOWLIST of pip-installable optional
│   │   │                    #   extras. The request names an entry here; the
│   │   │                    #   package spec is never client text
│   │   ├── embedmodels.py   # the same shape for embedding models: an
│   │   │                    #   allowlist, their real size in the HuggingFace
│   │   │                    #   cache, and download / re-download / remove
│   │   ├── logbuffer.py     # in-memory log capture + safe_value() for
│   │   │                    #   anything untrusted going into a log line
│   │   ├── security.py      # OriginCheckMiddleware, backend-URL local-only lock
│   │   ├── vault.py         # the private-note encryption key, derived + held in memory
│   │   ├── crypto.py        # scrypt key derivation, encrypt/decrypt primitives
│   │   ├── atomic_io.py     # temp-file + fsync + rename writes for preferences.json
│   │   ├── taskhistory.py   # "recently finished" record for Settings -> Background tasks
│   │   └── media_gc.py      # sweeps orphaned /media uploads nothing references any more
│   ├── entry/
│   │   ├── manager.py       # create/read/soft-delete entries, audit log
│   │   ├── timewords.py     # what "tomorrow" meant, resolved at capture
│   │   ├── duplicates.py    # near-duplicate finder + AI merge (routes_duplicates)
│   │   ├── importer.py      # markdown/document import (routes_settings, routes_documents)
│   │   ├── paths.py         # the graph's own traversal index (Trace, notebook_structure)
│   │   └── staleness.py     # the "forgotten notes" review the autonomous agent can run
│   ├── ai/
│   │   ├── provider.py      # what every backend must answer, + what doesn't
│   │   │                    #   vary by backend: the think-tag splitter, the
│   │   │                    #   tool-text gate, the context ceiling (§6)
│   │   ├── ollama_client.py # Ollama's native /api dialect
│   │   ├── openai_client.py # the /v1/chat/completions dialect: LM Studio,
│   │   │                    #   llama.cpp, Jan, vLLM (§6)
│   │   ├── presets.py       # quick/normal/detailed: reply cap, temperature,
│   │   │                    #   thinking toggle, length hint (§11)
│   │   ├── model_manager.py # list/pull models, pick chat/embedding backend
│   │   ├── embeddings.py    # embedding service + background warm-up
│   │   ├── janitor.py       # LLM prompt #1: file a note into a category
│   │   ├── librarian.py     # LLM prompt #2: answer from retrieved notes
│   │   ├── help_chat.py     # the Help tab's "Ask the guide" mini chat:
│   │   │                    #   app-guidance only, grounded in HELP_TOPICS,
│   │   │                    #   never touches notes or the database
│   │   ├── agent.py         # tool-calling loop (Wave G)
│   │   ├── autonomous.py    # the background librarian (§39A): a scheduled
│   │   │                    #   agent pass over the whole notebook. Off by
│   │   │                    #   default: it is the only place the model
│   │   │                    #   writes with nobody watching
│   │   ├── tools/            # the agent's tool registry (see §7): a package,
│   │   │                    #   split out of one file: __init__.py + categories.py,
│   │   │                    #   documents.py, files.py, whiteboard.py, _common.py
│   │   ├── context.py       # sizes one whole turn against the model's window (§7)
│   │   ├── skills.py        # what a skill is: steps, tools, inputs (§7b)
│   │   ├── skill_runner.py  # runs one, a step at a time, with a result
│   │   ├── extractor.py     # extract notes: free text -> AI-drafted, linked notes
│   │   ├── links.py         # link-reason generation between two notes
│   │   ├── entities.py      # auto-entities pass (people/places/etc, opt-in)
│   │   ├── reminder_parser.py # "call mum tomorrow evening" -> a due_at
│   │   ├── grounding.py · intent.py · drafter.py # chat-answer support: what
│   │   │                    #   the model is actually being asked, grounding
│   │   │                    #   an answer in retrieved notes, drafting one
│   │   └── voice.py         # optional local Whisper dictation
│   ├── search/
│   │   ├── search_manager.py# semantic + keyword search, with fallback
│   │   ├── query.py         # search-operator parsing (tag:, cat:, is:pinned, …)
│   │   ├── websearch.py     # opt-in web search (off by default) + PROVIDERS
│   │   └── searxng_manager.py · searxng_install.py · searxng_process.py ·
│   │       searxng_docker.py · searxng_settings.py # install/start/stop a
│   │                        #   local SearXNG, split by concern out of one file
│   └── api/
│       ├── app.py           # builds the FastAPI app, mounts frontend, gate
│       ├── schemas.py       # Pydantic request/response models
│       └── routes_*.py      # one router per feature area (see §6)
├── frontend/                # vanilla HTML/CSS/JS SPA + PWA (no build step)
│   ├── index.html · app.js · sw.js · manifest.webmanifest
│   ├── css/                 # style.css split into 9 linked files (Priority 0
│   │                         # item 2); index.html's <link> order is load-bearing
│   └── vendor/              # d3.v7, p5: vendored locally, never a CDN
├── tests/                   # pytest; all AI faked (tests/fakes.py)
├── docs/                    # you are here
├── .github/                 # CI, CodeQL, Dependabot, issue/PR templates
├── requirements.txt · pyproject.toml · pytest.ini
├── .env.example             # copy to .env to relocate data / set OLLAMA_URL
└── README.md · LICENSE · CHANGELOG.md · CONTRIBUTING.md · SECURITY.md
```

## 6. The API surface

The app is a FastAPI server. Every router except `/auth` and `/health` sits
behind the single-user **unlock gate** (`routes_auth.require_unlock`). Routers
are grouped by feature area:

| Router | Prefix | Responsibility |
| --- | --- | --- |
| `routes_auth` | `/auth` | first-run password setup, unlock, lock, change password, account state |
| `routes_entries` | `/entries` | create/read/edit/soft-delete notes, links, related, restore |
| `routes_chat` | `/chat` | ask questions, streaming answers, agentic tools, suggestions |
| `routes_conversations` | `/conversations` | saved chat threads |
| `routes_ask_history` | `/ask-history` | the Ask tab's past question/answer turns, independent of saved chats |
| `routes_models` | `/models` | Ollama status, pull models, switch chat/embedding/utility model |
| `routes_settings` | `/` | preferences, skills (`GET /skills`), audit log, JSON/CSV/Markdown export & import, logs, optional extras (`/extras`), embedding models (`/embedding-models`) |
| `routes_update` | `/update` | check GitHub for a newer release and apply it in place, instead of sending the user back through a browser to redownload the installer |
| `routes_websearch` | `/websearch` | web search provider selection + SearXNG install/start/status lifecycle, split out of `routes_settings` |
| `routes_backups` | `/`, `/backups` | `GET /storage` (where the data lives, how big it is) + daily local backup list/create/restore/delete |
| `routes_spaces` | `/spaces` | separate note "spaces" (workspaces) within the one notebook |
| `routes_documents` | `/documents` | long-form markdown documents, export, AI edit |
| `routes_duplicates` | `/duplicates` | near-duplicate finder + AI merge |
| `routes_drafts` | `/drafts` | the writing room's compose/rewrite calls |
| `routes_files` | `/`, `/media` | attachments upload/download/delete. `media_router` (`/media`, pasted/dropped inline images) is a second router from the same file, gated by `require_unlock_media` rather than the ordinary unlock dependency: it accepts a query-param token, since an `<img src>` cannot carry a header |
| `routes_tags` | `/tags` | list/rename/delete tags |
| `routes_categories` | `/categories` | list/rename/merge/delete categories |
| `routes_graph` | `/` | force-directed graph data + link suggestions |
| `routes_insights` | `/insights` | dashboard: stats, most-accessed, on-this-day, digest |
| `routes_reminders` | `/reminders` | create/list/complete reminders |
| `routes_bookmarks` | `/bookmarks` | saved links to somewhere outside the notebook, same shape as reminders, no AI involved |
| `routes_voice` | `/voice` | local Whisper transcription |
| `routes_help` | `/help` | the Help tab's mini AI chat (`POST /help/ask`), app guidance only, no persisted history |
| `routes_timeline` | `/timeline` | the notebook on a time axis, in bands |
| `routes_tasks` | `/tasks` | what is running in the background right now |
| `routes_library` | `/library` | **everything you have made, in one list**: notes, documents, chats, files, tags, bin, activity, assembled server-side |
| `routes_whiteboard` | `/whiteboard` | note cards and freehand sketches on a pannable canvas (§39C). A *board* is itself an entry, so it is searchable and filable like anything else; `board_id IS NULL` is the unnamed scratch board |
| `routes_debug` | `/debug` | `GET /debug/health`: one cheap, under-20ms read across data that already exists elsewhere (running jobs, task history, the log), for "is this notebook okay" in one glance |
| system | `/health` | liveness + version (open, no unlock) |

Interactive API docs live at `http://localhost:8000/docs` when the app is
running.

**`POST /chat/stream` is NDJSON over a plain POST, and that is a decision, not
an oversight.** It was rewritten as a WebSocket once and reverted, for four
reasons worth keeping written down because the rewrite looked like an upgrade:

- The agent loop is blocking, so a WebSocket handler has to run it on another
  thread, and the request's SQLAlchemy `Session` is not thread-safe.
- Nothing cancels that thread when the client disappears, so a closed tab
  leaves a model generating against a Session that is being torn down.
- A WebSocket route cannot carry `dependencies=locked`; auth has to be
  re-implemented by hand inside the handler, after `accept()`.
- **A WebSocket handshake is not subject to the same-origin policy.** A
  `fetch` from another origin is stopped by the browser; a `new WebSocket(…)`
  to `127.0.0.1` is not. For a local server holding someone's notebook, that
  is the whole argument on its own.

NDJSON over `fetch` delivers tokens exactly as promptly and has none of that.
The header `X-Accel-Buffering: no` is what keeps a reverse proxy from
defeating it.

**Anything that runs on a worker thread belongs in `routes_tasks.collect()`.**
Each job reports a label, a detail line, a `progress` fraction *only where one
is genuinely knowable*, whether it can be stopped, and the lines it has
printed. The log matters as much as the bar: pip building lxml sits on one
number for minutes, and its output is the only thing that distinguishes slow
from stuck.
Settings → Background tasks renders whatever that returns, so a new job shows
up there without the frontend being taught about it. It used to build the list
in `app.js` from the two jobs that happened to be in `/models/status`, which
is why the embedding warm-up and the multi-minute SearXNG install ran with
nothing on that screen to say so. Only *running* work is listed: a finished
job is not a task, and a screen that accumulates them is the Logs screen.

## 7. The agent's tools (Wave G)

`ai/tools/` (a package now: `__init__.py` plus `categories.py`,
`documents.py`, `files.py`, `whiteboard.py`, `_common.py`, split out once the
registry outgrew one file) defines a registry the chat model can call:
**58 tools**. Read-only tools run inline; the **destructive** ones (marked
⚠️ below) emit a confirmation event to the UI instead of executing.

*Reading the notebook:* `search_notes` · `get_note` · `list_notes` ·
`count_notes` · `list_tags` · `list_categories` · `summarize_notes` ·
`find_similar_notes` · `related_notes` · `notebook_overview` ·
`find_contradictions`: notes that disagree with each other: a reversed
decision, a date that moved

*Reading everything else:* `list_documents` · `get_document` ·
`search_chat_history` · `get_current_time` · `search_files` · `read_file`:
uploads, photos, scans and attachments, by name, caption or the text read
out of them, which notes never contain

*Writing:* `create_note` · `edit_note` · `tag_note` · `pin_note` · `link_notes` ·
`unlink_notes` ⚠️ · `restore_note` · `rename_tag` · `delete_note` ⚠️ ·
`delete_tag` ⚠️ · `audit_link_reasons`

*Categories:* `create_category` · `rename_category` · `merge_categories` ⚠️ ·
`delete_category` ⚠️, by name, never by id, since the model has never seen
one. Deleting a category keeps its notes (they become Uncategorised); the
destructive ones are so because none is reversible afterwards: nothing
records which notes came from where, or which two notes an unlinked pair was.

*Documents:* `create_document` · `get_document` · `list_documents` ·
`delete_document` ⚠️

*Whiteboard (§37G):* `add_whiteboard_card` · `add_whiteboard_link` ·
`read_whiteboard` · `search_whiteboard` · `generate_diagram`: lay out a
whole diagram from a set of notes in one call

*Mind maps* (a board that is a tree, `ai/tools/whiteboard.py` alongside the
whiteboard tools above): `create_mindmap` · `read_mindmap` ·
`add_map_node` · `link_map_nodes`

*Planning and structure:* `make_plan`: a ticked-step plan shown in the chat
timeline; `notebook_structure` and `path_between`: the same graph traversal
the Graph tab's own "Trace" feature uses, so the agent can read the
notebook's structure rather than only search it

*Reminders:* `set_reminder` · `list_reminders` · `complete_reminder`

*Skills:* `list_skills` · `run_skill` · `save_skill` · `delete_skill` ⚠️

*Conversation flow:* `ask_user`: the model asks a clarifying question
instead of guessing which note you meant; `compress_chat` ·
`save_user_preference`: a standing instruction ("always answer in British
English") remembered across conversations

*Online (opt-in, off by default):* `web_search` · `read_url`

### The context budget

`ai/context.py` sizes **one whole turn** against the model's window before any
of it is assembled. Nothing else in the AI path holds a fixed character limit,
because the bug it replaced was that each part had one and nothing added them
up: the worst case came to ~11,328 tokens against a window that is commonly
4,096, and overflow is dropped from the *front* (the system prompt), so a
model that overflowed simply stopped knowing it had tools.

```
window  ──┬── reply reserve (15%)      kept back; num_ctx covers both
          ├── system prompt            measured, not assumed (persona is editable)
          └── the rest, split:
                tool schemas  30%      what the agent needs to act at all
                tool results  30%      capped by TOOL_RESULT_BUDGET_CHARS
                notes         25%   ┐  recoverable: the model can ask for
                history       15%   ┘  more (get_note, the visible thread)
```

**Two things then shrink the fixed half, and only on a small window** (§94).
Measured on 8k with eight notes and no history, the prompt was 32% of the
context before the conversation started, with tool schemas costing nearly
twice the user's own notes:

- `tools.compact_schemas` trims each tool's description to one sentence,
  touching no name, type or required-ness. `within_budget` tries this
  **before dropping any tool**, because dropping one changes what the app can
  *do* while trimming prose only changes how verbosely it is explained.
- `agent.tools_guide(window)` swaps the 2,807-char guide for a 1,034-char
  rewrite at or below 8k. That guide is re-sent every round, so on a 4k model
  it was 17% of the whole context per round.

Result: 23%. `tests/test_prompt_budget.py` pins the fixed half under 20% and
asserts at least eight tools survive, so the saving cannot come from quietly
handing the model an empty toolbox.

### Which tools are offered

`ai/toolwords.py` reads the request for the tools it plausibly needs:
deterministic, word-boundary matching, no model call, in the same shape as
`entry/timewords.py`. Substring matching offered the tag tools for "my vintage
camera" and the link tools for "blinking lights".

**It advises; it never decides.** `CORE_TOOLS` is always offered, a broad or
unreadable request gets everything, `agent.FOCUS_NOTE` tells the model the list
is a suggestion it may reach past, and a call for an unoffered tool widens the
set to everything for the rest of the turn. A misread costs one round, not the
request.

Notes and history yield first when space is short *because they are
recoverable*: `get_note` reads one in full, and the conversation is still on
screen. Notes are dropped whole rather than all clipped shorter (ten notes cut
to a sentence each are ten things the model cannot quote, four whole ones are
four it can), and the model is told how many did not fit. History is kept in
whole user/assistant pairs, since half an exchange invites the model to invent
the missing side.

`OllamaClient.runtime_options` then sends `num_ctx` **and** `num_predict` with
every generation. Both matter, and the first is easy to miss: Ollama runs a
model at its own `num_ctx` default regardless of what the model was trained
for, so budgeting against a declared 32k without also *asking* for it
reproduces the exact overflow the budget prevents. The number budgeted against
and the number requested are the same one.

**How many tools a turn actually sends** is decided in two steps, and neither
is a fixed number:

1. **Relevance**: `tools.focus_for(question)` reads the question for what it
   plausibly needs and returns ~8–12 tools. Keyword-driven rather than another
   model call: a round-trip to decide what to send would cost more than it
   saves, and a deterministic rule can be read, tested and argued with.
   Settings → Tools can switch this off (`tool_focus: "all"`).
2. **Room**: `tools.within_budget` then fits whatever survives to the window
   the model *reports* (`ollama_client.usable_context`, from `/api/show`),
   spending at most `TOOL_SCHEMA_WINDOW_SHARE` of it on schemas. Anything that
   does not fit is dropped from the tail, and what was held back is logged.

This replaced a fixed character budget, which was the wrong shape: 4096 is
Ollama's *fallback* when a model declares nothing, not a fact about any
particular model. Rationing a 32k model against it withheld tools for no
reason; assuming otherwise on a real 3B dropped the system prompt off the
front, and a model that overflows stops knowing it has tools at all.

| Model window | Tools sent (whole registry offered) |
| --- | --- |
| 2,048 | 4 (core only) |
| 4,096 | 9 |
| 8,192 | 19 |
| 16,384 and up | all of them |

A skill's declared tool list is exempt from step 2: it asked for exactly those,
and silently dropping one would break the run rather than trim it.

> `agent.PROSE_BUDGET_CHARS` and `tests/test_prompt_budget.py` are the backstop
> on the **prose**: the system prompt and `TOOLS_GUIDE` are sent whatever the
> window and no per-turn trimming applies to them. There is deliberately no
> constant capping the tool *registry* any more: `within_budget` caps it
> against the model's real window instead, which is the only number that was
> ever a fact about anything.

`search_notes` and `list_notes` return **previews**, which is why `get_note`
exists and its description says so: a model that quoted a note from a preview
was quoting a truncation.

### Errors a tool is allowed to explain

Handlers raise **`tools.ToolError`** for failures they mean to explain ("no
note with that id"). Only that text is passed back to the model and out of
`POST /chat/tools/execute` to the user. A bare `ValueError`, `KeyError` or
`TypeError` from inside a handler is something else (whatever `int("abc")`
happened to say), so it is logged here and reported by *shape* instead. A
single `except ValueError` could not tell those apart, and the difference is
the one CodeQL flagged as stack-trace exposure.

### The per-round budget

Everything in this registry is serialised into the `tools` field on **every
round of every turn**, alongside the system prompt. That fixed overhead is
~3,050 tokens, and **77% of it is these schemas, not the prose in
`TOOLS_GUIDE`**: so a verbose new tool description costs more than a verbose
new paragraph.

`tools.within_budget` caps it against the window the model reported, per turn,
and `tests/test_prompt_budget.py` asserts what reaches a 4,096-token model
after that trim. A constant used to cap the whole registry; it was retired
after being raised three times for legitimate growth, because it measured a
case no turn has sent since the per-turn trim existed.

Why any of this matters: Ollama defaults to a 4096-token window and drops
overflow from the *front*, so a 3B model that overflows loses the system prompt
and stops knowing it has tools, which presents as "the AI won't use tools"
rather than as anything to do with length. Settings → Tools
(`disabled_tools`) is the user-facing escape hatch, and it filters at
`ollama_tools()`, the wire, not just at execution.

**Adding a tool is not free.** If the budget test fails, that is the design
working; either trim, or raise the constant deliberately and say why.

**Not every turn is offered every tool.** `tools.focus_for(question)` reads the
message and returns the reading core plus whatever the words ask for:
`set_reminder` for "remind me…", `tag_note` for "tag my…". An ordinary
question therefore carries ~3,340 characters of schema instead of 10,215,
which halves the fixed overhead a 3B model reads before it reaches the
question. Two rules keep it honest: a request that sounds like a job but does
not say which one ("tidy up my notes") gets **everything**, and the focus is
an *economy, not a policy*: unlike a skill's allowlist it never stops a tool
from running, so a cue that fails to fire costs tokens, not abilities.
Settings → Tools has the switch (`tool_focus`), because the honest failure of
a keyword rule is a phrasing it does not know.

**Two more rules hold the budget, and both are easy to break by accident:**

- **A note goes in short, and the model can ask for the rest.**
  `librarian.note_for_prompt` caps a note at `MAX_NOTE_CHARS` (900) and cuts
  with a marker naming the call that reads it whole (matching the code's own
  string exactly): `… [cut, call get_note(7) to read it in full]`. Retrieving
  ten notes is pointless if one
  note of several pages fills the prompt on its own. This is only safe because
  the truncation is *reversible*: `get_note` exists and `TOOLS_GUIDE` already
  tells the model to use it before quoting. **A cut the model cannot undo is
  just a missing piece of the note**: so if the marker or the tool ever goes,
  the cap has to go with it.
- **The front of the prompt must not move between rounds.** Ollama caches a
  prompt only up to the first difference, so anything volatile near the top
  invalidates everything below it. The clock in the system prompt is written
  to the *minute* for exactly this reason: at microsecond precision it
  differed on every round of every turn, and each round of a tool loop (whose
  rounds are seconds apart) re-read the whole prompt from scratch. Anything
  added above the history or the notes has to be stable for at least the
  length of a tool loop, or it costs a full re-read per round.

## 7b. Skills

A skill (`ai/skills.py`) is a **named, repeatable job over the notebook**, not
a saved sentence. It has a `prompt`, and optionally `steps` (ordered
instructions), `tools` (an allowlist), `inputs` (declared `{{placeholders}}`)
and a `description`. A skill with only a prompt is exactly what skills used to
be, so nothing was lost in the rebuild.

Three things are worth knowing before changing anything here:

1. **The declared tools are the only ones offered for the run.**
   `ollama_tools(allowed)` narrows the wire and `run_agent(allowed_tools=…)`
   refuses execution of anything outside the list, a safety property,
   not only a prompt. It is also §11a's win: the full registry is ~10,200
   characters of schema on *every round*; "Auto-tag my notes" ships 1,963.
   The user's own switches still win, so a skill can't re-enable a tool turned
   off in Settings → Tools.
2. **Naming the tools in the instruction text is deliberate**, on top of
   narrowing the wire. The reported failure was a model that had tools and
   didn't know it was meant to act; telling a 3B model "use `tag_note`" is
   what makes it reach for one.
3. **The built-ins live in Python, not `app.js`.** They are served from
   `GET /skills` with the user's own, for the same reason the web-search
   providers are: the server has to be able to resolve a skill the user just
   clicked, and a field added to a skill should not need adding twice.

Running one is `POST /chat/stream` with `skill` and `skill_inputs`: the
server builds the instruction, so what a skill *is* lives in one place.
`skills.normalise` validates both ways in, the editor and `save_skill`, so a
skill the AI can write is one the UI can write, and neither can store one that
won't run.

**A skill with steps runs one step per turn** (`ai/skill_runner.py`), not one
request carrying a numbered list. A list inside one request is a plan the
model may ignore, and a 3B model given four instructions at once does the
first and narrates the rest. One turn per step means the app *knows* where it
got to, so it can tick each step off, name the step that failed, and keep each
turn small. Each step gets the previous steps as history. A skill with no
steps is a single turn, exactly the pre-rebuild behaviour.

The run's events are the agent's, plus three:

| Event | Meaning |
| --- | --- |
| `plan` | the steps and tools, before anything runs |
| `step` | `running` / `done` / `failed` (with a reason), by index |
| `result` | `changes`: what was written, each with an `undo` |

`undo` is a **tool call**: `{"tool": "edit_note", "arguments": {…}}` captured
*before* the write, which the UI hands back to `POST /chat/tools/execute`,
the same path the confirm button uses. It is popped out of the result before
the result reaches the model, because everything left in a tool result is
resent on every later round.

The agent loop (`ai/agent.py`) streams: it calls `chat_tools_stream`, so the
model's prose reaches the user as it is written rather than arriving in one
block when the turn ends. Text that might turn out to be a tool call written
as prose is gated until it is clearly not one, so it is executed rather than
displayed. The UI renders the run as an ordered timeline (thinking, tool
calls and prose in the order they happened) and persists it with the turn.

## 8. Data model

SQLite via SQLAlchemy 2.0 (`core/database.py`). Main tables:

- **users**: single-user unlock (one bcrypt-hashed password). Exactly one
  row: separate notebooks are separate `MEMORYMAP_DATA_DIR`s, not separate
  accounts. The password can be changed from Settings → Account, which
  re-wraps the vault key onto the new password *before* replacing the hash:
  the other order would strand every private note.
- **vault**: the data key for private notes, wrapped with a key derived from
  the password. This is why a forgotten password loses private notes and only
  private notes: everything else is plain rows. `--reset-password` clears the
  credential and says exactly what that costs before it does.
- **categories**: named buckets; each has an embedding centroid used for the
  janitor's cheap-match path.
- **entries**: the notes themselves: `content`, `category_id`, JSON `tags`,
  `ai_confidence` (0–100), `access_count`, `parent_id` (train-of-thought
  threads), `pinned`, `user_filed` (user chose the category → janitor keeps
  hands off), timestamps, and soft-delete (`is_deleted` / `deleted_at`).
- **entry_links**: user- or AI-made connections between two entries (the graph).
- **whiteboard_nodes / whiteboard_sketches**: a note card, or a freehand
  stroke list, placed at an `(x, y, z)` on a board (§39C). `board_id` points at
  an *entry*, so a board is a note and inherits searching, tagging and filing;
  `NULL` is the unnamed scratch board. **Known gap:** deleting an entry leaves
  its cards behind: there is no cascade and no sweep yet.
- **user_preferences**: the memory stream (§39B): standing instructions the
  model wrote for itself with `save_user_preference`, replayed into its system
  prompt on every later turn. `active` exists so one can be switched off, and
  **nothing sets it yet**: there is no UI for this table, which is the top
  open item in §40.
- **embeddings**: per-entry vectors, stored as raw `float32` bytes.
- **attachments**: uploaded files, kept in `data/uploads/`.
- **conversations**: saved chat threads. Messages are one JSON column of flat
  user/assistant pairs. An assistant message carries `content` *and* `steps`:
  the run as an ordered timeline (thinking, tool calls, prose). `steps` is what
  the client replays when a chat is reopened; `content` is the flattened text
  used for copying and for the history sent with the next question. **Anything
  that edits an answer has to update both**, or the edit is invisible the
  moment the chat is reopened.
- **entry_dates**: what a note's relative time phrases resolved to when it
  was written ("next Friday" → 2026-08-07), with the phrase kept beside the
  date because the resolution is a rule, not a fact. Filled by
  `entry/timewords.py` at capture and on every content edit, deterministic
  regexes rather than a model call, because this runs on every save including
  when Ollama is off, and best-effort because a note must save even if it
  fails. **Anything derived from a note's text and stored in the clear has to
  be cleared when the note is made private**, exactly like its embedding:
  "the appointment is tomorrow" plus a date is most of the note.
- **entry_revisions**: edit history for notes. Documents have no equivalent
  yet, which is why the AI document edit overwrites on accept.
- **documents**: long-form markdown, separate from notes.
- **document_links**: which notes a document draws on. Its own table because
  the relationship is many-to-many and neither side owns the other: detaching
  removes a connection, never a note. `manager.link_document` /
  `unlink_document` / `documents_for_entry` / `entries_for_document` are the
  only four functions that know how the two are joined, so the note side and
  the document side cannot drift apart. A note can be attached as it is saved
  (`document_ids` on `POST /entries`), which is the point: the connection is
  obvious while you are writing and forgotten by the time the note is in a
  list.
- **reminders**: lightweight reminders the agent can set. Stored UTC-aware:
  SQLite drops timezones and JavaScript parses a naive date-time as *local*,
  which read as a reminder being hours overdue the moment it was set.
- **audit_log**: every meaningful action, shown in Settings → Activity.

**Migrations:** `database.py` runs an additive auto-migrator at startup: new
columns are added to existing databases in place. You never delete your data to
upgrade. Rename/removal-style migrations are out of scope until genuinely needed.

### Storage headroom, measured not guessed

Asked directly whether storage becomes a problem for a notebook that grows
for years. Measured with `scripts/scale_test.py` (roadmap ANALYSIS.md §34,
item 2) rather than estimated: a real 50,000-note SQLite file, checkpointed
out of WAL before measuring, was **12MB**: its `embeddings` table is the
only part that scales with vector size, and this fixture's vectors are 4
floats (16 bytes) rather than a real backend's 384–1024 dims. Re-priced at a
common local model's 384 dims (1536 bytes/vector), the same 50,000 notes come
to **~88MB**, or **~1.8KB per note** including its content, tags and
metadata. Extrapolated linearly (`entries`/`embeddings` are the only tables
that grow with note count, and both are simple fixed-width-ish rows, no
per-note table fan-out) that's **~350MB at 200,000 notes**, comfortably
inside "a notebook nobody will ever actually finish filling."

**What doesn't fit this rate, and isn't bounded by it:**

- **Attachments** (`data/uploads/`): arbitrary files, kept whole, with no
  cap and no relationship to note count. A notebook with a handful of large
  PDFs can outweigh 200,000 notes' worth of text easily; this is a
  per-attachment decision the user makes, not something the schema can
  budget for.
- **`entry_revisions`**: one row per edit, not per note. A note edited a
  hundred times costs a hundred times what one written once does; nothing
  currently prunes old revisions.
- **The `audit_log`**: one row per meaningful action, unbounded, growing
  with *usage* over time rather than with notebook size: a notebook used
  daily for years accumulates this independently of how many notes are in
  it.

None of the three above were sized in this pass, they are flagged, not
measured, because none of them is proportional to note count the way
`entries`/`embeddings` are, so a single "bytes per note" figure would
misrepresent them. Worth a dedicated look if either is ever reported as
actually large in practice; nothing today prunes `entry_revisions` or
`audit_log`, and neither has surfaced as a real complaint yet.

## 8b. Anything that leaves the machine

One module, `search/websearch.py`, owns every outbound request, and it has
three rules that are easy to break by accident. All three have already been
broken once.

**Which engine answers is the user's choice, read in one place.** The
`search_provider` preference is `auto` | `searxng` | `duckduckgo`
(`websearch.PROVIDERS`). `auto` tries SearXNG and falls back; **`searxng`
does not fall back**: reporting a failure is the point, because silently
re-routing to DuckDuckGo defeats running your own instance. Both callers (the
`/websearch` route and the agent's `web_search` tool) read it through
`websearch.settings_from(config)`. Two readers is how the tool ended up
honouring a different setting from the UI.

**Check an address and then connect to that address, not to the name.**
`_searxng_target` and `_pin_url` both resolve once, validate, and hand
`requests` an **IP literal** with the hostname in a `Host` header (and, for
HTTPS, `_PinnedAdapter` to keep SNI and certificate verification intact).
Resolving to check and resolving again to connect leaves a DNS-rebinding
window between the two. The reader path was fixed for this; the SearXNG search
path was not, and kept the hole for months while the *probe* beside it was
pinned correctly.

**A redirect is a new request.** `_get_external` follows hops by hand with
`allow_redirects=False`, re-checking each one, because `allow_redirects=True`
resolves the next hop inside `requests` where no guard can see it, and
"302 → http://127.0.0.1/" walks straight past a check on the first URL.

A configured SearXNG must resolve to this machine or the local network, and
**every** address it resolves to must, not merely one of them.

`search/searxng_manager.py` can install, start and stop an instance. Its
output goes to `data/searxng/searxng.log`: never `DEVNULL`, which is what
made a failed start unexplainable and reduced the error message to a guess
about the port.

Two things in there are Windows-specific and both were wrong in the same way,
a POSIX idiom that means something else entirely on Windows:

- **`os.kill(pid, 0)` does not ask a question on Windows, it terminates the
  process.** Any signal other than `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` is passed
  to `TerminateProcess`, so the liveness check inside `_source_state` (which
  `status()` calls, which the settings screen polls every three seconds)
  killed the instance seconds after starting it and then reported that it
  "started but never answered". `_alive` now goes through
  `OpenProcess`/`GetExitCodeProcess` on Windows and only signals on POSIX.
- **`shutil.rmtree(..., ignore_errors=True)` cannot delete a git checkout on
  Windows**, because git marks `.git/objects` read-only. It deleted everything
  writable, left the folder standing, and reported success, after which
  `data/searxng/src` existed but was no longer a Python project, the installer
  skipped the download because the folder was there, and pip said *"does not
  appear to be a Python project"* about a path the user had never heard of.
  `_remove_tree` clears the read-only bit and retries, moves the tree aside if
  it still can't delete it, and reports what survived instead of pretending.

The rule underneath both: **a folder existing is not the question.**
`is_checkout()` asks whether there is a `setup.py` or a `pyproject.toml` in
it, and installing, starting and `source_installed()` all ask that rather than
`.exists()`. `install_source` also verifies `import searx` in the new venv
before calling the install done, because pip exiting 0 and SearXNG being
runnable are different claims.

**How SearXNG is installed, and why it looks so indirect.** Three separate
things each rule out the obvious approach, and all three were found by running
it rather than by reading:

1. **`git clone` cannot work on Windows, ever.** Four files in the repository
   have a colon in the name (`…/searxng.conf:socket` and three like it). A
   colon separates a drive letter, so git fetches every object and then dies:
   *"fatal: unable to checkout working tree"*, leaving the half-written
   folder that caused the error above. `pip install <tarball-url>` fails the
   same way, because pip unpacks the same files. So the archive is downloaded
   and unpacked *here*, skipping members this filesystem can't hold (they are
   nginx/uwsgi deployment templates, nothing the app runs) and members that
   would escape the directory.
2. **`pip install -e .` cannot work anywhere.** SearXNG's `setup.py` imports
   `searx` to read its version, and `searx/__init__.py` imports `msgspec`,
   which does not exist in pip's isolated build environment. It fails with
   `ModuleNotFoundError` before declaring a single requirement. So
   `requirements.txt` is installed first and the package is then built with
   `--no-build-isolation`, which is what SearXNG's own `manage` script does.
3. **The generated `settings.yml` turns off `tracker_url_remover`.** That
   plugin downloads a rules file from `rules1.clearurls.xyz` *during startup*
   and does not catch a failure, so an offline or proxied machine loses the
   process before it binds the port, "started but never answered" again.
   `websearch.strip_tracking` already does that job locally.

Verified end to end in this sandbox except the download itself (the proxy
blocks the URL): the archive unpacks to a real tree, installs, starts, serves
its JSON API, and `websearch.probe_searxng` returns True against it.

## 9. AI stack

- **Chat model:** any model installed in **[Ollama](https://ollama.com)**
  (default `llama3.2`). Talked to over the local REST API via
  `ai/ollama_client.py`. Used by the janitor, librarian, and agent.
- **Embeddings:** default `BAAI/bge-small-en-v1.5` via `sentence-transformers`
  (auto-downloads on first use). **Nothing user-facing may hard-code that
  name**: it was `all-MiniLM-L6-v2` once, and the Models screen went on
  saying so long after it changed, so the only way to find out what was
  really running was to watch it download in the log. Ask
  `EmbeddingService.active_model()`, which the status endpoint exposes as
  `active_embedding_model`. Optionally switch the backend to an
  Ollama embedding model; notes re-index automatically with a progress bar.
- **Voice (optional):** local Whisper via `faster-whisper` for the 🎙 buttons.
- **Warm-up:** embeddings load in a background thread at startup so the first
  request isn't slow; the header pill tracks *ready / warming up / rebuilding
  index / off.*

Everything AI-related is designed to be *absent*: the app is fully usable with
Ollama stopped and no optional extras installed.

## 10. Frontend

A single-page app in **vanilla HTML/CSS/JS: no framework, no build step.**
Served as static files by the same FastAPI server (so no CORS is needed). It
is also a **PWA** (`manifest.webmanifest` + `sw.js`) with a mobile pass, a
command palette (Ctrl/Cmd-K), a graph of the notebook in three layouts: a
force-directed **web**, a **tree** (notebook → category → note, replies
branching off the note they answer) and a **radial tree**, drawn with D3
vendored locally in `frontend/vendor/`, and a sketch pad (p5, also vendored). No asset
is ever loaded from a CDN, consistent with the offline-first rule.

### Driving it in a browser

The test suite cannot see any of this, so verify UI work by running the app.
Chromium is preinstalled at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`;
`pip install playwright` (the browser is already there, do not run
`playwright install`). Launch the context with `service_workers="block"`, or
`sw.js` will serve a cached `app.js`/`style.css` and your change will not be
in the page you are looking at.

Top-level functions in `app.js` are plain globals, so a Playwright
`page.evaluate` can call `switchTab`, `applyThemePreset` or `renderEmbeddingPicker`
directly. Asserting on measured geometry (`scrollWidth - clientWidth`, a
focused element's `offsetParent`) catches far more than a screenshot.

### Invariants worth knowing

1. **The Notes tab has sub-tabs** (`capture` / `ask` / `browse`) and remembers
   the last one in `localStorage`. Anything that focuses or scrolls to an
   element there must call `showNotesSection(...)` first: focusing inside a
   `display: none` section silently does nothing, and the control reads as
   dead. This has caused the same bug four separate times.
2. **CSS automatic minimum sizing is the usual cause of a wide page.** A grid
   track of `1fr` and a flex item of `min-width: auto` both refuse to shrink
   below their content, so one wide code block or table widens its column, the
   page, and every paragraph beside it. `overflow-x: auto` on the child cannot
   take effect until every ancestor has an explicit floor: `minmax(0, 1fr)`
   on the track *and* `min-width: 0` on the item.
3. **Later CSS at equal specificity silently wins.** A media query that sets
   `flex` is undone by a base rule declaring `flex` further down the file. The
   header's tabs were pinned at a rigid 579px this way for a long time, and the
   block that was supposed to free them looked perfectly correct.
4. **Inline styles beat stylesheets, which is how colour layering works.** A
   palette sets `--accent` from a `[data-palette]` rule; an explicitly chosen
   accent is written as an inline custom property so it wins. Two rules of
   equal specificity would otherwise be decided by source order.
5. **The header degrades in a fixed order** as the window narrows: wordmark,
   then the status pill, then tab padding, then the tabs scroll. Its buttons
   never shrink. Breakpoints here are measured, not guessed: the desktop
   shell's window is 1200x800, which is less viewport than it sounds on a
   scaled display.
6. **`prefers-reduced-motion` disables animation**, so any animation carrying
   *meaning* needs a still fallback or it reads as a rendering fault.
7. **p5 measures a canvas as zero inside a `display: none` tab.** Anything
   using `renderEmblem` has to be drawn in its own tab's render, not at
   startup, which is also what makes it redraw when a theme change moves the
   accent.
8. **Note text is user content and is never parsed as markup.** Everything is
   built with `createElement` / `textContent`. `renderNoteText` layers
   `[[wiki links]]`, then `renderInlineMarkdown` (bold, italic, `code`,
   strike, inline only, deliberately), then `highlightInto` for filter
   matches, and all three have to keep working through each other. Block
   markdown is *not* used in the note list: rendered headings and tables make
   it enormous. The dashboard's one-line previews strip the markers instead
   (`notePreviewText`), because a 70-character clip can land mid-tag.
9. **Appearance is three layers, read manual-first**: defaults →
   the chosen theme → your manual tweaks (`appearancePref`). That order is
   right for a tweak made *after* choosing a theme and wrong for every theme
   chosen after the tweak: one stored palette cancelled that part of each new
   theme, so themes "did nothing". `applyThemePreset(name, chosenByUser)`
   therefore clears the manual keys *that theme has an opinion about* when the
   user picks one, and no others. **A new appearance key needs a decision
   about which layer owns it**, or it silently joins the layer that outranks
   the theme.
10. **A graph layout is a set of rules about what a label needs**, not about
   what the panel has. `d3.tree().size([...])` divides the panel height by the
   leaf count, which gave a 29-note notebook eighteen pixels a row; `nodeSize`
   and panning is the fix. The radial rings **by depth** (`d3.tree`), not by
   `d3.cluster`'s height, or a category containing a thread sits a ring in
   from its siblings. `frameTree` frames from the canvas's measured `getBBox`
   rather than from node coordinates plus a padding guess, because the labels
   are what overflow. Assert on the labels' rotated corners, not their
   axis-aligned boxes: those overlap when diagonal text does not.
11. **Settings sections are three things that must agree**: an entry in
   `SETTINGS_SECTIONS`, a `<section id="settings-NAME">`, and a
   `<button data-section="NAME">` in the nav. Miss the first and the section
   never hides; miss the third and it is unreachable.

## 11. Configuration

Three knobs, all optional, via `.env` (copy from `.env.example`):

- `MEMORYMAP_DATA_DIR`: where the database, preferences, uploads, and backups
  live (default `data/`).
- `OLLAMA_URL`: where the local Ollama server listens (default
  `http://localhost:11434`).
- `MEMORYMAP_SEARXNG_PORT`: the port to run a managed SearXNG on (default
  8888). Rarely needed: `searxng_manager.choose_port()` already moves to
  8080/8081/8890/8899 when the wanted port is held by something that is not a
  SearXNG. A port *already answering as SearXNG* beats a free one: that is
  ours from a previous run, and moving would start a second copy beside it.

User-facing preferences (chat model, embedding backend, recycle-bin days, answer
style, optional AI profile, …) live in `data/preferences.json`, managed by
`ConfigManager` and editable from the Preferences screen.

## 12. Testing & CI

- **Run locally:** `PYTHONPATH=src pytest` (3,500+ tests, ~7-8 minutes). Uses a
  throwaway database and fakes every AI call (`tests/fakes.py` +
  `tests/conftest.py`), so it is fast and fully offline.
- **The suite cannot see the UI.** Every layout and wiring bug fixed so far
  passed a fully green run: a header overflowing its own box by 215px, a
  button focusing an element inside a hidden section, an accent picker with no
  effect. Drive the app in a browser before believing a frontend change works;
  §10 says how.
- **Lint locally:** `ruff check .` (and, optionally, `ruff format` to tidy).
- **CI** (`.github/workflows/ci.yml`): lint with ruff, then run the full test
  suite on Python 3.11 / 3.12 / 3.13. No GPU, no Ollama, no models required.
- **CodeQL** (`.github/workflows/codeql.yml`): static security analysis on push,
  PR, and weekly.
- **Dependabot** (`.github/dependabot.yml`): weekly dependency + Action bumps.

## 13. Running it

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt && pip install -e .
python -m memorymap            # → http://localhost:8000
python -m memorymap --desktop  # same app in its own window (needs pywebview)
```

On first run you choose a password (bcrypt-hashed, stays local). See the
[README](../README.md) for the full walkthrough of each screen.

### One process, and why more is not an option

**MemoryMap runs with exactly one worker, and refuses to start with more.**
`core/deps.refuse_multiple_workers()` runs at the top of `create_app()` and
raises on `--workers N` (N > 1) or `WEB_CONCURRENCY`.

This is not caution: it is the direct consequence of §3's singletons. The
config, the database handle, the in-memory log buffer, the set of unlock
tokens and the handle on the SearXNG subprocess are all one-per-process,
which is correct and simple for one process and quietly wrong for two:

| With two workers | What you would actually see |
| --- | --- |
| Two log buffers | Settings → Logs shows roughly half of what happened |
| Two token sets | Unlocking works, then randomly 401s on the next request |
| Two SearXNG handles | Both workers think they own it; stop/reinstall fight |
| Two embedding warm-ups | The model loads twice, for twice the memory |

None of that fails loudly, which is exactly why it is refused rather than
warned about: it would present as flakiness and be debugged as a bug in the
app. `python -m memorymap` cannot hit this (it hands uvicorn an app object,
not an import string, and uvicorn cannot fork that); running `uvicorn` against
the factory directly can, and is the case the check exists for.

More workers is also not the lever for speed here. The slow paths are Ollama
and embedding, and both already run off the request thread.

## 14. Where to look when you want to…

| I want to… | Start here |
| --- | --- |
| Change how notes are categorised | `src/memorymap/ai/janitor.py` |
| Change how questions are answered | `src/memorymap/ai/librarian.py` |
| Add/adjust an agent action | `src/memorymap/ai/tools/` (+ `agent.py`) |
| Add an API endpoint | the matching `src/memorymap/api/routes_*.py` |
| Add a database column | `src/memorymap/core/database.py` (+ auto-migrator) |
| Teach it a new time phrase | `entry/timewords.py`: one rule, one test row |
| Change search behaviour | `src/memorymap/search/search_manager.py` |
| Change the UI | `frontend/app.js`, `frontend/css/*.css` (read §10's invariants first) |
| Add a graph layout | `layoutHierarchy` in `app.js` + an option in `#graph-layout`; d3's full v7 is vendored, so `tree`/`cluster`/`partition` are all there. Read §10 invariant 10 first: the readable-layout rules are not obvious |
| Add a theme or palette | `THEME_PRESETS` in `app.js` + a `[data-palette]` block in `frontend/css/05-sidebars-themes.css` (where the curated palettes live); §10 invariant 9 for why a theme has to clear manual keys |
| Change what the Timeline plots | `api/routes_timeline.py`: a note sits at what it is *about* when it says so |
| Work out why a page scrolls sideways | §10 invariant 2: an ancestor with no `min-width: 0` |
| Change what a saved chat replays | `steps` in `routes_conversations.py`: not just `content` |
| Add a preference | `DEFAULT_PREFERENCES` in `core/config.py`, then `PreferencesBody` + `get_preferences()` in `routes_settings.py` |
| Add a Settings screen | §10 invariant 11: three places, all three needed |
| Change which search engine answers | `websearch.PROVIDERS` + `settings_from()`; never read the preference directly |
| Add an agent tool | `ai/tools/`, then run `tests/test_prompt_budget.py`: schemas are 77% of the per-round cost |
| Change what a skill can be | `ai/skills.py`: `normalise` is the one validator both the editor and `save_skill` go through |
| Add a built-in skill | `skills.BUILTIN_SKILLS`, not `app.js`; name its tools (§7b) |
| Log something a user or a website typed | `logbuffer.safe_value()` at the call site; `sanitise` only protects the in-app viewer |
| Work out why SearXNG won't start | `data/searxng/searxng.log`, surfaced in Settings → Web search |
| Add a background job | `api/routes_tasks.collect()`: otherwise it runs invisibly |
| Add a kind to the Library | `api/routes_library.py`: one builder function, and `app.js` needs no change |
| Make something installable | `core/extras.py`'s allowlist, never a package name from a request. `unavailable` greys it out *and* refuses it server-side |
| Add an embedding model | `core/embedmodels.py`'s allowlist. The `org/name` → `models--org--name` flattening is the traversal defence, not formatting |
| Size something against the window | `--page-viewport` / `--page-sticky-h`, never a fresh `calc`. Three rules once wrote the same sum by hand and all three were wrong by the page's bottom padding |
| Add a test | `tests/`: copy an existing `test_*.py` and reuse the fakes |

---

*This document tracks the codebase: if you change the architecture, update it in
the same PR.*
