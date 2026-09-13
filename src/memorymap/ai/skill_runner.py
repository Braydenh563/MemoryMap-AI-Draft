"""Running a skill: one step at a time, with progress and a result.

The difference between this and handing the model a numbered list is the
difference between a plan and a job. A list inside one request is a plan the
model is free to ignore, and a 3B model given four instructions at once
reliably does the first, narrates the rest, and reports success. Here each
step is its own bounded agent turn, so:

- the app **knows** which step is running, and the UI ticks them off;
- a step that fails is named, instead of a run that quietly did less than it
  said (roadmap §21's "a skill that fails halfway should say which step");
- each turn carries one instruction and the skill's own few tool schemas
  rather than everything at once, which is what makes this work on the small
  models it is aimed at (§11a);
- what changed is collected as it happens, with the call that would undo it.

A skill with no steps is one turn, exactly what it was before the rebuild.

**A step is a goal, not a turn** (AGENT_SKILLS_REFORM.md, Phase A). One turn per
step fixed "the model did all four instructions at once"; it did not fix the
report that followed it, *"I ran a skill and it ran no tools… the models often
dont even properly complete a step before they are prompted for the next
step."* The cause was that this file decided a step was over when the model
stopped emitting, so a small model narrating "Here is the result of step 2…"
was indistinguishable from one that had done it. A step now carries a contract
(`skills.STEP_EXPECTS`), and a step that has not met it is re-prompted with a
nudge naming the tool rather than ticked off. A step declaring no contract, a
plain string, which is every skill anyone has saved by hand, behaves exactly
as it did before.

**Everything here has to stay lazy.** The events are consumed by a streaming
NDJSON response, so anything that materialises the iterator holds the whole
step back and releases it in one block. That was a real bug (§35H): putting
the first event back with `[first, *events]` looks harmless and is not, the
`*` runs the generator to exhaustion before the list even exists, so a step's
prose, tool chips and all arrived together once the step had finished. Reported
as "the steps don't stream visually as they are written and are instead dumped
once each section of the response is finished". `chain` is the version of that
line which does not.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from itertools import chain

from sqlalchemy.orm import Session

from memorymap.ai import agent, budget as run_budget, skills, tools
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient

logger = logging.getLogger("memorymap.skills")

# Rounds a single step may take before it has to earn more. Lower than a free
# chat turn on purpose: a step is one instruction, and a model still looping
# after this many rounds has misunderstood it rather than run out of room.
STEP_ROUNDS = 4

# …and rounds a step can earn by getting somewhere (agent.EARNED_ROUNDS is the
# same idea for an ordinary turn, and the reasoning is written up there).
#
# This is the reported failure seen from inside a run: *"the agent struggles
# with long tasks like skills, then cuts out half way through."* A step such as
# "tag every untagged note" is one instruction and a dozen tool calls, and four
# flat rounds cut it off in the middle every time, with the step ticked off as
# done, because the runner could only see that the turn had produced text.
# Both halves of that are fixed: a step that keeps doing new things keeps
# going, and a step that runs out is marked stalled rather than done.
STEP_EARNED_ROUNDS = 6

# How much of a step's answer is carried into the next step's history. Enough
# to say what it found, not enough to refill the window each time.
STEP_ANSWER_CHARS = 600

# How many touched-note ids one step's summary names before it just says
# "and N more", a step that tags a hundred notes must not spend the whole
# STEP_ANSWER_CHARS budget on ids and leave no room for the model's own words.
MAX_TOUCHED_IDS_NAMED = 15


def _touched_ids(step_changes: list[dict], field: str) -> list[int]:
    return sorted({c[field] for c in step_changes if c.get(field) is not None})


def _touched_clause(label: str, ids: list[int]) -> str:
    """`" [Notes touched this step: #3, #9]"`, or `""` if `ids` is empty."""
    if not ids:
        return ""
    named = ids[:MAX_TOUCHED_IDS_NAMED]
    text = ", ".join(f"#{i}" for i in named)
    if len(ids) > len(named):
        text += f", and {len(ids) - len(named)} more"
    return f" [{label} touched this step: {text}]"


def _step_answer(answer: str, step_changes: list[dict], truncated: str = "") -> str:
    """What the next step's history records for this one: the model's own
    words, plus which notes and documents it actually touched, if any did.

    **Reported, in the shape of "the agent loses the plot half way through a
    job":** a step's own narration ("tagged the relevant notes") is a prose
    summary the model wrote about itself, not a record of what happened, 
    and it is *all* the next step saw. A later step that needed "those notes"
    had nothing but that sentence to work from: too vague to act on, so it
    either re-searched (and could easily find a different set) or guessed.
    The ids in `step_changes` (`agent.py`'s own `change` events, the same
    ones that already back the chat UI's View/Undo buttons) are the ground
    truth of what this step did, appending them is handing the next step
    the same fact a human reading the transcript would have.

    Ids are the right thing to carry between steps even though the system
    prompt tells the model never to show one to the *user*, that rule is
    about what appears in an answer, not about how steps refer to things
    internally, which is exactly how every id-targeting tool (`edit_note`,
    `tag_note`, `link_notes`...) already works.
    """
    summary = _touched_clause("Notes", _touched_ids(step_changes, "note_id")) + _touched_clause(
        "Documents", _touched_ids(step_changes, "document_id")
    )
    # A step that could not finish paging says so here rather than only on the
    # event, because this string is the whole of what the *next* step is told
    # about this one: a later step that reports "every loose end in your
    # notebook" off a sixth of it is the fabrication this run exists to avoid.
    if truncated:
        summary += f" [{truncated}]"
    if not summary:
        return (answer[:STEP_ANSWER_CHARS] if answer else "") or "(nothing said)"
    # Truncate the model's own words first, not the ids, a next step that
    # cannot see what happened is guessing; the prose is what it can afford
    # to lose.
    base = answer[: max(0, STEP_ANSWER_CHARS - len(summary))] if answer else ""
    return (base or "(nothing said)") + summary


#: **What each `verify` predicate means**, keyed by the names
#: `skills.VERIFY_PREDICATES` accepts at save time.
#:
#: The two halves are deliberately in different modules and checked against
#: each other by `tests/test_harness_verifier.py`: `skills.py` is imported by
#: everything and must stay free of app imports, so it owns the vocabulary,
#: and this file owns the evaluation because it is the only thing that can
#: read the notebook. A name in one and not the other is the shape of bug
#: `core/events.py`'s driver table exists to catch: it would be accepted from
#: the user, stored, and then pass silently on every run.
#:
#: `before` is the same reading taken before the first step ran, which is what
#: makes `unchanged` answerable at all: "the notebook has as many notes as it
#: started with" is not a property of a number, it is a property of two.
PREDICATES = {
    "min": lambda got, want, before: got >= want,
    "max": lambda got, want, before: got <= want,
    "equals": lambda got, want, before: got == want,
    "unchanged": lambda got, want, before: (before is not None and got == before) is bool(want),
}


class Verification:
    """Did the run leave the notebook in the state the skill promised?

    **Why a run needs one at all.** Everything else in this file checks that
    the *model* did something: called a tool, changed a note, said words. None
    of that is the same as the job being done, and the gap between them is
    where the reported failures live ("I ran a skill and it ran no tools", "it
    only merged two categories and left it at that"). A verification is the
    one check made against the notebook rather than against the transcript.

    `ok` is False for a run that stopped early even when the skill declares no
    postcondition: a run that did four of its nine steps has not done the job,
    whatever the notebook says, and reporting that as verified would be the
    same silent tick one level up.
    """

    __slots__ = ("ok", "reason", "tool", "field", "expect", "got", "before")

    def __init__(
        self,
        ok: bool,
        reason: str,
        tool: str = "",
        field: str = "",
        expect: dict | None = None,
        got: int | None = None,
        before: int | None = None,
    ) -> None:
        self.ok = ok
        self.reason = reason
        self.tool = tool
        self.field = field
        self.expect = dict(expect or {})
        self.got = got
        self.before = before

    def as_event(self) -> dict:
        return {
            "type": "verification",
            "ok": self.ok,
            "reason": self.reason,
            "tool": self.tool,
            "field": self.field,
            "expect": self.expect,
            "got": self.got,
            "before": self.before,
        }


def _reading(session: Session, block: dict) -> tuple[int | None, str]:
    """The one number a verify block is about, and why it is missing if it is.

    Runs the tool itself rather than trusting anything the model reported: the
    whole value of the verifier is that its answer comes from the notebook.
    Never raises, for the reason `_record_run` does not either: a verification
    that blows up would take a run that did all its work with it.
    """
    name = block.get("tool") or ""
    #: **A verifier may not write.** The one thing that must never happen here
    #: is the check changing what it is checking: `verify` names any known
    #: tool, `_reading` runs it with no arguments twice per run (before the
    #: first step and after the last), and a block naming `delete_note` would
    #: therefore delete on every run of that skill, quietly, as part of
    #: "verifying" it. Refused at the one place the call is actually made
    #: rather than only at save time, because a skill stored before this
    #: existed reaches here without passing `skills.normalise` again.
    if name in tools.WRITE_TOOLS:
        return None, f"{name} changes things, so it cannot check anything"
    try:
        result = tools.execute_tool(session, name, {})
    except Exception as exc:  # noqa: BLE001  # a broken check must not break the run
        logger.warning("couldn't run the verifier tool %s", name, exc_info=True)
        return None, f"{name} could not be run ({exc})"
    if not isinstance(result, dict) or "error" in result:
        return None, f"{name} answered with an error"
    named = block.get("field")
    keys = [named] if named else list(skills.VERIFY_COUNT_FIELDS)
    for key in keys:
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value, ""
    return None, f"{name} returned no number to check ({', '.join(str(k) for k in keys)})"


def verify(
    session: Session,
    skill: dict,
    before: int | None,
    stopped_reason: str,
) -> Verification:
    """The run's own postcondition, checked against the notebook.

    `stopped_reason` is "" for a run that reached the end. Anything else short
    circuits: there is no point reading a count back out of a notebook a run
    never finished working on, and a `min` that happens to hold over a run
    that stopped at step two is a pass nobody should be shown.
    """
    block = skill.get("verify") or None
    if stopped_reason:
        return Verification(False, stopped_reason, tool=(block or {}).get("tool", ""))
    if not block:
        # No declared postcondition. The honest verification of a skill that
        # promised nothing specific is that every step it does have finished:
        # which, at this point, is true.
        return Verification(True, "every step finished")
    got, why = _reading(session, block)
    if got is None:
        return Verification(False, why, tool=block["tool"], field=block.get("field") or "")
    failures = [
        name
        for name, want in block["expect"].items()
        if not PREDICATES[name](got, want, before)
    ]
    where = f"{block['tool']}{'.' + block['field'] if block.get('field') else ''}"
    if failures:
        wanted = ", ".join(f"{name} {block['expect'][name]}" for name in failures)
        return Verification(
            False,
            f"{where} came back {got}, and this skill expects {wanted}",
            tool=block["tool"],
            field=block.get("field") or "",
            expect=block["expect"],
            got=got,
            before=before,
        )
    return Verification(
        True,
        f"{where} came back {got}, as this skill expects",
        tool=block["tool"],
        field=block.get("field") or "",
        expect=block["expect"],
        got=got,
        before=before,
    )


def _record_run(
    session: Session,
    skill: dict,
    changes: list[dict],
    stopped_at: int | None,
    steps: int,
    paused: bool,
) -> None:
    """Write one audit row for a finished skill run.

    **Nothing in this app ever wrote one, and the Library's AI Skills tab has
    a log panel that reads them.** Reported as "I dont think the skill logs
    work in the ai skills section in the library??", correct, and not because
    the panel was broken: `renderSkillLogs` filters `/audit` for
    `entity_type === "skill"`, and a grep for a `log_action` call with that
    entity type returns nothing at all. The panel could only ever say "No
    skill execution logs found". The "features that never ran once" shape from
    CLAUDE.md, one layer down: the reader ran, and the writer did not exist.

    Best-effort and never raises: a run that did real work must not fail at
    the last line over its own bookkeeping. Committed here rather than left to
    the caller, because the caller is a streaming route whose session may be
    closed by the time the generator is exhausted.
    """
    from memorymap.entry.manager import log_action

    outcome = (
        "paused"
        if paused
        else "completed"
        if stopped_at is None
        else f"stopped at step {stopped_at + 1}"
    )
    detail = f"{outcome} · {len(changes)} change(s)"
    if steps:
        detail = f"{outcome} · {steps} step(s) · {len(changes)} change(s)"
    try:
        log_action(
            session,
            "ran",
            "skill",
            None,
            f"{skill.get('name') or 'skill'}, {detail}",
            # The writes the run made are already attributed to the tool that
            # made them (`execute_tool`); this row is the run itself.
            actor=f"ai:{skill.get('name') or 'skill'}",
        )
        session.commit()
    except Exception:  # noqa: BLE001  # bookkeeping must not fail a finished run
        logger.warning("couldn't record the skill run", exc_info=True)
        session.rollback()


#: Event types that mean the turn handed over to somebody else rather than
#: finishing. `ask_user` is the one that reaches a skill run: it stops the turn
#: to put a question to the person, so the step is waiting rather than
#: unfinished, and neither the "nothing happened" branch nor a contract retry
#: should fire on it.
_HANDOVERS = frozenset({"ask", "confirm"})


def _unmet_reason(spec: dict) -> str:
    """One sentence naming the contract that was not met, for the step event.

    Phase D asks for "why did this stall?" in one sentence; this is that
    sentence, and it is written now because the information only exists here.
    """
    named = ", ".join(spec.get("tools") or [])
    if spec.get("expects") == "notes_changed":
        return (
            f"this step had to change something with {named} and nothing changed"
            if named
            else "this step had to change something and nothing changed"
        )
    if spec.get("expects") == "answer_only":
        return "this step had to answer in words and nothing was said"
    return (
        f"this step had to call {named} and it wasn't called"
        if named
        else "this step had to call a tool and none were called"
    )


#: How much of a tool's own result the carried state remembers. One line, so a
#: later step can see *what* the last call came back with without the whole
#: payload being resent on every round of every step after it.
STATE_RESULT_CHARS = 200

#: How many ids or tags the state tracks in total. The state line itself names
#: fewer (see `skills.MAX_STATE_IDS`); this is the ceiling on what a long run
#: accumulates in memory before it starts forgetting the oldest.
MAX_STATE_TRACKED = 40

#: How many note ids a run's `seen_ids` ledger holds (Brief 13). Deliberately
#: far larger than `MAX_STATE_TRACKED`, because the two answer different
#: questions: that one is "which notes is this run talking about", where a
#: forgotten oldest id costs a little precision, and this one is "how much of
#: the notebook has this run actually looked at", where forgetting is the
#: failure. Ints only, and nothing but the count reaches a prompt.
MAX_SEEN_TRACKED = 2000

#: **How many times one step may call its tool to page through a read.**
#: CHAT_PLAN decision 10's "up to N tool calls (default 6)". A step that has
#: paged this many times and still has pages left is reading something far
#: larger than a step was meant to cover; the run says so rather than spending
#: the rest of its budget on page seven.
MAX_PAGES_PER_STEP = 6

#: Argument names that carry tags. A name rule rather than a per-tool table for
#: the same reason `tools.call_example` builds itself from the schema: a tool
#: added later is covered without anyone remembering to come back here.
#:
#: `new` is deliberately **not** in this list, though `rename_tag(old, new)`
#: puts a tag there: `rename_category` has the same argument and puts a
#: category name in it, and this state is read back to the model as fact. A
#: tag that is missing costs a little precision; a category listed as a tag is
#: a wrong fact in the prompt, which is the more expensive of the two. See
#: `_tag_arguments` for the narrow case where `new` is read after all.
_TAG_ARGUMENT_KEYS = ("tags", "tag", "add")


def _tag_arguments(event: dict) -> tuple[str, ...]:
    """Which of a tool call's arguments name tags, for this particular call."""
    if "tag" in str(event.get("tool") or ""):
        # `rename_tag`, `delete_tag`, `tag_note`, the tag tools, where `new`
        # is a tag by definition.
        return (*_TAG_ARGUMENT_KEYS, "new")
    return _TAG_ARGUMENT_KEYS


def _remember(state: dict, key: str, value) -> None:
    """Add one value to a list in the state, keeping order and no duplicates."""
    seen = state.setdefault(key, [])
    if value in seen:
        return
    seen.append(value)
    if len(seen) > MAX_STATE_TRACKED:
        del seen[0]


def _absorb(state: dict, event: dict) -> None:
    """Fold one tool event into the run's structured state.

    **The third structural cause of the reported failure** (see this module's
    header and AGENT_SKILLS_REFORM.md): only prose used to cross a step
    boundary, so a step told to act on "those notes" got a sentence about them
    rather than their ids, and either re-searched, finding a different set , 
    or guessed. What a tool actually touched is already on the event, because
    the chat transcript needs it for the same reason; this keeps it.
    """
    if event.get("type") != "tool":
        return
    for item in event.get("touched") or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        if item.get("kind") == "document":
            _remember(state, "document_ids", item["id"])
        else:
            _remember(state, "note_ids", item["id"])
    arguments = event.get("arguments")
    if isinstance(arguments, dict):
        for key in _tag_arguments(event):
            value = arguments.get(key)
            for tag in value if isinstance(value, list) else [value]:
                if isinstance(tag, str) and tag.strip():
                    _remember(state, "tags", tag.strip())
    if not event.get("ok"):
        # A failed call touched nothing and read nothing. Recording it as
        # "last tool run" would tell the next step a lie in one word.
        return
    # Every note this read returned, uncapped by the chip limit: the ledger a
    # paging step is judged against (`_pages_left`), and the one number the
    # state line carries so the model can tell page one from the whole
    # notebook.
    #
    # A list and a linear membership test rather than a set, deliberately:
    # the whole `state` dict is yielded on the `result` event and serialised
    # straight to NDJSON, and a set there is a `TypeError` at the last line of
    # a run that did everything right. Order is also what makes the ledger
    # readable. Two thousand ints against a page of twenty is nothing.
    ledger = state.setdefault("seen_ids", [])
    for note_id in event.get("seen") or []:
        if not isinstance(note_id, int) or note_id in ledger:
            continue
        if len(ledger) >= MAX_SEEN_TRACKED:
            break
        ledger.append(note_id)
    if event.get("tool"):
        state["last_tool"] = event["tool"]
    summary = event.get("result_summary")
    if isinstance(summary, str) and summary.strip():
        state["last_tool_result"] = summary[:STATE_RESULT_CHARS]


def _absorb_change(state: dict, change: dict) -> None:
    """The ids a *write* touched, kept apart from the ids a read merely saw."""
    for field, key in (("note_id", "note_ids"), ("document_id", "document_ids")):
        if isinstance(change.get(field), int):
            _remember(state, key, change[field])
            _remember(state, "touched", change[field])


def _pages_left(spec: dict, events: list[dict]) -> dict | None:
    """The unfinished page of a read this step made, or None if there is none.

    **CHAT_PLAN decision 10, the half `skill_runner` did not have**: *"a step
    loops until its contract is met, up to N tool calls, with paging handled
    inside the step"*. `list_notes` has always said there is more (`has_more`,
    `next_offset`, and a `note_to_model` spelling out the next call), and the
    runner never read any of it: one call satisfied `tool_called`, the step
    went green, and a "go through every note" step had seen twenty of seventy.

    Judged on the **last** call of the tool rather than on any of them,
    because that is what "have I reached the end" means: a model that paged
    four times has three results saying "more" and a fourth saying "that is
    all", and a rule reading "any" would keep a finished step open for ever.

    Only a tool the step's contract names counts. A step that declares no
    tools declares nothing about what it must read, and holding it open on an
    incidental `list_notes` would stall runs that work today, which is the
    same reason a plain string step has no contract at all.
    """
    named = set(spec.get("tools") or [])
    if not named:
        return None
    for event in reversed(events):
        if event.get("tool") not in named or not event.get("ok"):
            continue
        return event if event.get("more") else None
    return None


def _paging_nudge(event: dict, page: int, of: int) -> str:
    """Tell the model to fetch the next page, with the call already written.

    The same lever `skills.contract_nudge` pulls and for the same measured
    reason: a small model does not need the concept of pagination explained,
    it needs the next call spelled out. The offset comes from the tool's own
    result, so this cannot name a page that does not exist.
    """
    tool = event.get("tool") or "the tool"
    offset = event.get("next_offset")
    where = f" with offset={offset}" if isinstance(offset, int) else " for the next page"
    return (
        f"You have not seen all of them yet: `{tool}` said there is more. "
        f"Call `{tool}` again{where} and keep going until it says there is "
        f"no more. This is page {page} of at most {of}."
    )


def _contract_met(spec: dict, called: set[str], changed: list[dict], answer: str) -> bool:
    """Has this step done what it declared it would?

    The one judgement worth writing down here: a **failed** call still counts
    for `tool_called`. The contract is "you reached for the tool", and a model
    that called it and got an error is not the failure this exists to catch, 
    that model is already handled, by the recovery hints the agent loop feeds
    back and by the run's own "no answer and a failure" branch. Re-prompting
    it would spend two more rounds re-running the same broken call. What this
    catches is the model that wrote *about* the tool and never called it.
    """
    expects = spec.get("expects")
    if not expects:
        return True  # a plain string step: unchecked, exactly as before
    if expects == "answer_only":
        return bool(answer)
    if expects == "notes_changed":
        return bool(changed)
    named = set(spec.get("tools") or [])
    return bool(called & named) if named else bool(called)


#: **How many times one run may re-plan a step that failed** (PLAN.md §4, A2:
#: "re-plans on a failed step (max 2)").
#:
#: The contract retries above (Phase A) re-send the *same* step with a nudge, 
#: they are for a model that narrated instead of calling. This is the level
#: above: a step that has genuinely failed or stalled is *rewritten* and tried
#: again, so a run bends rather than ending at the first bad step.
#:
#: **The step is rewritten in place, and the rest of the plan is not touched.**
#: That is a deliberate scope call, not a shortcut. `stopped_at` is an index
#: into the step list, and the client turns it into "Resume from step N" by
#: sending the *saved skill's* name back down `/chat/stream`, so a re-plan
#: that inserted, removed or reordered steps would leave `stopped_at` pointing
#: into a list nothing else has, and Resume would silently re-run the wrong
#: step, every one of which writes to the notebook. Rewriting one step keeps
#: every index, every `earlier` marker and Resume exactly as correct as they
#: were. What gets re-planned is *how* to do the step; what does not is the
#: shape of the job.
MAX_REPLANS = 2

REPLAN_PROMPT = (
    "You rewrite ONE step of a plan that has just failed, so it can be tried "
    "again. Reply with the rewritten step and nothing else: one short "
    "instruction, no numbering, no quotes, no explanation. Make it smaller "
    "and more literal than the one that failed, name the single thing to do."
)


def _fallback_replan(step_text: str, spec: dict) -> str:
    """The rewrite when the model cannot supply one.

    Deliberately still a rewrite rather than a bare retry: the step goes back
    with the tool it must call named inside it, which is the same lever the
    contract nudge pulls and the one that actually moves a small model. Kept
    inside `skills.MAX_STEP` so a re-planned step is still a step the plan
    card, the skill editor and a later `normalise` all accept.
    """
    tool = next(iter(spec.get("tools") or []), None)
    call = f" Call {tool} exactly once." if tool else " Do one thing only."
    return f"{step_text.rstrip('.')}.{call}"[: skills.MAX_STEP]


def _replan_step(
    model_manager: ModelManager,
    ollama: OllamaClient,
    skill: dict,
    values: dict | None,
    step_text: str,
    spec: dict,
    reason: str,
) -> str:
    """A rewritten version of one failed step. Never raises, never empty.

    Falls back to `_fallback_replan` on every failure path, offline, a
    transport error, an empty reply, a reply that came back as a paragraph, 
    for the same reason `followups.suggest_followups` returns `[]` on all of
    its: a run that stops because its own recovery could not reach the model
    is a worse outcome than one that retries with a mechanically improved
    instruction.
    """
    fallback = _fallback_replan(step_text, spec)
    if not ollama.is_running():
        return fallback
    named = ", ".join(spec.get("tools") or [])
    goal = skills.fill(skill.get("prompt") or "", skills.input_values(skill, values))
    try:
        reply = ollama.chat(
            model_manager.utility_model(),
            [
                {"role": "system", "content": REPLAN_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"The whole job: {goal[: skills.MAX_GOAL]}\n"
                        f"The step that failed: {step_text}\n"
                        f"What went wrong: {reason}\n"
                        + (f"It must call this tool: {named}\n" if named else "")
                        + "Rewrite the step."
                    ),
                },
            ],
        )
    except Exception:  # noqa: BLE001  # recovery must not itself end the run
        logger.warning("couldn't re-plan a failed step", exc_info=True)
        return fallback
    text = " ".join(str(reply.get("content") or "").split())
    # A model that answered with a paragraph, a refusal or an empty string has
    # not given a step. One line, and shorter than the cap a step is allowed
    # to be: otherwise the "rewrite" is a fresh wall of prose, which is the
    # failure this whole file exists to stop.
    if not text or len(text) > skills.MAX_STEP:
        return fallback
    return text


def _step_tools(spec: dict, allowed: list[str] | None, small_model: bool) -> list[str] | None:
    """Which tools this one step is offered.

    Ordinarily the skill's whole allowlist, which is already narrow. In
    small-model mode it is **only what the step's contract names**: Phase B:
    a 4B model handed five schemas for a step that needs one picks the wrong
    one often enough to be the reported failure, and every schema not sent is
    room the notes and the question get back. Falls back to the skill's list
    when the step names nothing, because offering no tools at all would make a
    `tool_called` contract impossible to meet.
    """
    if not small_model:
        return allowed
    named = [name for name in (spec.get("tools") or []) if allowed is None or name in allowed]
    return named or allowed


def run_skill(
    session: Session,
    skill: dict,
    values: dict | None,
    notes: list[dict],
    model_manager: ModelManager,
    ollama: OllamaClient,
    budget: run_budget.RunBudget | None = None,
    **kwargs,
) -> Iterator[dict]:
    """`_run_skill`, with the run's budget open around the whole of it.

    A thin wrapper rather than a `with` inside the body, because the body is
    four hundred lines and re-indenting it would bury this change in a diff
    nobody could review. The scope is what makes the budget true of every
    model call the run makes, including the ones written later by somebody
    who has never read this file: see `ai/budget.py`.

    The scope is entered by the generator, so it is set while the run is
    executing and released when it is exhausted or closed. A `contextvar` set
    inside a generator is visible to its caller between yields, which is
    harmless here (the streaming route makes no model calls of its own) and is
    the same trade `core/events.acting_as` already makes.
    """
    spend = budget if budget is not None else run_budget.RunBudget()
    with run_budget.spending(spend):
        yield from _run_skill(
            session, skill, values, notes, model_manager, ollama, budget=spend, **kwargs
        )


def _run_skill(
    session: Session,
    skill: dict,
    values: dict | None,
    notes: list[dict],
    model_manager: ModelManager,
    ollama: OllamaClient,
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    start_at: int = 0,
    manual: bool = False,
    manual_note: str | None = None,
    small_model: bool | None = None,
    budget: run_budget.RunBudget | None = None,
) -> Iterator[dict]:
    """Yields the agent's own event types, plus three of its own:

    {"type": "plan", "skill", "steps", "step_specs", "tools", "small_model"}
                                                    - before anything runs
    {"type": "step", "index", "state", "text"}, running | retrying | done
                                                      | failed | stalled
                                                      | earlier
    {"type": "result", "changes": [...], "stopped_at": int|None, "paused": bool,
     "state": {...}}, what actually changed,
                                                      where it stopped, and the
                                                      ids the run gathered

    The first event is either "unsupported" (the model can't call tools, so
    the caller should fall back to plain Q&A) or "plan", the same contract
    `run_agent` has, so the route's fallback works unchanged.

    `start_at` resumes: steps before it are marked `earlier` and not re-run.
    That is the answer to "it cuts out half way through and has to restart", 
    restarting a six-step run to reach step four means doing steps one to three
    again, and every one of them writes to the notebook.

    `manual` is the other half of that same request, asked for directly and
    explicitly, and never built until now: **"skills producing network
    errors, or models that cannot run them" and "a manual mode"**, a pause
    after every completed step with a Continue button, so a person can add
    what the agent missed or answer a question it raised before the next
    step starts, rather than the run barrelling on regardless. Reuses the
    exact same stop-and-resume machinery `start_at` already has for a
    failure: a pause is not a new code path, it's the same one with
    `result.paused = True` so the caller can tell "stopped because it's
    waiting for you" from "stopped because something went wrong" and render
    each one differently. `manual_note` is what the user typed at that
    pause; folded into the very next step's own instruction (not into
    history, which the model may or may not weigh, this is read as part of
    what it's being asked to do right now).

    `small_model` is Phase B of the skills reform: one tool per step and a
    worked example of the call. None means "decide from the model", which is
    read off the chat model's own name: see `model_manager.parameter_count`,
    and note that an unrecognised name means *off*.

    **The step contract is Phase A**, and it is the difference between this
    and what was here before: a step is over when its declared condition is
    met, not when the model stops emitting. A step that has not met it is
    re-prompted with a nudge naming the tool, up to its own `retries`, and
    only then marked `stalled`. It is never silently `done`, that was the
    reported bug, and the reason a run "ran no tools" and still ticked green.
    """
    #: **The reading the verifier compares against, taken before any step
    #: runs.** `unchanged` is the postcondition of every read-only skill in
    #: the catalogue, and it is a claim about two numbers rather than one, so
    #: the first has to be taken while the claim is still true by definition.
    #: One extra tool call per run that declares a verify block, and none at
    #: all for one that does not.
    before_reading: int | None = None
    if skill.get("verify"):
        before_reading, _why = _reading(session, skill["verify"])
    steps = skill.get("steps") or []
    specs = skills.step_specs(skill)
    allowed = skill.get("tools") or None
    if small_model is None:
        # "Auto": the model's own name is the only size hint available before a
        # request is made, and it is free. `chat_model_is_small` answers None
        # when the name says nothing, and None means off, narrowing a capable
        # model's toolbox on a guess is the worse mistake of the two.
        small_model = bool(model_manager.chat_model_is_small())
    plan = {
        "type": "plan",
        "skill": skill["name"],
        # Strings, for ever: `plan.steps` is rendered straight into `<li>`
        # textContent by the frontend, so anything else here is a plan card
        # full of "[object Object]". The contracts travel beside it.
        "steps": steps,
        "step_specs": specs,
        "tools": skill.get("tools") or [],
        "small_model": bool(small_model),
        # Which shape of run this is, so the UI can title it. A saved skill and
        # a plan the model drew for one request (§35K) both run through here.
        "kind": skill.get("kind") or "skill",
        "start_at": max(0, start_at),
    }
    changes: list[dict] = []
    # What the run knows so far, as ids rather than as prose, carried into
    # every later step's instruction and returned with the result.
    state: dict = {}

    def turn(
        question: str,
        turn_history: list[dict],
        note: str | None,
        offered: list[str] | None = allowed,
    ) -> Iterator[dict]:
        return agent.run_agent(
            session,
            question,
            notes,
            model_manager,
            ollama,
            style=style,
            profile=profile,
            history=turn_history,
            persona_prompt=persona_prompt,
            allowed_tools=offered,
            # A run may not start another run. A skill that *declares* its
            # tools is already safe (`skills.NEVER_IN_A_SKILL` refuses these at
            # save time), but a skill with no allowlist, and every ad-hoc plan
            #, is offered the whole registry, `make_plan` included. A plan
            # step that plans again would nest runs with fresh rounds each.
            blocked_tools=tools.RUN_STARTERS,
            max_rounds=STEP_ROUNDS if steps else agent.MAX_ROUNDS,
            earned_rounds=STEP_EARNED_ROUNDS if steps else agent.EARNED_ROUNDS,
            exhausted_note=note,
        )

    if not steps:
        # No steps declared: one turn on the whole instruction, as before.
        events = turn(skills.run_instruction(skill, values), list(history or []), None)
        first = next(events, None)
        if first is None:
            yield plan
            return
        if first.get("type") == "unsupported":
            yield first
            return
        yield plan
        for event in _collect(chain([first], events), changes, state):
            yield event
        # No steps to resume from, so no `stopped_at`: a stepless skill is one
        # turn, and re-running it is the only way to continue it. The turn's
        # own `limit` event is still there, and the chat's Continue button
        # reads that.
        # One turn, so the only way it can have stopped early is the budget;
        # `_collect` has already passed the `limit` event through to the
        # caller, and the verification is what says so in the result.
        spent_out = bool(budget and budget.stopped)
        checked = verify(session, skill, before_reading, budget.stopped if spent_out else "")
        yield checked.as_event()
        _record_run(session, skill, changes, None, 0, False)
        yield {
            "type": "result",
            "changes": changes,
            "stopped_at": None,
            "steps": 0,
            "paused": False,
            "truncated": False,
            "stopped_by": "budget" if spent_out else "",
            "verification": checked.as_event(),
            "undo_available": all(change.get("undo") for change in changes),
            "state": state,
        }
        return

    step_history = list(history or [])
    started = False
    stopped_at: int | None = None
    paused = False
    resume_from = min(max(0, start_at), len(steps))
    #: **A copy**, because re-planning rewrites a step in place and
    #: `skill["steps"]` belongs to the caller, a built-in skill's list *is*
    #: the module-level catalogue's own list, so mutating it here would
    #: quietly rewrite that skill for every later run in the process. The
    #: `plan` event above still carries the original list, which is what the
    #: plan card was drawn from; a rewrite arrives as its own `replanned`
    #: step event rather than by mutating what the reader was already shown.
    steps = list(steps)
    replans = 0
    # Did any step run out of pages before its read ran out of notes? Carried
    # to the result so the run as a whole can say it saw part of the notebook.
    run_truncated = False
    # Set to the sentence explaining the stop the first time a step hits the
    # run's budget. Read after the loop, several steps later, which is why it
    # is a run-level string rather than a per-step flag.
    out_of_budget = ""
    for index in range(resume_from):
        # Done in the run this one is resuming, so it is neither re-run nor
        # claimed as this run's work. The plan card shows it ticked in a
        # quieter state, because a step somebody watched succeed ten
        # minutes ago is not the same as one this run just did.
        if not started:
            yield plan
            started = True
        yield {"type": "step", "index": index, "state": "earlier", "text": steps[index]}
    index = resume_from
    #: A `while`, not a `for`: a re-planned step is run again at the same
    #: index with new text, and `continue` without advancing is what that is.
    while index < len(steps):
        step = steps[index]
        # Whether the way this step ended is worth re-planning at all, and the
        # one sentence saying what went wrong, the material `_replan_step`
        # gives the model, and the reason the `replanned` event carries.
        replannable = True
        fail_reason = ""
        spec = specs[index]
        offered = _step_tools(spec, allowed, small_model)
        example = (
            tools.call_example(spec["tools"][0])
            if small_model and spec.get("tools")
            else None
        )
        attempts = spec.get("retries", skills.DEFAULT_STEP_RETRIES) + 1
        attempt = 1
        # Pages fetched for this step so far, counted apart from `attempt` on
        # purpose: paging is the step *working*, and spending a contract retry
        # on it would end a step that is doing exactly what it was asked to.
        pages = 1
        # Set when the step ran out of pages before the read ran out of notes.
        truncated = ""
        announced = False
        nudge: str | None = None
        outcome: str | None = None  # set when the step is over, either way
        while outcome is None:
            instruction = skills.step_instruction(
                skill, values, index, state=state, only_tools=offered, example=example
            )
            # Folded into the instruction, not appended to `step_history`: this
            # is what the user is asking for as part of *this* step, not a fact
            # about an earlier one, and a history entry is something the model
            # may or may not weigh against everything else in the window.
            if manual_note and index == resume_from:
                instruction = (
                    f"Before this step, the person running this added: "
                    f"“{manual_note}”\n\n{instruction}"
                )
            if nudge:
                # First, and on its own line: this is a correction, and a
                # correction buried under three paragraphs of restated context
                # is one a small model reads as more context.
                instruction = f"{nudge}\n\n{instruction}"
            events = turn(
                instruction,
                step_history,
                f"I couldn't finish step {index + 1}: I used every round it had "
                "without reaching an answer.",
                offered,
            )
            first = next(events, None)
            if first is not None and first.get("type") == "unsupported":
                if not started:
                    # Nothing has been shown yet, so the caller can still fall
                    # back to a plain answer. Once a step has run, it cannot.
                    yield first
                    return
                yield {
                    "type": "step",
                    "index": index,
                    "state": "failed",
                    "text": step,
                    "reason": "The model stopped being able to use tools part-way through.",
                }
                stopped_at = index
                # Not re-plannable: no rewording of a step gives a model back
                # the ability to call tools.
                replannable = False
                outcome = "failed"
                break
            if not started:
                yield plan
                started = True
            if not announced:
                announced = True
                yield {"type": "step", "index": index, "state": "running", "text": step}

            said: list[str] = []
            failures: list[str] = []
            ran_out = False
            called: set[str] = set()
            # Every tool event of this turn, in order, so the paging check can
            # ask what the *last* call of the step's own tool came back with.
            tool_events: list[dict] = []
            ran_any_tool = False
            handed_over = False
            went_offline = False
            # Where this step's own changes start in the run's running list, so
            # they can be told apart from every earlier step's: see
            # _step_answer, and the `notes_changed` contract.
            changes_before = len(changes)
            for event in _collect(chain([first], events) if first else events, changes, state):
                if event["type"] == "answer":
                    said.append(event["delta"])
                    if event.get("offline"):
                        went_offline = True
                elif event["type"] == "tool":
                    ran_any_tool = True
                    tool_events.append(event)
                    if event.get("tool"):
                        called.add(event["tool"])
                    if not event.get("ok"):
                        failures.append(str(event.get("error") or event.get("label")))
                elif event["type"] == "limit":
                    # The step used every round it had and was still calling
                    # tools. Whatever it says next is a stopping notice, so it
                    # must not be read as the step's result.
                    ran_out = True
                    #: **A budget stop is not a rounds stop**, and telling
                    #: them apart is the whole of what the run does next. Out
                    #: of rounds means "this step is bigger than a step":
                    #: Resume it, split it, try again. Out of budget means the
                    #: *run* is over, so re-planning this step and running it
                    #: again would spend rounds the run does not have on a
                    #: model call that would be refused before it was made.
                    if event.get("reason") == "budget":
                        out_of_budget = str(event.get("detail") or "the run's budget ran out")
                elif event["type"] in _HANDOVERS:
                    # `ask_user` ends the turn by handing the question to the
                    # person. It never reaches here as a tool event, so a
                    # contract check would see a step that called nothing and
                    # re-prompt a model that is correctly waiting for an
                    # answer only the user can give.
                    handed_over = True
                yield event

            answer = "".join(said).strip()
            step_changes = changes[changes_before:]
            if went_offline:
                # **Tier 1 §3.** Ollama died mid-round, and `agent.run_agent`'s
                # own answer for that is a real sentence of prose ("Ollama
                # doesn't seem to be running…"), which used to satisfy the
                # "did this step say something" check below and get ticked
                # done. The run then quietly repeated the identical failure on
                # every later step, since the notebook did not get any less
                # offline between them. Named and stopped here instead, the
                # same way `ran_out` is. Not retried either: the notebook will
                # not come back online between two attempts a second apart.
                yield {
                    "type": "step",
                    "index": index,
                    "state": "failed",
                    "text": step,
                    "reason": "Ollama isn't reachable: check Settings → Models and try again.",
                }
                stopped_at = index
                # Not re-plannable, and the re-plan call itself would need the
                # same model that has just gone away.
                replannable = False
                outcome = "failed"
                break
            if out_of_budget:
                #: Checked before `ran_out`, which a budget stop also sets:
                #: the two arrive together and only one of them is the reason.
                yield {
                    "type": "step",
                    "index": index,
                    "state": "stalled",
                    "text": step,
                    "reason": out_of_budget,
                }
                stopped_at = index
                # Nothing to re-plan: the next attempt would be refused before
                # it reached the model, and a rewritten step is not a cheaper
                # one, it is another turn.
                replannable = False
                outcome = "stalled"
                break
            if ran_out:
                # **Stalled, not done.** This is the half of the reported
                # failure that made the other half invisible: the runner could
                # only see that the turn produced text, and the "I ran out of
                # rounds" notice is text: so a step that was cut off mid-job
                # was ticked green and the next step ran on top of half-finished
                # work. It stops here instead, and `stopped_at` is what Resume
                # picks up from.
                yield {
                    "type": "step",
                    "index": index,
                    "state": "stalled",
                    "text": step,
                    "reason": (
                        "ran out of rounds before finishing, Resume continues "
                        "from here, or split this step into two smaller ones"
                    ),
                }
                stopped_at = index
                fail_reason = "it used every round it had without finishing"
                #: **Not re-plannable, and this is the sharpest line in the
                #: whole mechanism.** A step that ran out of rounds was
                #: *doing the job* and got cut off half way, unlike every
                #: other ending here, work was done and more is left. Rewrite
                #: it and run it again and the model, having no rounds' worth
                #: of context about what it already tagged, answers in prose
                #:, and the step goes green over a job that is still half
                #: finished. That is precisely the bug this file exists to
                #: prevent (`tests/test_long_runs.py` catches it), and the
                #: honest ending for a cut-off step is the one it already
                #: has: stop, and let Resume carry on from here with the
                #: notebook as it now stands.
                replannable = False
                outcome = "stalled"
                break
            # A step that ran no tools and said nothing did not happen. Anything
            # else is reported as done, the model's own words are the record,
            # and calling a step failed because a tool errored mid-way would be
            # wrong when it recovered on the next call.
            if not answer and failures:
                yield {
                    "type": "step",
                    "index": index,
                    "state": "failed",
                    "text": step,
                    "reason": failures[-1],
                }
                stopped_at = index
                fail_reason = f"a tool failed: {failures[-1]}"
                outcome = "failed"
                break
            # **The other half of the reported bug.** A turn can end with no
            # answer, no tool call and no failure at all, a model that replies
            # with empty content and no tool calls produces exactly this, and it
            # used to fall straight through to "done" below because nothing here
            # checked for *nothing happening*. That is what made the skill's own
            # progress list lie: a step ticked green though the model never
            # actually said or did anything ("the AI fails to respond… and the
            # skill step counted as done"). Reported the same way `ran_out` was:
            # stop and let Resume pick it back up, rather than hand the next step
            # a "done" step with nothing in its history to build on.
            #
            # Deliberately *not* folded into the contract retry below: this is a
            # model that produced nothing at all, not one that did the wrong
            # thing, and the two want different words. Retrying it would also
            # change a failure the UI already explains ("Resume picks up from
            # this step") into two more silent rounds first.
            if not answer and not ran_any_tool and not handed_over:
                yield {
                    "type": "step",
                    "index": index,
                    "state": "failed",
                    "text": step,
                    #: **Say what to do about it, not only what happened.**
                    #: Reported: *"skills are too hard for small ais and things go
                    #: wrong often."* A small model producing one empty turn is the
                    #: single most common way a run stops, and it usually passes on
                    #: the next attempt: which the Resume button already does,
                    #: from this step, without re-running the ones before it. A
                    #: reason that does not say that leaves the reader with a dead
                    #: run and no move.
                    "reason": (
                        "the model didn't respond: no answer and no tool call. "
                        "Resume picks up from this step; a smaller model often "
                        "gets it on the second attempt, and Manual mode lets you "
                        "steer each step."
                    ),
                }
                stopped_at = index
                fail_reason = "the model said nothing and called no tool"
                outcome = "failed"
                break
            #: **More pages to read: the step is not over** (CHAT_PLAN
            #: decision 10). Checked before the contract rather than inside
            #: it, because the two say different things to the reader: the
            #: contract is "you never reached for the tool", and this is "you
            #: reached for it and stopped a quarter of the way through". The
            #: step event says `paging` for the same reason it says
            #: `retrying`: what the person is watching is progress, not a
            #: fault.
            page = None if handed_over else _pages_left(spec, tool_events)
            if page is not None and pages < MAX_PAGES_PER_STEP:
                pages += 1
                nudge = _paging_nudge(page, pages, MAX_PAGES_PER_STEP)
                yield {
                    "type": "step",
                    "index": index,
                    "state": "paging",
                    "text": step,
                    "page": pages,
                    "of": MAX_PAGES_PER_STEP,
                    "seen": len(state.get("seen_ids") or []),
                }
                continue
            #: **Out of pages with more still to read.** Said out loud, three
            #: times over: on the step event, in the step's own history so the
            #: next step knows what it is building on, and through
            #: `result.truncated` so the run does not report a partial pass as
            #: a complete one. This is the same failure the contract exists to
            #: catch, one level up: "I went through your notes" over the first
            #: sixth of them is the sentence nobody can tell from the truthful
            #: version unless the app says so.
            if page is not None:
                run_truncated = True
                truncated = (
                    f"stopped after {MAX_PAGES_PER_STEP} pages with more left "
                    f"to read; {len(state.get('seen_ids') or [])} notes were seen"
                )
            if handed_over or _contract_met(spec, called, step_changes, answer):
                done: dict = {"type": "step", "index": index, "state": "done", "text": step}
                if truncated:
                    done["reason"] = truncated
                    done["truncated"] = True
                yield done
                step_history.append(
                    {"question": step, "answer": _step_answer(answer, step_changes, truncated)}
                )
                outcome = "done"
                break
            if attempt < attempts:
                # **Re-prompted, not skipped.** The single highest-yield change
                # in the reform: a small model that narrated the step instead of
                # doing it is told, literally, which call to make. The step stays
                # open and the UI shows it retrying rather than ticked.
                attempt += 1
                nudge = skills.contract_nudge(spec, attempt, attempts)
                yield {
                    "type": "step",
                    "index": index,
                    "state": "retrying",
                    "text": step,
                    "attempt": attempt,
                    "of": attempts,
                    "reason": _unmet_reason(spec),
                }
                continue
            # Out of attempts. Stalled: never `done`, which is the whole point.
            yield {
                "type": "step",
                "index": index,
                "state": "stalled",
                "text": step,
                "reason": (
                    f"{_unmet_reason(spec)} after {attempts} attempt(s). Resume "
                    "continues from here: or, if there was genuinely nothing "
                    "to do in this step, skip past it by resuming from the next."
                ),
            }
            stopped_at = index
            fail_reason = _unmet_reason(spec)
            outcome = "stalled"
        if outcome != "done":
            #: **Re-plan, then try the step again** (PLAN.md §4 A2). Bounded by
            #: `MAX_REPLANS` per *run*, not per step: two rewrites is the point
            #: at which a run that keeps failing is telling you something about
            #: the job rather than about the wording, and an unbounded loop
            #: here would be a model rewriting its own instructions forever
            #: over a notebook it cannot act on.
            if replannable and replans < MAX_REPLANS:
                replans += 1
                revised = _replan_step(
                    model_manager, ollama, skill, values, step, spec, fail_reason
                )
                steps[index] = revised
                yield {
                    "type": "step",
                    "index": index,
                    "state": "replanned",
                    "text": revised,
                    "attempt": replans,
                    "of": MAX_REPLANS,
                    "reason": fail_reason,
                }
                # It is no longer where the run stopped, it is about to be
                # tried again, and a `stopped_at` left behind here would offer
                # a Resume for a step that is still running.
                stopped_at = None
                continue
            break
        # Manual mode: the same stop-and-resume machinery `stopped_at` already
        # gives a failed/stalled step, used deliberately here instead of a
        # second mechanism: the difference is only `paused` below, so the
        # client can render "waiting for you" rather than "something broke".
        # Nothing to pause for after the last step; that's just the run ending.
        if manual and index + 1 < len(steps):
            stopped_at = index + 1
            paused = True
            break
        index += 1

    if not started:  # every step failed before producing anything
        yield plan
    #: **Why the run ended, in one word for the app and one sentence for the
    #: person.** `stopped_at` alone cannot tell a budget stop from a stalled
    #: step from a manual pause, and all three want a different button.
    stopped_by = (
        "budget"
        if out_of_budget
        else "paused"
        if paused
        else "step"
        if stopped_at is not None
        else ""
    )
    checked = verify(
        session,
        skill,
        before_reading,
        out_of_budget
        or (
            f"the run stopped at step {stopped_at + 1} of {len(steps)}, so its "
            "postcondition was not checked"
            if stopped_at is not None and not paused
            else "the run is paused part-way through, so its postcondition was "
            "not checked"
            if paused
            else ""
        ),
    )
    yield checked.as_event()
    _record_run(session, skill, changes, stopped_at, len(steps), paused)
    # `stopped_at` is the index the run did not get past, None when it
    # finished. The client turns it into "Resume from step N", which is the
    # difference between carrying on and doing the first half again. `paused`
    # tells it which reason: waiting for the user (manual mode) rather than a
    # failure: Resume becomes Continue, and it's not reported as an error.
    yield {
        "type": "result",
        "changes": changes,
        "stopped_at": stopped_at,
        "steps": len(steps),
        "paused": paused,
        # A step somewhere in this run stopped paging with more to read, so
        # the run saw part of the notebook rather than all of it.
        "truncated": run_truncated,
        # "" when the run reached the end; "budget", "paused" or "step"
        # otherwise. The `verification` is repeated here as well as on its own
        # event because a client that reads only the result (a replay, the
        # skill log) must not have to reconstruct it.
        "stopped_by": stopped_by,
        "verification": checked.as_event(),
        # Can everything this run did be put back? A run that changed nothing
        # trivially can; a change with no undo call beside it cannot, and that
        # is the one case where offering the button would be a lie.
        "undo_available": all(change.get("undo") for change in changes),
        # The ids the run gathered, so whatever picks it up next, a Resume, a
        # follow-up question, Phase C's run view: can talk about "those notes"
        # with the same precision the steps did.
        "state": state,
    }


def _collect(events: Iterator[dict], changes: list[dict], state: dict) -> Iterator[dict]:
    """Pass events through, keeping the changes and the state for the result."""
    for event in events:
        if event.get("change"):
            changes.append(event["change"])
            _absorb_change(state, event["change"])
        _absorb(state, event)
        yield event


#: A skill name as a test or a fixture is likely to write it: `find_loose_ends`
#: for "Find loose ends". Not a general lookup (`skills.find` is that, and it
#: already forgives punctuation and case); this exists so a spec can name a
#: built-in without depending on its exact display wording, which is copy and
#: changes.
def _slug(name: str) -> str:
    return "_".join(str(name or "").lower().split())


class StepRun:
    """One step of a run, as a fact rather than as a stream of events."""

    __slots__ = ("index", "text", "state", "tool_calls", "pages", "truncated")

    def __init__(self, index: int, text: str) -> None:
        self.index = index
        self.text = text
        self.state = "running"
        self.tool_calls = 0
        self.pages = 1
        self.truncated = False


class RunResult:
    """A finished run, folded up: what each step did, what changed, what the
    verifier found, and why it stopped."""

    __slots__ = (
        "skill",
        "steps",
        "changes",
        "state",
        "stopped_at",
        "stopped_by",
        "verification",
        "undo_available",
        "truncated",
        "budget",
        "events",
    )


def run_for_test(
    ollama,
    *,
    skill: str,
    notes: int = 0,
    budget: dict | None = None,
    values: dict | None = None,
) -> RunResult:
    """Run one skill end to end against a model double, and return the run.

    The seam `tests/test_harness_verifier_spec.py` drives, and the same shape
    `core/events.exercise_for_test` already has in this codebase: a harness
    whose whole job is to be provable needs one call that *is* a run, rather
    than a test that reassembles one out of a hundred events and is therefore
    testing its own reassembly.

    Seeds `notes` notes first, because paging is only a behaviour over a
    notebook large enough to have pages.

    Reaches the app's own database and model manager through `importlib`
    rather than an import statement, the same way `entry/manager.py` does and
    for the same reason: `core.deps` builds the objects in this package, so
    naming it here is the wrong-direction edge `tests/test_no_import_cycles.py`
    exists to refuse.
    """
    import importlib

    deps = importlib.import_module("memorymap.core.deps")
    manager = importlib.import_module("memorymap.entry.manager")

    spend = run_budget.RunBudget(**budget) if budget else None
    wanted = _slug(skill)
    with deps.get_db().session() as session:
        for index in range(notes):
            manager.create_entry(
                session, f"note {index}: chase up the invoice", "Work", []
            )
        catalog = skills.catalog(deps.get_config(), set(tools.TOOLS))
        found = next((s for s in catalog if _slug(s["name"]) == wanted), None)
        if found is None:
            raise LookupError(
                f"no skill called {skill!r}; there are "
                + ", ".join(sorted(_slug(s["name"]) for s in catalog))
            )
        run = RunResult()
        run.skill = found["name"]
        run.steps = []
        run.changes = []
        run.state = {}
        run.stopped_at = None
        run.stopped_by = ""
        run.verification = Verification(False, "the run produced no result")
        run.undo_available = False
        run.truncated = False
        run.budget = spend
        run.events = []
        current: StepRun | None = None
        for event in run_skill(
            session,
            found,
            values or {},
            [],
            deps.get_model_manager(),
            ollama,
            budget=spend,
        ):
            run.events.append(event)
            kind = event.get("type")
            if kind == "step":
                index = event["index"]
                while len(run.steps) <= index:
                    run.steps.append(StepRun(len(run.steps), event.get("text") or ""))
                current = run.steps[index]
                current.text = event.get("text") or current.text
                current.state = event["state"]
                if event["state"] == "paging":
                    current.pages = event.get("page") or current.pages
                if event.get("truncated"):
                    current.truncated = True
            elif kind == "tool" and current is not None:
                current.tool_calls += 1
            elif kind == "verification":
                run.verification = Verification(
                    ok=event["ok"],
                    reason=event["reason"],
                    tool=event["tool"],
                    field=event["field"],
                    expect=event["expect"],
                    got=event["got"],
                    before=event["before"],
                )
            elif kind == "result":
                run.changes = event["changes"]
                run.state = event["state"]
                run.stopped_at = event["stopped_at"]
                run.stopped_by = event["stopped_by"]
                run.undo_available = event["undo_available"]
                run.truncated = event["truncated"]
        return run
