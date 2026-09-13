"""The dashboard greeting never calls the user by a name they did not save.

Reported: *"the model spelt my name wrong in the dashboard welcome message."*

The greeting is written by a local model, and the only thing that ever touched
its spelling was an exact, case-insensitive match against the saved name. A near
miss, "Braden" for "Brayden", sailed straight through it, and because that
match is also what clears `append_name`, the frontend then appended the correct
name on top: the banner greeted two people, one of them misspelt.

Two guards now. `_repair_misspelt_name` puts the saved spelling back where the
model got it nearly right; `_greets_a_stranger` refuses a greeting that addresses
someone else entirely, falling back to the handwritten phrase. Being greeted
impersonally is a non-event; being greeted by the wrong name is the kind of small
wrongness that stops a person trusting anything else the app says.
"""

from __future__ import annotations

import pytest

from memorymap.api.routes_insights import (
    _greets_a_stranger,
    _name_like_words,
    _repair_misspelt_name,
)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("Good morning, Braden", "Good morning, Brayden"),
        ("Welcome back, Bradyen!", "Welcome back, Brayden!"),
        ("Hey Brayden, ready?", "Hey Brayden, ready?"),  # already right
    ],
)
def test_a_near_miss_is_repaired(phrase, expected):
    fixed, changed = _repair_misspelt_name(phrase, "Brayden")
    assert fixed == expected
    assert changed == (phrase != expected)


def test_an_ordinary_word_is_not_mistaken_for_the_name():
    """The repair must not rewrite words that merely share letters."""
    phrase, changed = _repair_misspelt_name("Morning: Sunday already", "Sam")
    assert not changed
    assert phrase == "Morning: Sunday already"


def test_the_opening_word_is_never_treated_as_a_name():
    """Every greeting starts with a capital; that is grammar, not a name."""
    assert "Morning" not in _name_like_words("Morning, Sam!")


def test_a_greeting_for_somebody_else_is_refused():
    assert _greets_a_stranger("Good evening, Dave.", "Brayden") is True


def test_the_right_name_is_not_refused():
    assert _greets_a_stranger("Good evening, Brayden.", "Brayden") is False
    assert _greets_a_stranger("good evening, brayden.", "Brayden") is False


def test_a_nameless_greeting_is_fine():
    assert _greets_a_stranger("Time to write something down.", "Brayden") is False
    assert _greets_a_stranger("Morning: Tuesday already", "Brayden") is False


def test_any_name_is_refused_when_none_is_saved():
    """With no saved name there is nobody the model could correctly address."""
    assert _greets_a_stranger("Hello there, Sam!", "") is True
    assert _greets_a_stranger("Hello there.", "") is False
