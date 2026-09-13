"""The per-run budget: how many tokens and how long one job may take.

WORLD_CLASS_PLAN 4 B5, SESSION_BRIEFS Brief 13, spec in
`tests/test_harness_verifier_spec.py`.

**The gap this fills.** Every loop in `agent.py` is bounded per *turn*:
`MAX_ROUNDS`, `EARNED_ROUNDS`, `MAX_TOOL_FAILURES`, the tool-result cap. A
skill run is many turns, one per step, plus a retry per unmet contract and up
to two re-plans, and every one of them starts its own fresh allowance. So a
run that goes wrong does not loop, it *grinds*: ten steps, three attempts
each, six rounds apiece, each round a full prefill of the system prompt, the
notes and the tool schemas. Nothing anywhere knew what the whole thing had
cost, and on a local model the cost the user actually feels is minutes of a
saturated GPU.

**Why a context variable and not a parameter.** Taken directly from
`core/events.py`, which solved the same shape of problem for the actor of a
write: the thing that has to be true is *every model call made inside a run
counts against that run*, and a parameter threaded through `run_skill` into
`run_agent` is true only of the call sites somebody remembered to change. A
scope is true of the ones written later too, which is the whole point: the
next feature that calls `run_agent` from inside a run (a verifier that asks
the model, a re-plan, a summariser between steps) participates without
knowing this module exists.

**What it does not do.** It does not kill a request in flight: the check
happens between rounds, so the longest a run can overshoot by is one model
call. Stopping mid-stream would leave a half-written answer on screen and a
tool call whose result nobody read, which is a worse failure than finishing
the round. And it is advisory for *cost*, not for safety: nothing here can
roll back a write the run already made, which is why a run that hits its
budget still reports what it changed and how to undo it.

**Not verified**: the token counts come from the provider's own `stats`, and
`tests/` runs every provider against a fake transport (CLAUDE.md section 4).
What is measured here is that a budget is charged, checked and enforced on
the numbers a provider reports, not what a real 4B model reports for a real
run.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

#: Defaults, from Brief 13: 20k tokens and 90 seconds per run.
#:
#: Both are "a run that has gone wrong", not "a big job". Twenty thousand
#: tokens is roughly six full rounds against an 8k window, which is more than
#: any single step of a shipped skill has ever needed; ninety seconds is
#: longer than a ten-step run takes when each step works first time. A budget
#: set where a working run would hit it is a budget that teaches people to
#: turn it off.
DEFAULT_TOKENS = 20_000
DEFAULT_SECONDS = 90

#: What a round is charged when the provider reports no token counts at all.
#: Not zero: a transport that reports nothing would otherwise make the token
#: half of the budget unenforceable, and "the budget silently did nothing"
#: is the failure mode that matters. Roughly one small round.
ASSUMED_ROUND_TOKENS = 500


@dataclass
class RunBudget:
    """What one run may spend, and what it has spent.

    `stopped` is set the first time a check fails, and stays set: the reason
    a run ended has to survive to the `result` event, several turns later.
    """

    tokens: int = DEFAULT_TOKENS
    seconds: float = DEFAULT_SECONDS
    spent_tokens: int = 0
    rounds: int = 0
    started_at: float = field(default_factory=time.monotonic)
    stopped: str = ""

    def charge(self, stats: dict | None) -> None:
        """Count one model round against this run."""
        self.rounds += 1
        used = 0
        if isinstance(stats, dict):
            for key in ("prompt_tokens", "output_tokens"):
                value = stats.get(key)
                if isinstance(value, int) and value > 0:
                    used += value
        self.spent_tokens += used or ASSUMED_ROUND_TOKENS

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def exceeded(self) -> str:
        """`""` while there is room, else the sentence saying what ran out.

        One sentence, in the second person, because it is shown to the person
        watching the run and has to say what to do next. Naming the number is
        the difference between "it gave up" and "it did as much as it was
        allowed to".
        """
        if self.stopped:
            return self.stopped
        if self.tokens and self.spent_tokens >= self.tokens:
            self.stopped = (
                f"this run reached its budget of {self.tokens:,} tokens after "
                f"{self.rounds} rounds. Resume picks up from here, or raise the "
                "budget in Settings."
            )
        elif self.seconds and self.elapsed() >= self.seconds:
            self.stopped = (
                f"this run reached its time budget of {int(self.seconds)}s. "
                "Resume picks up from here, or raise the budget in Settings."
            )
        return self.stopped


_current: ContextVar[RunBudget | None] = ContextVar("memorymap_run_budget", default=None)


def current() -> RunBudget | None:
    """The budget the code running right now is spending, if any.

    None for an ordinary chat turn, which is bounded per turn already and has
    no notion of a run to belong to.
    """
    return _current.get()


@contextmanager
def spending(budget: RunBudget | None):
    """Everything done inside this block counts against `budget`.

    Nested scopes are left alone deliberately, the same call the outermost
    write scope in `core/events.py` makes: a run that somehow starts another
    run is one job as far as cost is concerned, and giving the inner one a
    fresh allowance is exactly the hole `tools.RUN_STARTERS` exists to close.
    """
    if budget is None or _current.get() is not None:
        yield _current.get()
        return
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def from_settings(config) -> RunBudget:
    """The budget one run gets, read from the user's settings.

    Zero in either field means "no limit on this one", which is a real answer
    for somebody running a ten-step audit over four thousand notes on hardware
    they are happy to give an hour to. Never raises: a settings file holding
    the word "lots" falls back to the default rather than failing the run that
    was about to start.
    """
    def _number(key: str, fallback):
        try:
            value = type(fallback)(config.get_preference(key, fallback))
        except (TypeError, ValueError):
            return fallback
        return value if value >= 0 else fallback

    return RunBudget(
        tokens=int(_number("run_budget_tokens", DEFAULT_TOKENS)),
        seconds=float(_number("run_budget_seconds", float(DEFAULT_SECONDS))),
    )
