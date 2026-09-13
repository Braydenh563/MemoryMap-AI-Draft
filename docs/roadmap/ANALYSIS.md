# Analysis and outside reads


> **The other three:** [ROADMAP.md](../ROADMAP.md) (live work) · [BACKLOG.md](BACKLOG.md) (§1–§29) · [ANALYSIS.md](ANALYSIS.md) (§30–§34, §59, §60, §66, §104 and §114 — the product-strategy read — including the licence constraint — MemoryMap is AGPL-3.0 now) · [HISTORY.md](HISTORY.md) (already built).

Split out of `ROADMAP.md`. These sections are **reference, not work** — they
record judgements, a competitor read, and what was deliberately *not* taken, so
nobody re-derives them. Nothing here is a task list.

The live work is in [ROADMAP.md](../ROADMAP.md); the standing backlog is in
[BACKLOG.md](BACKLOG.md).

## 30. External review, filtered — what didn't make the cut

The outside reviews (Perplexity, Gemini) were thorough, and had two
different problems, worth telling apart rather than filing under one excuse:

**Perplexity was working from a stale bio** — a real but out-of-date
one-line GitHub profile description — and reasoned carefully from it,
hedging what it couldn't verify. Its mistakes are all one mistake, repeated:
assuming bundled models, which the items below correct.

**Gemini's first pass fabricated an entire architecture it never saw.**
Denied repo access the same way Perplexity was, it didn't hedge — it
described a specific "Ghost Sidebar" UI, a ChromaDB/LlamaIndex RAG pipeline,
and a "cinematic sci-fi… neural constellation" visual theme, none of which
exist anywhere in this codebase. That's not staleness, it's invention, and
none of it is corrected below because none of it needs correcting against
real code — it was never describing real code. **Gemini's *second* pass**,
after it read the live GitHub Pages landing page, is accurate — the
six-tab (now seven) description matches, and the suggestions built on it are
judged on their merits in §4, §17, §24, §26, §29 and §21, wherever they
landed. Recorded here rather than silently dropped, since a future review
hitting the same access wall may fabricate the same way again:

- **Hardware-aware model routing, bundled model packs, checksums, delta
  updates, rollback.** All of this assumes the app ships models. It doesn't —
  Ollama does that job, has its own model management, and MemoryMap already
  has a thin layer over it (`ai/model_manager.py`, Settings → Models: list,
  pull, switch chat/embedding/utility model). Nothing here to build.
- **Backend abstraction across llama.cpp / MLX / ONNX / Vulkan / CUDA.**
  Same premise. The real version of "don't lock into one backend" is already
  scoped, correctly, in §6 — an OpenAI-compatible provider interface over
  Ollama, LM Studio, llama.cpp's server, Jan and vLLM, at the HTTP layer
  MemoryMap actually talks to, not the inference layer it never touches.
- **Opt-in anonymous telemetry / crash reporting.** Weighed deliberately, not
  just discarded for being off-brief: design principle 1 is "no feature may
  depend on a cloud service," and the pitch to users is "no account, no
  cloud, no telemetry" — an *opt-in* toggle for it would be the app's first
  outbound channel besides search and page-reading, both of which exist
  because the person explicitly asked a question that needs the web. A crash
  is not that; the support-bundle idea in §1 gets most of the real value (a
  file the person can choose to attach to a bug report) without the app ever
  sending anything on its own.
- **A capability dashboard / resource meter** (RAM, VRAM, estimated speed
  before loading a model). Not rejected outright, just downgraded — Ollama
  already reports this (`ollama ps`, its own API), so this would be
  re-surfacing data from a tool that already surfaces it, for marginal gain
  over what Settings → Models already shows. Worth doing only if someone
  actually asks for it in-app rather than a review guessing it's missing.
- **A structured memory taxonomy** (episodic/semantic memory, write/read
  policy, conflict resolution, decay). This read the name "MemoryMap" as an
  AI-memory-system product rather than what it is — a personal notebook an
  AI files for you. The genuinely useful parts of that suggestion already
  have real homes under their real names: deduplication is the existing
  near-duplicate finder (`routes_duplicates`), decay/archival is §26,
  retrieval quality is hybrid search and re-ranking in §11. Nothing needs a
  new "memory" abstraction layered on top of notes, tags, links and
  embeddings that already do these jobs.
  - **The one part of that critique worth taking seriously on its own terms,
    separate from the misread:** *"the name MemoryMap suggests something
    more distinctive — persistent memory visualization, editable memory
    structures, temporal recall, spatial/graph-based reasoning over saved
    knowledge."* Read literally, past the "AI memory system" framing, that's
    not a missing feature — it's already what §9 and §10C are. A
    force-directed, editable map of every note and how they connect *is*
    "editable memory structures" and "spatial/graph-based reasoning"; the
    branch/line timeline resolving what a note is *about*, not just when it
    was written, *is* "temporal recall." The product already does the thing
    the name promises. What it doesn't do yet is *say so* — the README
    pitches "your thoughts, mapped by a local AI," which undersells it, and
    nothing in onboarding (§27) tells a first-time user "this graph and this
    timeline are the map the name refers to." The gap isn't technical; it's
    that the identity is built but not narrated. Worth treating as a
    positioning task for §27 and the README, not an engineering one — see
    the product-direction note near the top of this document.
- **Dynamic LoRA adapter loading (`unsloth`), a local vision/RAG pipeline
  built on LlamaIndex/ChromaDB, and anything else describing the fabricated
  first-pass architecture.** Not evaluated on the merits, because there's
  nothing to merge — MemoryMap doesn't fine-tune or swap adapters, and its
  retrieval stack is the app's own `search/` module (keyword + local
  embeddings), not a third-party RAG framework. Recorded so it's clear these
  were seen and set aside deliberately, not missed.
- **Encryption at rest for "the vector database and raw markdown files."**
  Already answered, just under different names: private notes are already
  encrypted individually, and full-database encryption (SQLCipher) is
  already explicitly deferred with reasoning in the README's own
  "Operational decisions" section — OS-level disk encryption covers the rest
  of the file today. Nothing in Gemini's version of this changes that
  reasoning.
- **A weekly "learning journal" background agent.** Already exists in a
  lighter form — the dashboard's AI digest (§24's opening list) is a
  weekly synthesis already. Worth checking whether the digest actually
  covers what was being asked for before treating this as a gap.
- **Graph-to-chat interactivity** (clicking a node populates a chat query
  about that note). Already built — the Graph tab already lets you ask for
  related notes from a selected node. Not a gap.

---

## 31. Claude's own read: what I'd flag

Asked for separately from the outside reviews — my own pass, based on
`ARCHITECTURE.md`, `CHANGELOG.md` and this document, not on the repo's
marketing copy. Same rule as everywhere else here: these are things worth
checking, not things confirmed broken.

- **`app.js` is one ~12k-line file with no module system.** §11 already
  flags this for load-time performance; the maintainability side is a
  separate cost. Seven tabs now, with §3, §4, §23 and §24 all adding more UI
  to the same file — the project's own stated pain point is that "every
  layout and wiring bug found so far passed a fully green run" because the
  backend's ~560 tests can't see the frontend. A single enormous file makes
  that worse, not just slower: there's no natural seam to test a piece of it
  in isolation. Splitting into native ES modules (`<script type="module">`,
  one file per tab plus shared utilities) costs nothing at runtime and no
  build step — it doesn't have to mean adopting a bundler to get "this
  function is 200 lines away from anything unrelated to it" back. **Do this
  after the smoke suite below exists, not before** — see the priority map's
  Tier 3 for the reasoning and the suggested sequencing against §3.
- **The frontend has no CI coverage at all, only manual Playwright driving.**
  The direct consequence of the point above, and worth stating plainly since
  the project's own docs already admit it. If a handful of the driver
  scripts referenced throughout this document (load each tab, dismiss
  onboarding, assert no console errors, assert a couple of known elements
  render) ran headless in CI alongside the existing lint-and-pytest job, that
  specific admitted gap — layout bugs that pass a green run — would shrink
  without needing GPU, models, or network, matching the existing CI's own
  constraints.
- **Export exists in three formats; there's no import.** JSON, CSV and
  Markdown export are all built (§ various), which answers "can I get my
  data out," but nothing answers "can I bring notes in from somewhere else."
  For a single-user local notebook, first-run cold start is a real adoption
  question — someone with two years of Apple Notes or Obsidian has no path
  in short of pasting things one at a time. Doesn't need to be universal; even
  a plain-Markdown-folder importer (the mirror of the Markdown export already
  built) would cover a lot of the realistic cases.
- **No bulk operations in the note list itself.** The agent has
  `move_notes` and `merge_notes` as tools (§14), but a person doing the same
  thing by hand has to ask the agent to do it rather than multi-select in
  the UI and act. Given how much of this document is about giving the agent
  UI-equivalent power (§18), it's worth also closing the gap the other
  direction — a checkbox-select mode in the note list with bulk
  tag/move/archive/delete, so the human path isn't strictly weaker than the
  agent path for the same operation.
- **Backups are taken; restoring one looks unexercised.** `data/backups/`
  exists per the architecture doc, but nothing in this document describes a
  tested restore flow — worth checking directly whether "restore from
  backup" is an actual feature (a button, a documented command) or just
  "the files are there, copy them back yourself." An untested restore path
  is, functionally, not a backup strategy yet; worth confirming rather than
  assuming, and worth a test that actually restores a backup and asserts the
  data matches, not just that a backup file gets written.
- **There's no non-AI fallback for filing quality, only for filing
  happening.** Design principle 2 already guarantees a note always saves —
  it lands in Uncategorised when Ollama is off. That's a fallback for
  *availability*, not for *quality*: someone running fully offline by choice
  gets every note in one bucket forever. A small set of deterministic,
  regex-style rules a user can define themselves (`contains a phone number →
  tag #contact`, `starts with "TODO" → category Tasks`) would extend the
  same "works when the AI doesn't" principle from "doesn't fail" to "doesn't
  fail *uselessly*" — and would double as building blocks the janitor could
  also consult, not just a consolation prize for offline use.
- **Two tabs open on the same note, and nothing arbitrates.** Nothing in
  `ARCHITECTURE.md` describes an edit-conflict story for a note or a document
  open in two tabs (or two windows — `--desktop` alongside a browser tab is
  the obvious way this happens) at once. Given single-user, this reads as
  unlikely rather than impossible, but "unlikely" plus "the loser's edits
  silently vanish" is exactly the kind of bug that's invisible until it costs
  someone a real note. Worth checking directly what happens today — a
  last-write-wins overwrite is at least honest if that's the answer; the
  actual risk is if the *client* believes its stale copy is still current and
  shows it as saved.
- **Filing confidence has no visible trend, only a per-note flag.** The
  janitor already flags low-confidence filings for review (design principle
  1) — what doesn't exist is whether that rate is going up or down over
  time, notebook to notebook or model to model. Since §11's eval harness is
  already being built to measure prompt/token regressions, filing accuracy
  over a small fixed set of known-good notes is a natural thing to fold into
  the same harness rather than build separately — one more signal, not one
  more system.

---

## 32. Product direction — asked for directly, kept short on purpose

This document is now 32 sections long, and that's worth naming as a risk in
its own right before adding a 33rd. Asked directly what I'd suggest for
where this goes — the short version, since the long version is everything
above.

**The differentiated thing is already built — lean into it rather than
diluting it.** §30's note stands: the graph plus the branch/line timeline
plus AI filing is a genuinely distinctive combination — editable, spatial,
temporal recall over a personal notebook, which is what the name promises
and few other tools do together. Chasing Notion/Obsidian feature parity in
§5 is worth doing where it's cheap (wiki-links, backlinks — already mostly
built), but a full properties/database system or true collaborative editing
would be competing with much larger teams on their own ground, for a feature
set §5 has already correctly ruled out once. The graph and timeline are
unclaimed ground; Notion-parity is not.

**Two things earn their place ahead of almost everything else in this
document, because they're not features — they're what makes every feature
after them safe to build:** the frontend module split and the Playwright
smoke suite (§31, sequenced there already). Every tab this document adds —
Library, a whiteboard, a branch timeline — is more surface area on a file
with no automated way to catch a regression. That trade gets worse the
longer it's deferred, not better.

**Tier 4 in the priority map is a "maybe never" list, not a backlog, and is
worth treating that way on purpose.** MCP, a VS Code extension, the agent
controlling the screen, LAN sync — none of these were asked for twice, all
of them are large, and a roadmap that treats every recorded idea as
eventually-do creates its own kind of debt: the next person (or the next
session) reading this document has to re-derive which parts are live
priorities and which are a parking lot, same problem `IDEAS.md` solved once
already. Worth periodically pruning ideas that don't get re-requested,
rather than letting the document only ever grow.

**Worth saying plainly, since this reads as a portfolio piece as much as a
personal tool:** a small number of things done with real depth — the core
capture-file-ask loop, a graph and timeline that actually deliver on the
name, a codebase someone else could read — demonstrates more than a long
feature list does. Everything in Tier 1–3 of the priority map earns its
place either by fixing something broken or by deepening the part of the
product that's already distinctive. Tier 4 is where to be honestly
skeptical of new ideas, including this document's own.

---

## 33. Odysseus, read and triaged

Asked for directly: *"analyse the odysseus repo, then determine what parts of
it are valuable and can be incorporated into memorymap-ai."* Done the way §11's
Headroom evaluation was done — look at what this app actually does first, then
judge the import against it, rather than porting whatever looks impressive.

**The repository**: `pewdiepie-archdaemon/odysseus`, a self-hosted AI workspace
— chat, agents, deep research, documents, email, calendar, a model "cookbook",
an image gallery. Roughly 60k lines of Python against MemoryMap's ~6k, and a
much wider product: MemoryMap is a notebook that happens to have an AI in it,
odysseus is an AI workspace that happens to store things.

---

### The constraint that governs everything below — **now half-lifted**

**MemoryMap moved from MIT to AGPL-3.0. Odysseus is AGPL-3.0-or-later. The two
are now the same licence family, so the barrier that made this section
"lessons only" is no longer symmetrical.**

What changed, precisely, because this is the kind of thing that gets
misremembered in one direction or the other:

- **AGPL → MemoryMap is now permissible.** Copying odysseus source in no
  longer relicenses anything, because this project is already AGPL. It still
  requires the ordinary things copyleft requires: keep the notices, attribute
  the source, and do not strip the licence header off a file you took.
- **MemoryMap → an MIT project is still closed**, and is now *more* closed
  than before. Anything taken out of here carries AGPL with it.
- **The habit in this section is still the right one.** Everything below is
  written as a design lesson — an idea, a failure mode, a shape — and §6 did
  it that way deliberately: the provider work was written from the four
  questions odysseus's code *answers*, not from its code. Re-implementing
  independently keeps the provenance clean and keeps this codebase's own
  reasoning in its comments, which is worth more here than the saved typing.
  Copy only where there is a real reason to, and record where it came from.

**The AGPL clause that actually matters for an app like this** is §13:
someone who modifies MemoryMap and lets other people use it *over a network*
must offer those users the modified source. A plain GPL would not require
that — running a service is not distribution. Since the whole premise here is
"your notebook, on your machine", the licence now says the same thing the
product does: a hosted, modified, closed fork is not an option.

Two smaller things worth recording so nobody re-derives them:

- Odysseus's own dependency notes and `ACKNOWLEDGMENTS.md` are worth a look
  before adding any dependency it uses, because its licence tolerances are
  wider than this project's.
- The reverse direction is also closed. Nothing from MemoryMap should be
  offered upstream to odysseus as a patch without deciding, deliberately, to
  license that contribution under AGPL.

---

### Adopted this session

Each of these was re-implemented from scratch. What odysseus supplied was the
*idea* and, more valuably, the failure mode it had already hit.

- **A provider layer split by dialect, not by product (§6).** Odysseus's
  `_detect_provider` matches on hostname rather than substring, and falls back
  to "OpenAI-compatible" for everything unknown — which is right, because that
  is what the long tail implements. The lesson taken: build the *dialect*, and
  LM Studio, llama.cpp, Jan and vLLM all arrive together.

- **`loaded_context_length` beats `max_context_length`.** Odysseus reads both
  and prefers the loaded one. MemoryMap's plan for §6 named only the latter; a
  128k model *loaded* at 4k would have had its prompt budgeted at 128k and
  quietly lost its system prompt. This one measurement changed the design.

- **"Known" is a separate fact from "known value".** Odysseus carries a
  `known` flag beside every context length, because a fallback 128k is not
  proof a model holds 128k, and a budget scaled off an unproven number is worse
  than a conservative one. MemoryMap's version of this is `context_length`
  returning `None` and callers falling back rather than a made-up default
  propagating.

- **Multi-field catalog probing.** Every OpenAI-compatible server spells the
  window differently — `max_context_length`, `max_model_len`, `context_length`,
  nested `meta.n_ctx`. Odysseus reads all of them. So does
  `provider.context_from_catalog_entry` now.

- **Never auto-pick an embedding model as a chat model.** Odysseus's
  `_first_chat_model` exists because an OpenAI-style `/models` list routinely
  puts `text-embedding-ada-002` first and "use the first one" silently picks
  something that cannot hold a conversation. Re-implemented as
  `provider.first_chat_model`.

- **Model specs and context usage surfaced in the chat.** Odysseus reports
  `context_percent`, `usage_source: real|estimated`, and per-model metadata on
  every turn. This was the single most transferable *product* idea in the repo,
  and MemoryMap already had every piece needed for it. The message metadata
  line now says how full the window got, and marks an estimate as an estimate.

- **Read the capability list.** Odysseus tracks what each model supports rather
  than assuming. MemoryMap now reads Ollama's `capabilities` from `/api/show` —
  and it immediately caught a bug in the brand-new quick preset, which would
  have sent `think: false` to models that reject it.

- **SSRF hardening on a user-supplied backend URL.** Odysseus's `url_safety.py`
  makes exactly the right call for a local-first app: do *not* blanket-block
  private addresses, because pointing at a local server is the entire use case
  — block the link-local metadata range instead. Re-implemented as
  `security.check_backend_url`, plus a warning MemoryMap needs and odysseus
  does not, because MemoryMap promises the notes never leave the machine.

---

### Tools and skills: is odysseus leaner for small models? Measured, and no

Asked directly: *"does it handle tools and skills more efficiently such that
smaller models can better use them?"* The answer is the other way round, and
the numbers are worth keeping because they settle it.

| | MemoryMap | Odysseus |
| --- | ---: | ---: |
| Tools in the registry | 34 | 69 |
| Total description text | 3,849 chars | 17,792 chars |
| Mean per tool | 113 chars | 257 chars |
| Longest single tool | 306 chars | 1,205 chars |

Odysseus carries **twice the tools and 4.6× the description text**, and its
longest single tool description costs more than MemoryMap's ten shortest
combined. Its RAG tool retrieval is not a refinement that MemoryMap lacks — it
is the thing that makes a 17,792-character registry usable at all. Adopting the
retrieval without the bloat would be adopting a cure for an illness this app
does not have.

**Why their descriptions are that long is the transferable part.** They are not
padded; they are full of *disambiguation* — "do NOT use `app_api` for sessions",
"use `ui_control open_email_reply`, not `reply_to_email`", "this is for
EXISTING research; to START new research use `trigger_research`". That is the
tax on having 69 tools with overlapping responsibilities, paid on every request.
The lesson to keep is the inverse: **the cheapest way to keep the tool prompt
small is to not have two tools that a model could confuse.** Every time a new
tool here needs a sentence explaining when *not* to use it, that sentence is
evidence the boundary is in the wrong place.

**What MemoryMap already does that odysseus does not.** Worth recording so it
does not get "improved" away:

- `tools.within_budget` fits the schemas to the model's *reported* window and
  drops the least relevant tools, so a 4k model receives ~1,450 tokens of tool
  prompt and a 32k model receives all of it. Odysseus retrieves a fixed top-K
  regardless of the window.
- A skill run offers **only its declared tools** — 1,963 characters of schema
  instead of 10,215 — and the allowlist is enforced, not merely suggested.
- `tools.focus_for` is keyword-driven and therefore *readable and testable*.
  A cue that doesn't fire is a predictable failure; a retrieval that ranks
  wrong is not.

**Where MemoryMap's tools genuinely could improve**, in order:

1. ~~**The agent cannot run a skill.**~~ **built.** Flagged stale by this
   session's backlog audit — `run_skill` exists in `ai/tools.py`'s `HANDOFFS`
   table (§35 area of ROADMAP.md), so this section's own "single biggest gap"
   claim no longer holds. `make_plan` shipped alongside it: an open-ended
   request nobody saved as a skill gets a 2–6 step plan drawn by the agent,
   its turn ends, and the same runner works through it — which is also item 2
   below, "a live plan the agent ticks off", done the same way.
2. ~~**A skill has no "when to use".**~~ **built.** `when_to_use` is a field on
   a skill now, the agent can set it through `save_skill`, and `list_skills`
   returns it. This was the prerequisite for item 1: giving the agent the
   ability to run a skill without a basis for choosing one would have been
   worse than not giving it at all.
3. ~~**`list_skills` returns no cost signal.**~~ **built.** It now reports
   `step_count` and `changes_notes`, so a skill that alters the notebook reads
   differently from one that only summarises it — and the note to the model
   says plainly that it cannot start a skill itself, since a model that
   believes it can will narrate having done so.

### Worth building, not this session

Ordered by value-per-effort. Each is a shape to re-implement, never a file to
copy.

1. ~~**An `ask_user` tool that ends the turn (§18, §14).**~~ **built.** Odysseus's agent can
   stop mid-task and ask a multiple-choice question; the user gets clickable
   buttons and their answer arrives as the next message. This is the honest
   answer to a class of failure MemoryMap currently handles by guessing: an
   ambiguous instruction ("file this properly") becomes a confident wrong
   action. It also matches an IDEAS.md line directly ("an agent ask for
   permission dialogue in the chat"). MemoryMap already has the hard half —
   the destructive-action confirm card is exactly this UI — so this is mostly
   a second event type and a tool.

2. ~~**A live plan the agent ticks off (`update_plan`).**~~ **built, via
   `make_plan`** — see the correction on item 1 above. The skill runner's
   ticked-step display is now what any open-ended agent turn gets too, not
   only a saved skill.

3. **Semantic tool retrieval, replacing keyword `focus_for` (§11a, §14).**
   Odysseus embeds its tool descriptions and retrieves the top-K per message,
   with a deliberately tiny always-available core. MemoryMap's `tools.focus_for`
   does the same job with keyword cues and already cut fixed overhead from
   ~3,157 to ~1,439 tokens. **The honest note: this is an upgrade, not a fix.**
   MemoryMap has the embedding service to do it, but the current version works
   and the failure mode of the semantic one is worse — a cue that doesn't fire
   is predictable, a retrieval that ranks wrong is not. Worth doing *with a
   measurement*, the way §11 did: if it doesn't beat keyword cues on a set of
   real questions, don't ship it.

4. **A richer skill format.** Odysseus's `SKILL.md` carries frontmatter
   (`description`, `version`, `tags`, `requires_toolsets`, `confidence`,
   `source: learned|taught|imported`) and body sections: **When to Use**,
   **Procedure**, **Pitfalls**, **Verification**. MemoryMap's skills (§21) have
   ordered steps and a tool allowlist — the execution half — but nothing that
   says *when* a skill applies or *how to tell it worked*. "When to Use" is the
   one to steal first: it is what makes a skill findable by the model instead
   of only by the user. Two more ideas from the same file: usage counts live in
   a **sidecar** so the skill itself doesn't churn on every run, and the skill
   *index* (name + description) is always loaded while the *body* is fetched on
   demand — progressive disclosure, which is the same reversible-compression
   idea §11 already adopted for notes.

5. **A completion verifier for effectful turns.** After a turn that used a
   writing tool, odysseus runs an independent check that the claimed work
   actually happened, capped at two rounds. MemoryMap has a cheaper version of
   this already — `_CLAIM_PATTERN` catches a model that says it saved something
   when no write tool ran — and the cheap version covers the common case. The
   upgrade is checking that what was written is what was *asked for*, not just
   that something was written. Worth it only once agent turns get longer.

6. **Better degraded-state reporting.** Odysseus's own roadmap asks for this
   about its own app, which is a useful signal: it is a real gap in a system
   with this many optional parts. MemoryMap is in better shape here (the status
   pill, the embedding error line, the support bundle), but the same principle
   applies to the new provider work — "reachable but wants a key" is a
   different state from "off", and only the endpoint knows it today.

---

### Looked at and deliberately not taken

Recording these so a future session doesn't re-evaluate them from scratch.

- **The Cookbook / `services/hwfit`.** Hardware-aware model recommendation:
  detect the GPU and RAM, score every candidate model on quantisation, VRAM
  fit, architecture age and expected tokens/second. It is the most impressive
  thing in the repository and it is a *product of its own* — thousands of lines
  plus a curated model database that has to be maintained or it rots. MemoryMap
  has `SUGGESTED_MODELS`, a hand-written list of five models that work well on
  a laptop, and for a notebook app that is the right size of answer. Revisit
  only if "which model should I run" becomes a question people actually ask
  here.

- **Sub-sessions, pipelines and agent-to-agent messaging** (`create_session`,
  `send_to_session`, `pipeline`). Real capability, and completely out of scope
  for a single-user notebook: MemoryMap deliberately refuses to run with more
  than one worker.

- **`bash` and `python` tools.** Odysseus gives its agent a shell. MemoryMap
  should not, and this is not a close call — the whole safety story here is
  that the agent's blast radius is the notebook, destructive actions are
  confirmed, and everything is undoable. A shell tool ends all three properties
  at once.

- **The email, calendar and CalDAV integrations.** A different product.

- **Their search ranking (`services/search/ranking.py`).** Genuinely nice —
  recency scoring, domain quality, per-term title/snippet weighting. Not taken
  because MemoryMap's web search is a *reader*, not a search engine: results go
  to the model with a reader view, and the ranking that matters is the one
  SearXNG already did. Reconsider if §13 ever grows a results page people
  browse themselves.

- **`teacher_escalation` — asking a bigger cloud model when a local one is
  stuck.** Interesting, and squarely against this app's promise. A local model
  failing is a thing to report, not a thing to silently escalate to somebody
  else's computer.

---

### What reading it changed about how I'd judge this app

Two things, both uncomfortable and both worth writing down.

**Odysseus's roadmap opens by admitting the CSS is a swamp and that it doesn't
know if its own integrations work.** That candour is the most useful thing in
the repository. This document has the same risk in a milder form and already
names it — the audit that found four of §2's six "quick wins" already built.
The rule that came out of that ("check the running app before building
anything here") is the one worth keeping, and it is worth applying to §33
itself before starting any item above.

**Almost everything odysseus does better, it does by being bigger.** The
context tracking, the tool retrieval, the skill format, the provider layer —
each is a more elaborate version of something MemoryMap already has, and in
every case the elaborate version costs code that has to keep working. The
items adopted above were the ones where the idea was small and the *failure
mode* was the valuable part: `loaded_context_length` beating
`max_context_length` is four lines and a comment, and it prevents a bug that
would have been very hard to find from the symptom. That is the shape of import
worth making, and it is the filter to apply to the "worth building" list too.

---

## 34. Where I'd take this — an outside read

Asked for directly. Written as a working opinion rather than a plan: these are
judgements, and the roadmap's own rule — *check the running app before building
anything here* — applies to this section more than to any other.

### The thing this app is actually good at, which is not what it says on the tin

The pitch is "a local AI files your notes". That is the *capture* story, and it
is solved. What has quietly become the more valuable half is **retrieval you
can check**: an answer arrives beside the notes it came from, every tool result
says where it came from, the graph says *how* two notes connect, and a turn now
reports how full the model's window got and whether the token counts were
measured or guessed.

Almost nothing else in this space does that. Hosted assistants can't (the notes
aren't theirs to show), and most local ones don't bother. **That is the
differentiator, and it is worth defending explicitly** — every future feature
should be asked "can the user check this?" before "is this clever?". The
`might_connect` list is the model to copy: it would have been easier to mix
guesses into the results, and worthless.

### Three things I would prioritise, and why

1. ~~**Finish the agentic loop, then stop adding to it.**~~ **Done — the
   "then stop" half is now the live instruction.** `run_skill` and `make_plan`
   both shipped (§33's correction, this session's audit); the agent can plan,
   ask, act, and be checked. What's left of this recommendation is the second
   half, which is a standing constraint rather than a task: odysseus at 69
   tools is still the cautionary tale, so **every new tool should still have
   to displace an existing one or justify the trim** — that sentence doesn't
   get to retire just because the tool list it was warning about stopped
   growing for a while.

2. ~~**Make the notebook survive being large.**~~ **Measured, and two of the
   three predicted failures were real** — `scripts/scale_test.py`, a
   generated fixture up to 50,000 notes, run by hand (it isn't a pytest test;
   see the script's own docstring for why). The actual numbers, not the
   guess:

   | Call | at 50k notes, before | after |
   | --- | ---: | ---: |
   | `GET /graph` (no similarity) | ~19s (extrapolated) | 1.8s |
   | `search_manager.retrieve` — every chat turn's search | 6.6s | 0.5s |
   | `_suggested_neighbours` — one agent tool call | ~20s (extrapolated) | 1.3s |
   | `GET /graph?similarity=true` | O(n²), already known, off by default | unchanged |
   | `_graph_neighbours` / `_related_notes` | 1.3-1.5s, bounded by `MAX_GRAPH_NOTES` | unchanged, judged acceptable |

   Both fixed causes were the same shape: an ORM object (a full `Entry`, or a
   `Category` via `session.get()`) materialised for every row in a table
   scan, when only a handful were ever going to be used. `routes_graph.graph()`
   was resolving each note's category with its own query (10,000 calls of it
   were 87% of the endpoint's time on a 10k-note notebook, found by
   profiling, not by guessing); `semantic_search()`'s own docstring already
   said "revisit only if it ever feels slow" — it did. Both fixed by scoring
   or matching against raw ids/vectors first, and only fetching the small set
   of `Entry` rows that actually rank. Pinned by
   `tests/test_scale_query_counts.py` (query *count*, not wall-clock —
   deterministic under CI load where a timing assertion isn't).

   **`GET /graph?similarity=true`'s O(n²) is real and untouched** — 30
   seconds at just 2,000 notes in the same measurement run, which is well
   within an active user's actual reach (unlike 50k). It's off by default and
   the route's own comment already names the tradeoff ("it's personal-
   notebook scale"); worth a real fix (cap the comparison pool, or drop the
   pairwise scan for a nearest-neighbour index) before recommending anyone
   turn the toggle on, not before then.

   **Storage was not a problem** — 50,000 notes measured at 12MB (this
   fixture's small vectors); rescaled to a real ~384-dim embedding model,
   ~1.8KB/note, ~360MB for 200,000 notes. Attachments are separate and
   unbounded, but nothing here suggests the database itself is a concern at
   any size a real notebook would reach.

3. **Onboarding, because none of the above matters if nobody gets to it.** §27
   is unbuilt and the first run currently is: install Python, run a script,
   install Ollama separately, pull a model, come back. Every step is a place to
   give up, and the app is at its least impressive precisely then — no notes, so
   no retrieval, so no reason to trust it. The single highest-leverage version
   is not a tour: it is **shipping something to look at**, a handful of example
   notes that can be deleted in one click, so the graph, the timeline and the
   dashboard have something to draw on the first screen.

### Where I think the roadmap is over-invested

Said plainly because a backlog this size needs someone to argue *against* parts
of it:

- **Desktop packaging (§7) is a much bigger commitment than it reads as.**
  PyInstaller builds are the easy 20%; code signing, notarisation, an updater
  and three platforms of support burden are the rest, and they recur forever.
  `start.bat` and a browser tab are unglamorous and they work. I would do this
  only once someone who is not you is asking for it.
- **The whiteboard (§4a) and the in-built browser (§25/IDEAS) are separate
  products** wearing this one's clothes. Each is months, and neither makes the
  notes better.
- **Multi-category notes (§23) is a schema change chasing a small win.** Tags
  already do this. The honest version is "categories are a weak idea that tags
  do better" — worth *considering removing* the tension rather than deepening
  it.

### What is missing that nobody has asked for

- **An answer that says "I don't know" more often.** The hallucinated-write net
  catches the worst case, but a model that pattern-matches four notes into a
  confident wrong summary is the failure that damages trust in retrieval, and
  nothing measures it. A small set of questions with known-correct answers,
  run against each supported model, would turn "which model is good here?" from
  opinion into a table — and that table is worth more to a user choosing a
  model than anything in the Cookbook idea §33 rejected.
- **Export that includes the AI's work.** Notes export; conversations,
  reminders, links, skills and saved looks do not. "It's genuinely yours" is
  only true to the extent you can take it all with you.
- **A second pair of eyes on the crypto.** Private notes use scrypt and
  AES-GCM correctly as far as I can tell, and "as far as I can tell" is not the
  standard that claim deserves. It is the one part of the app where being
  wrong is unrecoverable and silent.

### The one process change worth making

**Nothing in this app has ever been run against a real model in a test.** The
whole suite fakes the provider, which is why it is fast and why it caught the
tool-call-fragment bug — but it also means "works" has always meant "works
against my idea of what Ollama does". One nightly job that pulls a 2B model and
runs ten real turns through both providers would have caught the `think: false`
rejection *before* I shipped it, rather than because I happened to read
`/api/show`'s capability list an hour later.


---

## 34b. Judging another agent's branch — what was kept, and on what grounds

Companions: [../ROADMAP.md](../ROADMAP.md) · [BACKLOG.md](BACKLOG.md) ·
[HISTORY.md](HISTORY.md) · [HANDOVER.md](HANDOVER.md).

The `fix/Antigravity-Audit` branch was ~9,600 insertions from a different
coding agent with no tests. The temptation with a branch like that is to judge
it as a whole — either trust it or throw it out. Both are wrong, and the ratio
is why: **one thing was reverted and everything else was kept.**

The test applied to each piece, in order:

1. **Does it do something the app wanted?** Almost everything did. The
   whiteboard, memory streams, semantic note search, the command palette, the
   background librarian and the activity monitor between them close five items
   that had been sitting in IDEAS.md for months.
2. **Is the mechanism defensible, separately from the feature?** This is where
   the WebSocket failed and nothing else did. The feature ("stream the answer")
   was already working; the new mechanism cost thread-safety, the auth gate and
   the same-origin policy, and bought nothing on a local-first app. A feature
   can be right and its mechanism still be the wrong trade.
3. **What does it cost at scale?** Several pieces were vectorised with NumPy,
   which was a real improvement over per-pair Python loops — but two of them
   allocated an N×N matrix to do it, which is a memory regression hiding inside
   a speed win. Kept the vectorisation, blocked the matrix (§34's O(n²) note
   now has a resolution for two of its three sites).
4. **Would anyone notice if it silently did nothing?** This is the question
   that found the most. Four separate features had never executed once, and
   every one of them was invisible: an exception swallowed by a broad `except`,
   a `start()` never called, a method that does not exist, a CSP quietly
   refusing thirty-five declarations.

### The general lesson, which is not about this agent

Every failure in categories 2–4 above shares a property: **the code reads as
correct.** A reviewer checking "does this look right" passes all of them. What
caught them was running the suite, running the linter, and pointing a browser
at the result — three things that take minutes and that the branch had never
had done to it, because it shipped without tests and CI never ran.

So the process conclusion is narrower and more useful than "review harder":
**a branch that cannot run CI has not been reviewed, however carefully it has
been read.** The 46 tests and 4 lints added in §40 exist so that the next such
branch is judged in minutes rather than in a session.

### The one thing deliberately not decided

`edit_note` was changed to `destructive=True`, so the agent now pauses for
confirmation on every edit rather than only on deletes. That is defensible —
an edit overwrites content — and it is also an unannounced change to how
multi-step agent work feels, and it interacts badly with the background
librarian, which abandons a run rather than ask. Left as it arrived, and
flagged in §40's open list, because "which of those two costs more" is a
product judgement rather than a correctness one.

---

## 59. Three sibling repos, read and triaged — claude-obsidian, cognee, graphify

Asked for directly: a full analysis of three other repos attached to the same
session (`claude-obsidian`, `cognee`, `graphify`), what they do better, what
this app has overlooked, and whether their backends are better designed —
followed up by *"for the parts you skipped [because MemoryMap already has
them], are there areas in which they do it better than is currently there?"*
The second question is the one that mattered: three separate read-only agents
summarised each repo, and every recommendation was then checked against this
app's actual code (`search_manager.py`, `entry/paths.py`,
`ai/ollama_client.py`, ROADMAP.md itself) before anything was written down
here, per this file's own standing rule and §33's own precedent — a
recommendation that survives a `grep` is worth more than one that doesn't.

**The repositories, in one line each:** claude-obsidian is a set of Agent
Skills for filing an Obsidian vault with source-cited notes, not a standalone
app. Cognee is an AI-memory platform that builds an LLM-extracted knowledge
graph over ingested data via a pipeline of pluggable graph/vector/relational
backends. Graphify maps a codebase (not notes) into a queryable graph via
tree-sitter, with an optional LLM pass and a vis.js visualisation.

**Licences — no constraint, unlike §33.** claude-obsidian is MIT, cognee and
graphify are both Apache-2.0. All three are permissive and compatible with
this project's AGPL-3.0: nothing here needs the AGPL clause in §33 to be
lifted. Apache-2.0 code carries a NOTICE/attribution requirement if anything
is copied close to verbatim; nothing below proposes that — as in §33, the
value found was in the *shape* of an idea, checked against and re-derived for
this app's own code, not a port.

---

### Looked at and deliberately not taken

- **Community-detection clustering (graphify's Leiden algorithm).** Not a
  gap. `entry/paths.py`'s `clusters()` already rejected Louvain/Leiden/label
  propagation in favour of connected components, with its own comment
  spelling out why: "a component is **exactly true**... where a community is
  a judgement call... an answer the user cannot verify by clicking two notes
  is one they cannot trust." Graphify's own hub-labelling is functionally
  what `pagerank()` (same file) already does for this app. Same call, made
  earlier, for the same reason — no action.
- **Direct cloud-provider breadth (graphify supports Anthropic/Gemini/Azure/
  Bedrock out of the box).** Not a gap — a deliberate scope boundary. This
  app's Ollama-plus-OpenAI-compatible pair (§6) is the whole of "100%
  offline"; adding hosted providers would be a different product, not a
  missing feature.
- **Cognee's multi-tenant ACLs and pluggable graph/vector/relational adapter
  interfaces.** Real engineering, and real overkill for a single-user local
  notebook. The one shape worth naming without adopting the machinery: this
  app already has the *equivalent* pattern where it matters — `ai/provider.py`
  is exactly cognee's adapter-interface idea applied to LLM backends instead
  of databases. Extending the same shape to storage is not worth it unless a
  second storage backend is ever actually planned.
- **claude-obsidian's filesystem transaction/dirfd safety layer** (atomic
  writes, casefold-alias detection, symlink-traversal rejection). Solves a
  problem — many agents concurrently writing loose Markdown files across
  Windows/macOS/Linux filesystems — that this app's single SQLite database
  with its own transactions doesn't have.

### Promoted to ROADMAP.md, Tier 3 — items 32–36

Two of the four things this app already has, checked against sibling repos
doing the "same" thing, turned out to be doing it worse in a concrete,
fixable way rather than just differently:

- **Keyword search has no IDF weighting and can't use an index**
  (`keyword_search`'s `Entry.content.ilike(f"%{term}%")` is a full-column
  scan with a leading wildcard). claude-obsidian's stdlib BM25 index is what
  surfaced this; the fix that fits this codebase is SQLite's own FTS5 +
  `bm25()`, not a port. → ROADMAP.md item 32.
- **`graph_expansion` is hard-capped at one hop**, so an answer two links
  away from what matched isn't reachable through search at all. Cognee's
  multi-hop `GRAPH_COMPLETION_COT` is what surfaced this, but the fix has to
  answer to this app's own already-stated verifiability principle (the same
  one that ruled out Leiden clustering above), not just add hops. → ROADMAP.md
  item 33.

Two are genuine new capability, not present in any form:

- **No entity/concept layer above notes** — every connection in the graph is
  note-to-note; there is no node for "this person" or "this project"
  independent of any one note that mentions them. This is the one thing
  cognee's LLM-entity-extraction genuinely has that this app doesn't, and
  it's the piece most directly in the way of "find things by following
  concepts through the graph," which is what was asked for. → ROADMAP.md item
  34.
- **No vision-capable image understanding.** Confirmed by grep, not assumed:
  `ollama_client.py` already reads a model's `vision` capability alongside
  `tools`/`thinking` (the same `/api/show` call, §6), but nothing consumes
  it — no code path sends an attached image to a vision model. Asked for
  directly this session, including how it should be configured. → ROADMAP.md
  item 35.

And one is a refinement of something this app already does better than any
of the three repos individually, closing the one real gap in it:

- **Q&A answers cite which notes matched (`match_info`) but not which
  specific claim inside the answer's prose came from which note.**
  claude-obsidian's claim ledger is the sibling idea, but most of what it
  does already exists here in a different shape — `unsupported_claims`
  (ROADMAP.md Tier 1 item 7) checks the agent's own narrated actions, and
  link `reason`/`reason_confidence` (Tier 2 item 9) already grounds a
  connection between two notes with an editable, backfillable confidence
  score, which is more than any of the three repos' link-provenance features
  do. The gap left after those two is narrower than a full claim ledger:
  per-sentence grounding inside a direct Q&A answer specifically. →
  ROADMAP.md item 36.

---

## 60. Odysseus, re-read — the repo tripled in size, and this time the question was answered from its own words

Asked again, directly: a fresh full read of odysseus, what it does better, what
this app has overlooked, and whether its backend is better designed. §33/§34
already did this once, in depth — read those first; nothing there is repeated
below. This section exists because the attached repo is not the one §33 read.

**It's grown roughly 3.3×.** §33 measured ~60k lines; this checkout
(`Braydenh563/odysseus`, `dev`, commit `c80462e` — a fork of
`pewdiepie-archdaemon/odysseus`, same project) is **~200,700 lines of Python**.
Whole subsystems exist now that weren't there to read before: an MCP client
*and* four MCP servers of its own, a mobile "companion" pairing flow, a
chat-derived passive memory extractor, multi-user privileges with optional
TOTP, a vault, contacts, signatures, workspace routes, STT/TTS, face
recognition, YouTube, and bridges to ChatGPT/Copilot/Codex. Everything below
is new material; §33's "adopted"/"not taken" lists still stand and weren't
re-litigated.

### Is its backend better designed? No — and it says so about itself

Odysseus carries its own Phase-0 refactor audit,
`specs/architecture-runtime-inventory.md` (dated 2026-06-16, written for its
own issue #4082, *"codebase readability improvements"*). Its numbers, not a
guess:

| | Odysseus (its own audit) | MemoryMap (this repo) |
| --- | --- | --- |
| `src/`-equivalent flat files | 95 (`src/`), no domain grouping | 5 subpackages (`ai/api/core/entry/search`) |
| Route handlers | 54 flat files in `routes/` | grouped by domain under `api/` |
| Largest single Python file | `src/tool_implementations.py`, 4,032 lines, rated **HIGH risk** | none over ~1,900 |
| DB model file | `core/database.py`, 2,265 lines, **imported by 102 files** — their own words: *"the highest-risk refactor... should be tackled last, never first"* | `core/database.py`, one model module, no comparable fan-in reported |
| Single largest CSS file | `static/style.css`, **36,653 lines**, tracked separately (#2617) | governed by `docs/DESIGN.md` + `tests/test_style_scale.py`, which exists specifically to prevent this |

This is the hard evidence for what §33 already suspected on softer grounds
(*"almost everything odysseus does better, it does by being bigger"*) — now
with the target's own internal audit on record instead of an outside
impression. A 200k-line app with 95 ungrouped files and a 36k-line stylesheet
is not a design to import; it is the specific failure `test_style_scale.py`
and this app's five-subpackage `src/` layout already exist to avoid. Bigger
is not the same axis as better-organised, and here they've come apart.

One narrower design comparison, checked by grep rather than assumed: odysseus's
agent tools reach the app's own HTTP API via a **loopback bearer token**
(`core/middleware.py`'s `INTERNAL_TOOL_TOKEN` / `X-Odysseus-Internal-Token`,
because *"the agent's tool calls don't carry the admin user's session
cookie"*) — an internal auth-bypass surface that has to be kept secret and
kept in sync with every admin-gated route. MemoryMap's tools
(`ai/tools.py`) call the same `Session`/manager objects the routes call,
in-process, with no HTTP hop and nothing to leak. Not a gap; a simpler
architecture that happens to also be safer, worth naming so it doesn't get
"improved" toward odysseus's shape later.

### A real, narrow bug this comparison surfaced

`core/atomic_io.py` — `atomic_write_json`/`atomic_write_text`, write-to-tmp +
`fsync` + `os.replace` — is used for every piece of live JSON state odysseus
persists outside its database, `auth.json` included. §59 already looked at
this *idea* once (claude-obsidian's transaction/dirfd layer) and correctly
judged it solved a problem this app doesn't have, because SQLite's own
transactions cover concurrent note writes. **That dismissal doesn't reach
this case.** `core.config.ConfigManager.set_preference`
(`src/memorymap/core/config.py:148`) persists preferences with a plain
`self.preferences_path.write_text(json.dumps(...))` — no tmp file, no fsync,
no atomic rename — and `preferences.json` holds `llm_api_key`, a secret, plus
every setting the user has ever changed. It is the one piece of live state in
this app that sits *outside* the database's transaction boundary, which is
exactly the condition under which a `kill -9` or power loss mid-write leaves
a truncated or half-written file. The docstring one line above the write
already promises *"a crash never loses a settings change"* — the promise and
the code disagree. Fix is odysseus's own two functions, ~15 lines, applied at
this one call site; grepped for other direct `write_text`/`open(..., "w")`
calls in `src/memorymap/` and found none else touching live user state (the
other three are a searxng pid file and a source-bootstrap shim, not user
data).

### Worth building — features, ranked by fit, and what actually happened

1. ~~MCP support~~ **Built** — `src/memorymap/mcp_server.py` exposes the tool
   registry over stdio, checked before writing this update rather than
   re-scoping it from nothing.
2. ~~Passive memory extraction from chat~~ **Built** —
   `ai/passive_capture.py` plus `auto_capture_enabled` (`core/config.py`),
   wired into `ai/autonomous.py`'s job list, a Settings toggle
   (`#pref-auto-capture`), and `tests/test_passive_capture.py`. Same
   default-off, fingerprint-short-circuited shape this entry originally
   asked for.
3. **QR + LAN pairing for a phone companion** — still not built, and still
   only worth doing *if* a phone companion is ever built on purpose; nothing
   here blocks on it. Kept as the pattern to copy when that decision is made.

### Looked at and not recommended

- **Multi-user privileges + optional TOTP** (`core/auth.py`'s
  `DEFAULT_PRIVILEGES`, per-user `allowed_models`/`max_messages_per_day`,
  `pyotp`). Out of scope for the same reason §33's sub-sessions/pipelines
  item was: this is deliberately a single-user local notebook. TOTP itself is
  orthogonal to multi-user-ness, but `routes_auth.py`'s existing model —
  idle + max-age token expiry, a global exponential-backoff throttle on wrong
  guesses, no cookie to leak — is already reasoned through for this app's
  actual threat model (someone with access to the machine), and adding a
  second factor to a single local password doesn't clearly strengthen that.
  Recorded so it isn't re-evaluated from nothing.
- **Face recognition, STT/TTS, YouTube, email/calendar/ChatGPT/Copilot/Codex
  bridging.** Different product, same call as §33 made on odysseus's email
  and calendar integrations the first time — a notebook doesn't need to
  become a workspace to stay itself.

### The one-line answers to the three questions asked

- **Does it do anything better?** Not on the axis it looked like it might —
  the backend is bigger, not better-organised, by its own audit. The two real
  wins are narrow: `atomic_write_json` (a real bug found in this app because
  of it) and a working MCP shape to copy.
- **Any features overlooked?** One real one: nothing in this app turns an
  offhand mention in ordinary chat into a filed note. Everything else new in
  odysseus is out of this app's stated scope on purpose.
- **Is its backend better designed?** No, and now there's their own
  refactor-planning document saying so about itself, not just this file's
  opinion of it.

## 66. Kortex.co, read and triaged — and the second-frontend question decided

Two asks arrived together: research a competitor (kortex.co, "the AI-powered
second brain") for features worth adopting, and a judgement call on building
a second, React-based frontend alongside the existing vanilla-JS one, sharing
this app's backend, user-switchable between the two.

**Kortex, in one line:** a unified capture/write/synthesize workspace built
around three pillars — Captures (quick chat-shaped idea dumping), Documents
(a full markdown editor with slash commands and block nesting), and
Sources/Highlights (a searchable library with Readwise/Kindle import and a
web clipper) — plus `kAI`, a Tab-triggered assistant that turns raw
fragments into a coherent draft, and 25+ prebuilt AI workflows. Direct fetch
of kortex.co was blocked by this session's network egress policy; read via
search-result summaries and cross-referenced against this app's actual code
before anything below was written down, per this file's own standing rule.

**Mapped against this app:** `kAI`'s Tab-to-draft is already covered by the
Writing Room (`app.js:5905+`). Document-as-AI-context and cross-note
synthesis are already covered by the existing chat/search tools. Three real
gaps, now in BACKLOG.md: the Skills system ships zero starter skills
against Kortex's 25+ workflows (§63); the Documents editor has no slash
commands or block nesting (§64); highlight/web-clip capture doesn't exist
at all (§65).

**The second-frontend question — decided against, user agreed.** A second
full React frontend sharing this backend means every feature ships twice,
tests twice, and drifts twice, indefinitely — not a one-time cost. It also
runs directly against work already in motion: ROADMAP.md §0's own
highest-priority frontend finding is that `app.js` needs *modularising*
(a `whiteboard.js`/`graph.js`/`state.js` split), not replacing, and a
second framework doesn't reduce that debt, it adds a second pile of it
next to the first. If the underlying complaint is "feels dated," that's a
`DESIGN.md`-scoped styling problem; if it's "hard to maintain," the
extraction already planned is the cheaper fix for the same symptom. This
project's own history has two direct data points against a rewrite-shaped
fix specifically: `/chat/stream`'s WebSocket rewrite (reverted, cost ~70
tests and the same-origin protection) and the "week of another agent's
work" that shipped 90 failing tests (§40's audit). Not adopted; revisit
only if a specific, concrete pain point emerges that modularisation
doesn't address.

## 104. Sub-categories, asked about directly — and whether the graph needs a new mechanism to answer it

Asked directly: should there be sub-categories — e.g. `Travel` with a
sub-category `Family Japan Trip December 2026` — and can the knowledge
graph's traversal/use/design be improved further. Two different questions,
answered separately.

**Sub-categories: no, not as a new hierarchy field — the tools to do this
already exist.** `Category` (`core/database.py`) is flat by design (name
only, no `parent_id`); adding a real parent/child layer means every surface
that already knows about categories — the janitor's filing prompt, the
Library's category filter, Timeline's category grouping, the graph's own
colour-by-category, the chat retrieval prompt — has to learn a second
concept ("category, or is it a sub-category?") for a need that is really
just "group these particular notes together under a name," which this app
already has two ways to do without a schema change:
- **Tag it**: `Travel` as the category, `family-japan-trip-dec-2026` as a
  tag. Filters, search (`tag:`), and the janitor's own filing already treat
  a tag as exactly this granularity.
- **Hub-note it**: one note titled `# Family Japan Trip — Dec 2026`,
  every related note linked to it (`[[wiki links]]`/`entry_links`, both
  already real relationships, not a workaround). The graph tab already
  renders that cluster as a visibly distinct neighbourhood — which is a
  truer picture than a rigid tree, since a trip note plausibly also belongs
  to `Family` or `2026 goals`, and a strict parent/child category can only
  ever pick one parent.

  If neither reads as discoverable enough in practice, the cheaper next
  step is surfacing what already exists better — e.g. a Library filter
  chip for "notes linked to this hub note" — before adding a second
  category concept.

**Graph traversal: already being worked, and already prioritised — see
BACKLOG.md §101, don't re-derive this here.** Short version: typed/weighted
links are built (`link_strength()`, wired into `graph_expansion()`);
per-stage token cost accounting is built (so a "did this change actually
help" question is answerable at all now); the *next* concrete step is
already named there — finish the composite signal (shared tags/category/
temporal proximity) and then re-measure whether the existing
`graph_expansion()` walk actually got better, which needs a real reachable
Ollama and cannot happen in this sandbox. Nothing about the sub-category
question above changes that order or adds a new item to it — a hub-note
cluster is read by the exact same traversal, not a different one.

## 114. A product-strategy read — competitive teardown, per-feature upgrades, inventions, and a 90-day plan

Asked for directly, as a strategy brief with blank placeholders (one-liner,
feature list, competitors, brand attributes, constraints, horizon). **The
placeholders were filled from the repo rather than handed back as a
question** — README.md's own one-liner, the seven tabs, the AGPL/offline
constraints, and the competitor reads already on file. Everything below was
checked against the running code first, per this file's standing rule; where
a claim is reasoning rather than observation it says so.

**Do not read this as a task list.** It is a judgement document like §32 and
§34. What it proposes that survives triage goes to
[../ROADMAP.md](../ROADMAP.md) or [BACKLOG.md](BACKLOG.md); what is already
built is in [HISTORY.md](HISTORY.md), which is where the grounding pass below
started.

### 114.0 The brief, filled in from the code

| Slot | Filled with | Source |
| --- | --- | --- |
| One-liner | "Your thoughts, mapped by a local AI. 100% offline, on your machine." | README.md |
| Target users | (1) privacy-motivated PKM users already running Ollama/LM Studio; (2) students/researchers with a document pile and no wish to upload it; (3) the local-LLM hobbyist looking for something to *point a model at*; (4) the author, as a daily notebook and portfolio piece | inferred — **assumption, not measured**, and the cheapest test is the issue tracker: see 114.5 |
| Platform/tech | Python 3.11–3.13 + FastAPI + SQLite/SQLAlchemy; vanilla JS frontend, no build step; PWA; PyInstaller Windows/Linux packages; any OpenAI-compatible local backend | pyproject, `frontend/`, `packaging/` |
| Constraints | Offline by default, no account, no telemetry, no cloud cost, AGPL-3.0 (code may come in from AGPL, nothing goes out to MIT), single-user, no bundler/CDN, must not require torch | CLAUDE.md, LICENSE, §33 |
| Brand attributes | **Checkable** · **Genuinely yours** · **Works when the AI doesn't** · **Spatial/temporal, not a list** · **Honest about what it didn't do** | README's four "why this exists" bullets + §34 |
| Horizon | v1 upgrades ≈ 6–8 weeks of sessions; moonshots 3–6 months | as asked |

**The metric problem, stated up front because it changes every answer below.**
This app has no analytics and must never get any — "no telemetry" is in the
pitch, the privacy doc and the licence rationale. So *activation rate, D7/D30
retention, conversion and NPS are not measurable here and no roadmap item
should be justified by one.* Three honest substitutes are used throughout, and
114.5 defines them properly:

- **GH** — GitHub-observable (release-asset downloads, issues per 100
  downloads, issue *mix*, star/fork velocity, PRs from strangers).
- **Local** — a user-visible, never-transmitted counter the user reads
  themselves (this is also a feature: see invention B7).
- **Bench** — a fixture measurement in-repo (`scripts/scale_test.py`'s shape,
  or a Playwright timing) or a hand-run 5-person usability session.

### 114.0b Three stale claims caught while grounding this

The grounding pass was worth its cost before it produced a single idea, which
is the point CLAUDE.md keeps making. Three items on live lists are already
built and should be struck rather than scheduled:

1. **§111.2 item 4, "Export a single note or document" — built.**
   `GET /entries/{id}/export.md` (`routes_entries.py:1241`) and
   `GET /documents/{id}/export.md` (`routes_documents.py:533`), reachable from
   the note ⋯ menu (`app.js:2958`) and from Library rows
   (`library.js:519,592`). Strike the item.
2. **§111.2 item 7, "A keyboard-shortcut sheet" — built.** `?` opens
   `#shortcuts-overlay` (`index.html:6324`), Settings → Shortcuts rebinds
   (`#settings-shortcuts`), and Help documents both. Strike the item.
3. **§111.2 item 2, "Backlinks on the note itself" — half built, and the
   remaining half is smaller than the item implies.** Documents already have a
   live backlinks panel (`#doc-backlinks`, `documents.js:404`), and notes have
   the Connections dialog (`GET /entries/{id}/connections`, §87 row 5). What is
   genuinely missing is only **an always-visible backlink strip on the note
   card/editor** rather than a dialog behind a ⋯ menu — which is upgrade
   F1-3 below, not a new subsystem.

Everything proposed in 114.2 and 114.3 was checked the same way; where a
proposal is a *promotion of something already scoped*, it says so and links
the existing scope instead of restating it.

---

### 114.1 Competitive teardown

Read live this session (search-result and review level, not first-hand renders
— Kortex and Granola remain blocked by this sandbox's egress proxy, same gap
§102 recorded). Sources at the end of this section.

| Competitor | Standout | UX pattern worth stealing | Pricing / growth loop | Structurally can't copy us |
| --- | --- | --- | --- | --- |
| **NotebookLM** (Google) | Studio panel: one click turns sources into Audio/Video Overview, Mind Map, slides, infographics, **quizzes and flashcards**; Deep Research with source-scoping; ~50 sources, 200 PDFs | *One click, many artefacts* from the same corpus — the artefact menu is the product | Free tier → Google One AI; distribution loop is Google itself | Your notes are on their servers; there is no offline mode and never will be |
| **Obsidian** (+Smart Connections) | Plain-file vault, plugin ecosystem, local semantic search via Ollama | Plugin ecosystem as feature surface; command palette-first | Free core → paid Sync/Publish; loop = plugin authors marketing the host | AI is bolt-on per plugin: no shared filing/agent/audit layer, no answer-with-sources as a first-class object |
| **Notion AI** | Databases, properties, collaboration, polished AI writing | Properties/typed objects; slash-command everything | Seat-based SaaS; team virality | Requires network for every AI interaction; no offline fallback |
| **Anytype** | Local-first, E2E encrypted, object/relation model, P2P sync, free | Objects + relations instead of folders | Free/OSS, community loop | Deliberately thin AI — no local model orchestration |
| **Capacities** | Object-based PKM, genuinely good AI organisation, Readwise/Raycast/WhatsApp/Telegram capture | *Capture from where you already are* | ~$10/mo; integration loop | Cloud-powered; the sync is the product |
| **Logseq** | Local-first outliner, Ollama plugins, journals-first | Daily-journal-first capture | OSS + donations | Outliner-shaped; no graph/timeline synthesis story |
| **Khoj** | Self-hostable "AI second brain", local LLMs via Ollama/llama.cpp, custom agents, free self-host / $8 hosted | Agents as named, shareable configs | OSS → hosted upsell | Chat-first, not notebook-first; no spatial/temporal views |
| **Reor** | Local-model note-taking with automatic semantic linking | Auto-linked as you type | OSS | Small surface; no agent, no audit trail |
| **Granola** | Rough bullets + transcript → merged meeting note; ~29 typed templates | Two-stream capture merged after the fact | Seat SaaS, meeting-network loop | Needs the cloud calendar/meeting graph |
| **Kortex** | Captures/Documents/Sources pillars, `kAI` Tab-to-draft, 25+ workflows, web clipper | Tab-to-continue writing; workflow library | Subscription; creator loop | Cloud |
| **Mem / Reflect / Recall / AFFiNE** | Auto-organising cloud notebooks; Recall in particular is built on summarise-the-web | Zero-effort filing as the pitch | SaaS | All cloud-first |

**Table stakes — match or exceed, no credit for having them**

1. **Import that actually lands** (Notion HTML/CSV, Obsidian vault, Apple/Google Keep). `POST /import/markdown` + `/import/directory` exist; the Notion dialect and a *first-run offer* do not. Already §109.3 item 1 — still the single biggest adoption blocker.
2. **Typed templates with real fields** (Granola ~29, Notion databases). §102 item 4 / §111.2 item 5, unbuilt.
3. **Capture from where you already are** — clipper/bookmarklet/tray hotkey. §102 item 5 and BACKLOG §95 item 9 (web clipper), both unbuilt.
4. **Artefacts from a corpus** — mind map, audio, quiz, flashcards. The whiteboard has mind-mapping; audio is scoped and unbuilt (ROADMAP §88.2 item 7); quiz/flashcards do not exist anywhere (`grep -i flashcard src frontend` is empty).
5. **A note editor that isn't embarrassing next to Obsidian's.** Documents got there (§93/§94); the note composer is deliberately behind, and §111.3's "text box or editor" question is still undecided.

**Wedges — where we can be 10x, and they'd have to rebuild to follow**

1. **Checkable answers.** Answer + the exact notes + the tool steps + how full the context window got, and `unsupported_claims` refusing to let the model claim a write it didn't do. A hosted assistant *cannot* show you your own corpus rows the way this does, and no local competitor has built the audit layer. **This is the moat; every feature below is asked "can the user check it?" first.**
2. **Tensions** (§104, built) — the notebook telling you where you contradicted yourself. Nobody ships this. It is the most under-marketed thing in the repo: it is not in the README's feature list at all.
3. **Spatial + temporal recall together** — graph (force/tree/radial/arc, typed links, trace paths) *and* a thread-banded timeline over the same corpus. §30/§32 already named this; it remains unclaimed ground.
4. **The offline studio.** NotebookLM's artefact menu, run entirely on CPU on your own machine, is a headline nobody else can write: "everything NotebookLM does to your documents, without uploading them."
5. **Works when the AI doesn't.** Saving a note never fails; search degrades to keywords; the status dot says what the AI is doing. Every cloud competitor is a blank page when the network is.

**Sources:** [AFFiNE, NotebookLM alternatives](https://affine.pro/blog/notebooklm-alternatives) · [Recall, best Obsidian alternatives](https://www.recall.it/compare/best-obsidian-alternatives) · [LocalAlternative, local PKM tools](https://www.localalternative.io/categories/note-taking) · [Vellum, best local AI assistants](https://www.vellum.ai/blog/best-local-ai-assistants) · [Khoj review](https://www.needaitool.com/tools/khoj-ai) · [Capacities vs Anytype](https://capacities.io/compare/anytype) · [NotebookLM review 2026](https://opentoolhq.com/notebooklm-review-2026/) · [DigitalOcean, what is NotebookLM](https://www.digitalocean.com/resources/articles/what-is-notebooklm)

---

### 114.2 Every existing feature, and what category-leading looks like

Effort: **S** ≤1 session · **M** 2–4 sessions · **L** a sprint or more.
Risk is *product* risk (will it be wrong/unloved), not build risk.

#### F1 — Capture and AI filing

*Today:* type a thought, the janitor files it into a category, tags it, links
it; guided mode lets you choose; `ai_first_filing` makes the round-trip a
choice; templates prefill the box. *Short of:* filing is a one-way verdict —
you see *which* category, but correcting it teaches nothing, and the composer
is a text box next to a four-view Documents editor.

*10x:* **capture that gets measurably better at your notebook**, where every
correction is a stored preference the filer reads next time, and the whole
thing still saves instantly with the model off.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Correction memory**: when you move a note out of the category the AI chose, store `(pattern → category)` and feed the last N corrections into the filing prompt as examples | Every competitor's auto-filing is stateless; "it learned from me" is the only auto-filing pitch users believe | M/Med | Local: % of captures kept as filed, shown in the health panel |
| 2 | **Inline chip suggestion while typing** (§102 item 9, unbuilt) — a category/tag chip appears under the box, opt-in, click to accept | Faster feedback than the audited batch job, without replacing its conservatism | S/Low | Bench: keystroke-to-filed time |
| 3 | **Always-visible backlink/connection strip** on the note card, replacing the ⋯ → Connections dialog for the common case (see 114.0b item 3) | "A connected notebook" is not connected if the connections are two clicks deep | S/Low | Bench: clicks-to-related-note (currently 2, target 0) |
| 4 | **Typed templates with structured fields** (§102 item 4 / §109.3 item 2) — a category-bound schema rendered as a form, stored as markdown skeleton + metadata | Granola ships 29 of these; Skills are saved *prompts*, which is a different thing | M/Med | Local: notes created from a template |
| 5 | **Capture anywhere**: tray hotkey → tiny always-on-top composer (§102 item 5); the tray already exists in `__main__.py` | Table stake 3; the cheapest half of "capture from where you already are" | S/Low | GH: appears in issues/feature asks as a *used* feature |

*Quick win (≤1 week):* #3, then #5.
*Signature interaction:* **"Filed as Ideas — because it looks like these three."** The filing chip names the three nearest existing notes it matched on, each clickable. Nobody else shows the *reason* for an auto-file, and the reason is already computed.

#### F2 — Chat and Agent mode

*Today:* saved resumable conversations, ~50 tools, visible tool timeline,
sources beside the answer, destructive actions confirmed, skills, the
hallucinated-write net. *Short of:* the answer text itself doesn't carry
per-claim citations (§102 item 6, unverified against a real model), and the
tool count is a standing liability (§34's "every new tool must displace one").

*10x:* **the only assistant whose every sentence can be clicked back to the
note that justifies it**, and which says "I don't know" when the notes don't
say.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Per-claim inline citations** — `[3]` markers in the answer text resolving to the retrieved note, hover to preview, click to jump | This *is* the moat, rendered. Hosted tools cannot do it over your private corpus | M/Med | Bench: % of answer sentences carrying a resolvable citation |
| 2 | **An "I don't know" bench** (§34's "what is missing that nobody asked for") — 30 questions with known answers + 10 with deliberately absent answers, run per model, published as a table | Turns "which model works here?" from folklore into the most useful page in the docs, and it is a *marketing asset* no competitor can publish about their own black box | M/Low | Bench: abstention rate on the 10 unanswerable |
| 3 | **Scope chips on the composer** — "these 4 notes / this document / this board" as visible pills (`note_ids` + `attached_notes_only` already exist server-side; §102 corrected the "no way to scope" claim, but it is not *visible*) | Source-scoping is NotebookLM's headline control; the backend is already there | S/Low | Local: scoped turns as a share of turns |
| 4 | **Answer → note in one click**, with the citation list preserved as real links, not pasted text | Closes capture→ask→capture; Kortex's synthesise loop without the cloud | S/Low | Local: notes created from answers |
| 5 | **Tool budget UI**: show "3 of 12 steps used" during an agent run with a stop button, and log the per-stage token cost already accounted for | Agents that run silently are the #1 trust failure in this category | S/Low | Local: agent runs cancelled vs completed |

*Quick win:* #3 and #4, both are UI over existing endpoints.
*Signature interaction:* **hover a sentence, the note that justifies it lights up in the sources rail** — and a sentence with no source gets a visible grey underline instead of silence.

#### F3 — Graph

*Today:* force/tree/radial/arc layouts, colour by category, typed links with
strength, focus mode, trace path (one BFS shortest path), keyboard layer,
documents in the graph, AI traversal via `graph_expansion()`. *Short of:*
§111.3's unanswered question — is the graph a picture or a retrieval index?
The two want opposite edge densities.

*10x:* **a map you navigate rather than admire** — the answer to "how did I
get from X to Y" and "what's near this that I've forgotten".

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Decide the question, then split the views**: a "Reading" mode (few, strong, typed edges) and an "AI" mode (dense, weighted) with one toggle, instead of one graph serving both badly | Resolves §111.3 by shipping both honestly rather than compromising | M/Med | Bench: edges rendered per node in each mode |
| 2 | **Multi-path trace, coloured and switchable** — already ROADMAP row 0c; cap N before building | "Show me *all* the ways these two ideas connect" is a question no competitor's graph answers | M/Med | Bench: paths returned, p95 latency at 10k notes |
| 3 | **Fix `?similarity=true`'s O(n²)** (30s at 2,000 notes, §34) — cap the comparison pool or add a nearest-neighbour index | The single most-recommendable toggle is currently unrecommendable | M/Low | Bench: `scripts/scale_test.py` |
| 4 | **Neighbourhood-to-draft**: select a cluster → "compose these into a draft" (§102 item 10, unbuilt; `expandNoteIntoDocument` only takes one note) | Kortex's Blogger, but from a spatial selection — a genuinely new gesture | M/Med | Local: drafts composed from selections |
| 5 | **Saved views** — a named, restorable filter+layout+focus ("Japan trip, radial, tag-coloured") | Makes the graph a workspace rather than a toy; also the answer to §104's sub-category ask | S/Low | Local: saved views per notebook |

*Quick win:* #5.
*Signature interaction:* **Trace, then "why"** — pick two notes, get every path, and each hop shows the *typed reason* the link exists. Obsidian shows you a hairball; this shows an argument.

#### F4 — Timeline

*Today:* grid and line views, banded by category/tag/thread, `days` filter,
thread bands via `parent_id`. *Short of:* it is a viewer, not a workspace —
nothing is *done* from the timeline, and the "very professional" complaint was
never made concrete.

*10x:* **the notebook's memory of itself** — the view you open to answer "what
was I thinking in March, and what came of it?"

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Period summary on demand**: brush a date range → an AI digest of that span, with the notes listed beside it | The weekly digest already exists on the Dashboard; this makes it arbitrary-range and *place*-bound | S/Low | Local: range digests generated |
| 2 | **Reminders and documents as lanes**, not just notes | The timeline is currently blind to half the notebook | S/Low | Bench: entity types rendered |
| 3 | **"What changed here"** — a thread lane with revision markers, so a note that was rewritten shows as a branch rather than a dot | Nobody in this space shows *note evolution* on a time axis | M/Med | Bench: revisions surfaced |
| 4 | **Drag a note along the axis** to correct its date (backdating an imported note) | Imports land everything on import day; this is the fix and it is a gesture, not a form | S/Med | GH: import complaints |
| 5 | **Gap detection** — visibly mark the weeks with nothing in them, with a one-click "what happened here?" prompt | Turns absence into a prompt to capture; the streak widget does this for today only | S/Low | Local: capture streak |

*Quick win:* #1.
*Signature interaction:* **brush-to-digest** — drag across two weeks and the app writes the paragraph you'd have written, with the notes beside it.

#### F5 — Library and the Documents editor

*Today:* everything in one grid (notes, docs, chats, files, tags, bin, log)
plus Links (bookmarks), Contents (hyperlinked outline) and Skills; a four-view
document editor with autosave, outline, find/replace, backlinks, AI edit,
extract-to-notes, md/PDF export, syntax highlighting, `/` menu, collapsible
blocks. *Short of:* the note composer and the document editor are two
different products with two markdown dialects (§111.1's three-grammar
problem), and highlights are characters in a body nobody can query.

*10x:* **one editing surface with two densities**, and a library that answers
"where did this come from" for every row.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **One markdown grammar module** consumed by `MD_ACTIONS`, `INLINE_MD` and editor.js's `/` menu | §110's Red/Grey bug lived exactly in the gap; this is the class-of-bug fix | M/Low | Bench: `tests/test_highlight_colours.py` + one new grammar test |
| 2 | **Highlights as a queryable collection** (§111.2 item 3) — `==marks==` are already in `content`, so this is an index + a view, not a schema | The honest version of Kortex's clippings library, without a second collection type | S/Low | Local: highlight searches run |
| 3 | **Notion importer** (HTML+CSV dialect) + a first-run "import your vault" offer | Table stake 1, the biggest adoption blocker on file | M/Med | GH: downloads → issues mentioning import |
| 4 | **Source provenance on every row** — imported-from-file, clipped-from-URL, extracted-from-document, transcribed-from-audio, all as one visible chip | "Where did this come from" is the question a big library makes urgent, and the data mostly exists already | S/Low | Bench: rows with provenance |
| 5 | **Virtualise the notes list** (§111.1 — 75k DOM nodes rebuilt per keystroke) | The biggest frontend scalability item on file, and invisible until it isn't | M/Low | Bench: render time at 10k/50k notes |

*Quick win:* #2.
*Signature interaction:* **`==highlight==` anywhere becomes a row in "Highlights"**, with the note, the source chip and the date — one syntax, two homes, no new object type.

#### F6 — Reminders

*Today:* natural-language scheduling, priority, repeats, snooze, calendar
view, linked back to the source note. *Short of:* it is a to-do list that
happens to sit next to a knowledge base; nothing connects "what I promised" to
"what I know".

*10x:* **commitments extracted from what you already wrote**, not typed twice.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Commitment detection**: the librarian flags "I said I'd send X by Friday" and *offers* a reminder (offer, never create — same gate as every other autonomous job) | This is the reason to keep a notebook and a task list in one app; Granola does it for meetings only, in the cloud | M/Med | Local: offers accepted / offered |
| 2 | **Reminder → note thread**: completing a reminder prompts one line of outcome, appended to the source note | Closes the loop that makes the notebook a record rather than a queue | S/Low | Local: reminders completed with an outcome |
| 3 | **Meeting-prep brief**: a reminder mentioning a person/topic pulls the last N related notes into a briefing card at fire time | The killer combo with Voice (see 114.4 combo 2) | M/Med | Local: briefs opened |
| 4 | **ICS export** (read-only, one file, no account) | "Genuinely yours" applied to dates; zero network | S/Low | GH: asked-for-ness |
| 5 | **Overdue triage view** — group by "still matters / drop / reschedule" with a bulk action | Every task app has this; ours is missing and it's cheap | S/Low | Local: overdue count trend |

*Quick win:* #2.
*Signature interaction:* **the reminder that knows why it exists** — every fired reminder shows the sentence in the note that created it.

#### F7 — Dashboard

*Today:* streak, stats, weekly AI digest, on-this-day, quick capture,
rearrangeable widgets. *Short of:* it reports activity, not understanding.

*10x:* **the page that tells you something you didn't know about your own
notebook**, once a day, cheaply.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Tensions widget** — surface §104's contradiction finder on the Dashboard (it is built and effectively hidden) | The most differentiated thing in the app is currently undiscoverable; this is pure marketing-by-UI | S/Low | Local: tensions reviewed |
| 2 | **"Notebook health"** — orphan notes, untagged notes, stale threads, duplicate candidates, index freshness, each with a one-click fix | Doubles as the app's only honest instrumentation (see 114.5) | M/Low | Local: it *is* the metric |
| 3 | **A question of the day** drawn from the corpus ("You wrote about X three times in June and never since — still live?") | Retrieval as a prompt to return; the only defensible retention loop for an offline app | M/Med | Local: D7 return proxy (days-with-a-capture) |
| 4 | **Digest → document** in one click, with sources | The weekly digest is currently disposable | S/Low | Local: digests kept |
| 5 | **Widget for "what the AI did while you were away"** — the librarian's audit log, summarised | Ties the automation to the audit trail rather than hiding it | S/Low | Local: audit log opens |

*Quick win:* #1 — it is a widget over an existing endpoint.
*Signature interaction:* **"You disagreed with yourself"** as a dashboard card, with both notes side by side and a "reconcile into one note" button.

#### F8 — Whiteboard

*Today:* pannable canvas, sketches, shapes, note cards, mind-mapping mode,
anchors/connectors, alignment guides, lasso, grouping, undo/redo, export.
*Short of:* ROADMAP row 0 — panels clash with each other and the canvas, and
the Pan tool needs a manual switch to select. Also §34's warning: this is a
separate product wearing this one's clothes.

*10x:* **the canvas is where a cluster of notes becomes a structure**, not a
second drawing app.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **The panel/tool redesign + pan-click-to-select** (ROADMAP row 0, already top priority by instruction) | It is the reported blocker; nothing else on this list matters until it lands | M/Low | Bench: panel overlap = 0 at 1280×720 and 1024×640 |
| 2 | **Board ⇄ graph round-trip**: drop a graph neighbourhood onto a board, and connectors drawn on the board become real typed links | Makes the whiteboard part of the notebook instead of adjacent to it — the one thing that answers §34's "separate product" objection | L/Med | Bench: links created from boards |
| 3 | **Board → outline → document**, one click | The synthesis path competitors charge for | M/Med | Local: documents from boards |
| 4 | **Templates** (2×2, timeline, decision tree, retro) | Cheap, and it is what makes a blank canvas usable | S/Low | Local: boards started from a template |
| 5 | **Board as a chat scope** — "answer using only what's on this board" | Reuses the F2-3 scope chips; spatially-scoped retrieval is genuinely novel | S/Med | Local: board-scoped turns |

*Quick win:* #4.
*Signature interaction:* **draw an arrow between two cards and the notebook gains a typed link** — the drawing *is* the data entry.

#### F9 — Voice, vision and OCR

*Today:* local Whisper dictation, meeting transcription, image captions,
vision-model transcription, Tesseract OCR, the OCR workspace with per-page
PDF reads, all editable and searchable. *Short of:* no speaker separation
(`grep -i speaker src` is empty), no two-stream meeting capture, no local TTS
at all (read-aloud is the browser's `speechSynthesis`, which cannot be saved
to a file — ROADMAP §88.2 item 7 scoped this and recommended Piper).

*10x:* **anything you can hear or see becomes a checkable note, offline** —
the demo that sells the whole app in 40 seconds.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Rough bullets + transcript merge** (§102 item 1 / §109.3 item 4) — type during the recording, merge after | Granola's entire core loop, run locally, with the transcript kept beside the merge so it is checkable | M/Med | Local: merged notes / recordings |
| 2 | **Structured meeting block** (decisions / actions / owners / dates) extracted once after transcription (§102 item 2) | Feeds F6-1 commitment detection directly | S/Med | Local: actions promoted to reminders |
| 3 | **Speaker separation** (§102 item 8, genuinely absent), nameless first, renameable second | Flat transcripts are the reason people don't reread them | M/Med | Bench: turns segmented |
| 4 | **Local TTS via Piper** as a `core/extras.py` package, evaluated exactly like Tesseract was | Unblocks the audio overview (invention B1) and makes read-aloud saveable | M/Med | Local: audio artefacts generated |
| 5 | **Camera/screenshot capture straight into OCR** from the tray composer | The whiteboard-photo-to-notes path, which is the most-demoed feature in this whole category | M/Low | Local: OCR captures |

*Quick win:* #2.
*Signature interaction:* **the transcript stays**. Every merged note has "show the raw transcript" beside it, so a summary is never the only copy — the checkability principle applied to audio.

#### F10 — Search

*Today:* keyword, opt-in semantic (falls back cleanly), `tag:` and friends,
opt-in web search via SearXNG. *Short of:* semantic is off by default because
it needs a package; there is no hybrid ranking; nothing explains *why* a
result ranked.

*10x:* **one box that finds it whether you remember the words, the meaning,
the picture or the week.**

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Hybrid ranking** (BM25-ish keyword + vector, reciprocal-rank fusion) instead of either/or | The measurable quality jump; both signals already exist | M/Med | Bench: recall@10 on a fixture query set |
| 2 | **"Why this result"** chip — matched term, similar meaning, same thread, linked to a match | Nobody in PKM explains ranking; it is the search-shaped version of the moat | S/Low | Bench: results carrying a reason |
| 3 | **Time and type facets in the same box** (`before:`, `after:`, `is:image`, `has:highlight`) | Cheap power-user surface; the parser already handles shortcuts | S/Low | Local: facet queries |
| 4 | **Search inside a board / a document / a thread**, sharing the scope-chip UI from F2-3 | One control, four places | S/Low | Local: scoped searches |
| 5 | **A "nothing found — here's what's near" fallback** using embeddings | Empty states are where trust dies | S/Low | Bench: empty-result rate |

*Quick win:* #2.
*Signature interaction:* every result carries **the reason it is there**, and reasons are clickable filters.

#### F11 — Privacy, local models and packaging

*Today:* any OpenAI-compatible backend, per-model sampling read from the GGUF,
private notes encrypted with a password-derived key, localhost binding, daily
backups with retention, Windows/Linux packages, Extras installer. *Short of:*
macOS packaging absent; `faster-whisper` install failures still undiagnosed
(ROADMAP 10a); the crypto has never had a second pair of eyes (§34).

*10x:* **the install is the pitch** — one download, a model included or
one-click fetched, notes on screen in under five minutes.

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **A "no model? pick one" first-run step** that downloads a small GGUF through the app and starts the built-in runner | Every competitor's local-AI story starts with "first install Ollama" — removing that step is the biggest single funnel win available | L/Med | GH: downloads → issues about "no AI" |
| 2 | **A privacy receipt page** — every outbound-capable code path, its current state, and the last time it fired, generated from the code rather than written by hand | "No telemetry" is a claim; this makes it an artefact, and it is un-copyable by anyone with a server | M/Low | GH: cited in reviews/comparisons |
| 3 | **External crypto review** of the private-note path (§34's third missing thing) | The one place being wrong is silent and unrecoverable | S/Low (cost: attention) | — |
| 4 | **macOS packaging** (ROADMAP item 10) | A third of this audience is on macOS | M/Med | GH: downloads by platform |
| 5 | **Diagnose 10a properly** — one run on the failing machine, Logs page, paste the output | Two sessions have guessed; guessing is the expensive path | S/Low | GH: issue closed |

*Quick win:* #5 (it needs a person, not a patch).
*Signature interaction:* **the network ledger** — a page that says "nothing has left this machine, here is every door and whether it is shut."

#### F12 — Onboarding and in-app help

*Today:* guided first-run tour, seeded example notes (`seed_example_notes`),
26-topic help with quick-links, an "Ask the guide" AI chat that never sees
your notes. *Short of:* the first run still assumes a model exists somewhere,
and there is no import offer at the point of maximum intent.

*10x:* **from download to a graph with your own notes in it, in one sitting,
without a terminal.**

| # | Change | Why it wins | E/R | Metric |
| --- | --- | --- | --- | --- |
| 1 | **Import as step 2 of onboarding** (folder of markdown → dry-run preview → import) | Table stake 1 delivered at the only moment people will do it | M/Low | GH: proxy via import-related issues |
| 2 | **A 60-second "watch it file three notes" demo** running against the seeded set, no model required | Shows the loop before the user has done any work | S/Low | Bench: usability sessions |
| 3 | **Progressive disclosure of the seven tabs** — start with Capture/Ask, unlock the rest with a visible "show me everything" | §R7.5's pane complaint is partly a first-run overwhelm problem | M/Med | Bench: 5-person session task success |
| 4 | **A "what can I ask?" chip row** on the empty chat, generated from the user's own categories | The blank prompt box is where local-AI apps lose people | S/Low | Local: chip-started turns |
| 5 | **Help chat cites the doc section** it answered from, with a jump link | Checkability, applied to the guide itself | S/Low | Bench: answers with a citation |

*Quick win:* #4.
*Signature interaction:* **the tour files a note in front of you** and then shows the graph redraw — one screen that demonstrates the whole product.

---

### 114.3 New inventions

18 ideas. Each: pitch · problem · why novel · loop · E/R · a ≤2-week first
experiment. Nothing here duplicates something already built (checked against
HISTORY.md and the code, per 114.0b).

#### Category A — obvious gaps competitors missed (high value, medium effort)

**A1. Recall practice (spaced repetition over your own notes).**
*Pitch:* the notebook quizzes you on what you saved, generating questions from
your own notes. *Problem:* you write things down and never read them again;
"second brain" apps are write-only. *Novel:* NotebookLM ships quizzes over a
temporary source set; Anki is a separate app you must author cards for. Nobody
generates cards from a living personal corpus *and* schedules them locally. A
competitor copying this needs local generation + a scheduler + your corpus.
*Loop:* a daily 3-minute review is the strongest return-hook known in this
category. *E/R:* M/Med. *Experiment:* generate 10 cards from 10 real notes with
the local model, hand-rate them for usefulness; if <6/10 are good, the
generation prompt is the project, not the scheduler.

**A2. Highlights as a first-class collection.** *Pitch:* every `==highlight==`
becomes a browsable, source-attributed quote shelf. *Problem:* the interesting
sentence is buried in a long note. *Novel:* Readwise's product, minus the
cloud and the subscription, over your *own* writing as well as clippings.
*Loop:* a "highlight of the day" resurfaces old thinking. *E/R:* S/Low.
*Experiment:* ship the view behind a flag, count searches against it in a week
of real use.

**A3. Web clipper without a browser extension.** *Pitch:* a bookmarklet plus
`read_url` turns the current page into a source-attributed note with the
selection quoted. *Problem:* capture-from-where-you-are is table stakes and
absent. *Novel:* everyone ships an extension (a store account, review, two
stores); a bookmarklet posting to `localhost` needs no store and works
offline. *Loop:* daily capture from reading. *E/R:* S/Med (CSRF/same-origin is
the real work). *Experiment:* a one-file bookmarklet against the running app;
measure how many pages clip cleanly out of 20.

**A4. Notebook diff — "what changed while I wasn't looking."** *Pitch:* a
since-you-were-last-here view: new notes, links the librarian added, tags
changed, tensions found. *Problem:* the autonomous librarian acts silently;
trust needs visibility. *Novel:* no competitor's auto-organiser shows a diff,
because most of them don't think you should care. *Loop:* the reason to open
the app in the morning. *E/R:* M/Low (the audit log exists). *Experiment:*
render one week of the existing audit log as a diff; is it interesting or
noise?

**A5. Person and project pages, derived not declared.** *Pitch:* entities the
extractor already finds get an auto-page — every mention, every commitment,
every open reminder. *Problem:* "what do I know about Sam?" needs a search and
a memory. *Novel:* Capacities charges for object pages you must *create*;
these are derived from text with zero user effort, and every fact links back.
*Loop:* before every meeting. *E/R:* M/Med (`ai/entities.py` exists).
*Experiment:* generate pages for the 5 most-mentioned entities in a real
notebook and ask "is this the page you'd have written?"

**A6. Print/share a notebook slice.** *Pitch:* pick a tag, a thread or a date
range → a clean PDF/HTML with a table of contents and the graph as a figure.
*Problem:* "genuinely yours" stops at export-everything; there is no "send
this to someone". *Novel:* offline, no share link, no account — a file.
*Loop:* weekly review, handing work over. *E/R:* M/Low (single-item export and
PDF already exist). *Experiment:* export one real tag and see whether it reads
as a document or a dump.

#### Category B — AI-native superpowers

**B1. The offline studio: audio overview, mind map, quiz, one-pager.**
*Pitch:* NotebookLM's Studio panel, on your machine, over your own notes.
*Problem:* the most-copied AI-notebook feature set is cloud-only. *Novel:* a
competitor would need local TTS, local generation, and a corpus that never
leaves — the whole point. *Loop:* commute listening; revision. *E/R:* L/Med;
gated on Piper (ROADMAP §88.2 item 7 already recommends it). *Experiment:*
Piper-generate a 3-minute overview of 10 notes on CPU; measure wall-clock and
listen once. If a 3-minute clip takes 10 minutes to render, the feature is a
background job, not a button — decide that before building the UI.

**B2. Contradiction watch, live.** *Pitch:* Tensions (built) promoted from a
finder to a *watcher* — saving a note that contradicts an existing one flags
it at capture time. *Problem:* you re-decide things you already decided.
*Novel:* nobody ships contradiction detection at all; doing it at write time
is the version that changes behaviour. *Loop:* it earns attention every time
it is right. *E/R:* M/Med. *Experiment:* run the existing tension prompt
against the last 200 notes pairwise-capped; count true positives by hand.

**B3. Ask the notebook a question it can't answer, and get a research plan.**
*Pitch:* when retrieval finds nothing, the app proposes what to capture or
read next rather than hallucinating. *Problem:* the empty answer is the worst
moment in every RAG product. *Novel:* it converts the failure mode into the
capture loop. *Loop:* the app tells you what to feed it. *E/R:* S/Med.
*Experiment:* 10 deliberately unanswerable questions; is the plan better than
"I don't know"?

**B4. Rewrite-with-your-own-voice.** *Pitch:* drafting uses your past notes as
the style exemplar, not a generic assistant voice. *Problem:* AI drafts read
like AI. *Novel:* the corpus needed is private and local; a cloud tool would
have to hold your writing to do it. *Loop:* every draft. *E/R:* M/Med.
*Experiment:* blind A/B of 5 drafts with and without exemplars; can you tell?

**B5. Agentic weekly review.** *Pitch:* one scheduled agent run that files
strays, proposes merges for duplicates, closes stale threads, and produces a
reviewable **plan** — every action confirmable, nothing applied silently.
*Problem:* housekeeping never happens. *Novel:* the audit-and-confirm shape is
this app's existing discipline applied to a bigger job; competitors' auto-tidy
is invisible. *Loop:* Sunday. *E/R:* M/Med (`autonomous.py` + `make_plan`
exist). *Experiment:* generate the plan, apply none of it, count how many
proposals you'd accept.

**B6. Trigger → action rules** (ROADMAP §88.2 item 8, honestly sized there as
a new subsystem). *Pitch:* "when a note is filed as Health, add tag `body` and
remind me in 30 days." *Novel:* local automation with no Zapier and no cloud.
*Loop:* set once, benefit forever. *E/R:* L/Med. *Experiment:* hard-code two
rules for a week before building the rules UI — if you don't miss them, don't
build it.

**B7. Your numbers, on your machine.** *Pitch:* the instrumentation panel from
114.5, shipped as a user feature: capture cadence, answer-with-source rate,
which model you actually use, filing corrections. *Problem:* the author has no
metrics and users have no self-knowledge. *Novel:* every competitor's
analytics serve *them*; this one serves only you and never transmits. *Loop:*
monthly self-review. *E/R:* M/Low. *Experiment:* ship it locally, read it for
two weeks, see which number you'd act on.

#### Category C — moonshots (12–24 month defensibility)

**C1. Notebook-to-notebook exchange, no server.** A signed, encrypted
`.mmpack` of a *slice* (notes + links + attachments + provenance) that another
MemoryMap imports as a linked, attributed sub-graph. Not sync — no server, no
account, no conflict resolution. Defensible because the format plus the
attribution model is a standard others would have to adopt; AGPL keeps it
open. E/R: L/High. *Experiment:* export/import a 20-note slice round-trip and
diff.

**C2. The local model leaderboard for *this* task.** F2-2's honesty bench,
generalised: a reproducible suite anyone can run against their own hardware,
publishing filing accuracy, abstention rate, tool-call correctness and tokens
per answer per model. Becomes the page the local-LLM community links to — a
distribution loop no feature can buy. E/R: L/Med. *Experiment:* run three
models on 30 questions and publish the table.

**C3. Ambient capture with consent.** Opt-in, local-only watchers (a screenshot
folder, a downloads folder, a voice memo folder) that OCR/transcribe/file and
*always* show what they took. `passive_capture.py` exists as a starting point.
Defensible because everyone else needs a cloud pipeline; risky because it is
the one feature that could break the privacy promise if done sloppily. E/R:
L/High. *Experiment:* one folder watcher, dry-run only, for a week.

**C4. The reasoning archive.** Every answer, its sources, its tool steps and
its context-window stats retained as a queryable object, so "why did I believe
that in March?" is answerable. Turns the audit trail into a second corpus.
E/R: L/Med. *Experiment:* keep 50 answers with full provenance; ask three
retrospective questions of the archive.

**C5. Teach mode.** The notebook builds a curriculum out of your own corpus —
what you know, what you have half-written, what you keep contradicting — and
runs you through it with A1's cards and B1's audio. This is the version of
"second brain" that changes what is in the *first* one. E/R: L/High.
*Experiment:* hand-build one curriculum from a real notebook and run it for a
week.

---

### 114.4 Prioritisation

**Score = (Impact 1–5 × Confidence 0.5–1.0) ÷ Effort (S=1, M=2, L=4).** Reach
is deliberately omitted: with no telemetry there is no honest reach number, and
faking one is how a roadmap starts lying. Top of the ranked list:

| Item | I | C | E | Score |
| --- | --: | --: | --: | --: |
| F8-1 whiteboard panel redesign + pan-click-select (already row 0) | 4 | 1.0 | 2 | 2.00 |
| F7-1 Tensions on the Dashboard | 4 | 1.0 | 1 | 4.00 |
| F2-3 scope chips (backend exists) | 4 | 0.9 | 1 | 3.60 |
| F2-4 answer → note with citations | 4 | 0.9 | 1 | 3.60 |
| F10-2 "why this result" | 4 | 0.9 | 1 | 3.60 |
| F1-3 always-visible connections strip | 4 | 0.85 | 1 | 3.40 |
| A2 highlights collection | 4 | 0.85 | 1 | 3.40 |
| F12-4 "what can I ask?" chips | 3 | 1.0 | 1 | 3.00 |
| F4-1 brush-to-digest | 3 | 0.9 | 1 | 2.70 |
| F2-1 per-claim citations | 5 | 0.8 | 2 | 2.00 |
| F5-3 Notion importer + first-run offer | 5 | 0.8 | 2 | 2.00 |
| F11-1 model-included first run | 5 | 0.6 | 4 | 0.75 |
| F2-2 the "I don't know" bench | 4 | 0.9 | 2 | 1.80 |
| A1 recall practice | 4 | 0.7 | 2 | 1.40 |
| F9-1 bullets + transcript merge | 4 | 0.7 | 2 | 1.40 |
| B1 offline studio | 5 | 0.5 | 4 | 0.63 |
| F3-3 fix `?similarity=true` O(n²) | 3 | 1.0 | 2 | 1.50 |
| F5-5 virtualise the notes list | 3 | 0.9 | 2 | 1.35 |
| B2 live contradiction watch | 4 | 0.6 | 2 | 1.20 |
| A5 derived person/project pages | 4 | 0.6 | 2 | 1.20 |

**90-day roadmap**

*Phase 1 — Now (weeks 1–4): make the moat visible.* Everything here is UI over
machinery that already exists, so it ships fast and it is all evidence for the
positioning.
1. F8-1 whiteboard panels + pan-click-select (**the standing top priority; nothing else jumps it**)
2. F7-1 Tensions widget · 3. F2-3 scope chips · 4. F2-4 answer → note
5. F10-2 "why this result" · 6. F1-3 connections strip · 7. A2 highlights
8. F12-4 empty-chat chips
*Outcome:* a first-time user meets three differentiated things (checkable
answers, contradiction detection, explained ranking) in the first session
instead of never.

*Phase 2 — Next (weeks 5–9): close the two table stakes that block adoption.*
1. F2-1 per-claim inline citations · 2. F5-3 Notion importer + F12-1 first-run
import · 3. F2-2 the "I don't know" bench, published in docs/MODELS.md
4. F3-3 similarity O(n²) · 5. F5-5 notes-list virtualisation
6. F9-2 structured meeting block · 7. F1-1 correction memory
*Outcome:* someone with a 3,000-note Obsidian vault can move in, and the
answer they get is checkable sentence by sentence.

*Phase 3 — Later (weeks 10–13): one headline, one loop.*
1. B1 offline studio, starting with Piper + audio overview (F9-4 first)
2. A1 recall practice · 3. F9-1 bullets+transcript merge · 4. A4 notebook diff
5. F11-1 model-included first run (spike only — size it before committing)
6. A5 derived person/project pages
*Outcome:* one thing to put at the top of the README that no competitor can
match, plus the first genuine return-loop the app has ever had.

**Three killer combos**

1. **"Checkable" end-to-end** = per-claim citations (F2-1) + why-this-result
   (F10-2) + the "I don't know" bench (F2-2) + the privacy receipt (F11-2).
   The claim stops being marketing and becomes four artefacts. *No hosted
   competitor can ship any of the four over your private corpus.*
2. **The meeting loop** = bullets+transcript merge (F9-1) + structured meeting
   block (F9-2) + commitment detection (F6-1) + meeting-prep brief (F6-3).
   Granola's entire product, offline, with the transcript kept beside the
   summary so it stays checkable.
3. **The offline studio** = Piper TTS (F9-4) + audio overview + mind map from
   the existing whiteboard + recall cards (A1). The one-line pitch:
   *everything NotebookLM does to your documents, without uploading them.*

---

### 114.5 Risk, moat, and how to measure anything without telemetry

**Top five ideas, their real risks, and the de-risking step**

| Idea | Biggest risk | De-risk |
| --- | --- | --- |
| F2-1 per-claim citations | The local model won't emit reliable markers, and a wrong citation is worse than none | Post-hoc attribution instead of asking the model to cite: match each sentence back to retrieved chunks by embedding similarity, show a marker only above a threshold, grey-underline the rest. Test on 20 real answers before building UI |
| F5-3 Notion importer | Notion's export dialect drifts and imports are destructive-feeling | Dry-run preview + an import that is one undoable batch (the audit log already models this); test against two real exports, not a synthetic one |
| B1 offline studio | Piper is a new dependency, and this project has been burned by heavy installs (torch, sentence-transformers) | Ship it as a `core/extras.py` package exactly like Tesseract; feature stays fully absent, never broken, when not installed. Measure CPU wall-clock *first* (see B1's experiment) |
| A1 recall practice | Auto-generated cards may be bad enough to be insulting | Hand-rate 10 before building the scheduler; ship "edit this card" from day one |
| F11-1 model-included first run | Licence and size (a GGUF in the installer), plus support burden across three platforms | Don't bundle — *fetch* on first run with a visible size and a skip button; check each candidate model's licence against AGPL redistribution before it appears in the picker |

**Moats, ranked by how hard they are to copy**

1. **Verifiability as an architecture, not a feature.** Sources, tool steps,
   context accounting, `unsupported_claims`, the audit log, the privacy
   receipt. A cloud competitor cannot show you rows it doesn't hold; a local
   competitor would have to build all six. *Deepen it deliberately: every new
   AI feature ships with visible reasoning, an undo and a log, or it doesn't
   ship.*
2. **Workflow lock-in through structure you'd lose.** Typed links, threads,
   boards, saved views, provenance chips. Export keeps the promise ("genuinely
   yours") while the *structure* is what makes leaving unattractive — which is
   the only ethical version of lock-in, and it needs C1's export format to
   stay honest.
3. **Community authority via the benchmark (C2).** Publishing "which local
   model is actually good at this, measured" makes the repo the reference page
   for a whole community, and reference pages compound. This is the only
   growth loop available to an app with no accounts, no sharing and no
   telemetry — and it costs a weekend, not a quarter.

**Metrics, defined honestly**

*The rule: nothing is transmitted, ever. Any number the author sees is either
public GitHub data or something a user chose to send in an issue.*

| Phase | GH (observable) | Local (user-visible only) | Bench (run by hand) |
| --- | --- | --- | --- |
| Now | Issue *mix* shifting from "how do I" to "can it also" | Notebook health panel exists; tensions reviewed | 5-person session: can they get a cited answer in 10 min? |
| Next | Release downloads ÷ install-failure issues; import-related issues trending down | Days-with-a-capture; scoped-turn share | Recall@10 on a fixture query set; render time at 10k notes |
| Later | Star/fork velocity after the benchmark page; external PRs | Cards reviewed per week; audio artefacts made | Piper wall-clock per minute of audio; abstention rate per model |

**Time-to-value is the one number worth obsessing over**, and it is
measurable without telemetry: *download → first cited answer over your own
notes*, timed by hand with five people. Today that path includes "install
Ollama, pull a model" — which is why F11-1 scores as the highest-impact
lowest-confidence item on the board.

---

### 114.6 Start tomorrow — the five highest-leverage actions

1. **Finish the whiteboard panel redesign + pan-click-to-select** (ROADMAP row
   0). It is the standing top priority by direct instruction and it is the one
   reported blocker; nothing on this list jumps it.
2. **Ship the Tensions dashboard widget and put Tensions in the README's
   feature list.** The most differentiated thing in the app is invisible in
   the UI *and* absent from the pitch. One widget, one paragraph, one session.
3. **Strike the three stale items in 114.0b** from §111.2 so the next session
   doesn't schedule work that is already done — the fourth, fifth and sixth
   "already built" catches this project has now recorded.
4. **Build the "I don't know" bench** (40 questions, 30 answerable, 10 not) and
   run it against two models. It is a test fixture, a docs page, a model
   picker and a marketing asset in one, and it is the first honest quality
   number this project would have.
5. **Spike Piper for 90 minutes** — install it in a venv, generate 60 seconds
   of speech on CPU, record the wall-clock. That single number decides whether
   the offline studio (the strongest headline available) is a Phase-3 feature
   or a nice idea, and no amount of further reading answers it.


### §114 addendum — after the whiteboard / documents / search sprint

The strategy prompt was re-sent verbatim after this sprint; the teardown,
per-feature upgrades, inventions, RICE scores, 90-day plan, moats and
metrics above still stand, so this is the delta, not a rewrite.

**What moved from "Now" to shipped (PR #142):** the whiteboard's chrome is
a top bar + centred dock + drawer (no draggable panels), connectors attach
to everything and follow rotation, wheel-pan/pinch-zoom, templates and
table navigation in Documents, typo-tolerant keyword search, the Files rows
and OCR reader defects, the notifications panel. See HANDOVER.md.

**What this changes in the ranking.** Two wedges got cheaper and should
move up a phase:

1. *AI on the board* (§114's category-B item; PLAN W11) — now that every
   item is a first-class link endpoint and the drawer is a stable surface,
   "summarise this cluster / explain this link / turn these stickies into
   a note" is a drawer group and three agent tools, not a redesign.
2. *Backlinks and unlinked mentions everywhere* (PLAN S7) — the FTS
   vocabulary table exists now, so "notes that mention this title without
   linking" is one `MATCH` per panel open.

One item should move down: *frames* (PLAN W4). Group-move exists through
multi-select; a frame's remaining value is export-by-frame and titling,
which templates on the Documents side now cover for the assignment
use-case the user named.

**Start tomorrow (revised):**
1. Floating selection toolbar on the whiteboard (align, distribute, colour,
   delete) — the one thing every app the user named has that this does not.
2. Split `run_agent` (complexity 45) before adding board tools to it.
3. Unlinked mentions on the note and document panels (S7).
4. Undo across Live↔Source in Documents (D3) — the last "feels fake" seam.
5. Run the OCR readers, translation and Tensions against a real model and
   record the hit rates (task #120).

### §114 addendum, two external write-ups folded in and removed

`docs/memorymap-ai-expansion-gemini.docx` and
`docs/memorymap-ai-expansion-perplexity.md` were chat transcripts asking
Gemini and Perplexity to analyse this repository and suggest what it is
missing. Read in full and checked against the running code, per this
section's own rule, before deciding what survives.

**Most of both does not survive.** Neither model could actually fetch the
repository (both say so in their own text: GitHub's crawler block, and a
raw.githubusercontent.com permission error), so most of it reasons from a
generic "local-first AI notebook" premise rather than this one. The
Perplexity file and Gemini's first pass invent an architecture this app
does not have (LlamaIndex, ChromaDB, a "Ghost Sidebar" UI, a "cinematic
sci-fi" theme with "neural constellation" visuals, bundled models needing
no Ollama), and Gemini's second pass, after reading the live landing page,
gets the shape right but still cites "28 distinct tools" for the agent,
which was already wrong when written and is 58 now (§7 of
ARCHITECTURE.md). Several of the "missing" features in both files are
already built and just not what the model expected to find: encryption at
rest for private notes, daily local backups, image and audio ingestion
through the OCR/vision pipeline, full Markdown/CSV export, and the
context-window budgeting ARCHITECTURE.md §7 already documents at length.

**What is real and not already decided:** nothing, on inspection. The one
concrete, specific, buildable idea in either file, a local browser clipper
extension, is already recorded, credited to Gemini by name, in
BACKLOG.md §29. Cross-device sync (Gemini's second pass) is the
single most-discussed deferred decision in BACKLOG.md (§"A second
device", §29's sync note, and the "Sync / multi-device" entries later in
that file), not a gap anyone missed. The "serendipity engine" idea
(proactively surfacing links between notes nobody looked at) is
substantially what the background librarian and the graph's own link
suggestions already do. A "project bundle" exporter overlaps enough with
the Trace panel's "generate story from path" (six shapes, already built)
that it is not a new item so much as a request to widen that feature from
a path to an arbitrary tag or cluster, which is a BACKLOG line worth one
day, not a new subsystem: see BACKLOG.md's Graph section for where that
would land if picked up.

Both source files are deleted with this commit; nothing in them was left
unrecorded.
