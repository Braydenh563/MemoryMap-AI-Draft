"""One budget for the whole prompt, derived from the model's actual window.

Asked for directly: *"make sure the AI can run as efficiently and effectively
as possible. I don't want it being too prompt and context heavy and then taking
ages to respond or failing due to a quickly maxed out token window."*

**The bug this exists to fix is that nothing added the parts up.** Every piece
of the prompt had its own cap, each individually reasonable, each tuned in a
different session against a different concern:

    system prompt (fixed)            2,416 chars   ~604 tok
    tool schemas                     4,096         ~1,024
    history (4 turns)                5,800         ~1,450
    notes (10 x MAX_NOTE_CHARS)      9,000         ~2,250
    tool results across a loop      24,000         ~6,000
    ------------------------------------------------------
    worst case                      45,312 chars ~11,328 tok

Against a 4,096-token window that is **2.8x over**, and the tool-result budget
alone exceeded the whole window by nearly half. Ollama drops overflow from the
*front*, which is the system prompt, so the failure is not an error message,
it is the model quietly forgetting it has tools and answering from nothing.
That is exactly the reported "fails once the token window maxes out".

So the caps are no longer constants. Each is a share of what is actually left
after the two things that cannot be traded away: the system prompt, and room
for the model to answer in. On a 4k model everything tightens; on a 32k model
the app becomes *more* capable than the old constants allowed, because those
were sized for the smallest case and applied to everyone.

Chars rather than tokens throughout: a real tokeniser per model is a download
and a dependency, ~4 chars/token is close enough for a stop rule, and being
approximately right on every model beats being exactly right on one.
"""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4

# Room kept back for the answer itself. Ollama's num_ctx covers the prompt and
# the response together, so a prompt that fills the window leaves the model
# nowhere to reply: it stops mid-sentence, which reads as a crash rather than
# a budget. 15% of 4,096 is ~600 tokens, about 450 words: enough for a real
# answer, and generous on any larger model.
OUTPUT_RESERVE_SHARE = 0.15

# How the remainder is divided. These are shares of what is LEFT after the
# system prompt and the output reserve, not of the whole window, so they cannot
# quietly add up to more than exists.
#
# Tool schemas get the largest share because they are the price of the agent
# working at all, and results get the same because a tool loop that cannot hold
# its own output has to stop early and say so. Notes and history are the parts
# a model can recover by *asking*, `get_note` reads a note in full, and the
# conversation is still on screen, so they yield first when space is short.
TOOL_SCHEMA_SHARE = 0.30
TOOL_RESULT_SHARE = 0.30
NOTES_SHARE = 0.25
HISTORY_SHARE = 0.15

# Floors, in characters. A share of a very small window can round down to
# something useless, and "one note, badly cut" is worse than the app admitting
# the model is too small for the job. These are the smallest amounts at which
# each part still does something.
MIN_TOOL_SCHEMA_CHARS = 600  # roughly one tool
MIN_NOTES_CHARS = 900  # one note at full length
MIN_HISTORY_CHARS = 400  # one short exchange
MIN_TOOL_RESULT_CHARS = 800  # one tool's answer


@dataclass(frozen=True)
class ContextBudget:
    """How many characters each part of one turn may spend."""

    window_tokens: int
    system_chars: int
    output_reserve_chars: int
    tool_schema_chars: int
    tool_result_chars: int
    notes_chars: int
    history_chars: int

    @property
    def prompt_chars(self) -> int:
        """Everything that goes up, if every part spends its whole allowance."""
        return (
            self.system_chars
            + self.tool_schema_chars
            + self.tool_result_chars
            + self.notes_chars
            + self.history_chars
        )

    @property
    def fits(self) -> bool:
        """Does the worst case leave room for an answer? The whole point."""
        return (
            self.prompt_chars + self.output_reserve_chars
            <= self.window_tokens * CHARS_PER_TOKEN
        )

    def as_log_line(self) -> str:
        return (
            f"context budget: {self.window_tokens} tok window -> "
            f"system={self.system_chars} tools={self.tool_schema_chars} "
            f"results={self.tool_result_chars} notes={self.notes_chars} "
            f"history={self.history_chars} reply={self.output_reserve_chars} chars"
        )


def plan(window_tokens: int, system_chars: int) -> ContextBudget:
    """Divide one model's window between the parts of one turn.

    `system_chars` is measured rather than assumed, because the persona is
    user-editable: a long custom persona genuinely does leave less room for
    everything else, and pretending otherwise is how the total drifts over.
    """
    window_chars = max(0, window_tokens) * CHARS_PER_TOKEN
    reserve = int(window_chars * OUTPUT_RESERVE_SHARE)
    available = window_chars - reserve - system_chars

    if available <= 0:
        # The persona and the reply do not fit on their own. Nothing sensible
        # can be allocated; hand back the floors so the caller still has a
        # working (if cramped) turn rather than zeroes, and let `fits` report
        # the truth.
        return ContextBudget(
            window_tokens=window_tokens,
            system_chars=system_chars,
            output_reserve_chars=reserve,
            tool_schema_chars=MIN_TOOL_SCHEMA_CHARS,
            tool_result_chars=MIN_TOOL_RESULT_CHARS,
            notes_chars=MIN_NOTES_CHARS,
            history_chars=MIN_HISTORY_CHARS,
        )

    return ContextBudget(
        window_tokens=window_tokens,
        system_chars=system_chars,
        output_reserve_chars=reserve,
        tool_schema_chars=max(
            MIN_TOOL_SCHEMA_CHARS, int(available * TOOL_SCHEMA_SHARE)
        ),
        tool_result_chars=max(
            MIN_TOOL_RESULT_CHARS, int(available * TOOL_RESULT_SHARE)
        ),
        notes_chars=max(MIN_NOTES_CHARS, int(available * NOTES_SHARE)),
        history_chars=max(MIN_HISTORY_CHARS, int(available * HISTORY_SHARE)),
    )


def fit_notes(notes: list[dict], budget_chars: int, render) -> tuple[list[dict], int]:
    """(the notes that fit, how many were left out).

    Retrieval hands back its best guesses in order, so dropping from the tail
    drops the least relevant. Cutting every note shorter instead would be the
    wrong trade: ten notes clipped to a sentence each are ten things the model
    cannot quote, where four whole ones are four it can.
    """
    if budget_chars <= 0 or not notes:
        return notes, 0
    kept: list[dict] = []
    spent = 0
    for note in notes:
        cost = len(render(note)) + 40  # + the numbering and category wrapper
        if kept and spent + cost > budget_chars:
            break
        kept.append(note)
        spent += cost
    return kept, len(notes) - len(kept)


def fit_history(messages: list[dict], budget_chars: int) -> list[dict]:
    """The most recent exchanges that fit, oldest dropped first.

    Kept in whole user/assistant pairs: half an exchange is a question with no
    answer or an answer with no question, and a model reading either will
    happily invent the missing side.
    """
    if budget_chars <= 0 or not messages:
        return []
    pairs = [messages[i : i + 2] for i in range(0, len(messages), 2)]
    kept: list[dict] = []
    spent = 0
    for pair in reversed(pairs):
        cost = sum(len(m.get("content", "")) for m in pair)
        if kept and spent + cost > budget_chars:
            break
        kept = pair + kept
        spent += cost
    return kept
