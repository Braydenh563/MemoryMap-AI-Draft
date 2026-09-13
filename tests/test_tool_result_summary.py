"""What a tool call shows in the chat transcript (agent._result_summary).

Reported with a screenshot: *"tools render fine in the chat initially but then
I come back to them after reloading the app later and they look like this"*, 
rows reading `Listed your categories{'categories': [{'name': 'Games',
'notes': 3}], 'total_notes': 27, 'label': 'ph:folders Listed your
categories'}`. That is Python's `repr` of the result dict.
"""

from __future__ import annotations

import json

from memorymap.ai.agent import RESULT_SUMMARY_CHARS, _result_summary


def test_a_tools_own_summary_wins():
    assert _result_summary({"summary": "Filed 3 notes", "notes": [1, 2, 3]}) == "Filed 3 notes"


def test_a_result_without_a_summary_is_json_not_a_python_repr():
    text = _result_summary({"categories": [{"name": "Games", "notes": 3}], "total_notes": 27})
    assert json.loads(text) == {
        "categories": [{"name": "Games", "notes": 3}],
        "total_notes": 27,
    }
    # The repr's fingerprints, each of which was visible in the report.
    assert "'" not in text
    assert "\n" in text


def test_the_display_label_is_not_repeated_inside_the_body():
    """The row's heading already *is* the label, see the screenshot, where it
    appears twice in one row."""
    text = _result_summary({"total_notes": 27, "label": "ph:folders Listed your categories"})
    assert "label" not in text
    assert "ph:folders" not in text
    assert json.loads(text) == {"total_notes": 27}


def test_booleans_are_json_booleans():
    assert '"has_more": false' in _result_summary({"has_more": False})


def test_a_huge_result_is_bounded():
    text = _result_summary({"pages": ["x" * 200 for _ in range(200)]})
    assert len(text) == RESULT_SUMMARY_CHARS + 1  # the ellipsis
    assert text.endswith("…")


def test_something_json_cannot_serialise_still_renders():
    class Odd:
        def __repr__(self):
            return "<odd>"

    text = _result_summary({"thing": Odd()})
    assert "<odd>" in text
