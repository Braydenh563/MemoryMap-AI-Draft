"""No module in `memorymap` may import its way back to itself.

This is a lint, not a behaviour test, and it exists because a cycle costs
nothing until it costs everything: CodeQL alert #364 ("Cyclic import",
`ai/embeddings.py:24`) sat open on `main` because nothing in the suite could
see it, and the cycle it named, 

    ai.embeddings -> ai.ollama_client -> ai.provider -> core.deps
                  -> ai.embeddings

- was only reachable at import time in one ordering, so every test passed.
Two more cycles of the same shape were sitting next to it, unreported:
`ai.embeddings -> core.extras -> core.ocr -> core.deps -> ai.embeddings`
and `__main__ -> api.app -> api.routes_settings -> __main__`.

All three had the same wrong-direction edge, a module the dependency
container *builds* naming the container back, and all three were broken the
same way, with `importlib.import_module` at the call site. That detail is the
reason this file counts every `import` statement anywhere in a file, not just
the module-level ones: CodeQL counts the *statement*, so moving an import
into a function body hides the cycle from a naive checker while leaving the
alert open. `entry/manager.py` records the same finding in a comment.

If this fails, the fix is to find the edge that points the wrong way, from a
leaf back into `core.deps`, `api.app` or `__main__`, and drop that `import`
statement in favour of `importlib.import_module`, with a comment saying which
cycle it breaks. Do not add the new cycle to an allowlist; there isn't one.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = "memorymap"

# Depth cap on the search. Every cycle found so far has been four modules
# long; six leaves room for one that is longer without the walk blowing up on
# a package this size.
MAX_CYCLE_LENGTH = 6


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    name = ".".join(rel.parts)
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def _import_graph() -> dict[str, set[str]]:
    modules = {_module_name(p): p for p in SRC.rglob("*.py")}
    graph: dict[str, set[str]] = defaultdict(set)
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                # `from a.b import c` may name either the module `a.b.c` or an
                # attribute of `a.b`; try the longer form first and fall back.
                targets = [node.module] + [
                    f"{node.module}.{alias.name}" for alias in node.names
                ]
            for target in targets:
                if not target.startswith(PACKAGE):
                    continue
                resolved = target
                while resolved and resolved not in modules:
                    resolved = resolved.rpartition(".")[0]
                if resolved and resolved != name:
                    graph[name].add(resolved)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for start in sorted(graph):

        def walk(node: str, path: list[str], start: str = start) -> None:
            if len(path) > MAX_CYCLE_LENGTH:
                return
            for nxt in sorted(graph.get(node, ())):
                if nxt == start:
                    found.add(tuple(path))
                    continue
                # `nxt < start` keeps each cycle to one representative: it is
                # only enumerated from its alphabetically first module.
                if nxt in path or nxt < start:
                    continue
                walk(nxt, [*path, nxt])

        walk(start, [start])
    return sorted(found, key=len)


def test_the_package_has_no_import_cycles() -> None:
    cycles = _cycles(_import_graph())
    rendered = "\n".join(" -> ".join(c) + f" -> {c[0]}" for c in cycles)
    assert not cycles, f"import cycle(s) reintroduced:\n{rendered}"
