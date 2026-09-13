"""The launcher's status file, parsed.

`start.sh` and `start.bat` write one line per phase transition into the
file named by MM_SPLASH_FILE:

    step|total|title|detail|state          state in active, done, failed

Appended, never rewritten, so the file is a history rather than a single
current value. That matters because the window that renders it opens late:
the Python loading window in `__main__.py` only exists once the git pull,
the venv build and the pip install have already finished, and without the
history it would show an empty list and only learn about the steps still
to come. With it, the handoff shows Update, Python and Dependencies
already ticked.

Three surfaces read this shape: `scripts/splash.ps1` has its own
implementation, because it runs before Python exists and cannot import
anything; `__main__.py`'s `_LOADING_HTML` seeds itself from this module;
and the tests check the two implementations agree on the grammar.

Malformed lines are dropped rather than raised on. A status file is
diagnostics, not input: a half-written line caught mid-append, a stray
echo, or a file left over from an older version must never be able to stop
a launch that is otherwise working.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The three states a step can be in. `active` is the step being worked on
#: right now; `done` and `failed` are terminal for that step.
STATES = ("active", "done", "failed")

#: A launcher writes at most this many steps, so a line claiming more is a
#: corrupt line rather than a future version. Generous on purpose: the
#: point is to reject nonsense, not to pin today's five.
MAX_TOTAL = 20


@dataclass(frozen=True)
class Step:
    """One line of the protocol."""

    step: int
    total: int
    title: str
    detail: str
    state: str

    @property
    def done(self) -> bool:
        return self.state == "done"

    @property
    def failed(self) -> bool:
        return self.state == "failed"


def parse_line(line: str) -> Step | None:
    """One protocol line, or None if it is not one.

    Split with a bounded `maxsplit` so a bar inside the *detail* text is
    kept rather than turning one good line into a rejected one: only the
    first four bars are separators, whatever follows belongs to the last
    field. The detail is the free-text field, and free text is exactly
    where a stray bar comes from.
    """
    if not line:
        return None
    parts = line.rstrip("\r\n").split("|")
    if len(parts) < 5:
        return None
    # Re-join anything past the fifth field into `detail`, then take the
    # last part as the state: state is a fixed vocabulary, detail is not.
    step_s, total_s, title = parts[0], parts[1], parts[2]
    state = parts[-1].strip()
    detail = "|".join(parts[3:-1])
    if state not in STATES:
        return None
    try:
        step, total = int(step_s), int(total_s)
    except ValueError:
        return None
    if not 1 <= total <= MAX_TOTAL:
        return None
    if not 1 <= step <= total:
        return None
    title = title.strip()
    if not title:
        return None
    return Step(step=step, total=total, title=title, detail=detail.strip(), state=state)


def parse(text: str) -> list[Step]:
    """Every parseable line, in order. Unparseable ones are skipped."""
    steps = []
    for line in text.splitlines():
        parsed = parse_line(line)
        if parsed is not None:
            steps.append(parsed)
    return steps


def read_file(path: str | None) -> list[Step]:
    """The history in the file at `path`, or an empty list.

    Never raises. The file lives in TEMP, is written by another process,
    and is deleted the moment the loading window is on screen, so every
    one of "no path", "already gone", "not readable" and "not text" is an
    ordinary outcome rather than an error.
    """
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return parse(handle.read())
    except OSError:
        return []


def latest(steps: list[Step]) -> Step | None:
    """The line that is current: the last one written."""
    return steps[-1] if steps else None


def summarise(steps: list[Step]) -> list[Step]:
    """One entry per step number, the last state each reached, in order.

    The history carries a line per *transition*, so a step appears twice:
    once active, once done. A step list wants one row each, showing where
    that step ended up, which is what this collapses it to.
    """
    by_step: dict[int, Step] = {}
    for entry in steps:
        by_step[entry.step] = entry
    return [by_step[key] for key in sorted(by_step)]


def percent(steps: list[Step]) -> int:
    """Steps finished over total, 0 to 100.

    The active step counts as not yet done, which is why this is a count
    of `done` rather than the current step number: a bar that jumps to
    100% while the last and longest phase is still running is the lie the
    old marquee existed to avoid. A failed step does not count as done
    either, so the bar stops where the failure happened.
    """
    rows = summarise(steps)
    if not rows:
        return 0
    total = rows[-1].total
    finished = sum(1 for row in rows if row.done)
    return max(0, min(100, finished * 100 // total))
