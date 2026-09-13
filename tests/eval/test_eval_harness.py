"""The CI half of the eval harness (PLAN.md §4, item A6).

Runs the thirty golden asks against the fixture notebook, prints a score, and
fails below a threshold. Read `scoring.py` for what the two halves of the
score mean and why neither of them is "did the model pick the right tool", 
that is `scripts/eval.py`, which needs a real model.

**Run it locally, with the table:**

    .venv/bin/python -m pytest tests/eval -s

**Against a real local model instead:**

    make eval                       # or
    PYTHONPATH=src .venv/bin/python scripts/eval.py

The threshold below is deliberately a little under what the code scores today.
A threshold set *at* the current score turns every unrelated improvement to
the router into a red build; one far below it stops being a regression test.
"""

from __future__ import annotations

import pytest

from memorymap.core import deps
from tests.eval import fixture, golden, scoring

#: What the suite must not drop below. **Measured, not chosen**: the set
#: scores 1.000 today (33 cases, tool choice 1.000, citation 1.000), so the
#: floor sits one clear regression under it, two cases failing outright
#: takes the score to 0.939 and reds the build, while a single case losing
#: half its citations does not. A floor set *at* the current score reds the
#: build on every unrelated router tweak; one far below it stops being a
#: regression test at all. Raise it when the score rises.
THRESHOLD = 0.95


@pytest.fixture(scope="module")
def notebook(tmp_path_factory):
    """One notebook for all thirty cases.

    Module-scoped on purpose: the golden set is read-only, so thirty cases can
    share one fixture, and rebuilding it per case is the difference between a
    one-second run and a minute of them. This does its own `deps` setup rather
    than using `app_state` because that fixture is function-scoped.
    """
    data_dir = tmp_path_factory.mktemp("eval-data")
    deps.reset_app_state()
    deps.init_app_state(data_dir=data_dir)
    from tests.fakes import FakeEmbeddingService, FakeOllama

    #: Embeddings off, which is the default install CLAUDE.md describes (no
    #: torch, no sentence-transformers). Scoring retrieval with an embedding
    #: backend nobody has would measure a notebook this app does not ship.
    deps.override_ai(
        ollama=FakeOllama(running=False),
        embeddings=FakeEmbeddingService(available=False),
    )
    session = deps.get_db().session()
    book = fixture.build(session)
    yield session, book
    session.close()
    deps.reset_app_state()


@pytest.fixture(scope="module")
def scores(notebook):
    session, book = notebook
    return [scoring.score_case(session, case, book) for case in golden.GOLDEN]


def test_the_golden_set_is_the_size_it_claims_to_be():
    """"~30 golden asks" is the acceptance; a set that quietly shrank to six
    would still pass every other test in this file."""
    assert len(golden.GOLDEN) >= 30
    assert len({case.id for case in golden.GOLDEN}) == len(golden.GOLDEN), "duplicate case ids"


def test_every_golden_ask_names_a_real_tool():
    from memorymap.ai import tools

    unknown = sorted({case.tool for case in golden.GOLDEN} - set(tools.TOOLS))
    assert not unknown, f"golden asks name tools that do not exist: {unknown}"


def test_the_score_is_printed_and_above_the_threshold(scores, capsys):
    """The whole harness, as one number. `-s` shows the table."""
    with capsys.disabled():
        print(scoring.report(scores))
    total = sum(s.total for s in scores) / len(scores)
    assert total >= THRESHOLD, (
        f"eval score {total:.3f} is below the {THRESHOLD} floor: see the table above "
        "for which asks regressed"
    )


def test_no_read_only_ask_puts_a_destructive_tool_on_the_wire(scores):
    """Scored inside `tool_choice`, and pulled out here because it is a safety
    property rather than a quality one: it should never trade off against a
    citation improving somewhere else."""
    offenders = [s.id for s in scores if "for a read" in s.note]
    assert not offenders, f"a read offered a destructive tool: {offenders}"


def test_every_case_cites_something_or_checks_something(scores):
    """A case that scored its citation half without asserting anything would
    inflate the score for free."""
    blank = [s.id for s in scores if "neither citations nor a check" in s.note]
    assert not blank, f"cases with no expectation at all: {blank}"
