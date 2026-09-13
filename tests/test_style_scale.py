"""Spacing stays on the scale (roadmap §35L).

Asked for repeatedly, and in the end bluntly:

> *"the way spacing, alignment and margins of all the ui features in each tab
> aren't consistent and it changes each tab. I want the UI across the
> application to be very professional, consistent and clean. not to look like
> it is just a bunch of ai generated slop features joined together."*

That description was accurate, and the cause was structural rather than
cosmetic: `style.css` had 667 margin/padding/gap declarations across more than
twenty-five distinct values, seven of them between 0.3rem and 0.6rem, all
meaning "a small gap", all slightly different, and each one a place where two
things that should line up nearly do.

**This test is the part that makes the fix hold.** Extracting a scale and
converting the file is a one-off; without something that fails, the next tab
built in the next session reaches for whatever looks right at the time and the
drift starts again. §35L calls this out explicitly: "a lint that fails on a raw
px margin or padding outside the token block, so tab seven cannot reintroduce
the problem. This is the step that makes it stick; without it this section will
be rewritten in six months."

The scale is deliberately generous, nine steps, fitted to the distribution
that was already in the file rather than imposed on it, so adopting it moved
nothing by more than 0.1rem. If a value genuinely needs to be off-scale, add it
to ALLOWED with the reason. Being made to write the reason is the point.
"""

from __future__ import annotations

import re
from collections import Counter

from tests._css_paths import FRONTEND_DIR, css_text

#: The scale, in rem. Mirrors the --space-* custom properties in :root.
SCALE = {0.05, 0.1, 0.15, 0.25, 0.4, 0.5, 0.6, 0.8, 1.0, 1.25, 1.5, 2.0}

#: Off-scale values that earn their place. Keep this list short, and keep the
#: reasons real: an entry with a vague reason is a value that should have been
#: snapped to the scale instead.
ALLOWED = {
    # Indent steps for the document outline: each level is one nesting depth,
    # and they have to stay evenly spaced relative to each other rather than
    # land on a scale built for gaps between unrelated things.
    1.65,
    2.4,
    # A negative pull-back that cancels a list's own indent exactly.
    1.1,
}

SPACING = re.compile(
    r"\b(?:margin|padding|gap|row-gap|column-gap)"
    r"(?:-top|-right|-bottom|-left|-inline|-block)?\s*:\s*([^;{}]+);"
)
VALUE = re.compile(r"(?<![\w.-])(-?[0-9]*\.?[0-9]+)rem\b")


def _stylesheet() -> str:
    """All of CSS_FILES (see tests/_css_paths.py), comments stripped.

    The comments here explain layout decisions, so they quote lengths, and a
    naive scan reads those as real declarations. `test_frontend_ids.py` had to
    learn the same lesson about markup comments quoting ids.
    """
    return re.sub(r"/\*.*?\*/", "", css_text(), flags=re.S)


def _offenders() -> Counter:
    text = _stylesheet()
    found: Counter = Counter()
    for declaration in SPACING.findall(text):
        for raw in VALUE.findall(declaration):
            size = abs(float(raw))
            if size and size not in SCALE and size not in ALLOWED:
                found[size] += 1
    return found


def test_every_spacing_value_is_on_the_scale():
    offenders = _offenders()
    assert not offenders, (
        "These margin/padding/gap values are off the spacing scale:\n  "
        + "\n  ".join(f"{size}rem: used {n}×" for size, n in sorted(offenders.items()))
        + "\n\nUse a --space-* step (see :root in style.css). If the value is "
        "genuinely special, add it to ALLOWED in this file with the reason."
    )


def test_the_scale_is_actually_declared():
    """The test and the stylesheet must agree, or this passes while the
    properties it is protecting have been renamed out from under it."""
    text = _stylesheet()
    # The steps are wrapped in calc(... * var(--density)) so one setting can
    # tighten the whole scale, the base value is what has to be on it.
    declared = {
        float(m)
        for m in re.findall(r"--space-\d+:\s*(?:calc\()?([0-9.]+)rem", text)
    }
    assert declared, "no --space-* custom properties found in style.css"
    assert declared <= SCALE, f"declared but not in SCALE: {sorted(declared - SCALE)}"


def test_the_scale_did_not_quietly_grow():
    """Nine steps is a scale; twenty is the problem this replaced. A new step
    should be a deliberate decision, not something that accretes."""
    text = _stylesheet()
    assert len(re.findall(r"--space-\d+:", text)) <= 10


# --- type ---------------------------------------------------------------------

#: The type scale, in rem. Mirrors the --text-* custom properties.
TYPE_SCALE = {0.7, 0.75, 0.8, 0.85, 0.92, 1.0, 1.15, 1.3, 1.7, 2.2}

#: Single hero elements, each the only thing at its size. A display size is a
#: deliberate one-off, not a step other components should reach for.
TYPE_ALLOWED = {2.4, 2.6, 2.8}

FONT_SIZE = re.compile(r"\bfont-size\s*:\s*([^;{}]+);")


def test_every_font_size_is_on_the_scale():
    """Thirty-seven distinct sizes, nine of them between 0.74 and 0.85rem.

    Text that is *almost* the same size in two adjacent components is the
    texture the report called "a bunch of ai generated slop features joined
    together", nothing quite lines up, and no size means anything because
    every one is slightly its own.
    """
    offenders = Counter()
    for declaration in FONT_SIZE.findall(_stylesheet()):
        for raw in VALUE.findall(declaration):
            size = abs(float(raw))
            if size and size not in TYPE_SCALE and size not in TYPE_ALLOWED:
                offenders[size] += 1
    assert not offenders, (
        "Off-scale font sizes:\n  "
        + "\n  ".join(f"{s}rem: used {n}×" for s, n in sorted(offenders.items()))
        + "\n\nUse a --text-* step (see :root in style.css)."
    )


# --- corners ------------------------------------------------------------------

RADIUS = re.compile(r"\bborder(?:-[a-z]+)?-radius\s*:\s*([^;{}]+);")
PX = re.compile(r"(?<![\w.-])([0-9]+)px\b")


def test_no_corner_is_hard_coded_in_pixels():
    """Corners have to follow the slider in Settings → Appearance.

    Everything rounded used to be one of twelve hard-coded pixel values, none
    of which moved when that slider did, so choosing square corners squared
    the cards and left every chip, popup and button rounded, and adjacent
    surfaces at 8px and 10px read as belonging to different applications.

    The tiers are multiples of --radius, so this is a property about the whole
    interface responding to one setting, not only about consistency.
    """
    offenders = Counter()
    for declaration in RADIUS.findall(_stylesheet()):
        # calc(var(--radius) * 0.6) is the point, not a violation.
        if "var(--radius" in declaration:
            continue
        for raw in PX.findall(declaration):
            offenders[int(raw)] += 1
    assert not offenders, (
        "Hard-coded corner radii:\n  "
        + "\n  ".join(f"{px}px: used {n}×" for px, n in sorted(offenders.items()))
        + "\n\nUse --radius-sm / --radius-md / --radius-lg / --radius-pill."
    )


def test_the_corner_tiers_are_derived_from_the_setting():
    """If a tier is ever pinned to a constant, the slider silently stops
    reaching whatever uses it, which is the bug this replaced."""
    text = _stylesheet()
    for tier in ("--radius-sm", "--radius-md", "--radius-lg"):
        line = re.search(rf"{tier}:\s*([^;]+);", text)
        assert line, f"{tier} is not declared"
        assert "var(--radius)" in line.group(1), f"{tier} does not follow --radius"


#: A radius written as a tier minus a length: the shape of a hand-picked inner
#: corner. `- 1px` is exempt and is a different thing (see the test).
HAND_PICKED_INNER = re.compile(r"calc\(\s*var\(--radius[a-z-]*\)\s*-([^)]+)\)")


def test_an_inner_corner_uses_the_concentric_token():
    """A shape inside a rounded container is concentric or it is wrong.

    UI_MODERNISATION_PLAN Phase 10 / INBOX 101, from the HIG: "rounded shapes
    that are concentric to their containers". The inner radius is the outer
    one minus the padding between them, which is `--radius-inner`. Picking a
    number instead breaks the relationship at every radius except the one it
    was eyeballed at, and the radius is a user setting.

    `calc(var(--radius-lg) - 1px)` is deliberately allowed and is not the same
    thing: three rules square off the top corners of a panel inside a 1px
    border, where the subtraction is the border's own width rather than a
    guess at an inset.
    """
    offenders = Counter()
    for declaration in RADIUS.findall(_stylesheet()):
        for raw in HAND_PICKED_INNER.findall(declaration):
            if raw.strip() == "1px":
                continue
            offenders[raw.strip()] += 1
    assert not offenders, (
        "Hand-picked inner radii:\n  "
        + "\n  ".join(f"minus {v}: used {n}×" for v, n in sorted(offenders.items()))
        + "\n\nUse var(--radius-inner)."
    )


def test_the_concentric_token_follows_the_setting():
    """Same reason the three tiers do: pin it to a constant and the slider
    stops reaching every inner corner in the app at once."""
    line = re.search(r"--radius-inner:\s*([^;]+);", _stylesheet())
    assert line, "--radius-inner is not declared"
    assert "var(--radius)" in line.group(1), "--radius-inner does not follow --radius"
    # A negative radius is invalid where it is *used*, so the declaration is
    # dropped and the element inherits something unrelated. At the square end
    # of the slider --radius is 2px and the subtraction is negative.
    assert "max(" in line.group(1), (
        "--radius-inner needs a floor of 0px: --radius goes down to 2px and a "
        "negative border-radius is an invalid declaration, not a square corner"
    )


# --- the page shell -----------------------------------------------------------

#: Containers that sit directly inside a tab page. Each one used to draw its
#: own outer gutter, and no two agreed, see .tab-page in style.css.
#:
#: The four dashboard rows joined this list after the gutter they draw was
#: *photographed* rather than found by the lint: the hero banner began at x=32
#: and every row beneath it at x=64, on the same screen, because each added
#: 2rem of its own on top of --page-gutter. One tab disagreeing with itself is
#: worse than two tabs disagreeing with each other, both edges are visible at
#: once: and the rule this file already enforced would have caught it if the
#: list had named them.
PAGE_CONTAINERS = (
    ".layout",
    ".doc-layout",
    ".dash-hero",
    ".reminders-card",
    "#graph-card",
    ".dash-quicklinks",
    ".dash-stats",
    ".dash-toolbar",
    "#dash-grid",
)

#: Selectors with no background of their own: a pure wrapper's padding is an
#: outer inset by another name, so both properties are checked. A container
#: that paints something, .dash-hero is a visible panel, owns its padding.
#:
#: `.dash-toolbar` moved off this list when it became a bar. It was a pure
#: wrapper: transparent, no edge, no radius, two 28px controls sitting loose
#: between the stats strip and the grid, which is what docks.md section 3 left
#: open about it. 08-consistency.css now gives it the same surface every other
#: head row in the app draws, so it paints, and by this list's own stated
#: distinction a container that paints owns its padding. The membership test is
#: "does it have a background", not "is it on the Dashboard": moving it is the
#: rule being applied, not widened.
PURE_WRAPPERS = frozenset({".layout", ".doc-layout", ".dash-quicklinks", ".dash-stats", "#dash-grid"})


def test_no_page_draws_its_own_outer_gutter():
    """Seven tabs had four gutter treatments between them.

    The side inset was 2rem in five separate rules, but the space above the
    first element was 1rem on Notes and Chat, 0 on Documents and 0.8rem on the
    Dashboard, Reminders and Graph, each *on top of* .tab-page's own 0.8rem.
    Content therefore began 1.8rem down one tab and 0.8rem down the next,
    which is the page-level form of "spacing… changes each tab".

    A page container may set its internal gap. The distance from the window is
    the shell's business, and only the shell's.
    """
    text = _stylesheet()
    offenders = []
    for selector in PAGE_CONTAINERS:
        # `margin` is what holds a box away from the window, so a horizontal
        # margin on a page container *is* a gutter however it is spelled.
        # `padding` is internal: .dash-hero is a visible panel and its own
        # padding is none of the shell's business: except on the pure
        # wrappers, which have no background and nothing to pad.
        props = "padding|margin" if selector in PURE_WRAPPERS else "margin"
        # Leading whitespace is allowed so a rule *inside* a media query is
        # checked too. That is not hypothetical: the dashboard's 720px block
        # re-declared `margin: 0.8rem 1rem 0`, putting the gutter back on
        # exactly the screens with the least room for it, and the anchored
        # pattern never saw it.
        # The boundary stops a prefix from matching a longer name, without it
        # `.dash-hero` claims `.dash-hero-emblem` and reports its rules under
        # the wrong selector.
        for m in re.finditer(
            rf"(?m)^\s*{re.escape(selector)}(?![\w-])[^{{,]*\{{([^}}]*)\}}", text
        ):
            for prop, value in re.findall(rf"\b({props})\s*:\s*([^;]+);", m.group(1)):
                parts = value.split()
                horizontal = parts[1] if len(parts) > 1 else parts[0]
                if horizontal not in ("0", "auto"):
                    offenders.append(f"{selector} {{ {prop}: {value}; }}")
    assert not offenders, (
        "These page containers set their own outer inset:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe gutter belongs to .tab-page (--page-gutter). Set only the "
        "internal gap here."
    )


def test_the_shell_is_declared_once_and_responsively():
    """One place to tighten on a narrow window. Per-page media queries shrinking
    to different numbers is how the desktop drift got reproduced on mobile."""
    text = _stylesheet()
    for token in ("--page-gutter", "--page-top", "--page-bottom"):
        assert f"{token}:" in text, f"{token} is not declared"
        assert f"var({token})" in text, f"{token} is declared but never used"
    assert "padding: var(--page-top) var(--page-gutter) var(--page-bottom);" in text


# --- colour -------------------------------------------------------------------

#: Tokens whose fallback is legitimate: a font stack has to name real families,
#: an opacity needs a number when the art is off, and --bar-scale is not a
#: design token at all, it's set inline, per bar, per frame, by
#: startMicLevelMeter() in app.js, so its "declaration" is JS, not this
#: stylesheet.
#:
#: --wb-map-edge-colour is the same shape and arrived the same way: a mind
#: map's edge takes its branch's colour, written per element by the map
#: renderer with `el.style.setProperty`, and falls back to the accent for an
#: edge whose branch has none. It is written that way rather than as a
#: `stroke` attribute because a stylesheet declaration beats an attribute and
#: the attribute version was dead markup, which is what
#: `tests/test_svg_paint_attributes.py` now catches.
FALLBACK_ALLOWED = {
    "--mono",
    "--ui-font",
    "--bg-art-opacity",
    "--modal-bg",
    "--chip-bg",
    "--bar-scale",
    "--wb-map-edge-colour",
}

VAR_WITH_FALLBACK = re.compile(r"var\(\s*(--[\w-]+)\s*,")
DECLARED = re.compile(r"(?m)^\s*(--[\w-]+)\s*:")


def test_no_token_is_used_with_a_dead_fallback():
    """`var(--danger, #e2534b)` in six rules, and `--danger` declared nowhere.

    All six therefore rendered the hard-coded red in *both* themes, ignoring
    the theme-aware `--error` that already existed and is a different colour in
    dark mode. `var(--text-muted, inherit)` was the same bug quieter still, it
    simply inherited, so the text was never muted at all.

    A fallback on a token that IS declared is dead code with a sharper edge: it
    looks like a safety net and is actually a way for a rename to silently stop
    applying, since the rule keeps working while quietly showing the wrong
    colour. Either the token exists, use it plainly, or it does not, and the
    fallback is hiding a bug.
    """
    text = _stylesheet()
    declared = set(DECLARED.findall(text))
    offenders = sorted(
        {
            name
            for name in VAR_WITH_FALLBACK.findall(text)
            if name not in FALLBACK_ALLOWED
        }
    )
    detail = [
        f"{name}: {'declared, so the fallback is dead code' if name in declared else 'NOT DECLARED, so the fallback is what renders'}"
        for name in offenders
    ]
    assert not offenders, "Tokens used with a fallback:\n  " + "\n  ".join(detail)


#: `var(--x)` with no fallback. The fallback form is the sibling test's job.
VAR_NO_FALLBACK = re.compile(r"var\(\s*(--[\w-]+)\s*\)")


def test_every_token_the_stylesheet_uses_is_declared_somewhere():
    """A `var(--x)` with no fallback and no declaration renders as *nothing*.

    The sibling test above only sees tokens written with a fallback, and that
    gap cost the app a visible bug: `.glass` set `background: var(--bg-glass)`
    against a token no theme declares. It resolved to the guaranteed-invalid
    value, computed to transparent, and, sitting after `.card` at equal
    specificity: won, so every `class="card glass"` element in the app painted
    no background at all. The command palette showed an input and a hint
    floating over the page with no surface behind them.

    Undeclared-with-a-fallback is a wrong colour; undeclared-without-one is an
    erased declaration that can take a working rule down with it. This catches
    the second kind.
    """
    text = _stylesheet()
    declared = set(DECLARED.findall(text))
    # Set from JavaScript rather than in the stylesheet. Each one is written
    # with `setProperty` on an element, so the sheet never declares it.
    SET_BY_JS = {"--zoom", "--density", "--glass-blur", "--radius", "--page", "--bg-art-opacity"}
    missing = sorted({n for n in VAR_NO_FALLBACK.findall(text) if n not in declared} - SET_BY_JS)
    assert not missing, (
        "These tokens are used but declared nowhere, so they render as nothing "
        "and can override a rule that worked:\n  " + "\n  ".join(missing)
    )


def test_the_semantic_colour_set_is_complete_in_both_themes():
    """Every state colour needs a dark-mode value, or a component using it is
    unreadable on one of the two themes the app ships with."""
    text = _stylesheet()
    for token in ("--ok", "--warn", "--error", "--accent", "--muted", "--ink"):
        assert len(re.findall(rf"(?m)^\s*{token}\s*:", text)) >= 2, (
            f"{token} is declared once, it needs a dark-mode value too"
        )


def test_density_is_a_multiplier_over_the_scale():
    """It used to be nine rules in two places, each re-stating literal paddings
    for the four components somebody happened to remember, .card, .layout,
    .dash-hero and .entry-list li. So "compact" tightened those four and left
    every dialog, chip row, toolbar and settings pane at comfortable.

    Multiplying the scale means the setting reaches everything spaced by a
    token, which after §35L is everything. A density rule that names a
    component is that regression coming back.
    """
    text = _stylesheet()
    assert "--density: 1;" in text
    steps = re.findall(r"--space-\d+:\s*([^;]+);", text)
    assert steps and all("var(--density)" in s for s in steps), (
        "every --space-* step must scale with --density"
    )
    # A descendant selector after the attribute is the giveaway: `:root[...] {`
    # sets the multiplier, `:root[...] .card {` reaches into a component.
    component_rules = re.findall(
        r'(?m)^:root\[data-density="[^"]+"\]\s+[^{\s][^{]*\{', text
    )
    assert not component_rules, (
        "density must set --density only, never a component's padding: "
        + ", ".join(component_rules)
    )


# --- form controls ------------------------------------------------------------

#: Input types that are text boxes and must share one look.
TEXTUAL_INPUTS = {
    "text", "password", "number", "search", "email", "url", "tel",
    "date", "time", "datetime-local",
}
#: Types that are their own kind of control and must NOT get the text-box
#: treatment: a checkbox with `width: 100%` and 0.8rem of padding is not a
#: checkbox any more.
NON_TEXTUAL_INPUTS = {"checkbox", "radio", "range", "color", "file", "hidden", "submit", "button"}


def test_every_text_input_in_the_markup_is_styled():
    """Reported: "all the ui elements need the same style otherwise they look
    out of place."

    The base rule had been extended a type at a time, text, password, number , 
    so every other text-like input fell through to the browser's default and
    sat next to a styled one with a different border, height and background.
    `search` was the note filter, the conversation search and the settings
    search; `date` and `time` were the whole reminder form.

    This checks the markup against the stylesheet rather than the stylesheet
    against itself, so adding an `<input type="email">` to a page fails here
    until it is given the same look as everything around it.
    """
    markup = re.sub(r"<!--.*?-->", "", (FRONTEND_DIR / "index.html").read_text(encoding="utf-8"), flags=re.S)
    used = set(re.findall(r'<input[^>]*type="([\w-]+)"', markup))
    styled = set(re.findall(r'input\[type="([\w-]+)"\]', _stylesheet()))
    missing = sorted((used & TEXTUAL_INPUTS) - styled)
    assert not missing, (
        f"These input types are used in index.html but never styled: {missing}. "
        "Add them to the shared text-input rule in style.css."
    )


def test_the_shared_rule_never_swallows_a_non_text_control():
    """A checkbox with `width: 100%` and 0.8rem of padding stops being a
    checkbox. The rule lists its types explicitly for exactly this reason, 
    a negation would be forever chasing the next control that isn't a text
    box."""
    block = re.search(
        r"((?:(?:textarea|select|input\[type=\"[\w-]+\"\]),?\s*)+)\{[^}]*width:\s*100%",
        _stylesheet(),
    )
    assert block, "the shared text-input rule was not found"
    listed = set(re.findall(r'input\[type="([\w-]+)"\]', block.group(1)))
    assert not (listed & NON_TEXTUAL_INPUTS), (
        f"non-text controls in the shared text-input rule: {sorted(listed & NON_TEXTUAL_INPUTS)}"
    )


# --- the CARP additions (DESIGN.md, "The principles this system is an
# implementation of") -------------------------------------------------------
#
# The four tests above this line cover spacing, type and corners: the values a
# rule *declares*. The two below cover the two failures that survived all of
# them, because a stylesheet can be perfectly on-scale and still render
# inconsistently:
#
#   - A control class can declare padding and font-size and no height, and
#     then render at five different heights depending only on what each
#     instance happens to contain. `button.small` did exactly that: measured
#     live at 19, 24, 25, 26 and 30px across six screens.
#   - A hit target can be below the size a person can reliably hit. The
#     Semantic toggles measured 32x18 and the reminder checkboxes 13x13,
#     against WCAG 2.2 AA's 24px floor.
#
# Neither is visible in a diff, and both were found by measuring a running
# browser. These make them visible in CI instead.


def test_the_hit_target_floor_is_declared_and_used():
    """`--target-min` exists, and the controls that had no height use it.

    DESIGN.md's "Hit targets" section is the contract. Without this, the token
    can be quietly dropped by a later refactor and every control it was
    holding up goes back to being sized by its content, which is how it got
    to 19px in the first place.
    """
    css = css_text()
    assert "--target-min:" in css, (
        "--target-min is gone. It is the floor under every interactive "
        "element (DESIGN.md, 'Hit targets'), a control with no declared "
        "height falls back to being sized by whatever text it holds."
    )
    for selector in ("button.small", 'input[type="checkbox"]'):
        block = _rule_block(css, selector)
        assert block is not None, f"{selector} has no rule at all any more"
        assert "--target-min" in block, (
            f"`{selector}` no longer uses --target-min. Measured before it "
            f"did: button.small rendered at 19/24/25/26/30px across six "
            f"screens, and checkboxes at 13x13 against WCAG 2.2 AA's 24px."
        )


def test_every_indefinite_animation_answers_reduced_motion():
    """An `infinite` animation has a `prefers-reduced-motion` branch.

    DESIGN.md states the rule and why the branch must *keep the information*:
    stopping a spinner is right, removing the thing it was telling you is not.
    This checks the mechanical half, that a branch exists at all, because
    that is the half a new component silently skips.
    """
    css = css_text()
    animated = set(re.findall(r"animation:[^;]*\binfinite\b[^;]*;", css))
    if not animated:
        return
    reduced = re.findall(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}", css, re.S
    )
    blob = "\n".join(reduced)
    # Every selector that declares an infinite animation should appear inside
    # at least one reduced-motion block. Matched on the selector rather than
    # the declaration, since the branch turns the animation *off*.
    offenders = []
    for match in re.finditer(
        r"([^{}]+)\{[^{}]*animation:[^;]*\binfinite\b[^;]*;[^{}]*\}", css
    ):
        selector = match.group(1).strip().split("\n")[-1].strip()
        if not selector or selector.startswith("@"):
            continue
        head = selector.split()[-1].lstrip(".#")
        if head and head not in blob:
            offenders.append(selector)
    assert not offenders, (
        "These run an indefinite animation with no prefers-reduced-motion "
        "branch:\n  " + "\n  ".join(offenders) + "\n\nSee DESIGN.md, 'Motion'."
    )


def _rule_block(css: str, selector: str) -> str | None:
    """The declaration block of the first rule whose selector *list* contains
    `selector` as a whole entry.

    Written as a depth-tracking scan rather than a regex over `{...}` pairs.
    A flat regex desyncs on the first `@keyframes`, nested braces, and then
    attributes every later rule to the wrong selector, which is how this
    helper failed twice before being written this way. Comments are stripped
    first so a brace inside one cannot do the same.
    """
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth, i, head = 0, 0, 0
    while i < len(body):
        char = body[i]
        if char == "{":
            depth += 1
            if depth == 1:
                selectors = [s.strip() for s in body[head:i].split(",")]
                if selector in selectors:
                    end, inner = i + 1, 1
                    while end < len(body) and inner:
                        inner += (body[end] == "{") - (body[end] == "}")
                        end += 1
                    return body[i + 1 : end - 1]
        elif char == "}":
            depth -= 1
            if depth == 0:
                head = i + 1
        i += 1
    return None


def test_the_hidden_attribute_is_enforced_over_the_apps_own_display_rules():
    """`<button hidden>` must actually be hidden.

    Reported with a screenshot, "there's an empty bubble in the header next
    to the model name??", and measured as `hidden: true` with
    `display: "flex"`, a 24.8x20px pill with nothing in it. The attribute's
    `display: none` comes from the *user agent* stylesheet, so any author rule
    beats it, and this app sets `display: flex` on every `button`: every
    `<button hidden>` in the app was visible. A `<span hidden>` in the same row
    was correctly invisible, which is why it went unnoticed for so long.

    A lint rather than a behaviour test for the usual reason: nothing in this
    Python suite can see a rendered DOM, and the rule is one line to keep and
    a screenshot plus several rounds to rediscover.
    """
    block = _rule_block(_stylesheet(), "[hidden]")
    assert block is not None, "no `[hidden]` rule: see this test's docstring"
    assert "display" in block and "none" in block and "!important" in block
