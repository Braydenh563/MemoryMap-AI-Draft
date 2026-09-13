"""A shared helper lives in a file every caller is loaded after.

There is no bundler and no module system here: `index.html` lists the scripts
and the browser runs them in that order. A `function` declaration is hoisted
inside its own file only, so code that runs while the page is still loading can
reach helpers from a script that has already run, and nothing else.

The report this exists for, from the running app:

    ReferenceError: apiPagedList is not defined
        at loadCaptureDocuments (app.js:10059)
        at showNotesSection (app.js:25240)
        at initNotesSubtabs (app.js:25290)
        at app.js:32441

`apiPagedList` was defined in documents.js, which index.html loads ten lines
after app.js. Its own comment argued the placement was safe because "both call
it from inside a function body, so load order is satisfied either way": true
when it was written, false the moment app.js called it from boot code. The
Notes tab died before drawing anything, and no other test here could see it,
because a Python test cannot run the page and every call site reads as correct
on its own.

**What this checks, and what it does not.** Two cheap rules: a call written as
a statement in a script's own top-level code, and the placement of the helpers
that are shared widely enough for the question to arise at all. The general
version, following the call graph from every top-level statement, was written
and then cut: the walk has to know which bodies are callbacks (a body handed to
`addEventListener` runs later, not now), and getting that right without a
parser took longer to run than the whole lint set. `errors.js` in the sweeps
catches the runtime half by loading the page and reading the console, which is
how this one would have been caught before it shipped. Recorded in BACKLOG.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
INDEX = FRONTEND / "index.html"

#: Scripts that run before the app's own code and guard every cross-file call
#: they make (`typeof x === "function"`, `window.x?.()`). They are the boot
#: shims, and the guard is the point of them.
BOOT_SHIMS = {"boot-guard.js", "theme-boot.js"}

def _script_order() -> list[str]:
    html = INDEX.read_text(encoding="utf-8")
    names: list[str] = []
    for match in re.finditer(r'<script src="/([A-Za-z0-9_.-]+\.js)', html):
        name = match.group(1)
        if (FRONTEND / name).exists() and name not in names:
            names.append(name)
    assert names, "no local scripts found in index.html"
    return names


def _top_level(source: str) -> str:
    """Everything outside a top-level `function` declaration: the code that
    runs the moment the browser reaches the line."""
    out: list[str] = []
    depth = 0
    for line in source.split("\n"):
        stripped = line.strip()
        if depth == 0 and not stripped.startswith(("//", "/*", "*")):
            out.append(line)
        depth += line.count("{") - line.count("}")
        depth = max(depth, 0)
    return "\n".join(out)


STATEMENT_CALL = re.compile(r"^\s*(?:await\s+|void\s+)?([A-Za-z_$][\w$]*)\s*\(", re.M)
NOT_CALLS = {"if", "for", "while", "switch", "catch", "return", "typeof", "function"}


def test_no_script_calls_a_later_script_from_its_own_top_level():
    order = _script_order()
    sources = {name: (FRONTEND / name).read_text(encoding="utf-8") for name in order}
    defined_in: dict[str, str] = {}
    for name in order:
        for function in re.findall(r"^(?:async )?function ([A-Za-z_$][\w$]*)\(", sources[name], re.M):
            defined_in.setdefault(function, name)

    problems = []
    for index, name in enumerate(order):
        if name in BOOT_SHIMS:
            continue
        already = set(order[: index + 1])
        called = {m.group(1) for m in STATEMENT_CALL.finditer(_top_level(sources[name]))} - NOT_CALLS
        for function in sorted(called):
            home = defined_in.get(function)
            if home and home not in already:
                problems.append(f"{name} calls {function}() at load, defined in {home}")

    assert not problems, (
        "these calls run while the page is loading and name a helper from a "
        "script that has not run yet, which is a ReferenceError in the browser "
        "and invisible to every other test here: " + "; ".join(problems)
    )


def test_the_paging_helper_is_reachable_from_the_script_that_boots_with_it():
    """The specific case, named, because the walk above only sees the direct
    call and this one arrived three frames deep: `initNotesSubtabs()` at the
    bottom of app.js, into `showNotesSection`, into `loadCaptureDocuments`.

    Six frontend files call `apiPagedList` now. The one they are all loaded
    after is app.js, so that is where it lives.
    """
    order = [name for name in _script_order() if name not in BOOT_SHIMS]
    callers = [
        name
        for name in order
        if re.search(r"(?<![\w$.])apiPagedList\s*\(", (FRONTEND / name).read_text(encoding="utf-8"))
    ]
    assert callers, "nothing calls apiPagedList any more; is it still needed?"
    home = [
        name
        for name in order
        if re.search(r"^(?:async )?function apiPagedList\(", (FRONTEND / name).read_text(encoding="utf-8"), re.M)
    ]
    assert len(home) == 1, f"apiPagedList is defined in {home}"
    assert order.index(home[0]) <= order.index(callers[0]), (
        f"apiPagedList lives in {home[0]}, which index.html loads after "
        f"{callers[0]}, and app.js reaches it from `initNotesSubtabs` at load"
    )
