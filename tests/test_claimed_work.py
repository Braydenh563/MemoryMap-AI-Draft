"""Claiming work that never happened (roadmap §35B).

This is the failure that costs the most trust, because the user cannot see it.
A reported turn wrote a confident numbered list, "**Linked Notes:** We
connected your main Social Skills Guide (ID 12) to your pickup lines (ID 13)…
We unlinked the Gym Routine Overview (ID 28)", having called `related_notes`
once and no write tool at all.

The net that exists for exactly this did not fire, and it missed twice over:

1. it knew only the first person singular ("I linked"), and the model wrote
   "we" throughout;
2. it asked one question of the whole turn, "did *any* write run?", so a
   turn that legitimately linked one pair and then claimed four more would
   have passed on the strength of the one that was real.

So claims are matched per action now and checked against the tool that would
have made each one true. It is §33's "completion verifier" in its cheap form:
no second model round, just what was said against what was called.

The line these tests hold: **a warning must name which claim was unsupported.**
"It looks like I didn't save it" is useless when the answer claimed five
different things and four of them were real.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import agent


# The reported answer, trimmed to the sentences that matter. Kept verbatim
# rather than paraphrased: the phrasing is the bug.
REPORTED_ANSWER = """Here's what we did:

1.  **Linked Notes:** We connected your main **Social Skills Guide (ID 12)** to
your specific pickup lines (**ID 13**), your ice breakers (**ID 15**), and the
follow-up questions (**ID 16**).
2.  **Unlinked Note:** We unlinked the **Gym Routine Overview (ID 28)** from the
main guide, as it seemed like an extra connection that didn't fit.
"""


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


# --- the reported answer, which is the whole point --------------------------


def test_the_reported_answer_is_caught():
    """The turn that motivated all of this. `related_notes` ran, a read, so
    no write tool is in `ran`."""
    claims = agent.unsupported_claims(REPORTED_ANSWER, set())
    assert "linked notes" in claims
    assert "unlinked notes" in claims


def test_we_counts_as_a_claim_just_like_i():
    """The single reason the original net missed: it matched "I linked" and
    the model said "We connected"."""
    assert agent.unsupported_claims("We connected note 12 to note 13.", set())
    assert agent.unsupported_claims("I connected note 12 to note 13.", set())


@pytest.mark.parametrize(
    "answer",
    [
        "I've tagged all three notes for you.",
        "We have deleted the duplicate.",
        "I just saved that as a note.",
        "We successfully linked them.",
        "I then pinned it to the top.",
    ],
)
def test_the_phrasings_a_model_actually_reaches_for(answer):
    assert agent.unsupported_claims(answer, set())


# --- checked per action, not per turn ---------------------------------------


def test_a_claim_backed_by_its_own_tool_passes():
    assert agent.unsupported_claims("I linked them for you.", {"link_notes"}) == []


def test_one_real_write_does_not_cover_a_different_claim():
    """The second gap, and the more dangerous one. Under the old boolean, a
    turn that genuinely created a note could then claim to have linked, tagged
    and deleted things and none of it would be questioned."""
    claims = agent.unsupported_claims(
        "I saved that note, and I also linked it to note 4 and tagged them both.",
        {"create_note"},
    )
    assert "saved a note" not in claims  # this part really happened
    assert "linked notes" in claims
    assert "tagged a note" in claims


def test_linking_does_not_excuse_unlinking():
    """Two tools, two claims. `link_notes` running says nothing about whether
    `unlink_notes` did: and `\\b` alone would let "linked" match inside
    "unlinked", which is why the matchers are ordered."""
    claims = agent.unsupported_claims(
        "I linked 12 to 13, and I unlinked 28.", {"link_notes"}
    )
    assert claims == ["unlinked notes"]


# --- what must NOT be reported as a false claim -----------------------------


def test_a_verb_carried_on_from_an_earlier_subject_still_counts():
    """"I linked 12 to 13 and tagged them both", models write this constantly,
    and requiring an explicit "I"/"we" in front of every verb missed the whole
    second half of the sentence."""
    claims = agent.unsupported_claims("I linked 12 to 13, and tagged them both.", set())
    assert "linked notes" in claims
    assert "tagged a note" in claims


def test_a_carried_on_verb_needs_a_claim_to_carry_from():
    """The looser half only applies inside an answer that already claimed
    something outright. On its own it would read "the notes you tagged in
    March, and pinned last week" as two fabrications."""
    assert agent.unsupported_claims("The notes you tagged, and pinned, are here.", set()) == []


def test_a_suggestion_is_not_a_claim():
    """"We could link these" is the model being helpful. Reporting it as a
    fabrication would train the user to ignore the warning, which costs more
    than the warning is worth."""
    for answer in (
        "We could link these two notes if you like.",
        "I can tag them for you, shall I?",
        "We should probably delete the duplicate.",
        "I will link them once you confirm.",
    ):
        assert agent.unsupported_claims(answer, set()) == [], answer


def test_describing_the_notebook_is_not_a_claim():
    """Read-only answers are most of what this app does. Every one of them
    would be a false positive if the pattern were loose about the subject."""
    for answer in (
        "Note 12 is connected to five others.",
        "You saved that one in March.",
        "These notes are tagged #work.",
        "Found 5 notes connected to #12.",
    ):
        assert agent.unsupported_claims(answer, set()) == [], answer


def test_an_empty_answer_claims_nothing():
    assert agent.unsupported_claims("", set()) == []


# --- through the agent loop -------------------------------------------------


def test_the_warning_names_the_unsupported_claim(ai_client, fake_ollama):
    """A warning that says *which* claim failed is actionable; "something
    didn't happen" is not."""
    fake_ollama.tool_script = []
    fake_ollama.librarian_reply = REPORTED_ANSWER
    events = _events(ai_client, "link my social skills notes together", use_tools=True)
    text = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "Heads up" in text
    assert "linked notes" in text
    assert "unlinked notes" in text


def test_no_warning_when_the_tool_really_ran(ai_client, fake_ollama, session):
    """The net must be silent on a turn that did the work, or it is noise."""
    from memorymap.entry import manager

    first = manager.create_entry(session, "A note about beans")
    second = manager.create_entry(session, "Another note about beans")
    session.commit()
    fake_ollama.tool_script = [
        [
            {
                "name": "link_notes",
                "arguments": {"note_id": first.id, "other_note_id": second.id},
            }
        ]
    ]
    fake_ollama.librarian_reply = "I linked those two notes for you."
    events = _events(ai_client, "link my two bean notes", use_tools=True)
    text = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "Heads up" not in text


def test_a_read_only_answer_is_never_warned_about(ai_client, fake_ollama):
    fake_ollama.tool_script = []
    fake_ollama.librarian_reply = "You have three notes about beans, saved in March."
    events = _events(ai_client, "what did I write about beans", use_tools=True)
    text = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "Heads up" not in text
