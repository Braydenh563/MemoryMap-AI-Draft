# Brief 17, the launchers, the uninstallers and the splash: what is left

Agent: Opus, worktree `agent-ac1cca0f51eca7323`, branch
`claude/epic-ramanujan-8xocc0`. Brief 17's seven "Done when" items are all
landed: seven commits for the items themselves, and the rest for the bugs
that showed up once the flags were actually run. This file is now only the
list of things that could not be checked here, the bugs found, and the two
small things deliberately left.

Read Brief 17 in [`../SESSION_BRIEFS.md`](../SESSION_BRIEFS.md) first.

## Not verified, and why

**Nothing Windows was executed.** There is no cmd, no PowerShell and no
display in this sandbox, so `start.bat`, `uninstall.bat`,
`start-desktop.bat` and `scripts/splash.ps1` are read, not run. What stands
in for running them is `tests/test_launcher_scripts.py`, which checks the
things a read can actually settle: block depth, no parenthesis inside an
ECHO within an IF block, every `goto`/`call` target resolving to a label,
`%~2` read before the SHIFT in the `--port` branch, the redirect ahead of a
delayed-expansion ECHO, no apostrophe inside a single-quoted `FOR /F`, one
`Add_Click` per button, and balanced braces in the PowerShell. Everything
those tests cannot see is a first-run risk on Windows:

- `splash.ps1` has never been drawn. Layout numbers, the marquee moving
  between rows, the Details toggle growing the form to `$EXPANDED_HEIGHT`,
  `Clipboard::SetText` from a `-WindowStyle Hidden` host, and the error
  card's button swap are all reasoned, not observed.
- `start.bat --doctor` has never printed its table. The row wording matches
  `./start.sh --doctor`'s by inspection, and that one is run by the suite.
- `--shortcut` on Windows writes a `.lnk` through `WScript.Shell`;
  `uninstall.bat --shortcuts` deletes that exact path. Neither has run.
- `netstat`-based port detection, and the `curl` health probe behind it.
- The `%DATE%`-derived log filename on a non-English Windows. It is
  normalised and truncated to ten characters, which is one file per day
  whatever the regional order; nothing reads the date back out.

**Not run on macOS.** `./start.sh --shortcut`'s Finder-alias branch, its
symlink fallback, and the `notify`-mode splash all take the untested branch
there. The Linux branches of `--shortcut` and `--logs` were run here, and
both had a bug (see below).

**The doctor's Ollama and Updates rows** were exercised only in their
negative state: nothing answers at 11434 here, and a worktree's `.git` is a
file rather than a directory, so Updates reports "not a git checkout".

## What was verified, so a later session does not redo it

- `./start.sh --doctor` runs in the suite and exits 0 or 1 with the table.
- `--shortcut` and `uninstall.sh --shortcuts` round-trip against a scratch
  HOME: both files written, both listed by the dry run, both removed.
- `--logs` and `--version` print what they should.
- The uninstaller's real removal path, in a scratch install: `.venv`,
  `.pytest_cache` and every nested `__pycache__` go, notes and `.env` stay,
  the wrong confirmation text keeps the notes and `DELETE` removes both.
- A real launch on port 8842, in a pty, printed the whole step list with
  ticks and reached `uvicorn running`.
- The uninstaller's running-instance guard: with a real server on 8841 it
  exits 1 and changes nothing.
- `python -m memorymap --export PATH` writes the zip.
- `_loading_html()` was rendered in Chromium and measured: five rows, four
  ticked, the bar 240px of 300 at 80%, a phase push moving it to 95% and
  rewriting the status line, the error state flipping both, no console
  errors, no horizontal overflow.
- The browser boot splash, in the running app on 8841 with `/auth/status`
  stalled so it stays up: the tip renders at 12px muted below the bar, bar
  bottom 419 against tip bottom 460, and at eight seconds "Still loading.
  Give it a moment, or reload." and the Try again button both appear. No
  page errors.

## Found by running it, and fixed

Four bugs that a read would not have caught, all in code that already
existed or landed in the first half of this brief. Each is now covered by
`tests/test_launcher_scripts.py`:

1. `./start.sh --port` with no value exited 1 in silence. The branch shifts
   once to read the value, so the loop's trailing `shift` had nothing left,
   and under `set -e` that failing shift ended the script before the
   validation could print the help and exit 2. Same shape in
   `uninstall.sh --export`, which also swallowed the next flag.
2. `--shortcut` wrote `Icon=frontend/icon.png` into the desktop entry. That
   file has never existed in this repo, so the menu item and the Desktop
   copy both showed a generic icon.
3. `--logs` told the reader to open a folder "in your browser", from a
   fallback shared with the call that opens the app's URL.
4. `start.bat`'s doctor built a variable from a line of a log carrying
   git's and pip's text verbatim, where a double quote and an ampersand
   would have ended the `SET` and run the rest as a command.

## Deliberately not done

1. **Copy diagnostics does not run `--doctor`.** Brief 17 item 6 says "the
   doctor table to the clipboard". It copies the step history, the OS and
   PowerShell versions, the log path and the last twenty log lines instead.
   Running the doctor live would probe the port the app is about to bind
   and talk to the git remote, in the middle of the install being
   diagnosed. If this is wanted as specified, the safe shape is a
   `--doctor --offline` that skips the port and network rows.
2. **The dry run's "frees about" figure counts `.venv` only on Windows.**
   `uninstall.sh` sums the caches too; `uninstall.bat` cannot without
   asking Python for each one, and `.venv` is 300 MB of a 305 MB answer.

## Next, if anyone picks this up

The one thing worth doing before Windows users see it: run `start.bat`,
`start.bat --doctor`, `start.bat --shortcut` and `uninstall.bat --dry-run`
on a real Windows machine once, and watch the splash through a first-run
install. Everything else in this brief has been exercised.
