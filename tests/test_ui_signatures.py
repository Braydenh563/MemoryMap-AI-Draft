"""Component families keep one recipe (UI_MODERNISATION_PLAN.md, Phase 0).

`test_style_scale.py` guarantees every spacing value is *on the scale*. It
says nothing about how many of those on-scale values one component family
uses: and that is the thing the eye reads as "assembled from parts". The
last session measured `.row` gaps of 4/6.4/8/9.6/16px across the tabs, head
rows at three heights and two card radii, every one of them a legal token.

This lint counts, statically, the **distinct** values a family reaches for,
and holds each family to a ceiling. The ceilings start at what the stylesheet
does today (measured in the run that added this file) and are lowered by the
phases that consolidate a family, Phase 2's targets are two row gaps
(`--space-3` inside a control group, `--space-4` between groups) and one
surface radius. A ceiling is a ratchet: **lower it when a phase lands, never
raise it.** If a new rule genuinely needs a value the family does not have,
the answer is to use the family's value, not to widen the count.

It cannot see the DOM (the Playwright sweeps in `scratchpad/ui-sweeps/` do
that, against a running app); it exists so the counts cannot drift back
between sessions without a test going red.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from tests._css_paths import css_text

# A raw rem on the scale means the same thing as its token, so the two must
# count as one value, otherwise a family could pass with one token and one
# literal that render identically, which is a rounding error, not drift.
REM_TO_TOKEN = {
    "0.25rem": "var(--space-1)",
    "0.4rem": "var(--space-2)",
    "0.5rem": "var(--space-3)",
    "0.6rem": "var(--space-4)",
    "0.8rem": "var(--space-5)",
    "1rem": "var(--space-6)",
    "1.25rem": "var(--space-7)",
    "1.5rem": "var(--space-8)",
    "2rem": "var(--space-9)",
}

# Selectors that are "a row": a horizontal run of controls. Toolbars and card
# head rows are rows by another name, and the sweeps treat them as one family.
ROW_SELECTOR = re.compile(r"\.row\b|toolbar|\.card-head\b|\.card\s*>\s*header")

# Selectors that are "a surface": something with its own edge and radius.
SURFACE_SELECTOR = re.compile(
    r"\.card\b|\.modal-card\b|\.popover\b|-menu\b|\.panel\b|\.dash-widget\b"
)

# Ceilings. Each is the count measured when this lint was added; a phase that
# lowers one writes the new number here with the commit that earned it.
#
# Row gap: Phase 2 brought 5 → 3. The three are `--space-3` inside a control
# group, `--space-4` between groups, and `--space-1` for the two icon-only
# formatting strips (`.doc-toolbar`, `.note-toolbar`, 60 controls each, where
# an 8px gap would cost 240px of width). A fourth value is drift.
ROW_GAP_CEILING = 3
ROW_PADDING_CEILING = 11
SURFACE_RADIUS_CEILING = 4


def _rules() -> list[tuple[str, str]]:
    """(selector, body) for every innermost rule, comments stripped.

    Innermost only, so a rule inside `@media` is captured with its own
    selector rather than the media query's: good enough for counting what a
    selector *declares*, which is all this needs.
    """
    text = re.sub(r"/\*.*?\*/", "", css_text(), flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]


def _normalise(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    for rem, token in REM_TO_TOKEN.items():
        value = re.sub(rf"(?<![\w.-]){re.escape(rem)}(?![\w-])", token, value)
    return value


def _distinct(selector: re.Pattern, prop: str) -> Counter:
    found: Counter = Counter()
    pattern = re.compile(rf"(?<![\w-]){prop}\s*:\s*([^;]+);")
    for sel, body in _rules():
        if not selector.search(sel):
            continue
        for raw in pattern.findall(body):
            found[_normalise(raw)] += 1
    return found


def _report(label: str, found: Counter, ceiling: int) -> str:
    rows = "\n".join(f"  {n:3d}  {v}" for v, n in found.most_common())
    return f"{label}: {len(found)} distinct values, ceiling {ceiling}\n{rows}"


@pytest.mark.parametrize(
    ("label", "selector", "prop", "ceiling"),
    [
        ("row gap", ROW_SELECTOR, "gap", ROW_GAP_CEILING),
        ("row padding", ROW_SELECTOR, "padding", ROW_PADDING_CEILING),
        ("surface border-radius", SURFACE_SELECTOR, "border-radius", SURFACE_RADIUS_CEILING),
    ],
)
def test_a_component_family_does_not_grow_a_new_recipe(label, selector, prop, ceiling):
    found = _distinct(selector, prop)
    assert found, f"{label}: the selector pattern matched nothing, the lint is looking at the wrong thing"
    assert len(found) <= ceiling, _report(label, found, ceiling)


def test_the_ceilings_are_still_load_bearing():
    """A ceiling far above the real count guards nothing. Each must be within
    one of what the stylesheet does, so lowering the count means lowering the
    ceiling in the same commit, that is what makes it a ratchet."""
    for label, selector, prop, ceiling in [
        ("row gap", ROW_SELECTOR, "gap", ROW_GAP_CEILING),
        ("row padding", ROW_SELECTOR, "padding", ROW_PADDING_CEILING),
        ("surface border-radius", SURFACE_SELECTOR, "border-radius", SURFACE_RADIUS_CEILING),
    ]:
        found = _distinct(selector, prop)
        assert ceiling - len(found) <= 1, _report(label, found, ceiling) + "\n  lower the ceiling"
