"""Numbered citations inside an AI answer, not only in a row beneath it.

Asked for directly: *"inline referencing with hyperlinks in ai chat messages
would be amazing."*

The data always existed, `ground_answer_sentences` returns {sentence,
note_id} pairs: and only ever reached a chip row under the answer, which is
the one place a claim and its source are *not* read together.

Asserted against the source because this app has no DOM in its Python suite
(same reason `test_frontend_ids.py` exists). The behaviour itself was driven
in Chromium: two grounded sentences in one paragraph produced markers 1 and 2
in the right places, a grounded sentence that does not appear in the answer
produced none, and the chips renumbered to match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


@pytest.fixture(scope="module")
def app_js() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_function_exists(app_js):
    assert "function addInlineCitations(" in app_js


def test_it_is_actually_called(app_js):
    """CLAUDE.md's own "features that never ran once" category: a function
    with no call site is not a feature. `renderAnswerGrounding` is the one
    place that has both the sentences and the answer element."""
    assert "addInlineCitations(answerEl, sentences, rawResults)" in app_js


def _grounding_call_args(app_js: str) -> list[list[str]]:
    """The argument list of every `renderAnswerGrounding` call, one list of
    trimmed source expressions per call site, the definition excluded.

    Read positionally rather than grepped for a needle, because the first
    version of this test asserted the literal text `"answerBox\n"`: true only
    while the answer element happened to be the *last* argument. Adding a
    fifth argument (the turn's question, so opening a source teaches the
    search) broke the assertion without breaking anything it was protecting.
    A test whose failure does not mean the bug it names is a test that gets
    widened next time, so it reads the position instead.
    """
    calls = []
    needle = "renderAnswerGrounding("
    at = app_js.find(needle)
    while at != -1:
        start = at + len(needle)
        depth, end = 1, start
        while depth:
            char = app_js[end]
            depth += {"(": 1, ")": -1}.get(char, 0)
            end += 1
        # Comments explaining an argument sit on their own lines above it, and
        # they contain commas and parentheses of their own, so they go before
        # anything is split.
        body = "\n".join(
            line
            for line in app_js[start : end - 1].splitlines()
            if not line.strip().startswith("//")
        )
        # The definition, not a call: its argument list names the parameters.
        if "target" not in body.split(",")[0]:
            args, depth, current = [], 0, []
            for char in body:
                if char in "([{":
                    depth += 1
                elif char in ")]}":
                    depth -= 1
                if char == "," and depth == 0:
                    args.append("".join(current))
                    current = []
                else:
                    current.append(char)
            args.append("".join(current))
            calls.append([" ".join(arg.split()) for arg in args])
        at = app_js.find(needle, end)
    return calls


def test_every_grounding_call_site_passes_the_answer_element(app_js):
    """Three surfaces render grounding, the Ask box, a live chat turn, and a
    reopened conversation. A call site that forgets the fourth argument gets
    the chips and silently no markers, which is exactly the half-wired state
    this file exists to prevent."""
    calls = _grounding_call_args(app_js)
    assert len(calls) == 3, f"expected 3 call sites, found {len(calls)}"
    fourth = sorted(args[3] for args in calls if len(args) > 3)
    assert len(fourth) == 3, f"a call site passes no answer element: {calls}"
    assert fourth == sorted(
        [
            "answerBox",
            'bubble.querySelectorAll(".bubble-answer")',
            'handles.bubble?.querySelectorAll(".bubble-answer") || null',
        ]
    ), fourth


def test_a_chat_turn_hands_over_all_of_its_prose_blocks(app_js):
    """INBOX 40: a skill run and an agent turn showed no markers at all.

    The timeline gives each step's prose its own `.bubble-answer` node, so
    `querySelector` handed the citation walker step 1's narration while every
    grounded sentence was in the final answer, several nodes further down.
    `querySelectorAll` is the fix and the rule: a call site that narrows back
    to one node silently loses the markers again on exactly the two surfaces
    that need them most.
    """
    assert 'querySelector(".bubble-answer")' not in app_js
    assert app_js.count('querySelectorAll(".bubble-answer")') == 3


def test_the_live_renderer_is_stopped_before_the_markers_go_in(app_js):
    """The second half of INBOX 40, and the one nothing on screen showed.

    Every streamed delta arms a paint up to `LIVE_RENDER_INTERVAL_MS` ahead.
    A turn that ends between the last delta and that timer had its markers
    placed by the code after `finalise()` and then wiped by the timer, with
    identical prose left behind, so it read as "citations do not work in a
    skill run" rather than as a race. `finalise` cancels the armed paint
    first; without the cancel the markers survive about a tenth of a second.
    """
    assert "render.stop = () => {" in app_js
    body = app_js.split("    finalise() {")[1].split("\n    },")[0]
    assert "step.render?.stop?.()" in body, "finalise must cancel the armed paint first"
    assert body.index("stop?.()") < body.index("renderMarkdown"), (
        "the cancel has to come before the re-render, not after it"
    )


def test_a_sentence_split_across_markup_is_skipped_not_reassembled(app_js):
    """A citation attached to the wrong half of a sentence is worse than no
    citation, and the chip row still lists every source either way."""
    body = app_js.split("function addInlineCitations(")[1].split("\nfunction renderAnswerGrounding(")[0]
    assert "indexOf(" in body, "matching must stay a whole-sentence search inside one text node"
    assert "NodeFilter.SHOW_TEXT" in body


def test_both_halves_of_a_split_node_are_rescanned(app_js):
    """The measured bug: placing a marker splits the text node, and a
    paragraph routinely holds several grounded sentences. Re-queueing only
    the tail left the first sentence of a paragraph unmarked whenever the
    second one happened to be longer (they are matched longest-first)."""
    body = app_js.split("function addInlineCitations(")[1].split("\nfunction renderAnswerGrounding(")[0]
    assert "queue.unshift(tail)" in body
    assert "queue.unshift(node)" in body


def test_the_chips_are_numbered_to_match_the_markers(app_js):
    body = app_js.split("function renderAnswerGrounding(")[1].split("\n}")[0]
    assert "${n}." in body, "the chip row is the key to the markers, so it has to count"
