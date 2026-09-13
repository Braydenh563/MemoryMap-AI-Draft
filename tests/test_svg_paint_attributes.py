"""A stylesheet `fill` silently beats a `fill` attribute, so the pair is a lint.

**This exists because it cost a measurement round.** `mapPreview` (app.js)
draws a map's labels and, when a label sits inside a coloured node, has to
paint it white or near-black by that colour's own luminance. The first
version set `text.setAttribute("fill", ...)`, which is exactly how the SVG
spec says to give an element a paint, and the label's contrast did not move:
3.82:1 before and 3.82:1 after, measured in the browser both times. The cause
is one line of CSS: `.board-minimap-label { fill: var(--ink) }`. A
presentation attribute is a declaration at the *bottom* of the cascade, below
every author rule however unspecific, so any stylesheet rule for that
property wins and the attribute is dead markup.

Nothing about that is visible in a diff. The attribute is right there in the
code, spelled correctly, on the right element, and a reviewer reading either
file alone sees nothing wrong; the blocks in the same function already carried
a comment about it and the labels still hit it. So the check is here: JavaScript
that sets a paint attribute on an element carrying a class that the stylesheets
paint is a fault, and the fix is a class (`.board-minimap-label-light`) or
`el.style.fill`, both of which sit above the stylesheet.

**Scope, and what it cannot see.** Only `fill` and `stroke`, only where the
same function assigns a class to that element in the ten lines above the
attribute, and only for classes the stylesheets paint. The class may be
assigned conditionally (`setAttribute("class", flag ? "a" : "b")`, a
`classList.add(a, b)` with several names, a template literal with a suffix
interpolated into it): every class name spelled out in the assignment is
checked, because the version that only read a bare string literal walked past
`mapPreview`'s own coloured block, one function away from the bug that caused
this file.

What it cannot see is an element with **no** class that a descendant selector
paints: `.graph-node text { fill: ... }` reaches a `<text>` that names no
class of its own, and knowing whether a given `createElementNS(..., "text")`
ends up inside a `.graph-node` means knowing the tree, which a text scan does
not. Matching on the element name alone was tried and is wrong: the four
descendant paint rules in the stylesheets (`.board-minimap-ghost path`,
`.graph-node text`, `.timeline-branch-ticks line`, `.timeline-branch-ticks
text`) would flag `whiteboard.js`'s alignment guide, a `<line>` painted by
attribute in a different subtree entirely, and a lint with a false positive in
it gets widened until it is silent. Nine paint attributes on unclassed
elements are outside this file's reach for that reason.

That half is checked in a browser instead, where the tree is real:
`scratchpad/ui-sweeps/paint.js` walks every rendered SVG element carrying a
`fill` or `stroke` attribute and reports the ones whose computed paint is a
different colour, which is the same fault from the other end.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._css_paths import css_text

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

#: The two paint properties a stylesheet and an attribute can both name. The
#: rest of the SVG presentation attributes (`opacity`, `stroke-width`, `rx`)
#: have the same rule, and are left out until one of them actually bites:
#: a lint nobody has seen fire is a lint nobody trusts.
PAINTS = ("fill", "stroke")

#: How far above a `setAttribute("fill", ...)` to look for the class that
#: element was given. Ten lines covers "make the element, class it, place it,
#: paint it", which is the shape every one of these sites has, and stops the
#: search well before the previous element in the same loop.
LOOKBACK = 10

#: The three ways this codebase gives an element a class, matched as far as
#: the closing bracket or the end of the line rather than to one string
#: literal. `mapPreview` writes `dot.setAttribute("class", item.color ?
#: "board-minimap-branch" : grey)`, and a pattern that insisted on a literal
#: right after the comma saw no class there at all and so checked nothing,
#: three lines above a `fill` attribute. Every name the assignment spells out
#: is then taken from the captured text by `_class_names`; one built entirely
#: out of variables is invisible either way, and stays that way.
CLASS_ASSIGNMENT = re.compile(
    r"""setAttribute\(\s*["']class["']\s*,([^)]*)\)"""
    r"""|className\s*=(?!=)([^;]*)"""
    r"""|classList\.add\(([^)]*)\)"""
)

#: A string literal inside such an assignment, single-quoted, double-quoted or
#: a template. A template's interpolations are dropped and its fixed text is
#: kept: `` `board-minimap-label-${tone}` `` contributes no class name, which
#: is the honest reading, while `` `${base} graph-label` `` contributes one.
STRING_LITERAL = re.compile(r"""'([^']*)'|"([^"]*)"|`([^`]*)`""")

#: A template literal's `${...}` while the names around it are read: a
#: character no class name can contain and no source file holds, so a name
#: that touches one is recognisable afterwards and thrown away.
HOLE = "\x01"
PAINT_ATTRIBUTE = re.compile(
    r"""(\w+)\.setAttribute\(\s*["'](fill|stroke)["']"""
)


def _painted_classes() -> dict[str, set[str]]:
    """Every class the stylesheets give a `fill` or a `stroke`, by property.

    Comments are stripped first for the reason `test_style_scale.py` strips
    them: this file's comments quote CSS, and a scan that reads a quoted
    declaration as a real one reports a rule that does not exist.
    """
    text = re.sub(r"/\*.*?\*/", "", css_text(), flags=re.S)
    painted: dict[str, set[str]] = {paint: set() for paint in PAINTS}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        for paint in PAINTS:
            if not re.search(rf"(?m)^\s*{paint}\s*:", body):
                continue
            painted[paint].update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
    return painted


def _class_names(assignment: re.Match[str]) -> list[str]:
    """Every class name spelled out in one class assignment.

    A name is taken only from a string literal, so a variable holding a class
    contributes nothing and a template's `${...}` holes contribute nothing:
    both are simply unknown here, and a lint that guesses at them would be
    matching on the shape of the code rather than on what it does. Splitting
    on whitespace is what turns `class="a b"` into two names.
    """
    text = " ".join(group for group in assignment.groups() if group)
    names = []
    for literal in STRING_LITERAL.finditer(text):
        value = next(group for group in literal.groups() if group is not None)
        #: A template's interpolations are holes *inside* a name as often as
        #: they are whole names: `wb-align-guide-${kind}` is one class whose
        #: ending is unknown, not the class `wb-align-guide-`. So each hole
        #: becomes a marker that counts as part of a word, and any name that
        #: ends up carrying one is dropped rather than reported as a prefix.
        #: The neighbouring `wb-align-guide-line` in the same literal is still
        #: read, which is the point of splitting on whitespace at all.
        marked = re.sub(r"\$\{[^}]*\}", HOLE, value)
        for name in re.findall(rf"[A-Za-z{HOLE}][\w{HOLE}-]*", marked):
            if HOLE not in name:
                names.append(name)
    return names


def _sites_in(source: str, where: str) -> list[tuple[str, int, str, str, str]]:
    """Every `el.setAttribute("fill"|"stroke", ...)` in one file, with the
    classes that element was given just above it: `(where, line, variable,
    paint, class)`.

    Split from `_sites` so the self-check below can run it over a fabricated
    two-line sample. A lint whose only proof is "the codebase is clean" proves
    nothing once the codebase *is* clean, which is exactly what happened here
    the moment the bug it was written for was fixed.
    """
    found = []
    lines = source.splitlines()
    for number, line in enumerate(lines, start=1):
        match = PAINT_ATTRIBUTE.search(line)
        if not match:
            continue
        variable, paint = match.group(1), match.group(2)
        for above in lines[max(0, number - 1 - LOOKBACK) : number - 1]:
            if variable not in above:
                continue
            assignment = CLASS_ASSIGNMENT.search(above)
            if not assignment:
                continue
            for name in _class_names(assignment):
                found.append((where, number, variable, paint, name))
    return found


def _sites() -> list[tuple[str, int, str, str, str]]:
    """The same, across every frontend script."""
    found = []
    for path in sorted(FRONTEND.glob("*.js")):
        found.extend(_sites_in(path.read_text(encoding="utf-8"), path.name))
    return found


def test_no_paint_attribute_is_overridden_by_a_stylesheet_rule():
    painted = _painted_classes()
    offenders = []
    for where, number, variable, paint, name in _sites():
        if name in painted[paint]:
            offenders.append(
                f"{where}:{number}: {variable}.setAttribute('{paint}', ...) "
                f"on .{name}, which the stylesheets already paint"
            )
    assert not offenders, (
        "A stylesheet declaration beats a presentation attribute, so these "
        "attributes are dead markup:\n  "
        + "\n  ".join(sorted(set(offenders)))
        + "\n\nGive the element a class that paints it, or set el.style."
        + PAINTS[0]
        + " , which sits above the stylesheet."
    )


SAMPLE = '''
  const text = document.createElementNS(NS, "text");
  text.setAttribute("class", "board-minimap-label");
  text.setAttribute("fill", "#ffffff");
  const other = document.createElementNS(NS, "text");
  other.setAttribute("class", tone ? "board-minimap-label" : "quiet");
  other.setAttribute("fill", "#ffffff");
  const third = document.createElementNS(NS, "line");
  third.setAttribute("class", `board-minimap-edge guide-${kind}`);
  third.setAttribute("stroke", "#ffffff");
'''


def test_the_lint_can_see_the_bug_it_was_written_for():
    """The check that this is a lint rather than a shape that happens to pass.

    Both halves have to keep working: the CSS scan has to find that
    `.board-minimap-label` is painted (it is the class that started this), and
    the JavaScript scan has to pair a class with the attribute set below it.
    The second half is run over a fabricated sample on purpose. The real
    frontend has no such pair left, because the two this found were fixed, and
    a lint that can only demonstrate itself while the bug is present stops
    demonstrating anything the moment it works.
    """
    painted = _painted_classes()
    assert "board-minimap-label" in painted["fill"], (
        "the CSS scan no longer finds .board-minimap-label's fill, so this "
        "file would pass whatever the JavaScript does"
    )
    caught = _sites_in(SAMPLE, "sample")
    assert [(paint, name) for _, _, _, paint, name in caught] == [
        ("fill", "board-minimap-label"),
        ("fill", "board-minimap-label"),
        ("fill", "quiet"),
        ("stroke", "board-minimap-edge"),
    ], f"the JavaScript scan no longer pairs a class with its paint: {caught}"
