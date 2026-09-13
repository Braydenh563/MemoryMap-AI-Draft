"""Math renders as MathML, from a TeX subset, with no library behind it.

DOCUMENTS_PLAN Phase 3 item 2 asks for `$…$` "via a small in-repo MathML
renderer, no KaTeX". The reasons for the constraint are in documents.js beside
the code; what this file does is measure the claim, because a renderer that
half-understands a formula and prints something confident is worse than one
that prints the source.

Two properties are worth a test rather than a browser check. The first is the
shape of the tree: an operator has to be an `mo` and a variable an `mi`, or
the spacing is wrong in a way that reads as a font problem rather than as a
bug; a fraction has to be an `mfrac` with two children; `x_i^2` has to be one
`msubsup` rather than a superscript sitting on a subscript. The second is the
rule for what counts as math at all, which in a notebook full of prices is the
thing most likely to embarrass this feature: `$5 and $10` must stay two
prices.

The marked region of documents.js (`DOC-MATH-BEGIN` to `DOC-MATH-END`) is pure
string and object work with no DOM in it, so node can run it, and that
property is enforced by this test existing: the day it reaches for `document`
it stops running here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_JS = ROOT / "frontend" / "documents.js"

BEGIN = "// DOC-MATH-BEGIN"
END = "// DOC-MATH-END"


def math_source() -> str:
    text = DOCUMENTS_JS.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    end = text.find(END)
    assert start != -1, f"{BEGIN} marker is missing from documents.js"
    assert end > start, f"{END} marker is missing or before {BEGIN}"
    return text[start + len(BEGIN) : end]


DRIVER = r"""
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail: detail == null ? null : String(detail) });

//: The tree as a compact string, so an expectation reads like the formula.
function sketch(node) {
  if (node.text != null && !(node.kids || []).length) {
    return `${node.tag}(${node.text})`;
  }
  return `${node.tag}[${(node.kids || []).map(sketch).join(" ")}]`;
}

const CASES = [
  ["x", "math[mi(x)]"],
  ["1+2", "math[mrow[mn(1) mo(+) mn(2)]]"],
  ["E=mc^2", "math[mrow[mi(E) mo(=) mi(m) msup[mi(c) mn(2)]]]"],
  ["\\frac{a}{b}", "math[mfrac[mi(a) mi(b)]]"],
  ["\\frac{1}{2}x", "math[mrow[mfrac[mn(1) mn(2)] mi(x)]]"],
  ["\\sqrt{2}", "math[msqrt[mn(2)]]"],
  ["\\sqrt[3]{x}", "math[mroot[mi(x) mn(3)]]"],
  ["\\alpha + \\beta", "math[mrow[mi(α) mo(+) mi(β)]]"],
  ["a \\times b \\le c", "math[mrow[mi(a) mo(×) mi(b) mo(≤) mi(c)]]"],
  ["x_i^2", "math[msubsup[mi(x) mi(i) mn(2)]]"],
  ["x^2_i", "math[msubsup[mi(x) mi(i) mn(2)]]"],
  ["x_{i+1}", "math[msub[mi(x) mrow[mi(i) mo(+) mn(1)]]]"],
  ["\\sum_{n=1}^{10} n", "math[mrow[msubsup[mo(∑) mrow[mi(n) mo(=) mn(1)] mn(10)] mi(n)]]"],
  ["\\sin x", "math[mrow[mi(sin) mi(x)]]"],
  ["\\text{one two}", "math[mtext(one two)]"],
  //: `\left` and `\right` are sizing hints, not a group: they come out as
  //: the delimiters they name, in the row they were written in, which is what
  //: MathML stretches on its own.
  ["\\left(x+1\\right)", "math[mrow[mo(() mi(x) mo(+) mn(1) mo())]]"],
];

for (const [tex, want] of CASES) {
  let got;
  try {
    got = sketch(docMathTree(tex));
  } catch (error) {
    got = `threw: ${error.message}`;
  }
  check(`tree/${tex}`, got === want, `${got} (wanted ${want})`);
}

// A function name is upright; a variable is not.
{
  const tree = docMathTree("\\sin x");
  check("sin is upright", tree.kids[0].kids[0].attrs.mathvariant === "normal",
    JSON.stringify(tree.kids[0].kids[0].attrs));
  check("x has no variant", !tree.kids[0].kids[1].attrs, JSON.stringify(tree.kids[0].kids[1]));
}

// Display and inline are the same tree with a different attribute.
check("inline by default", docMathTree("x").attrs.display === "inline", docMathTree("x").attrs.display);
check("display when asked", docMathTree("x", true).attrs.display === "block", "");

// Nothing in this region may reach for the DOM.
check("no inline styles", JSON.stringify(docMathTree("\\mathbf{a}")).includes("mathvariant"), "");

// **What is math and what is a price.**
const MATHS = ["x^2", "a+b", "\\frac{1}{2}", "E=mc^2", "\\pi r^2", "n_1"];
const PRICES = ["5 and ", "5-", "5", " x ", "", "1,000", "10 to "];
for (const body of MATHS) {
  check(`is math/${body}`, docMathLooksLikeMath(body), "read as prose");
}
for (const body of PRICES) {
  check(`not math/${JSON.stringify(body)}`, !docMathLooksLikeMath(body), "read as math");
}

// Nothing throws, whatever it is handed: an editor renders as you type, so
// every half-typed formula in the document is an input to this.
for (const partial of ["\\frac{", "x^", "{", "}", "\\", "\\unknown{x}", "^{}_{}", "$$", "\\sqrt["]) {
  let ok = true;
  try {
    docMathTree(partial);
  } catch (error) {
    ok = false;
  }
  check(`survives/${JSON.stringify(partial)}`, ok, "threw");
}

process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def math_checks(tmp_path_factory) -> list[dict]:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is in the sandbox and in CI
        pytest.skip("node is not available")
    script = tmp_path_factory.mktemp("docmath") / "run.js"
    script.write_text(math_source() + DRIVER, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_renderer_runs_without_a_browser(math_checks: list[dict]) -> None:
    assert len(math_checks) > 30


def test_the_tex_subset_renders_as_the_mathml_it_claims(math_checks: list[dict]) -> None:
    failed = [c for c in math_checks if not c["ok"]]
    assert not failed, "\n".join(f"{c['name']}: {c['detail']}" for c in failed[:20])
