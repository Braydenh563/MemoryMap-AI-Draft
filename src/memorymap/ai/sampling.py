"""Sampling parameters: what the model recommends, what the task needs, what you set.

Asked for directly: *"there should be advanced settings … for the response
parameters like top-k, top-p, repeat penalty etc. because different models
require different parameters to get the same result?? Is there a way to detect
this and auto adjust accordingly?"*

**Yes, and it does not need a guess.** A GGUF ships its author's recommended
sampling parameters in its own metadata, and Ollama hands them over in
``/api/show`` under ``parameters``, `temperature 0.6`, `top_p 0.95`,
`repeat_penalty 1.1`, one per line. This app has been calling ``/api/show`` for
the context window and the capability list since those were added, caching the
whole payload, and dropping that field on the floor. So "detect the right
parameters for this model" is a parsing problem, not a research problem: the
model already told us.

That matters because the alternative, a table of recommended settings per
model family, maintained by hand, is exactly the kind of thing that is right
on the day it is written and quietly wrong six months later, and wrong in a way
nobody can see. Reading the model's own file cannot go stale.

Four sources, and the order between them is the whole design
------------------------------------------------------------
Later beats earlier:

1. **The backend's default.** Expressed by sending nothing at all. An absent
   key means "whatever you normally do"; a key set to null is an instruction to
   use nothing, which some backends reject and others read as zero. Omission is
   load-bearing here exactly as it is in `presets.sampling_options`.
2. **The model's own recommendation**, parsed from ``/api/show``.
3. **The task preset** (`ai/presets.py`), Quick/Normal/Detailed, and the
   per-feature choices around them. A preset only sets what it has a *reason*
   to set: Quick lowers temperature because looking something up wants the
   likeliest words. It does not touch `top_k`, because "how literal should this
   answer be" says nothing about how wide the candidate pool should be.
4. **The user's own override**, from Settings. Always wins, and is stored
   sparsely, only the fields actually changed, so a model with different
   recommendations still gets its own for everything untouched.

The sparse storage is the part worth being careful about. Storing a full set of
values the moment the panel is opened would silently pin one model's
recommendations onto every other model the user ever runs, which is the precise
failure this module exists to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Knob:
    """One sampling parameter, and what a person needs to know to touch it."""

    #: The Ollama option name. Also the preference key suffix.
    name: str
    label: str
    #: Plain-language, and about the effect rather than the mechanism, "how
    #: adventurous" is actionable, "softmax temperature" is not.
    help: str
    minimum: float
    maximum: float
    step: float
    #: True when the backend wants a whole number (`top_k`, `num_predict`).
    integer: bool = False


#: The knobs offered, in the order they are shown.
#:
#: Deliberately short. Every one of these is a parameter people actually change
#: when a local model misbehaves, a repeat penalty for a model that loops, a
#: min_p for one that rambles. `mirostat`, `tfs_z` and the rest are left out:
#: they are real, and offering fourteen sliders to someone who wanted their
#: model to stop repeating itself is not help.
KNOBS: tuple[Knob, ...] = (
    Knob("temperature", "Temperature",
         "How adventurous the wording is. Lower repeats the likeliest words; "
         "higher takes more risks.", 0.0, 2.0, 0.05),
    Knob("top_p", "Top-p",
         "Ignores the least likely words. 0.9 keeps the top 90% of "
         "probability; lower is tighter.", 0.0, 1.0, 0.01),
    Knob("top_k", "Top-k",
         "Only ever consider this many candidate words. 0 turns the limit "
         "off.", 0, 200, 1, integer=True),
    Knob("min_p", "Min-p",
         "Drops any word far less likely than the best one. Often a better "
         "handle than top-p on small models.", 0.0, 1.0, 0.01),
    Knob("repeat_penalty", "Repeat penalty",
         "Pushes the model away from words it has just used. Raise it if it "
         "loops; above about 1.3 it starts avoiding ordinary words too.",
         0.5, 2.0, 0.01),
    Knob("repeat_last_n", "Repeat window",
         "How far back the repeat penalty looks, in tokens. -1 means the "
         "whole context.", -1, 2048, 1, integer=True),
)

KNOBS_BY_NAME = {knob.name: knob for knob in KNOBS}

#: `/api/show`'s `parameters` field: one `key value` per line, values sometimes
#: quoted, and repeated keys for list-valued ones like `stop`.
_PARAM_LINE = re.compile(r"^\s*(\w+)\s+(.+?)\s*$")


def parse_model_parameters(shown: dict) -> dict[str, float]:
    """A model's own recommended values for the knobs above, from `/api/show`.

    Only the knobs this app offers are returned, and only when they parse as a
    number: `stop` sequences and any future string-valued parameter are not
    sampling knobs and must not end up in an options block as text.

    Never raises, and returns {} for anything unexpected. A model with no
    recommendations, a backend that does not report them, and a malformed
    payload all mean the same thing here, use the backend's defaults, and
    that is the safe answer for all three.
    """
    raw = (shown or {}).get("parameters")
    if not isinstance(raw, str):
        return {}
    out: dict[str, float] = {}
    for line in raw.splitlines():
        match = _PARAM_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip().strip('"')
        knob = KNOBS_BY_NAME.get(key)
        if knob is None:
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        # A model recommending something outside the range this app offers is
        # reporting a value the app cannot show a control for. Clamped rather
        # than dropped: the recommendation is still better information than the
        # backend default, and the slider would otherwise disagree with what is
        # actually being sent.
        number = max(knob.minimum, min(knob.maximum, number))
        out[key] = int(number) if knob.integer else number
    return out


def resolve(
    model_defaults: dict | None = None,
    preset: dict | None = None,
    overrides: dict | None = None,
) -> dict:
    """The options block to send, and nothing more, see the module docstring.

    Anything not set by any layer is simply absent, which is how the backend is
    told to use its own default.
    """
    merged: dict = {}
    for layer in (model_defaults, preset, overrides):
        for key, value in (layer or {}).items():
            if value is None or key not in KNOBS_BY_NAME:
                continue
            knob = KNOBS_BY_NAME[key]
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            number = max(knob.minimum, min(knob.maximum, number))
            merged[key] = int(number) if knob.integer else number
    return merged


def explain(
    model_defaults: dict | None = None,
    preset: dict | None = None,
    overrides: dict | None = None,
) -> dict[str, str]:
    """Where each resolved value came from, for the settings panel.

    "Temperature is 0.6" is not useful on its own, "0.6, recommended by this
    model" and "0.6, because you set it" want different buttons next to them,
    and the second should be revertible while the first has nothing to revert
    to.
    """
    sources: dict[str, str] = {}
    for key in resolve(model_defaults, preset, overrides):
        if key in (overrides or {}):
            sources[key] = "you"
        elif key in (preset or {}):
            sources[key] = "task"
        elif key in (model_defaults or {}):
            sources[key] = "model"
    return sources


def as_dicts() -> list[dict]:
    """The knob catalogue for the settings UI, one table, on the server, for
    the same reason `core/filetypes.py` is: a second copy in JS is a second
    thing to keep in step, and the failure mode is a slider whose range
    disagrees with what the backend will accept."""
    return [
        {
            "name": knob.name,
            "label": knob.label,
            "help": knob.help,
            "min": knob.minimum,
            "max": knob.maximum,
            "step": knob.step,
            "integer": knob.integer,
        }
        for knob in KNOBS
    ]
