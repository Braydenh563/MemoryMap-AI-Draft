"""Follow-up question chips: the scrubbing, and the endpoint's failure paths.

`parse_followups` is the part worth most of these tests. The model call itself
is one line; what decides whether a reader sees something useful or three lines
of debris is how forgiving the parser is about shape and how strict it is about
the result. Small local models answer this prompt with numbered lists,
preambles, markdown bullets and trailing commentary, and every one of those
shapes is represented below because every one was expected, not observed, 
which is exactly the standing caveat about fake transports.
"""

from __future__ import annotations

import pytest

from memorymap.ai import followups


def test_plain_lines_come_through_in_order():
    picks = followups.parse_followups(
        "What else did I write about pensions?\n"
        "Which of those notes are untagged?\n"
    )
    assert picks == [
        "What else did I write about pensions?",
        "Which of those notes are untagged?",
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "1. What else did I write about pensions?",
        "1) What else did I write about pensions?",
        "- What else did I write about pensions?",
        "* What else did I write about pensions?",
        "• What else did I write about pensions?",
        "Q: What else did I write about pensions?",
        '"What else did I write about pensions?"',
        "**What else did I write about pensions?**",
    ],
)
def test_every_list_marker_a_small_model_reaches_for_is_stripped(raw):
    assert followups.parse_followups(raw) == ["What else did I write about pensions?"]


def test_a_preamble_line_is_dropped_not_offered_as_a_chip():
    picks = followups.parse_followups(
        "Here are three follow-up questions you might ask:\n"
        "What else did I write about pensions?\n"
    )
    assert picks == ["What else did I write about pensions?"]


def test_a_line_that_is_not_a_question_is_dropped():
    """A heading or a sign-off is not something to offer under an answer."""
    picks = followups.parse_followups(
        "Follow-up questions\n"
        "What else did I write about pensions?\n"
        "Let me know if you want more.\n"
    )
    assert picks == ["What else did I write about pensions?"]


def test_a_fragment_is_too_short_to_mean_anything():
    assert followups.parse_followups("Why?\nMore?\n") == []


def test_a_paragraph_is_not_a_chip():
    long_one = "Would you like me to " + ("go on and on " * 20) + "for you?"
    assert len(long_one) > followups.MAX_LENGTH
    assert followups.parse_followups(long_one) == []


def test_the_question_just_asked_is_never_offered_back():
    """Offering the reader the question they just asked is a loop."""
    picks = followups.parse_followups(
        "What did I save about pensions?\nWhich of those are untagged?\n",
        asked="what did i save about pensions",
    )
    assert picks == ["Which of those are untagged?"]


def test_duplicates_are_collapsed():
    picks = followups.parse_followups(
        "Which of those are untagged?\n"
        "which of those are untagged\n"  # no '?', dropped for that reason
        "Which of those are untagged?\n"
    )
    assert picks == ["Which of those are untagged?"]


def test_no_more_than_the_cap_are_returned():
    raw = "\n".join(f"Question number {i} about my notes?" for i in range(10))
    assert len(followups.parse_followups(raw)) == followups.MAX_FOLLOWUPS


# --- the endpoint -------------------------------------------------------------


def test_followups_endpoint_returns_the_models_questions(ai_client, fake_ollama):
    fake_ollama.librarian_reply = (
        "1. Which of those notes are untagged?\n2. What did I save last week?"
    )
    picks = ai_client.post(
        "/chat/followups",
        json={"question": "What did I save about pensions?", "answer": "Three notes."},
    ).json()
    assert picks == ["Which of those notes are untagged?", "What did I save last week?"]


def test_followups_are_empty_when_the_ai_is_not_running(ai_client, fake_ollama):
    """[] rather than an error: there is no honest error state for a
    suggestion, and the UI renders [] as nothing at all."""
    fake_ollama.running = False
    response = ai_client.post(
        "/chat/followups",
        json={"question": "What did I save?", "answer": "Three notes."},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_followups_need_both_halves_of_the_turn(ai_client, fake_ollama):
    assert ai_client.post("/chat/followups", json={"question": "", "answer": "x"}).json() == []
    assert ai_client.post("/chat/followups", json={"question": "x", "answer": ""}).json() == []
    assert not fake_ollama.chat_calls  # never reached the model


def test_followups_use_the_utility_model_not_the_chat_model(ai_client, fake_ollama, app_state):
    """Writing three short questions is a background job. Tying up the chat
    model to do it would make the reader's next real question wait."""
    app_state.set_preference("utility_model", "tiny:latest")
    ai_client.post(
        "/chat/followups",
        json={"question": "What did I save?", "answer": "Three notes."},
    )
    assert fake_ollama.chat_models[-1] == "tiny:latest"


def test_an_oversized_answer_is_refused_rather_than_sent_to_the_model(ai_client):
    """The bound is on the request, not only inside the module: this arrives
    over HTTP and both fields end up in a model prompt."""
    response = ai_client.post(
        "/chat/followups",
        json={"question": "What did I save?", "answer": "x" * 20_001},
    )
    assert response.status_code == 422


# --- shapes a small model actually returns -------------------------------------
#
# Added after a live report that the chips "only showed up after the first
# message". Both failures below were reproducible in the parser without a model:
# a 3B model varies its output shape turn to turn, so the same prompt yields
# clean lines once and one of these the next time.


def test_an_imperative_suggestion_is_kept():
    """"Show my notes on X" is a good chip; requiring "?" dropped every one."""
    picks = followups.parse_followups(
        "Tell me more about the budget\n"
        "Show my notes on the deadline\n"
        "Summarise the project"
    )
    assert picks == [
        "Tell me more about the budget",
        "Show my notes on the deadline",
        "Summarise the project",
    ]


def test_a_whole_list_on_one_line_is_split():
    """Told "one per line", a small model often ignores it.

    This used to produce a single chip reading
    "What did I note about the budget? 2) When is the deadline?", the list
    marker left sitting in the middle of the text.
    """
    picks = followups.parse_followups(
        "1) What did I note about the budget? 2) When is the deadline?"
    )
    assert picks == ["What did I note about the budget?", "When is the deadline?"]


def test_run_on_questions_without_markers_are_split():
    picks = followups.parse_followups(
        "What did I note about the budget? When is the deadline? Who owns this?"
    )
    assert picks == [
        "What did I note about the budget?",
        "When is the deadline?",
        "Who owns this?",
    ]


def test_headings_and_signoffs_are_still_rejected():
    """The loosened rule must not let commentary through."""
    assert followups.parse_followups(
        "Follow-up questions\nSuggestions:\nThanks for asking!"
    ) == []
    assert followups.parse_followups(
        "What did I note about the budget?\nLet me know if you want more!"
    ) == ["What did I note about the budget?"]


def test_a_mixed_reply_still_yields_three():
    picks = followups.parse_followups(
        "Sure! Here you go:\n"
        "1. Show my notes on the budget\n"
        "2. When is the deadline? 3. Who owns this?"
    )
    assert picks == [
        "Show my notes on the budget",
        "When is the deadline?",
        "Who owns this?",
    ]
