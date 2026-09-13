"""Run the golden eval set against a **real** local model (PLAN.md §4, A6).

    make eval                                   # the documented command
    PYTHONPATH=src python scripts/eval.py       # the same thing by hand
    PYTHONPATH=src python scripts/eval.py --model qwen3:4b --limit 5

## What this scores that CI cannot

`tests/eval/test_eval_harness.py` runs the same thirty asks against the fake
transport, and scores the two things that are observable without a model: was
the answering tool *offered*, and does it cite the right things when it runs.
It deliberately does not score "did the model pick the right tool", because
the fake calls whatever it was scripted to call — scoring that would be
scoring the script (CLAUDE.md's standing caveat).

This does score exactly that. Each ask goes through `agent.run_agent` with the
real provider, and the **first tool the model actually calls** is compared
with the tool the golden set says answers it. That is the number that moves
when a prompt changes, when the tool descriptions change, or when you swap a
7B model for a 4B one — and it is the number nobody can get from CI.

## What it costs

One turn per ask, thirty asks. On a small local model that is a few minutes.
Nothing is written: the golden set is read-only and every write tool is left
out of the offered set below, so this can be pointed at a scratch notebook
without risk. It builds its own throwaway notebook in a temp directory and
never touches the real data dir.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Runnable as `python scripts/eval.py` from a checkout, without an editable
# install — the same courtesy `pytest.ini`'s `pythonpath = src` gives the
# suite. The repo root is this file's parent's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="", help="Chat model to use (default: the notebook's configured one)")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N asks")
    parser.add_argument("--verbose", action="store_true", help="Print every ask, not only the misses")
    args = parser.parse_args()

    from memorymap.ai import agent, tools
    from memorymap.core import deps
    from tests.eval import fixture, golden

    with tempfile.TemporaryDirectory(prefix="memorymap-eval-") as tmp:
        deps.reset_app_state()
        deps.init_app_state(data_dir=Path(tmp))
        config = deps.get_config()
        if args.model:
            config.set_preference("chat_model", args.model)
        ollama = deps.get_ollama()
        if not ollama.is_running():
            print(
                "No local model is reachable. Start Ollama (or point the app at an "
                "OpenAI-compatible server in Settings → Models) and try again.",
                file=sys.stderr,
            )
            return 2
        model_manager = deps.get_model_manager()
        session = deps.get_db().session()
        # The notebook has to exist for the asks to have anything to find; the
        # ids it returns are only needed by the CI scorer, which checks
        # citations. This run scores tool *choice*, which is about the ask.
        fixture.build(session)

        cases = golden.GOLDEN[: args.limit] if args.limit else golden.GOLDEN
        hits = 0
        misses: list[tuple[str, str, str]] = []
        for case in cases:
            called = ""
            try:
                for event in agent.run_agent(
                    session,
                    case.ask,
                    [],
                    model_manager,
                    ollama,
                    # Reads only. A golden set that could write would need a
                    # fresh notebook per ask, and a model that deleted a note
                    # while being measured would be an expensive surprise.
                    allowed_tools=sorted(set(tools.TOOLS) - set(tools.WRITE_TOOLS)),
                ):
                    if event.get("type") == "tool" and event.get("tool"):
                        called = event["tool"]
                        break
            except Exception as exc:  # noqa: BLE001 — one bad ask must not end the run
                misses.append((case.id, case.tool, f"raised {exc!r}"))
                continue
            if called == case.tool:
                hits += 1
                if args.verbose:
                    print(f"  ok    {case.id:<22} {called}")
            else:
                misses.append((case.id, case.tool, called or "(no tool called)"))

        session.close()
        deps.reset_app_state()

    print(f"\nreal-model eval — {model_manager.chat_model()}\n")
    for case_id, wanted, got in misses:
        print(f"  miss  {case_id:<22} wanted {wanted}, got {got}")
    if not misses:
        print("  every ask reached for the right tool")
    print(f"\n  tool choice {hits / max(1, len(cases)):.3f}   ({hits}/{len(cases)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
