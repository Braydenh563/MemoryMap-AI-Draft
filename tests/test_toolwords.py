"""Reading a request for the tools it needs, see `ai/toolwords.py`.

The same deterministic, no-model-call shape as `entry/timewords.py`. These
tests are the argument for it: every false positive below was produced by the
substring matching this replaced, against an ordinary question.
"""

from __future__ import annotations

import pytest

from memorymap.ai import agent, tools, toolwords

CORE = set(tools.CORE_TOOLS) | {"web_search", "read_url"}


def extras(question: str, recent: str = "") -> list[str]:
    """The tools this question earned, beyond the ones every turn gets."""
    got = tools.focus_for(question, recent)
    if got is None:
        return ["<ALL>"]
    return [name for name in got if name not in CORE]


# --- the class of bug this module exists for -----------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "what did I write about my vintage camera?",   # "tag" inside vintage
        "what are the advantages of this approach?",   # "tag" inside advantages
        "notes about blinking lights",                 # "link" inside blinking
        "is there a doctor note?",                     # "doc" inside doctor
        "my docker setup notes",                       # "doc" inside docker
    ],
)
def test_a_word_inside_another_word_is_not_a_cue(question):
    """Substring matching offered the tag tools for a question about a camera,
    and the link tools for one about lights. Each dragged three to five schemas
    into the prompt of a model that may have four thousand tokens in total, 
    and put delete_tag in front of a model that was asked about a camera."""
    assert extras(question) == []


# --- ...without losing the true positives --------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        ("tag all my gym notes as fitness", "tag_note"),
        ("link the budget note to the plan note", "link_notes"),
        ("remind me about the dentist tomorrow", "set_reminder"),
        ("delete the note about beans", "delete_note"),
        ("what's in my documents about the lease?", "list_documents"),
        ("make a mind map of my project notes", "generate_diagram"),
        ("what did we talk about last time?", "search_chat_history"),
    ],
)
def test_a_request_that_names_its_subject_gets_those_tools(question, expected):
    assert expected in extras(question)


@pytest.mark.parametrize(
    "question",
    ["tagging my notes properly", "I tagged those already", "my tags are a mess"],
)
def test_an_inflected_cue_still_matches(question):
    """Anchoring both ends of the cue was the first attempt, and it broke every
    plural: `\\bdocument\\b` does not match "documents", so "what's in my
    documents" was offered no document tools at all. Substring matching got
    that right by accident."""
    assert "tag_note" in extras(question)


# --- asking about a capability is not asking for it ----------------------------


@pytest.mark.parametrize(
    "question,asking",
    [
        ("how do I tag a note?", True),
        ("what does the link tool do?", True),
        ("explain how linking works", True),
        ("why do my notes have tags?", True),
        ("tag all my gym notes", False),
        ("please tag these", False),
        ("what's the best way to do this - please tag them all", False),
        ("can you explain how to tag, and tag these for me", False),
    ],
)
def test_a_question_about_a_capability_is_told_apart_from_a_request(question, asking):
    assert toolwords.looks_like_a_question_about(question) is asking


def test_asking_how_tagging_works_does_not_hand_over_delete_tag():
    """The write tools are held back, not the group: the question is still
    about tags, so anything that *reads* them stays available to answer it."""
    got = extras("how do I tag a note?")
    assert "delete_tag" not in got
    assert "rename_tag" not in got
    # list_tags is core, so the model can still look at them to answer well.
    assert "list_tags" in tools.focus_for("how do I tag a note?", "")


# --- the guess is never final --------------------------------------------------


def test_a_broad_request_gets_everything():
    assert extras("tidy up my notebook") == ["<ALL>"]
    assert extras("go through my notes and sort them out") == ["<ALL>"]


def test_a_follow_through_reads_the_previous_turn():
    """Reported: asking for category suggestions and then "implement those"
    produced the suggestions again, the follow-up named no category, so no
    category tool was offered and the model had nothing it could call.

    What matters is that the tool ends up reachable, not that the focus stayed
    narrow: "merge" in the previous turn is itself a broad cue, and answering
    a follow-through with the whole toolbox is the safe reading of a turn where
    the user is expecting an action.
    """
    got = tools.focus_for("implement those suggestions",
                          "you could merge these categories")
    reachable = {t["function"]["name"] for t in tools.ollama_tools(got)}
    assert "merge_categories" in reachable


def test_a_follow_through_with_no_subject_anywhere_gets_everything():
    assert extras("do it", recent="") == ["<ALL>"]


# --- the scores rank; they never gate ------------------------------------------


def test_one_cue_is_enough():
    """This was briefly wrong the other way, a threshold a single word could
    not clear: and "tag all my gym notes" was offered no tag tools. Trading a
    false positive for a false negative is a bad trade: an unnecessary schema
    costs a few hundred characters, a missing one costs the user the thing they
    asked for."""
    assert toolwords.SCORE_THRESHOLD <= toolwords.WORD_WEIGHT


def test_a_phrase_outranks_a_bare_word():
    """Ranking is what the scores are for: when not every group fits, take the
    ones the sentence argued for hardest."""
    ranked, _ = toolwords.score_groups(" mind map of the whiteboard ", tools.TOOL_GROUPS)
    assert ranked
    assert ranked[0][1] > toolwords.WORD_WEIGHT


def test_the_reasoning_is_available_for_the_log():
    """"Why was delete_tag offered?" has to be answerable from Settings → Logs
    rather than by re-deriving the match by hand."""
    detail = tools.focus_detail("tag all my gym notes", "")
    assert "tag" in detail.cues
    assert "focus:" in detail.explain()
    assert tools.focus_detail("tidy my notebook", "").broad is True


# --- the model may overrule the suggestion -------------------------------------


def test_a_narrowed_turn_tells_the_model_the_list_is_a_suggestion():
    """Asked for directly: if the words suggest tools and the AI thinks that is
    wrong, it does not have to use them, and, the other way round, must be
    able to reach for one that was not suggested.

    It always *could*: `permitted` is None on an ordinary turn, so a tool the
    model names runs whether or not it was offered. What was missing was
    saying so. Without it a well-behaved model treats the list as exhaustive,
    which is what makes a narrow guess expensive rather than merely wrong.
    """
    note = agent.FOCUS_NOTE.lower()
    assert "suggestion" in note
    assert "not a limit" in note
    assert "call it by name anyway" in note
    assert "ignore any that do not fit" in note


def test_the_note_is_only_added_when_the_list_was_actually_narrowed():
    """On a broad request the model already has everything, so a note saying
    the list is partial would simply be untrue."""
    source = (
        __import__("pathlib").Path("src/memorymap/ai/agent.py")
        .read_text(encoding="utf-8")
    )
    block = source.split("focused_only = allowed_tools is None")[1][:500]
    assert "focus_names is not None" in block
