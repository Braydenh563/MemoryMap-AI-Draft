"""Quick, normal, detailed: one dial over the settings a turn actually needs (§11).

**The gap this closes.** The prompt side of a turn is budgeted carefully:
`ai/context.py` rations every part of the input against the model's real
window. The *output* side had one number for everything, `num_predict` was a
flat 1,024 whether the question was "when did I write about beans" or "draft me
a summary of the last month". Output tokens are generated one at a time, so
they cost far more wall-clock each than prompt tokens do: an unbounded or
over-generous reply cap is the single most common reason an answer "takes
ages", and a uniform one means every short question pays for the possibility of
a long answer.

**Why a preset rather than automatic.** Choosing settings *by task* needs a
"how hard is this turn" judgement, which is itself a model call, and it fails
by being wrong confidently rather than obviously. A preset the person picks is
honest about being a preset. Automatic routing can be layered on later; it
cannot be un-layered once someone has learned not to trust it.

**What varies, and why each one.**

- `max_output_tokens`, the direct latency lever, and the reason this exists.
- `temperature`, recalling what you wrote wants the likeliest words; drafting
  and brainstorming want room to move. Sending 0.8 for "when did I write X" is
  asking a fact question to be creative.
- `think`, reasoning models spend output tokens *before* the answer starts.
  On a quick lookup that is the whole latency budget spent on deliberation
  nobody reads.
- `length_hint`, the model has to be told, not only capped. A cap alone
  truncates mid-sentence, which reads as a crash; a hint plus a cap produces a
  short answer that ends.

**Failing closed on a model that can't.** Not every model supports a thinking
toggle, and `think` sent to one that doesn't is either ignored or an error
depending on the backend and its version. So the toggle is only ever sent when
it is being turned *off*, and only where the backend has somewhere to put it, 
turning thinking off on a model with none is a no-op either way, while turning
it on where it isn't supported is the request that fails. Sending nothing is
always the safe direction, because "nothing" means "whatever the model does by
default", which is what happened before this module existed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResponseMode:
    """One preset. Everything a turn's *output* side needs, in one place."""

    #: Stored in preferences and sent by the UI.
    id: str
    #: Shown on the picker.
    label: str
    #: What the user gets, in the tooltip.
    description: str
    #: The reply cap: `num_predict` on Ollama, `max_tokens` on OpenAI.
    max_output_tokens: int
    #: Lower is more literal. None means "whatever the backend defaults to",
    #: which is what every turn got before this existed.
    temperature: float | None
    #: False asks a reasoning model not to think. None never sends the field, 
    #: see the module docstring on failing closed.
    think: bool | None
    #: Appended to the system prompt. A cap without a hint truncates
    #: mid-sentence, which reads as a crash rather than as brevity.
    length_hint: str


MODES: dict[str, ResponseMode] = {
    "quick": ResponseMode(
        id="quick",
        label="Quick",
        description="Short, literal answers. Fastest: best for looking something up.",
        # Roughly 200 words. Enough for a fact, a date, or a list of note
        # titles, which is what this mode is for.
        max_output_tokens=256,
        temperature=0.2,
        think=False,
        length_hint=(
            " Answer in at most two or three sentences. Do not explain your "
            "reasoning, and do not add caveats or suggestions unless asked."
        ),
    ),
    "normal": ResponseMode(
        id="normal",
        label="Normal",
        description="The balanced default: a full answer, not a summary.",
        # The value every turn used before presets existed, kept deliberately:
        # the default mode must not change anyone's experience on upgrade.
        max_output_tokens=1024,
        temperature=None,
        think=None,
        # **It used to say nothing at all, and that was the bug.** Reported:
        # *"the normal (balanced) setting writes too concisely, it is closer to
        # the quick setting."* Exactly right, and an empty hint is why, the
        # two neighbouring modes both steer, so with no sentence of its own
        # Normal inherited whatever the base prompt implied, and the base
        # prompt is written for a local model on a budget and leans terse. A
        # default that is the absence of an instruction is not a middle
        # setting; it is whichever end the surrounding text happens to pull to.
        #
        # This asks for the middle explicitly. It does not raise the cap: 1024
        # tokens is ~750 words and the old answers were nowhere near it, so the
        # ceiling was never what was binding, the instruction was.
        length_hint=(
            " Give a complete answer in a short paragraph or two: say what the "
            "notes actually say, with the specifics, rather than summarising "
            "them in a sentence. Stop once the question is answered."
        ),
    ),
    "detailed": ResponseMode(
        id="detailed",
        label="Detailed",
        description="Longer, more thorough answers. Slower: best for drafting.",
        max_output_tokens=3072,
        temperature=0.8,
        think=None,  # let a reasoning model reason; that is the point here
        length_hint=(
            " Be thorough. Work through the relevant notes, draw connections "
            "between them, and explain your reasoning."
        ),
    ),
}

#: What a turn gets when nobody has said otherwise. `normal` reproduces the
#: behaviour that predates this module exactly.
DEFAULT_MODE = "normal"


def resolve(mode: str | None) -> ResponseMode:
    """The preset for a name, falling back rather than raising.

    Reached from a preference file the user may have edited by hand and from a
    request body, so an unknown name is a thing to absorb. Falling back to
    `normal` means a typo costs the setting, not the chat.
    """
    return MODES.get((mode or "").strip().lower(), MODES[DEFAULT_MODE])


def sampling_options(mode: ResponseMode) -> dict:
    """The parts of a preset that go in the request, omitting what isn't set.

    Omission is load-bearing: a key that is absent means "the backend's own
    default", which is exactly what every turn used before presets existed. A
    key present with a null would instead be an explicit instruction to use
    nothing, which some backends reject and others read as zero.
    """
    options: dict = {}
    if mode.temperature is not None:
        options["temperature"] = mode.temperature
    return options
