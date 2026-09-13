"""Skills: a named, repeatable job over the notebook.

Reported directly, and accurately: *"the way skills are used currently, and
what the skills are at the moment, are incorrect and are closer to just
presaved mini prompts. I keep on trying to get the AI to make me some skills
in the chat but it doesn't recognise that it needs to use tools."*

A skill used to be `{name, prompt}`, and clicking one dropped its prompt into
the chat box. There was no notion of what a skill *does*: no declared inputs,
no tools it may use, no steps, nothing to show progress against. `save_skill`
took a name and a string, so "make me a skill that files my inbox notes" could
only ever produce another sentence, the storage had nowhere to put the steps.
That is why fixing the prompt alone would not have helped.

A skill is now four things, all optional except the first two:

- **prompt**: what it should do, in the user's words. A skill with only this
  behaves exactly as it did before, which is why nothing is lost.
- **steps**: ordered instructions. This is what makes a skill replayable and
  what the UI shows progress against (roadmap §18's missing plan). A step is
  either a plain string or a dict declaring its *contract*, what must be true
  before the run may move on. See `STEP_EXPECTS`; the canonical form comes back
  as `step_specs`, beside a `steps` list that stays strings because the
  frontend renders it directly.
- **tools**: an explicit allowlist. Both a safety property *and* a prompt:
  naming the three tools a skill needs is what makes a small model reach for
  them, which is the reported failure. It is also roadmap §11a's win: only
  those schemas go on the wire for the run, instead of all 28.
- **inputs**: declared placeholders, so a skill can be "file everything
  tagged `{{tag}}`" rather than a sentence hoping the model guesses the tag.

This module is deliberately free of app imports: it validates against a set of
tool names handed in by the caller rather than importing the registry, because
`tools.py` imports *this*. Cycles in this codebase have been paid for before.
"""

from __future__ import annotations

import re

MAX_SKILLS = 30
MAX_NAME = 40
MAX_PROMPT = 2000
MAX_DESCRIPTION = 200
# When this skill applies, in the user's own words. Separate from the
# description, which says what the skill *is*, this says when to reach for it,
# and it is the field that makes a skill findable by the model rather than only
# by the person who remembered writing it (§33). Short on purpose: it is
# carried in `list_skills` output, which a turn may read before doing anything.
MAX_WHEN = 160
MAX_STEPS = 10
MAX_STEP = 300

#: What has to be true before a step counts as finished, a step's *contract*.
#:
#: Reported: *"I ran a skill and it ran no tools... the models often dont even
#: properly complete a step before they are prompted for the next step."* The
#: cause is structural rather than a bad prompt: a step used to be over when
#: the model stopped emitting, so a 4B model that narrates ("Here is the result
#: of step 2…") without calling anything was indistinguishable, to the runner,
#: from one that did the work. A contract is the missing half, the machine
#: -checkable thing that must have happened, so "step 2 is done" is something
#: the app knows rather than hopes.
#:
#: - `tool_called`, at least one tool ran (any of `tools`, if named).
#: - `notes_changed`, the step actually changed something in the notebook.
#: - `answer_only`, words are the deliverable; a judgement or a report.
#:
#: A **plain string step has no contract at all**, and that is deliberate:
#: every skill saved before this existed is a list of strings, as is every
#: ad-hoc plan and everything the settings textarea writes. Applying a guessed
#: contract to those would stall runs that work today, so an unchecked step
#: advances exactly as it did before.
STEP_EXPECTS = ("tool_called", "notes_changed", "answer_only")

#: How many times a step whose contract was not met is re-prompted before the
#: run gives up on it. Two, because the nudges do different jobs: the first
#: names the tool literally (the one that works on a small model), the second
#: catches a model that answered the nudge with more prose. A third has never
#: been worth another full round of tool schemas on the wire.
DEFAULT_STEP_RETRIES = 2
MAX_STEP_RETRIES = 5

#: How many tools one step may name as satisfying its contract. A step naming
#: four is not declaring a contract, it is restating the skill's allowlist: 
#: and the whole point of Phase B is that a small model is offered *one*.
MAX_STEP_TOOLS = 4
MAX_TOOLS = 12
MAX_INPUTS = 5
MAX_INPUT_VALUE = 200
# Manual (step-through) mode: what the user types in at a pause between
# steps, to add what the agent missed or answer a question it raised. Short
# on purpose: it is folded straight into the next step's own instruction,
# not stored anywhere.
MAX_MANUAL_NOTE = 500

#: Tools a skill may never declare. Both hand a turn to a *run*, so a skill
#: holding one could start itself: each run brings fresh rounds, and the
#: per-turn budget that stops an ordinary loop never applies. Named here rather
#: than imported from `tools` because `tools` imports this module.
NEVER_IN_A_SKILL = frozenset({"run_skill", "make_plan"})

#: **What a skill's `verify` block may assert** (Brief 13; CHAT_PLAN decision
#: 10). A run ends by reading one number back out of the notebook and checking
#: it, which is the difference between "the model said it tagged them" and
#: "the notebook now says so".
#:
#: Four predicates, each answerable from one integer, because a postcondition
#: a small model can be graded against has to be a fact rather than a
#: judgement:
#:
#: - `min` / `max`: the reading is at least / at most this.
#: - `equals`: exactly this.
#: - `unchanged`: the same as it was *before the run started*, which is the
#:   postcondition of every read-only skill in the catalogue ("Notebook health
#:   check" says in its own prompt that it changes nothing; this is what makes
#:   that a checked claim rather than a promise).
#:
#: The names are the vocabulary and `skill_runner._PREDICATES` holds the
#: function per name; `tests/test_harness_verifier.py` asserts the two sets are
#: equal, which is the `core/events.py` driver trick in miniature: a predicate
#: added here without an evaluator fails the build rather than silently
#: passing every run that uses it.
VERIFY_PREDICATES = ("min", "max", "equals", "unchanged")

#: Where the verifier looks for its number when the `verify` block does not
#: name a field. Ordered: the first of these the tool's result carries wins.
#: Every counting tool in the registry answers to one of them (`count_notes`
#: returns `total` or `count`, `list_notes` returns `total_matching`), so the
#: common case needs no `field` at all, and a tool that answers to none of
#: them is told so at save time rather than at the end of a run.
VERIFY_COUNT_FIELDS = ("total", "count", "total_matching", "returned")

#: An ad-hoc plan's title, shown on the plan card. Longer than MAX_NAME because
#: it is the job in the user's own words: "tidy up my categories and retag
#: anything that got missed", rather than a name somebody chose for a skill.
MAX_GOAL = 120

# {{tag}}: doubled braces so a skill can still talk about {json} literally.
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]{0,23})\s*\}\}")
INPUT_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,23}$")


class SkillError(ValueError):
    """Something about this skill is wrong, phrased for whoever wrote it."""


def _text(value, limit: int, what: str) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise SkillError(f"{what} is limited to {limit} characters")
    return text


def _step_specs(
    raw: dict, known_tools: set[str] | None, declared: list[str]
) -> list[dict]:
    """Every step of one skill in canonical form: `{text, expects, tools,
    retries}` each.

    A step arrives as **either** a plain string (what the settings textarea
    writes, what every skill saved before contracts existed holds, and what an
    ad-hoc plan is made of) **or** a dict declaring its contract. Both are
    valid for ever: the string form is not a legacy shape to be migrated away,
    it is the shape a person types.

    `step_specs` on the input is read too, so normalising an already-normalised
    skill is idempotent. Without it a skill would lose its contracts simply by
    being round-tripped through `catalog()`, which re-normalises everything the
    user has stored: the sort of silent loss that only shows up as "the
    built-in works and my copy of it doesn't".
    """
    raw_steps = raw.get("steps") or []
    carried = raw.get("step_specs") or []
    specs: list[dict] = []
    for index, raw_step in enumerate(raw_steps):
        step = raw_step
        if isinstance(step, str) and index < len(carried) and isinstance(carried[index], dict):
            step = {**carried[index], "text": step}
        if isinstance(step, dict):
            text = _text(step.get("text") or step.get("step"), MAX_STEP, "A skill step")
        else:
            text = _text(step, MAX_STEP, "A skill step")
            step = {}
        if not text:
            continue  # a blank line in the textarea is not a step
        specs.append(_one_step_spec(text, step, known_tools, declared))
    if len(specs) > MAX_STEPS:
        raise SkillError(f"A skill can have at most {MAX_STEPS} steps")
    return specs


def _one_step_spec(
    text: str, step: dict, known_tools: set[str] | None, declared: list[str]
) -> dict:
    expects = str(step.get("expects") or "").strip() or None
    if expects is not None and expects not in STEP_EXPECTS:
        raise SkillError(
            f"“{expects}” is not something a step can expect, use one of "
            + ", ".join(STEP_EXPECTS)
            + "."
        )
    tools: list[str] = []
    for tool in step.get("tools") or []:
        tool = str(tool or "").strip()
        if not tool or tool in tools:
            continue
        if known_tools is not None and tool not in known_tools:
            raise SkillError(
                f"Step “{text[:40]}” names a tool that does not exist: “{tool}”."
            )
        if declared and tool not in declared:
            # A step may only be satisfied by a tool the run will actually be
            # offered. Caught here rather than at run time because the run
            # would otherwise re-prompt for a tool the allowlist refuses, twice,
            # and then stall: a contract nothing could ever meet.
            raise SkillError(
                f"Step “{text[:40]}” expects “{tool}”, which this skill does "
                "not declare in its tools."
            )
        tools.append(tool)
    if len(tools) > MAX_STEP_TOOLS:
        raise SkillError(f"A step can name at most {MAX_STEP_TOOLS} tools")
    retries = step.get("retries", DEFAULT_STEP_RETRIES)
    try:
        retries = int(retries)
    except (TypeError, ValueError):
        retries = DEFAULT_STEP_RETRIES
    return {
        "text": text,
        "expects": expects,
        "tools": tools,
        "retries": max(0, min(retries, MAX_STEP_RETRIES)),
    }


def verify_spec(raw: dict, known_tools: set[str] | None, declared: list[str]) -> dict | None:
    """One skill's `verify` block in canonical form, or None if it has none.

    `{"tool": name, "field": str|None, "expect": {predicate: value}}`.

    **Why a declaration rather than a step.** A skill could always have ended
    with a step saying "check it worked", and that is exactly the thing a 3B
    model reports having done without doing: the failure this whole file is
    about. A `verify` block is read and run by the app, so the answer comes
    from the notebook rather than from the model's account of itself, and a
    run that stopped early cannot claim it passed.

    Validated here, at save time, for the same reason a step's contract is:
    the alternative is a run that does all its work and then fails at the last
    line on a typo in a predicate name.
    """
    block = raw.get("verify")
    if not isinstance(block, dict) or not block:
        return None
    tool = str(block.get("tool") or "").strip()
    if not tool:
        raise SkillError("A verify block needs a tool to read the answer from")
    if known_tools is not None and tool not in known_tools:
        raise SkillError(f"There is no tool called “{tool}” to verify with.")
    if declared and tool not in declared:
        # Same rule as a step's contract, and the same reason: a verifier the
        # run's own allowlist refuses is a postcondition that can never pass.
        raise SkillError(
            f"This skill verifies with “{tool}”, which it does not declare in "
            "its tools."
        )
    expect = block.get("expect")
    if not isinstance(expect, dict) or not expect:
        raise SkillError("A verify block needs an expect, for example {\"min\": 1}")
    unknown = sorted(set(expect) - set(VERIFY_PREDICATES))
    if unknown:
        raise SkillError(
            "A verify block can't expect "
            + ", ".join(f"“{name}”" for name in unknown)
            + ", use one of "
            + ", ".join(VERIFY_PREDICATES)
            + "."
        )
    checks: dict = {}
    for name, value in expect.items():
        if name == "unchanged":
            checks[name] = bool(value)
            continue
        try:
            checks[name] = int(value)
        except (TypeError, ValueError):
            raise SkillError(f"“{name}” in a verify block wants a whole number.") from None
    field = str(block.get("field") or "").strip()
    return {"tool": tool, "field": field or None, "expect": checks}


def step_specs(skill: dict) -> list[dict]:
    """The contracts for a skill's steps, whatever shape it was stored in.

    A skill that came from `normalise` has them; one built by hand (an ad-hoc
    plan, a fixture, anything read straight out of preferences without going
    through the catalogue) may not, and the runner must not have to care. A
    missing spec is an unchecked step, which is exactly what a bare string
    step means anywhere else.
    """
    steps = skill.get("steps") or []
    specs = skill.get("step_specs") or []
    out: list[dict] = []
    for index, step in enumerate(steps):
        spec = specs[index] if index < len(specs) and isinstance(specs[index], dict) else {}
        out.append(
            {
                "text": spec.get("text") or str(step),
                "expects": spec.get("expects") or None,
                "tools": list(spec.get("tools") or []),
                "retries": int(spec.get("retries", DEFAULT_STEP_RETRIES)),
            }
        )
    return out


def contract_nudge(spec: dict, attempt: int, of: int) -> str:
    """The re-prompt for a step whose contract was not met.

    **The single highest-yield change in the reform**, and the reason it is
    worded like this: a small model does not need a better explanation of the
    job, it needs to be told literally which call to make. "You did not call
    `find_contradictions`. Call it now." outperforms any amount of restated
    context, and every word here is spent on that rather than on politeness.

    It says which attempt this is on purpose, a model that has already been
    nudged once and produced more prose is being told the loop is finite,
    which is the honest thing to tell it and cheap to say.
    """
    named = spec.get("tools") or []
    tool = f"`{named[0]}`" if len(named) == 1 else " or ".join(f"`{t}`" for t in named)
    if spec.get("expects") == "answer_only":
        # Reachable, and not a corner case: a model that runs a tool and then
        # says nothing at all leaves a step whose deliverable is words with no
        # words in it. Telling it "you did not call a tool" there would be
        # both false and the opposite of what it needs to hear.
        opening = (
            "You did not answer. This step is asking you for words, say what "
            "you found, in a sentence or two."
        )
    elif spec.get("expects") == "notes_changed":
        opening = (
            f"Nothing in my notebook changed. You have to actually call {tool} "
            "for this step: describing the change does not make it."
            if named
            else "Nothing in my notebook changed, and this step is supposed to "
            "change something. Make the change with a tool."
        )
    elif named:
        opening = (
            f"You did not call {tool}. Call it now, with the arguments this "
            "step needs: do not describe what you would do, do it."
        )
    else:
        opening = (
            "You did not call any tool. This step cannot be done by writing "
            "about it: make the call."
        )
    return (
        f"{opening} This is attempt {attempt} of {of}; if the step genuinely "
        "cannot be done, say so plainly in one sentence instead of trying again."
    )


#: How many ids of one kind the carried-over state names before it stops. The
#: state line is prepended to every later step's instruction, so it is paid for
#: on every round of every step after the one that filled it in.
MAX_STATE_IDS = 12


def state_line(state: dict | None) -> str:
    """"State so far: notes #3, #9; tags: admin, tax", or "" if nothing is known.

    Structured state, rather than the prose a step wrote about itself, is the
    third of the three structural problems behind the reported failure: a step
    that must act on "those notes" used to get a *sentence* about them. Named
    ids resolve that, and they are the same ids every id-taking tool already
    wants.
    """
    if not state:
        return ""
    parts: list[str] = []
    notes = list(state.get("note_ids") or [])[:MAX_STATE_IDS]
    if notes:
        parts.append("notes " + ", ".join(f"#{i}" for i in notes))
    documents = list(state.get("document_ids") or [])[:MAX_STATE_IDS]
    if documents:
        parts.append("documents " + ", ".join(f"#{i}" for i in documents))
    tags = list(state.get("tags") or [])[:MAX_STATE_IDS]
    if tags:
        parts.append("tags: " + ", ".join(tags))
    # How many notes the run has actually read, which is the fact a paging
    # step needs and the id list cannot carry: `notes` above names twelve, and
    # a step working through seventy has to be able to tell "I have read them
    # all" from "I have read the first page". Five words, not seventy ids.
    seen = len(state.get("seen_ids") or [])
    if seen > len(notes):
        parts.append(f"notes read so far: {seen}")
    last = str(state.get("last_tool") or "").strip()
    if last:
        parts.append(f"last tool run: {last}")
    if not parts:
        return ""
    return "State so far: " + "; ".join(parts) + "."


def normalise(raw: dict, known_tools: set[str] | None = None) -> dict:
    """Validate one skill and return it in canonical form.

    Raises `SkillError` with a sentence meant for the person (or the model)
    that wrote the skill. Unknown keys are dropped rather than rejected: a
    skill saved by an older version carries `useTools`, and refusing it would
    make an upgrade lose the user's skills.
    """
    name = _text(raw.get("name"), MAX_NAME, "A skill name")
    prompt = _text(raw.get("prompt"), MAX_PROMPT, "A skill prompt")
    if not name:
        raise SkillError("A skill needs a name")
    #: **Steps count as the prompt** (Brief 13's decision, recorded in
    #: CHAT_PLAN "Decisions made"). A numbered list of steps already says what
    #: the job is, and making the author write it twice is how the two drift
    #: apart: the prompt says one thing, the steps do another, and the model
    #: reads both. A skill with neither is still refused, because that is a
    #: skill that says nothing at all.
    if not prompt and not (raw.get("steps") or raw.get("step_specs")):
        raise SkillError("A skill needs a prompt saying what it should do, or steps")

    tools: list[str] = []
    for tool in raw.get("tools") or []:
        tool = str(tool or "").strip()
        if not tool or tool in tools:
            continue
        if tool in NEVER_IN_A_SKILL:
            # A skill that can start a skill is a loop with no bottom: each
            # run gets its own rounds, so the budget that bounds a turn never
            # binds. Refused at save rather than at execution, because the
            # allowlist would only refuse it once the run was already going.
            raise SkillError(
                f"A skill can't use “{tool}”: a skill that starts another "
                "skill would never have to stop. Put the steps in this one."
            )
        if known_tools is not None and tool not in known_tools:
            raise SkillError(
                f"There is no tool called “{tool}”. Call list_tools, or pick "
                "from the tools shown in Settings → Tools."
            )
        tools.append(tool)
    if len(tools) > MAX_TOOLS:
        raise SkillError(f"A skill can name at most {MAX_TOOLS} tools")

    specs = _step_specs(raw, known_tools, tools)
    steps = [spec["text"] for spec in specs]

    inputs = []
    for item in raw.get("inputs") or []:
        if isinstance(item, str):
            item = {"name": item}
        input_name = str((item or {}).get("name") or "").strip()
        if not INPUT_NAME.match(input_name):
            raise SkillError(
                f"“{input_name or item}” is not a usable input name, use "
                "letters, digits and underscores, starting with a letter."
            )
        inputs.append(
            {
                "name": input_name,
                "label": _text(item.get("label"), 60, "An input label")
                or f"{input_name}?",
                "required": bool(item.get("required", True)),
                "default": _text(item.get("default"), MAX_INPUT_VALUE, "An input default"),
            }
        )
    if len(inputs) > MAX_INPUTS:
        raise SkillError(f"A skill can declare at most {MAX_INPUTS} inputs")

    skill = {
        "name": name,
        "prompt": prompt,
        "description": _text(raw.get("description"), MAX_DESCRIPTION, "A description"),
        "when_to_use": _text(raw.get("when_to_use"), MAX_WHEN, "A when-to-use note"),
        # Two views of the same list, and both are load-bearing. `steps` is
        # the list of strings the frontend has always read, `plan.steps` is
        # rendered straight into `<li>.textContent` and the skill editor joins
        # it with newlines into a textarea, so anything but strings there is a
        # broken settings screen and a plan card full of "[object Object]".
        # `step_specs` carries the contract beside it for the runner. Adding a
        # parallel field rather than changing the shape of an existing one is
        # what keeps this backwards compatible in both directions.
        "steps": steps,
        "step_specs": specs,
        "tools": tools,
        "inputs": inputs,
    }
    # Only when it was declared: a skill with no postcondition must round-trip
    # through here unchanged, and a `verify: None` key on every stored skill
    # would be a schema change nothing asked for.
    verify = verify_spec(raw, known_tools, tools)
    if verify:
        skill["verify"] = verify
    # Every placeholder used has to be declared, or running the skill sends
    # the model a literal {{tag}} and it invents a value. Cheaper to catch on
    # save than to debug in a run.
    declared = {item["name"] for item in inputs}
    used = set()
    for text in [prompt, *steps]:
        used.update(PLACEHOLDER.findall(text))
    missing = sorted(used - declared)
    if missing:
        raise SkillError(
            "This skill uses "
            + ", ".join(f"{{{{{name}}}}}" for name in missing)
            + " but doesn't declare "
            + ("them" if len(missing) > 1 else "it")
            + " as an input."
        )
    # An action skill is one that names tools or steps; kept as `useTools` so
    # skills saved before this rebuild keep the flag the UI already reads.
    if raw.get("useTools") or steps or tools:
        skill["useTools"] = True
    return skill


def is_action(skill: dict) -> bool:
    """Does running this skill mean acting, rather than just answering?"""
    return bool(skill.get("useTools") or skill.get("steps") or skill.get("tools"))


def ad_hoc_plan(goal: str, steps: list[str]) -> dict:
    """A plan the model drew for one request, in the shape the runner takes.

    **Why this exists** (§35K, and §33's `update_plan`): *"I will say fix my
    categories and it will only merge two categories and leave it at that,
    ignoring the rest."* That is the same failure §21 found for skills, a
    model given one broad instruction does the first part and reports success, 
    and the skill runner already solves it, by giving each step its own turn.

    What was missing is that the fix only applied to jobs somebody had saved as
    a skill. An open-ended request needs the identical treatment, so this is
    the identical structure with nothing saved: a name, a job, ordered steps.
    The runner cannot tell the difference, which is the point, a plan gets the
    ticked steps, the change list and the Undo on each that a skill run gets.

    No tool allowlist, deliberately. A skill declares its tools because its
    author knew the job in advance; a plan is drawn for one request, and
    guessing an allowlist from a sentence would silently refuse the tool the
    job actually needed. Each step is focused on its own text instead
    (`tools.focus_for`), which is the same economy without the guess.
    """
    text = " ".join(str(goal or "").split())[:MAX_GOAL]
    return {
        # Read by the runner and the plan card; `kind` is what lets the UI say
        # "the plan it made" rather than "the skill it ran".
        "kind": "plan",
        "name": text,
        "prompt": text,
        "steps": list(steps),
        "tools": [],
        "inputs": [],
        "useTools": True,
    }


def fill(text: str, values: dict) -> str:
    """Substitute {{input}} placeholders.

    A *declared* input substitutes even when it is empty, an optional input
    left blank should disappear, not print `{{to}}` at the model. An
    undeclared name is left alone so the mistake is visible, though
    `normalise` refuses to store one in the first place.
    """

    def swap(match: re.Match) -> str:
        name = match.group(1)
        return str(values[name]) if name in values else match.group(0)

    return re.sub(r"[ \t]{2,}", " ", PLACEHOLDER.sub(swap, text))


def missing_inputs(skill: dict, values: dict) -> list[str]:
    """Required inputs with nothing to fill them, by name."""
    return [
        item["name"]
        for item in skill.get("inputs") or []
        if item.get("required")
        and not str(values.get(item["name"], "") or "").strip()
        and not str(item.get("default") or "").strip()
    ]


def input_values(skill: dict, given: dict | None) -> dict:
    """The values a run will actually use: what was given, else the defaults."""
    given = given or {}
    values = {}
    for item in skill.get("inputs") or []:
        name = item["name"]
        supplied = str(given.get(name, "") or "").strip()
        values[name] = supplied or str(item.get("default") or "")
    return values


def run_instruction(skill: dict, values: dict | None = None) -> str:
    """What the model is actually asked, when a skill is run.

    The declared tools are named in the text as well as being the only ones on
    the wire. That is not redundancy: a 3B model that is *told* "use
    tag_note" reaches for it, and the reported failure was a model that had
    the tools and did not know it was meant to act.
    """
    values = input_values(skill, values)
    parts = [
        "Carry out the job you planned."
        if skill.get("kind") == "plan"
        else f"Run my saved skill “{skill['name']}”."
    ]
    if skill.get("description"):
        parts.append(fill(skill["description"], values))
    # A skill may say what it does in its prompt, in its steps, or in both
    # (see `normalise`). An empty line saying "What it should do:" and nothing
    # after it is worse than no line, so it is only added when there is one.
    if skill.get("prompt"):
        parts.append(f"What it should do: {fill(skill['prompt'], values)}")
    if skill.get("steps"):
        numbered = "\n".join(
            f"{i}. {fill(step, values)}" for i, step in enumerate(skill["steps"], start=1)
        )
        parts.append(f"Follow these steps in order, and don't skip one:\n{numbered}")
    given = {name: value for name, value in values.items() if value}
    if given:
        parts.append(
            "Values for this run: "
            + ", ".join(f"{name} = “{value}”" for name, value in given.items())
        )
    if skill.get("tools"):
        parts.append(
            "For this run you have only these tools: "
            + ", ".join(skill["tools"])
            + ". They are the tools this skill needs, use them rather than "
            "answering from memory."
        )
    if is_action(skill):
        parts.append(
            "When you have finished, list what you actually changed. If a step "
            "could not be done, say which one and why."
        )
    return "\n\n".join(parts)


def step_instruction(
    skill: dict,
    values: dict | None,
    index: int,
    state: dict | None = None,
    only_tools: list[str] | None = None,
    example: str | None = None,
) -> str:
    """What the model is asked for **one** step of a skill.

    A skill's steps used to be handed over as one numbered list inside one
    request, which is a plan the model is free to ignore, and a 3B model
    given four instructions at once reliably does the first and narrates the
    rest. Each step is its own turn now, so "the model did step 2" is
    something the app knows rather than something it hopes for.
    """
    values = input_values(skill, values)
    steps = skill.get("steps") or []
    total = len(steps)
    # A plan the model drew for this request is not a skill and must not be
    # described as one: told it is "running the skill 'fix my categories'", a
    # small model looks for a skill by that name and reports that there isn't
    # one. It planned this itself a moment ago, and saying so is both true and
    # the stronger instruction.
    opening = (
        f"You are working through the plan you made. This is step "
        f"{index + 1} of {total}."
        if skill.get("kind") == "plan"
        else f"You are running the skill “{skill['name']}” for me. "
        f"This is step {index + 1} of {total}."
    )
    parts = [opening]
    if skill.get("prompt"):
        parts.append(f"The whole job: {fill(skill['prompt'], values)}")
    if index:
        parts.append(
            "Earlier steps are in the conversation above, build on what they "
            "found rather than starting again."
        )
    parts.append(f"Step {index + 1}, and only this step: {fill(steps[index], values)}")
    given = {name: value for name, value in values.items() if value}
    if given:
        parts.append(
            "Values for this run: "
            + ", ".join(f"{name} = “{value}”" for name, value in given.items())
        )
    # **What earlier steps actually did, as ids rather than as prose.** The
    # step above says "read each of those notes"; without this the model has
    # only its own summary of the last step to work out which those are, and a
    # small one re-searches (finding a different set) or invents ids. See
    # `state_line`.
    carried = state_line(state)
    if carried:
        parts.append(carried)
    # In small-model mode the step is offered exactly the tools its contract
    # names, so naming the skill's whole allowlist here would describe a
    # toolbox this turn does not have, and a model told about a tool it was
    # not sent will call it and get refused, burning the round.
    named = list(only_tools) if only_tools is not None else list(skill.get("tools") or [])
    if named:
        parts.append(
            "Tools for this step: "
            + ", ".join(named)
            + ". Use them rather than answering from memory."
        )
    if example:
        # Small models copy structure far more reliably than they follow a
        # description of it, so one worked call, built from the tool's own
        # schema, never hand-written per tool, is worth more than another
        # sentence of instruction. See `tools.call_example`.
        parts.append(example)
    parts.append(
        "Do this step and then stop, not the later ones. Say what you did in "
        "a sentence or two. If it cannot be done, say so plainly instead of "
        "pretending it worked."
    )
    return "\n\n".join(parts)


# --- what ships with the app --------------------------------------------------
#
# These lived in `app.js` as BUILTIN_SKILLS, which meant the server could not
# resolve a skill the user clicked and every field added here had to be added
# there too. They are served from `GET /skills` now, the same way the web
# search providers are served rather than written out in the frontend.
#
# Every one of them names its tools. That is the point of the rebuild, and it
# is also roadmap §11a: a run offers those schemas instead of all 28, which is
# most of the fixed per-round overhead on a 3B model.
_READING_TOOLS = ["search_notes", "list_notes", "get_note", "count_notes"]

#: One built-in step, with its contract. A helper rather than a dict literal
#: per step because the contract is the point: every shipped step declares
#: what must be true when it finishes, and a helper makes a step that forgot
#: to look wrong on the page.
#:
#: **How the three are chosen, since this is a judgement and not a rule the
#: code can enforce:**
#:
#: - `tool_called` for a step that *looks*, a read, a search, an overview,
#:   an audit tool. There is always something to read, so a model that
#:   narrates instead of calling has certainly not done the step. This is the
#:   reported failure ("I ran a skill and it ran no tools") and most of the
#:   shipped steps are this.
#: - `notes_changed` where the step exists to change something and the step
#:   before it found what to change. Used sparingly and deliberately: a run
#:   over a notebook with nothing to do would stall, which is honest but is
#:   not what somebody wants to read.
#: - `answer_only` for judgements, reports, and actions that may legitimately
#:   be a no-op ("merge the duplicate tags, if there are none, say so").
#:   Forcing a tool call there would stall a run for doing the right thing.
def _step(text: str, expects: str, *tools: str) -> dict:
    return {"text": text, "expects": expects, "tools": list(tools)}


# --- the notebook audit set ---------------------------------------------------
#
# Asked for directly: *"a skill that can do a full audit and clean up of my
# notebook: linking notes, removing inaccurate links, analysing categories and
# tags, retagging notes, adding and removing tags, changing categories, moving
# notes around, combining notes to declutter."*
#
# Deliberately **five skills rather than one**, and the reason is not tidiness:
#
# - A skill runs one step per turn, and a skill has at most ten steps. That
#   whole list is comfortably more than ten steps, so one "audit everything"
#   skill would either stop half-finished or have steps so broad that a 3B
#   model cannot tell whether it has done them.
# - Each of those jobs wants a *different* toolbox, and the allowlist is what
#   keeps a run cheap and safe. One skill needing every write tool in the app
#   is one skill that can do anything, offered the schemas to match.
# - They fail independently. A tag clean-up that goes wrong should not leave a
#   category reorganisation half-applied.
#
# The first is read-only on purpose. "Audit" and "clean up" are two requests,
# and running the one that changes 400 notes before you have read what it plans
# to do is not a thing anyone means to do twice.
#
# **Every step below names at most one tool**, which is Phase B of the skills
# reform rather than a style preference: in small-model mode a step is offered
# only the tools its contract names, and a step naming three is three schemas
# on the wire and three ways for a 4B model to pick the wrong one. Steps that
# used to say "read the notes **and** judge them" are two steps now, the "and"
# was the model's licence to do the first half and narrate the second.
_AUDIT_SKILLS: list[dict] = [
    {
        "name": "Notebook health check",
        "description": "A full audit: reports what needs fixing, changes nothing.",
        "when_to_use": "before a clean-up, or when the notebook feels disorganised",
        "prompt": (
            "Audit my whole notebook and report what needs attention. Do NOT "
            "change anything: this is a report, not a clean-up."
        ),
        "steps": [
            _step(
                "Get the notebook's overview: categories, tags and the total "
                "note count: in one notebook_overview call.",
                "tool_called",
                "notebook_overview",
            ),
            _step(
                "Name the categories that are nearly empty, and any that hold "
                "so much they are not really sorting anything.",
                "answer_only",
            ),
            _step(
                "Name the tags that look like duplicates of each other "
                "(singular and plural, different spellings, near-synonyms).",
                "answer_only",
            ),
            _step(
                "List a sample of the notes sitting in Uncategorised.",
                "tool_called",
                "list_notes",
            ),
            _step(
                "Say what those Uncategorised notes are actually about, so I "
                "can see which categories are missing.",
                "answer_only",
            ),
            _step(
                "Finish with a short numbered list of what to fix, worst "
                "first, naming which of the clean-up skills would fix each "
                "one. Remind me you changed nothing.",
                "answer_only",
            ),
        ],
        # No write tool at all. The safety property here is structural rather
        # than promised: the run cannot alter the notebook because it was never
        # offered anything that could.
        "tools": [*_READING_TOOLS, "notebook_overview"],
        #: The skill's own prompt says "do NOT change anything: this is a
        #: report". This is that sentence made checkable (Brief 13).
        "verify": {"tool": "count_notes", "expect": {"unchanged": True}},
    },
    {
        "name": "Clean up my tags",
        "description": "Merges duplicate tags and removes ones that don't fit.",
        "when_to_use": "when tags have drifted, plurals, synonyms, one-offs",
        "prompt": "Go through my tags, merge the duplicates, and remove the ones that don't fit.",
        "steps": [
            _step("List every tag I use, with its count.", "tool_called", "list_tags"),
            _step(
                "Group the tags that mean the same thing, singular and "
                "plural, different spellings, near-synonyms, and pick the "
                "best name for each group.",
                "answer_only",
            ),
            _step(
                "Merge each group with rename_tag, onto the name you picked; "
                "renaming a tag onto an existing one merges them. If you found "
                "no duplicates, say so and move on.",
                "answer_only",
            ),
            _step(
                "List the notes whose tags may not match what they actually "
                "say, so you have something to check.",
                "tool_called",
                "list_notes",
            ),
            _step(
                "Read each of those notes in full with get_note before judging "
                "its tags.",
                "tool_called",
                "get_note",
            ),
            _step(
                "Use tag_note to remove the tags that do not fit. If they all "
                "fit, say so rather than removing something to look busy.",
                "answer_only",
            ),
            _step(
                "Use tag_note to add better tags where a note is under-tagged.",
                "answer_only",
            ),
            _step(
                "Tell me every change you made, grouped by what kind it was.",
                "answer_only",
            ),
        ],
        "tools": ["list_notes", "get_note", "list_tags", "rename_tag", "tag_note"],
    },
    {
        "name": "Reorganise my categories",
        "description": "Proposes a category structure, then moves notes into it.",
        "when_to_use": "when Uncategorised is full or categories have stopped fitting",
        "prompt": "Reorganise my categories so they actually fit what I write about.",
        "steps": [
            _step("List my categories with their counts.", "tool_called", "list_categories"),
            _step(
                "Read a sample of notes from the biggest category and from "
                "Uncategorised.",
                "tool_called",
                "list_notes",
            ),
            _step(
                "Tell me the structure you propose, which categories to add, "
                "which to rename, which to merge, and why, before changing "
                "anything.",
                "answer_only",
            ),
            _step(
                "Create the categories you proposed with create_category. If "
                "you proposed none, say so.",
                "answer_only",
            ),
            _step(
                "Rename the categories whose names no longer fit, with "
                "rename_category.",
                "answer_only",
            ),
            _step(
                "Merge the categories that are really the same thing, with "
                "merge_categories.",
                "answer_only",
            ),
            _step(
                "Read a note with get_note before deciding where it belongs, "
                "the choice has to be based on what it says.",
                "tool_called",
                "get_note",
            ),
            _step("Move each note into the right category with edit_note.", "answer_only"),
            _step("Tell me what you changed and how many notes moved.", "answer_only"),
        ],
        # `delete_category` is deliberately absent. It is destructive, so it
        # would stop the run for a confirm card on a step that is meant to be
        # bulk work: and merging is the operation that was actually wanted
        # anyway, since it keeps the notes together rather than scattering them
        # back into Uncategorised.
        "tools": [
            *_READING_TOOLS,
            "list_categories",
            "create_category",
            "rename_category",
            "merge_categories",
            "edit_note",
        ],
    },
    {
        "name": "Fix my links",
        "description": "Removes connections that don't hold up, and adds ones that should exist.",
        "when_to_use": "when the graph has links that no longer make sense",
        "prompt": "Check the links between my notes: remove the ones that don't hold up, add the ones that should be there.",
        "steps": [
            _step(
                "Pick a well-connected note and use related_notes to see what "
                "it connects to, and how.",
                "tool_called",
                "related_notes",
            ),
            _step(
                "Read the notes on both ends of each existing link with "
                "get_note.",
                "tool_called",
                "get_note",
            ),
            _step(
                "Say which of those links genuinely belong together and which "
                "do not, with a reason for each.",
                "answer_only",
            ),
            _step(
                "Use unlink_notes on the ones that do not hold up. If they all "
                "hold up, say so rather than removing one anyway.",
                "answer_only",
            ),
            _step(
                "Use related_notes with include_suggestions to find notes that "
                "read alike but were never linked.",
                "tool_called",
                "related_notes",
            ),
            _step(
                "Read those pairs with get_note, a similar score is a hint, "
                "not a reason.",
                "tool_called",
                "get_note",
            ),
            _step(
                "Use link_notes only where the connection is real.",
                "answer_only",
            ),
            _step(
                "Report what you unlinked and what you linked, with the reason "
                "for each.",
                "answer_only",
            ),
        ],
        "tools": [
            *_READING_TOOLS,
            "related_notes",
            "link_notes",
            "unlink_notes",
        ],
    },
    {
        "name": "Find notes worth combining",
        "description": "Spots fragments and duplicates that should be one note. Reports only.",
        "when_to_use": "when the same thing has been written down several times",
        "prompt": (
            "Find notes that are really the same thing written more than once, "
            "and show me what combining them would look like. Do not merge or "
            "delete anything yourself."
        ),
        "steps": [
            _step(
                "Use related_notes with include_suggestions on a few notes to "
                "find ones that read alike but were never linked.",
                "tool_called",
                "related_notes",
            ),
            _step(
                "Read each candidate pair or group in full with get_note, a "
                "similar score is a hint and is often wrong.",
                "tool_called",
                "get_note",
            ),
            _step(
                "For each group that is genuinely the same thing, show me the "
                "combined note you would write, with the note ids it came from.",
                "answer_only",
            ),
            _step(
                "Link the members of each group together with link_notes, so "
                "they are easy to find again.",
                "answer_only",
            ),
            _step(
                "Tell me you have not deleted or merged anything.",
                "answer_only",
            ),
        ],
        # Links, but no deletes: combining notes means deciding what to lose,
        # and that is not a judgement to hand a model over a whole notebook.
        # The proposed text comes back for the person to accept.
        "tools": [*_READING_TOOLS, "related_notes", "link_notes"],
    },
]

BUILTIN_SKILLS: list[dict] = [
    {
        "name": "Audit link reasons",
        "prompt": (
            "Audit the graph for links that have vague reasons (like 'similar in meaning') "
            "and rewrite them to be more accurate based on the notes' contents."
        ),
        "description": "Rewrites vague 'similar in meaning' links into specific reasons.",
        "when_to_use": "When I ask you to clean up or audit my links, or when the graph feels too vague.",
        "tools": ["audit_link_reasons"],
        "steps": [
            _step(
                "Run the audit_link_reasons tool to process a batch of vague "
                "links.",
                "tool_called",
                "audit_link_reasons",
            ),
            _step("Report back how many links were updated.", "answer_only"),
        ],
    },

    {
        "name": "Find where I disagreed with myself",
        "prompt": (
            "Look for places where my own notes contradict each other, a decision I "
            "reversed, a date that moved, a view I changed, and tell me what you found."
        ),
        "description": "Reads related notes and reports the ones that can't both be right.",
        "when_to_use": (
            "When I ask what I changed my mind about, whether my notes are consistent, "
            "or where I contradicted myself."
        ),
        "tools": ["find_contradictions", "link_notes"],
        "steps": [
            _step("Run the find_contradictions tool.", "tool_called", "find_contradictions"),
            _step(
                "For each one, say what the two notes claim and how far apart "
                "they were written: the gap is the point, since the "
                "interesting case is a change of mind rather than a slip.",
                "answer_only",
            ),
            _step(
                "Do NOT link anything on your own. Offer to link the ones I "
                "agree with, and only then use link_notes with link_type "
                "'contradicts'.",
                "answer_only",
            ),
            _step(
                "If nothing was found, say so plainly rather than reaching for "
                "a weak example: a wrong accusation is worse here than no "
                "answer.",
                "answer_only",
            ),
        ],
    },

    *_AUDIT_SKILLS,
    {
        "name": "Summarise my week",
        "description": "The last seven days, in a paragraph.",
        "prompt": "Summarise what I saved in the last 7 days.",
        "steps": [
            _step("Find the notes I saved in the last 7 days.", "tool_called", "list_notes"),
            _step(
                "Read the ones that look substantial with get_note, rather "
                "than working from the previews.",
                "tool_called",
                "get_note",
            ),
            _step(
                "Write the summary: the main topics, anything that looks "
                "important, and one thing worth revisiting.",
                "answer_only",
            ),
        ],
        "tools": [*_READING_TOOLS, "summarize_notes"],
    },
    {
        "name": "Find loose ends",
        "description": "Unfinished things you wrote down and left.",
        "prompt": "Find the loose ends in my notes and list them.",
        "steps": [
            #: **A paged pass, not a search** (Brief 13; CHAT_PLAN decision
            #: 10). This step used to be one `search_notes` call for "todo,
            #: need to, should", which is a top-k similarity query: it returns
            #: the five or twenty notes that most resemble those words, and
            #: the skill's whole claim is *the* loose ends, all of them. A
            #: note saying "ring the landlord back" resembles nothing on that
            #: list and is exactly what the skill is for. Paging the notebook
            #: is the only way to make the claim true, and the runner now
            #: holds the step open until `list_notes` says there is no more
            #: (bounded by `skill_runner.MAX_PAGES_PER_STEP`, which says so
            #: out loud when it runs out rather than quietly reporting a
            #: partial answer as a complete one).
            _step(
                "Go through my notes page by page with list_notes, and keep "
                "going until it says there are no more. Note which ones read "
                "as unfinished: todo, need to, should, waiting on, must, "
                "chase up, follow up.",
                "tool_called",
                "list_notes",
            ),
            _step(
                "Read each candidate with get_note, to check it is genuinely "
                "unfinished rather than something I already closed off.",
                "tool_called",
                "get_note",
            ),
            _step("List each loose end with its note id, newest first.", "answer_only"),
        ],
        "tools": _READING_TOOLS,
        #: A report, so its postcondition is that it stayed a report: the
        #: notebook has exactly as many notes as it started with. Cheap (one
        #: `count_notes`) and it is the claim the skill actually makes.
        "verify": {"tool": "count_notes", "expect": {"unchanged": True}},
    },
    {
        "name": "Auto-tag my notes",
        "description": "Adds 2–3 tags to notes that have none.",
        "prompt": "Tag the notes in my notebook that have no tags yet.",
        "steps": [
            _step(
                "List the tags I already use, so new ones match rather than "
                "duplicate them.",
                "tool_called",
                "list_tags",
            ),
            _step("Find my notes with no tags, or only one.", "tool_called", "list_notes"),
            _step(
                "Read each of those notes with get_note, so the tags describe "
                "what it actually says.",
                "tool_called",
                "get_note",
            ),
            # The one `notes_changed` contract in the shipped set. This skill
            # exists to tag notes and the step before it has just listed the
            # untagged ones, so a step that ends with nothing tagged did not
            # happen: whatever the model wrote about it.
            _step(
                "Call tag_note on each of those notes with 2–3 short, reusable "
                "tags.",
                "notes_changed",
                "tag_note",
            ),
            _step("Tell me which notes you tagged, and with what.", "answer_only"),
        ],
        "tools": ["list_notes", "get_note", "list_tags", "tag_note"],
    },
    {
        "name": "Link related notes",
        "description": "Connects notes that are clearly about the same thing.",
        "prompt": "Connect the notes in my notebook that belong together.",
        "steps": [
            _step(
                "Look through my notes for pairs that are clearly about the "
                "same thing but aren't linked yet.",
                "tool_called",
                "list_notes",
            ),
            _step(
                "Read both notes of a pair with get_note before deciding, a "
                "shared word is not a shared subject.",
                "tool_called",
                "get_note",
            ),
            _step(
                "Link each pair you are confident about with link_notes.",
                "answer_only",
            ),
            _step(
                "Give me a short summary of what you connected, and why.",
                "answer_only",
            ),
        ],
        "tools": ["search_notes", "list_notes", "get_note", "link_notes"],
    },
    {
        "name": "Tidy suggestions",
        "description": "Proposes tidy-ups. Changes nothing on its own.",
        "prompt": "Suggest how I could tidy my notebook, without changing it.",
        "steps": [
            _step(
                "Get the notebook's overview, categories, tags and totals, "
                "in one notebook_overview call.",
                "tool_called",
                "notebook_overview",
            ),
            _step(
                "Find the overlaps: tags that mean the same thing, categories "
                "with one or two notes, notes that look misfiled.",
                "answer_only",
            ),
            _step(
                "Give me the suggestions as a numbered list and ask which ones "
                "I want applied. Do not change anything yourself.",
                "answer_only",
            ),
        ],
        "tools": ["notebook_overview", "count_notes", "list_notes"],
        #: "Changes nothing on its own", in its own description. Checked.
        "verify": {"tool": "count_notes", "expect": {"unchanged": True}},
    },
    {
        "name": "Catch up on a topic",
        "description": "Everything you've written about one thing.",
        "prompt": "Pull together everything I have written about {{topic}}.",
        "steps": [
            _step("Search my notes for {{topic}}.", "tool_called", "search_notes"),
            _step("Read the most relevant ones in full with get_note.", "tool_called", "get_note"),
            _step(
                "Tell me what I seem to think about {{topic}}, what is still "
                "unresolved, and what I said about it most recently.",
                "answer_only",
            ),
        ],
        "inputs": [{"name": "topic", "label": "Which topic?", "required": True}],
        "tools": _READING_TOOLS,
    },
    {
        "name": "Daily review",
        "description": "Today's notes, turned into tomorrow's list.",
        "prompt": "Review what I captured today and tell me what needs doing.",
        "steps": [
            _step("Find the notes I saved today.", "tool_called", "list_notes"),
            _step("Read those notes in full with get_note.", "tool_called", "get_note"),
            _step(
                "Pick out anything in them that is actually an action, rather "
                "than a thought I wrote down.",
                "answer_only",
            ),
            _step(
                "Check the current time with get_current_time, so any reminder "
                "lands on the right date.",
                "tool_called",
                "get_current_time",
            ),
            _step(
                "Set a reminder with set_reminder for each action that has a "
                "time in it.",
                "answer_only",
            ),
            _step(
                "Give me the rest as a short list of what is still open.",
                "answer_only",
            ),
        ],
        "tools": [*_READING_TOOLS, "get_current_time", "set_reminder"],
    },
    {
        "name": "Draft an email",
        "description": "A clear first draft you can edit.",
        "prompt": "Draft an email to {{to}} about {{about}}.",
        "steps": [
            _step(
                "Check my notes for anything about {{about}} or {{to}} that "
                "the email should take into account.",
                "tool_called",
                "search_notes",
            ),
            _step(
                "Write the draft: a clear subject line, a short opening, the "
                "point, and a plain closing. Friendly, not formal.",
                "answer_only",
            ),
        ],
        "inputs": [
            {"name": "to", "label": "Who is it to?", "required": True},
            {"name": "about", "label": "What is it about?", "required": True},
        ],
        "tools": ["search_notes", "get_note"],
    },
    {
        "name": "Brainstorm ideas",
        "description": "A varied list, drawing on your notes.",
        "prompt": "Brainstorm ideas about {{topic}} with me.",
        "steps": [
            _step(
                "Look for anything in my notes about {{topic}}, so the ideas "
                "build on what I already think.",
                "tool_called",
                "search_notes",
            ),
            _step(
                "Give me a varied list of ideas, some obvious, some not, and "
                "say which one you would start with.",
                "answer_only",
            ),
        ],
        "inputs": [{"name": "topic", "label": "What are we brainstorming?"}],
        "tools": ["search_notes", "get_note"],
    },
    {
        "name": "Explain a concept",
        "description": "Plain English, with an example.",
        "prompt": "Explain {{concept}} to me clearly and simply.",
        "steps": [
            _step(
                "Check whether I already have notes on {{concept}}.",
                "tool_called",
                "search_notes",
            ),
            _step(
                "Explain it in plain English with one short example, pitched "
                "at what those notes show I already know.",
                "answer_only",
            ),
            _step("Offer to save the explanation as a note.", "answer_only"),
        ],
        "inputs": [{"name": "concept", "label": "Which concept?"}],
        "tools": ["search_notes", "get_note", "create_note"],
    },
    {
        "name": "Create a study plan",
        "description": "A realistic plan, with reminders set.",
        "prompt": "Help me plan how to get {{goal}} done by {{deadline}}.",
        "steps": [
            _step(
                "Check my notes for anything already written about {{goal}}.",
                "tool_called",
                "search_notes",
            ),
            _step(
                "Check the current time with get_current_time, so the dates "
                "you work out are real ones.",
                "tool_called",
                "get_current_time",
            ),
            _step(
                "Lay out a realistic step-by-step plan between now and "
                "{{deadline}}.",
                "answer_only",
            ),
            _step(
                "Set a reminder for the first milestone with set_reminder, and "
                "ask before setting the rest.",
                "answer_only",
            ),
        ],
        "inputs": [
            {"name": "goal", "label": "What are you working towards?"},
            {"name": "deadline", "label": "By when? (e.g. 3 weeks, 12 May)"},
        ],
        "tools": ["search_notes", "get_note", "get_current_time", "set_reminder"],
    },
    # ROADMAP §88.2's Kortex/Eden read named this the cheapest of everything
    # worth taking from there, "it is a skill, not a feature". The point,
    # from that read: a generic "write about {{topic}}" prompt hands back
    # the model's own generic take; asking the *person* questions about
    # their own half-formed idea and writing up their answers is a genuinely
    # different output, and this app already has the one tool (`ask_user`)
    # that makes a real back-and-forth possible mid-skill.
    #
    # Its asking steps are `answer_only` rather than `tool_called` on
    # `ask_user`, and that is not an oversight: `ask_user` ends the turn by
    # handing over to the person, so it never reaches the runner as a tool
    # event at all. A contract naming it could not be met by anything.
    {
        "name": "Interview me about an idea",
        "description": "Asks you questions to draw out your own thinking, then saves it as a note, not the AI's take on the topic, yours.",
        "when_to_use": "when an idea is still half-formed and you want to think it through out loud, not be handed a generic explanation",
        "prompt": "Interview me about {{topic}}: ask me questions rather than explaining it back to me.",
        "steps": [
            _step(
                "Check whether I already have notes on {{topic}}, so you don't "
                "ask me to repeat what I've already written down.",
                "tool_called",
                "search_notes",
            ),
            _step(
                "Ask me one open question about {{topic}}: what's prompting "
                "it, or what I already think, and wait for my answer before "
                "asking anything else.",
                "answer_only",
            ),
            _step(
                "Ask 2-3 more questions, one at a time, each building on what "
                "I just said rather than a fixed list, the kind a good "
                "interviewer asks to get specifics instead of generalities.",
                "answer_only",
            ),
            _step(
                "Reflect back what you've understood, in my own words and "
                "phrasing where you can, and ask me to correct anything that's "
                "off before going further.",
                "answer_only",
            ),
            _step(
                "Write it up as a note: my thinking, in the order it came out, "
                "not a generic explanation of {{topic}} and not your own "
                "opinions on it. Ask before saving.",
                "answer_only",
            ),
        ],
        "inputs": [{"name": "topic", "label": "What idea do you want to think through?"}],
        "tools": [*_READING_TOOLS, "ask_user", "create_note"],
    },
    # BACKLOG §22: "the way skills are used... it doesn't recognise that it
    # needs to use tools" was fixed at the mechanism level (this module's own
    # header), but a user still has to know that shape exists to use it, 
    # `save_skill` already takes steps and a tool allowlist, so the missing
    # piece was never capability, only that nobody had wired an interview
    # around it. Reuses the same ask_user back-and-forth as the skill above,
    # aimed at *building* a skill instead of *thinking through* an idea.
    {
        "name": "Build a skill",
        "description": "Interviews you about a job you do often, then saves it as a real skill, with steps and an actual tool allowlist, not just a saved sentence.",
        "when_to_use": "when something you keep asking the AI to do by hand should become a one-click skill instead",
        "prompt": "Help me turn {{task}} into a saved skill.",
        "steps": [
            _step(
                "Call list_skills first: {{task}} may already be close to one "
                "that exists, and a near-duplicate is worse than refining the "
                "one that's there.",
                "tool_called",
                "list_skills",
            ),
            _step(
                "Ask what {{task}} should actually do, step by step, in the "
                "order they'd do it themselves, one question, wait for the "
                "answer, rather than a checklist dumped at once.",
                "answer_only",
            ),
            _step(
                "Ask whether it should ever change their notes (create, edit, "
                "tag, delete, set reminders) or only read and answer, this "
                "decides the tool allowlist.",
                "answer_only",
            ),
            _step(
                "Ask if any part of it should be a fill-in-the-blank each time "
                "it runs (a topic, a deadline, a tag) rather than fixed, that "
                "becomes the skill's inputs.",
                "answer_only",
            ),
            _step(
                "Draft the name, prompt, ordered steps, the specific tools "
                "each step needs (nothing broader), and when_to_use, then show "
                "the draft and ask before saving anything.",
                "answer_only",
            ),
            _step(
                "Save it with save_skill once they confirm, using exactly the "
                "steps and tools agreed, not a paraphrase.",
                "answer_only",
            ),
        ],
        "inputs": [{"name": "task", "label": "What do you want to turn into a skill?"}],
        "tools": [*_READING_TOOLS, "ask_user", "list_skills", "save_skill"],
    },
]


def builtins(known_tools: set[str] | None = None) -> list[dict]:
    """The shipped skills, normalised and marked as not editable."""
    return [
        {**normalise(skill, known_tools), "builtin": True} for skill in BUILTIN_SKILLS
    ]


def stored(config) -> list[dict]:
    """The user's own skills, exactly as saved."""
    return list(config.get_preference("skills", []) or [])


def catalog(config, known_tools: set[str] | None = None) -> list[dict]:
    """Everything runnable: built-ins first, then the user's own.

    A stored skill that no longer validates (a tool it named has since been
    renamed, say) is carried through as a prompt-only skill rather than
    dropped: losing someone's skill because a field went stale is worse than
    running it with fewer powers than it asked for.
    """
    out = builtins(known_tools)
    for raw in stored(config):
        try:
            skill = normalise(raw, known_tools)
        except SkillError:
            try:
                skill = normalise({"name": raw.get("name"), "prompt": raw.get("prompt")})
            except SkillError:
                continue
        out.append({**skill, "builtin": False})
    return out


def find(config, name: str, known_tools: set[str] | None = None) -> dict | None:
    """One runnable skill by name, built-in or the user's own."""
    wanted = str(name or "").strip()
    for skill in catalog(config, known_tools):
        if skill["name"] == wanted:
            return skill
    return None
