"""How one golden ask is scored, and what a score means.

Two halves, weighted equally, because they fail independently and a single
number that hid either would be useless for finding a regression:

**Tool choice.** Was the tool that answers this ask actually offered for it?
`tools.focus_for` is the app's own answer to that question, a deterministic
keyword router that narrows the schemas a turn puts on the wire (and, in
small-model mode, is most of what decides what a 4B model can do at all). It
returns `None` when it declines to narrow, which means the whole registry is
offered and the tool *is* reachable; that scores, but it is counted separately
as well, because a router that narrowed nothing would score a perfect 1.0 and
have stopped working. The `forbid` list is the other direction: a read must
not put `delete_note` on the wire.

**Citation correctness.** Run the tool with the golden arguments against the
fixture notebook and ask whether the answer names the right things, read off
`ai/cards.py`, so this scores exactly what the chat would put in front of the
reader as openable cards, not some private view of the result. A case whose
tool has no cards (a count, a tag list) carries a `check` predicate instead.

**Why not "did the model pick the right tool".** Because there is no model in
CI: every provider test here runs against a fake transport (CLAUDE.md's
standing caveat), and a fake that calls whatever it was scripted to call would
be scoring the script. `scripts/eval.py` runs the same set against a real
local model and scores exactly that, which is the half only a real model can
answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from memorymap.ai import cards, tools
from tests.eval.fixture import Notebook
from tests.eval.golden import Ask


@dataclass
class Score:
    """One case, scored."""

    id: str
    tool_choice: float
    citation: float
    #: Whether the router narrowed at all for this ask, reported, never
    #: scored. See the module docstring.
    narrowed: bool
    note: str = ""

    @property
    def total(self) -> float:
        return (self.tool_choice + self.citation) / 2


def score_tool_choice(case: Ask) -> tuple[float, bool, str]:
    """Is the answering tool reachable for this ask, and is nothing dangerous?"""
    offered = tools.focus_for(case.ask)
    narrowed = offered is not None
    reachable = offered is None or case.tool in offered
    problems = []
    if not reachable:
        problems.append(f"{case.tool} was not offered (offered: {', '.join(sorted(offered))})")
    for banned in case.forbid:
        if offered is not None and banned in offered:
            problems.append(f"{banned} was offered for a read")
        elif offered is None and banned in tools.CORE_TOOLS:
            # Nothing was narrowed, so everything in the core set is on the
            # wire: including this one. Worth saying, not worth failing on:
            # the destructive tools are gated again at execution.
            problems.append(f"nothing was narrowed, so {banned} is on the wire")
    return (0.0 if problems else 1.0), narrowed, "; ".join(problems)


def score_citation(session: Session, case: Ask, book: Notebook) -> tuple[float, str]:
    """Run the tool for real and check what it comes back naming."""
    result = tools.execute_tool(session, case.tool, case.arguments(book))
    if "error" in result:
        return 0.0, f"the tool errored: {result['error']}"
    wanted = case.cites(book)
    if wanted:
        got = {
            (group["kind"], item["id"])
            for group in cards.result_cards(case.tool, result)
            for item in group["items"]
        }
        missing = [pair for pair in wanted if pair not in got]
        if missing:
            return (len(wanted) - len(missing)) / len(wanted), (
                f"did not cite {missing} (cited: {sorted(got)})"
            )
        return 1.0, ""
    if case.check is not None:
        try:
            return (1.0 if case.check(result, book) else 0.0), ("" if case.check(result, book) else "the answer was wrong")
        except Exception as exc:  # noqa: BLE001  # a broken check is a failed case, not a crashed run
            return 0.0, f"the check raised {exc!r}"
    return 0.0, "the case declared neither citations nor a check"


def score_case(session: Session, case: Ask, book: Notebook) -> Score:
    choice, narrowed, choice_note = score_tool_choice(case)
    citation, citation_note = score_citation(session, case, book)
    return Score(
        id=case.id,
        tool_choice=choice,
        citation=citation,
        narrowed=narrowed,
        note="; ".join(part for part in (choice_note, citation_note) if part),
    )


def report(scores: list[Score]) -> str:
    """The table the CI run prints. Failures first: a passing row says
    nothing anybody needs to read, and burying four bad rows in thirty good
    ones is how a score becomes decoration."""
    lines = ["", f"eval: {len(scores)} golden asks over the fixture notebook", ""]
    bad = [s for s in scores if s.total < 1.0]
    for s in sorted(bad, key=lambda s: s.total):
        lines.append(f"  {s.total:>4.0%}  {s.id:<22} tool={s.tool_choice:.0f} cite={s.citation:.2f}  {s.note}")
    if not bad:
        lines.append("  every case scored 1.00")
    total = sum(s.total for s in scores) / max(1, len(scores))
    choice = sum(s.tool_choice for s in scores) / max(1, len(scores))
    citation = sum(s.citation for s in scores) / max(1, len(scores))
    narrowed = sum(1 for s in scores if s.narrowed) / max(1, len(scores))
    lines += [
        "",
        f"  score       {total:.3f}   ({len(scores)} cases)",
        f"  tool choice {choice:.3f}",
        f"  citation    {citation:.3f}",
        f"  narrowed    {narrowed:.0%} of asks (reported, not scored)",
        "",
    ]
    return "\n".join(lines)
