# CHAT batch B (Opus): INBOX 39 and 40

Branch `claude/epic-ramanujan-8xocc0`, worktree `agent-aaf982b12113f9499`,
server on :8871 with data in `/tmp/mm-chat-b`, stand-in model server on
:8879 (`scratchpad/ui-sweeps/fake.sh`, new).

## Done

- **INBOX 39** (commit "The chat mode is called Agent, and a skill switches
  to it"). The mode segment, its tooltip and accessible name, the per-turn
  chip on a message meta line, the progress musing, the nudge action, the
  Plan-mode toast and the plan docs all say "Agent" now; `tools_enabled` and
  `use_tools` are untouched. `startSkill` switches the mode to Agent before
  it sends, toasts "Switched to Agent for this skill." and leaves it
  switched.
- **INBOX 40** (commit "Citations land on the answer a run actually ends
  with"). Three causes, all measured, any one of which alone left a skill run
  uncited:
  1. `addInlineCitations` was handed the *first* `.bubble-answer` by
     `querySelector`, and a run's prose is one block per step, so the walker
     hunted the final answer's sentences in step one's narration. It takes
     every block of the turn now, latest first; three call sites pass all of
     them and `test_inline_citations.py` fails any that narrows back.
  2. `routes_chat.py` concatenated the answer deltas of every round with no
     separator, gluing the last sentence of one round to the first of the
     next; `split_sentences` cannot split that, so the grounding row named
     text that exists in no paragraph on screen. It now breaks paragraphs
     where the transcript does (`tests/test_grounding.py`, and the new test
     fails without the fix).
  3. `liveMarkdownRenderer` arms a paint up to `LIVE_RENDER_INTERVAL_MS`
     ahead. On a fast run it fired after `finalise()` and after the markers
     went in, repainting identical prose without them, which is why this read
     as "citations do not work" rather than as a race. `finalise` (and
     `replaceAnswer`) cancel it first.
  Plus the badges: `setNoteLabel`/`plainText`/`flattenNoteMarkdown` render a
  badge's Markdown instead of printing it, on the grounding chips, the
  "elsewhere" chips and the touched ("viewed") badges.
  Sweeps: `phasec.js` (extended, prints an "INBOX 40" pass/fail),
  `citeunit.js` (the placement rule in isolation), `citeskill.js` (an
  instrumented skill run: what each `addInlineCitations` call was handed, and
  a three-second trace of whether the markers survive), `fake.sh` (starts the
  stand-in model server the way `serve.sh` starts the app).

## Done (INBOX batch C, 2026-09-08)

Items 1-3 below, from this file's own "Left" list, are done:

1. **One Markdown stripper, confirmed rather than assumed.** `plainText` had
   exactly one caller (`setNoteLabel`) and `stripMarkdownPreview` had no
   duplicate from batch A's merge -- grepped, not guessed. The popup agent's
   `cmdPaletteResultRow`/`cmdPaletteTouchedRow` chips now route through
   `setNoteLabel` instead of `noteLabel` + `setLabel`, which only ever
   flattened.
2. **A truncated badge renders Markdown up to a generous margin now, and
   ellipses in CSS past it.** `setNoteLabel` used to fall back to flattened
   text whenever the label passed `length` plain characters (30 for the
   grounding chip, so any note opening over 30 characters showed its own
   `**asterisks**`); it renders up to `length * 4` now and only the
   genuinely pathological case still falls back to a plain character cut.
   `.result-reason-chip` carries a measured `max-width: 22rem` (the same cap
   `.tool-touched-chip` already used), with the ellipsis on the label's own
   `.ph-text` span.
3. **The grounding chip's ordinal is its own element**
   (`.note-label-prefix`, `flex-shrink: 0`), not text prepended into the
   rendered span, so a chip's ellipsis can never clip the number along with
   the label.

`groundingchip.js`, `cmdpalettechips.js` and `notelabelregress.js` cover the
three changes and the other `setNoteLabel` callers that were not touched
(the "elsewhere" and touched-item chips, which have no ordinal and were
confirmed to still get their existing per-chip ellipsis rules).

## Left, with the next step

1. **Not verified: a real model.** Everything measured here (this batch
   included) ran against `scratchpad/fake_openai_server.py` (CLAUDE.md
   section 4). The grounding event was made possible by seeding a note that
   contains the stand-in's one fixed sentence (`seedGroundableNote` in
   phasec.js); a real model paraphrases, and the distinctive-terms half of
   `ground_answer_sentences` is what would carry it. Untested.
2. **Not verified: narrow widths for the badges.** Light and dark both pass
   `groundingchip.js`'s checks at 1440 (this batch); a 1024 pass, where
   these chips wrap, is still not measured, and nor is the truncated case at
   a real note length on a narrow dock.
