# Contributing to MemoryMap AI

Thanks for your interest. This is a small, focused project with one
strong guiding principle, so a little context goes a long way.

## The one rule that shapes everything

**MemoryMap AI is 100% offline and local-first.** Every feature must
work on the user's own machine with no cloud dependency. The single
exception is web search, which is strictly opt-in and clearly marked.
If an idea needs to phone home, it's out of scope by design, but it's
still welcome in a discussion.

A few more principles worth knowing (the full list is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)):

- The app must stay usable with the AI (Ollama) turned off: degrade,
  never crash.
- Database migrations are **additive only** (new columns), so users
  never lose data.
- Shared state lives in exactly one place (`core/deps.py`); don't build
  your own `DatabaseManager` or `ConfigManager`.

If you're using an AI assistant on this codebase, read
[`CLAUDE.md`](CLAUDE.md) first. It's the project's own operating manual:
where things are checked before they're rebuilt, the standing lint set,
and the failure shapes seen most often when an assistant works here
without reading it first.

## Getting set up

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .            # editable install, don't forget the dot
```

Run the app with `python -m memorymap` and open <http://localhost:8000>.

## Before you open a PR

Two commands, both fast and fully offline (no Ollama, no models
needed):

```bash
pytest              # the full test suite
ruff check .        # lint
```

Or use the Makefile shortcut, which runs both:

```bash
make check          # lint + tests, the pre-push gate
```

Optional, to keep formatting tidy:

```bash
ruff format .       # auto-format (make format)
```

Prefer to catch problems automatically? Install the pre-commit hooks
once and the lint and hygiene checks run on every commit:

```bash
pip install pre-commit && pre-commit install
```

CI runs `ruff check` and `pytest` on Python 3.11, 3.12, and 3.13. Keep
both green. Run `make help` to see all the available tasks.

A handful of lints exist because the test suite cannot see the DOM:
`test_style_scale.py`, `test_ui_signatures.py`, `test_css_braces.py`,
`test_frontend_ids.py`, `test_frontend_handlers.py`,
`test_dock_grammar.py`, `test_docs_layout.py`,
`test_asset_cache_busting.py`, `test_no_em_dashes.py`,
`test_no_innerhtml_interpolation.py` and `test_markdown_link_schemes.py`.
If one of these fails, it has found something real: fix the cause,
never widen the rule.

## Writing code that fits in

- Match the style of the file you're editing: naming, comment density,
  idioms. The codebase favours short explanatory comments that say
  *why*, not *what*.
- New behaviour needs a test. Copy an existing `tests/test_*.py` and
  reuse the AI fakes in `tests/fakes.py` / `tests/conftest.py`, never
  call real Ollama.
- If you touch the architecture (new module, new table, new data flow),
  update `docs/ARCHITECTURE.md` in the same PR.
- Add a bullet to `CHANGELOG.md` under "Unreleased".

## Working with an AI assistant

AI coding tools are welcome here, but this codebase is mature (most
obvious features already exist), and the common failure mode is an
assistant "adding" something that's already there and gutting the
working version in the process. Three rules keep that from happening:

- **Reconcile before building.** Search for the feature first. If it
  exists, extend it, don't reimplement it. (Snooze, chat export,
  theming, the command palette, the skills bar and much more are
  already built.)
- **Additive only.** Extend functions rather than replacing them, and
  never delete a feature, widget, or CSS rule to make room for a new
  one without asking. `frontend/app.js` is one large script: make
  small, targeted edits.
- **One feature per commit.** After each commit, `git diff --stat`
  should list only the files that feature touches. An unexpectedly wide
  diff is the early warning sign of a regression.

## Commit and PR conventions

- Write clear, descriptive commit messages that explain the *why*.
- Keep PRs focused: one logical change per PR is easier to review.
- The PR template will prompt you for the essentials (what and why, how
  to test, the checklist). Fill it in.

## Reporting bugs and suggesting features

Use the issue templates: they ask the few questions that make a
local-first app easy to reproduce and reason about. For open-ended
ideas, start a Discussion instead of an issue.

## Security

Please don't file security problems as public issues. See
[`SECURITY.md`](SECURITY.md) for how to report them privately.
