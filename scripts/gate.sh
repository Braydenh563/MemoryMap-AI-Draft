#!/usr/bin/env bash
# The merge gate, in one command, so no merge skips a step it is tired of:
#
#   scripts/gate.sh            # lint set + node --check + ruff (about 40 s)
#   scripts/gate.sh --changed  # plus the tests that name files changed since
#                              # origin/main (the routine local gate)
#   scripts/gate.sh --full     # plus the whole suite (10 to 15 minutes: CI runs
#                              # it on push; locally once before the PR closes)
#   scripts/gate.sh --staged   # the lint set against what is STAGED, not the
#                              # working tree: the one that catches a commit
#                              # that splits a pair (see below)
#   BASE=http://127.0.0.1:8784 scripts/gate.sh --sweeps   # plus errors, docks,
#                                                          # contrast, touch on a running app
#
# Exit code is the first failure's. Prints the five-line shape the reports
# use: what ran, what passed, what failed, what was skipped, where the logs
# are. CLAUDE.md standing orders 5 and 5a; HANDOVER's merge recipe.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# An agent worktree has no `.venv` of its own, so resolve the interpreter and
# ruff from the main checkout when this copy lacks them. Reported by an agent
# whose ruff step failed for that reason alone, on a tree with nothing wrong
# with it. `git rev-parse --git-common-dir` names the main repo's .git even
# from inside a linked worktree, which is what makes the fallback findable
# without hard-coding a path.
MAIN="$(cd "$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || echo "$ROOT/.git")/.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$MAIN/.venv/bin/python"
RUFF="$ROOT/.venv/bin/ruff"
[ -x "$RUFF" ] || RUFF="$MAIN/.venv/bin/ruff"
LOG="${GATE_LOG:-$ROOT/.gate}"
mkdir -p "$LOG"
FULL=0; SWEEPS=0; CHANGED=0; STAGED=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --changed) CHANGED=1 ;;
    --sweeps) SWEEPS=1 ;;
    --staged) STAGED=1 ;;
  esac
done
ran=(); passed=(); failed=(); skipped=()
step() {  # name, command...
  local name="$1"; shift
  ran+=("$name")
  if "$@" > "$LOG/$name.log" 2>&1; then passed+=("$name"); else failed+=("$name"); fi
}
LINTS=(tests/test_style_scale.py tests/test_ui_signatures.py tests/test_css_braces.py
  tests/test_frontend_ids.py tests/test_frontend_handlers.py tests/test_dock_grammar.py
  tests/test_docs_layout.py tests/test_asset_cache_busting.py tests/test_no_em_dashes.py
  tests/test_no_innerhtml_interpolation.py tests/test_markdown_link_schemes.py
  tests/test_frontend_load_order.py tests/test_ui_recipes.py tests/test_perf_mode.py
  tests/test_plan_hygiene.py tests/test_readme_freshness.py tests/test_vendor_licences.py
  # Mirror drift (docs/CHANGELOG.md and friends) belongs here rather than in
  # --changed: the file that goes stale is a `.md` at the repo root, and the
  # changed-test heuristic matches on a test naming a changed *source* file, so
  # it never selects this one. A full local run caught six edits' worth of
  # drift on 2026-09-12 that every `--changed` gate that day had passed. One
  # second.
  tests/test_docs_site.py)
step lints "$PY" -m pytest -q -p no:warnings "${LINTS[@]}"

# --staged: the same lint set, against the *index* rather than the working
# tree.
#
# Why this exists, and it cost a broken build to learn. In the shared
# worktree two agents and the orchestrator edit at once, so `git add <file>`
# stages the whole of a file including whatever someone else has half-written
# in it. One commit on 2026-09-12 staged `frontend/index.html` while an agent
# was mid-way through removing the "Add to document" select: the id went, its
# `$("entry-document").addEventListener` in `app.js` stayed (unstaged), and a
# top-level listener on `null` aborted the whole of `app.js`. `initAuth` never
# ran, the lock overlay never left `.hidden`, and the app did not boot at all
# on that head.
#
# `test_frontend_ids.py` would have caught it: it is in LINTS above and it
# checks exactly that every `$("id")` exists in the markup. It passed, because
# it ran against the *working tree*, where the pair was still whole. The gate
# was checking something nobody was about to commit.
#
# `git checkout-index` writes the staged content of every tracked file into a
# scratch tree, and the lints run there, which is what CI will see.
staged_lints() {
  # No RETURN trap: this script runs under `set -u` and the trap body is
  # evaluated after the local has gone, which fails as "tmp: unbound
  # variable" and hides the real result. Clean up on both paths instead.
  local tmp rc
  tmp="$(mktemp -d)"
  if git -C "$ROOT" checkout-index -a --prefix="$tmp/"; then
    (cd "$tmp" && "$PY" -m pytest -q -p no:warnings "${LINTS[@]}")
    rc=$?
  else
    rc=1
  fi
  rm -rf "$tmp"
  return "$rc"
}
if [ "$STAGED" = 1 ]; then
  if git -C "$ROOT" diff --cached --quiet; then
    skipped+=("staged-lints (nothing staged)")
  else
    step staged-lints staged_lints
  fi
else
  skipped+=("staged-lints (--staged)")
fi
node_check() { local bad=0; for f in frontend/*.js; do node --check "$f" || bad=1; done; return $bad; }
step node-check node_check
step ruff "$RUFF" check .
# --changed: every changed test file, plus tests/test_<stem>*.py for each
# changed source or frontend file (routes_files.py -> test_files*.py and
# test_routes_files*.py; graph.js -> test_graph*.py), for the files changed
# since the last push (the branch's upstream; GATE_BASE overrides) plus the
# working tree. Not since origin/main: on a long branch that is the whole
# suite again. It prints the list it picked so a miss is visible.
changed_tests() {
  local base; base="${GATE_BASE:-$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || echo HEAD~1)}"
  { git diff --name-only "$base"; git diff --name-only; git ls-files --others --exclude-standard; } | sort -u |
  while read -r f; do
    case "$f" in
      tests/test_*.py) [ -f "$f" ] && echo "$f" ;;
      src/memorymap/*.py|src/memorymap/*/*.py|frontend/*.js|frontend/css/*.css)
        stem="$(basename "$f")"; stem="${stem%.*}"
        ls tests/test_"${stem}"*.py 2>/dev/null
        case "$stem" in routes_*) ls tests/test_"${stem#routes_}"*.py 2>/dev/null ;; esac
        # **And any test that names this file, when the name is distinctive.**
        # The rule above maps a changed file to tests *named* after it, which
        # misses a test that exercises it under another name: on 2026-09-09 a
        # preview change turned `tests/test_library_previews.py` red and this
        # gate stayed green, because nothing anyone touched was called
        # "library_previews". An agent found it while doing something else.
        #
        # Distinctive is the whole difficulty. A first attempt grepped every
        # stem and `app`, `library` and `graph` selected most of the suite,
        # which is the full run this flag exists to avoid. So: at least seven
        # characters, and never one of the handful of words that name a whole
        # surface. A stem below the bar keeps the name-based rule above and
        # nothing more, and `--full` and CI are what cover the rest.
        case "$stem" in
          app|main|utils|index|graph|library|settings|documents|whiteboard|chat|notes) ;;
          ???????*) grep -rls --include='test_*.py' -e "$stem" tests/ 2>/dev/null ;;
        esac ;;
    esac
  done | sort -u
}
if [ "$CHANGED" = 1 ]; then
  mapfile -t TARGETED < <(changed_tests)
  # A selection this large is not a targeted run any more, and pretending
  # otherwise would hide how long the gate is about to take. Say so and run
  # it: a slow honest gate beats a fast one that skipped the thing that
  # matters.
  if [ "${#TARGETED[@]}" -gt 40 ]; then
    echo "changed-tests: ${#TARGETED[@]} files selected, which is most of the suite; consider --full"
  fi
  if [ "${#TARGETED[@]}" = 0 ]; then skipped+=("changed-tests (none matched)");
  else
    [ "${#TARGETED[@]}" -le 40 ] && echo "changed-tests: ${TARGETED[*]}"
    step changed-tests "$PY" -m pytest -q -p no:warnings "${TARGETED[@]}"
  fi
else skipped+=("changed-tests (--changed)"); fi
if [ "$FULL" = 1 ]; then step full-suite "$PY" -m pytest -q -p no:warnings tests/; else skipped+=("full-suite (--full)"); fi
if [ "$SWEEPS" = 1 ]; then
  export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
  export BASE="${BASE:-http://127.0.0.1:8781}"
  for s in errors docks contrast touch; do step "sweep-$s" node "scratchpad/ui-sweeps/$s.js"; done
else
  skipped+=("sweeps (--sweeps, needs BASE)")
fi
echo "ran:     ${ran[*]}"
echo "passed:  ${passed[*]:-none}"
echo "failed:  ${failed[*]:-none}"
echo "skipped: ${skipped[*]:-none}"
echo "logs:    $LOG/<step>.log"
[ "${#failed[@]}" = 0 ]
