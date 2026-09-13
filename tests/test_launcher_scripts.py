"""The launcher scripts, checked from Linux CI.

Brief 17's contract is that `./start.sh` and `start.bat` are one launcher
with two spellings: the same flags, in the same order, in the same help
text, writing the same status protocol. Nothing in the suite can run cmd or
PowerShell, so this file reads the two scripts as text and fails the build
when they drift, which is the only way that promise survives a session that
only edits one of them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# **The repo's own .venv is not a fixture.** The first version of the shortcut
# round-trip below ran `./uninstall.sh --shortcuts --yes` with cwd=ROOT, and
# `--shortcuts` is "also remove", so `--yes` took the sandbox's real .venv
# with it, mid-suite, and every later test that spawned sys.executable died
# with "No such file or directory". A test that runs a script capable of
# deleting things runs it in a scratch copy (see `_scratch_repo`), and this
# fixture fails loudly if anything here ever touches the real one again.
@pytest.fixture(autouse=True)
def _repo_venv_is_not_a_fixture():
    before = (ROOT / ".venv").exists()
    yield
    after = (ROOT / ".venv").exists()
    assert before == after, "a test in this module created or deleted the repo's .venv"


def _scratch_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the two scripts and the one asset `--shortcut`
    reads, with a fake .venv, so an uninstaller run has something of its
    own to remove and nothing of ours."""
    repo = tmp_path / "repo"
    (repo / "frontend").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    for name in ("start.sh", "uninstall.sh"):
        target = repo / name
        shutil.copy2(ROOT / name, target)
        target.chmod(0o755)
    shutil.copy2(ROOT / "frontend" / "icon-512.png", repo / "frontend" / "icon-512.png")
    return repo
START_SH = ROOT / "start.sh"
START_BAT = ROOT / "start.bat"
START_DESKTOP_SH = ROOT / "start-desktop.sh"
START_DESKTOP_BAT = ROOT / "start-desktop.bat"
UNINSTALL_SH = ROOT / "uninstall.sh"
UNINSTALL_BAT = ROOT / "uninstall.bat"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class TestPortFromEnv:
    """`--port N` reaches the server.

    The launcher exports MEMORYMAP_PORT; before this was read, the flag
    moved the launcher's port checks and the URL it opened but left the
    server itself on 8000, so `--port 8010` opened a browser at a port
    nothing was listening on.
    """

    def test_default_is_8000(self, monkeypatch):
        from memorymap.__main__ import _port_from_env

        monkeypatch.delenv("MEMORYMAP_PORT", raising=False)
        assert _port_from_env() == 8000

    def test_a_number_is_honoured(self):
        from memorymap.__main__ import _port_from_env

        assert _port_from_env("8010") == 8010
        assert _port_from_env(" 8781 ") == 8781

    @pytest.mark.parametrize("raw", ["", "abc", "80.5", "0", "-1", "65536", "99999999"])
    def test_junk_falls_back_rather_than_raising(self, raw):
        from memorymap.__main__ import _port_from_env

        assert _port_from_env(raw) == 8000

    def test_the_module_reads_the_environment(self, monkeypatch):
        """PORT is what the desktop paths and _run_server actually use."""
        import importlib

        monkeypatch.setenv("MEMORYMAP_PORT", "8123")
        launcher = importlib.reload(importlib.import_module("memorymap.__main__"))
        try:
            assert launcher.PORT == 8123
        finally:
            monkeypatch.delenv("MEMORYMAP_PORT", raising=False)
            importlib.reload(launcher)

    def test_start_sh_exports_the_variable_the_module_reads(self):
        assert re.search(r"export\s+MEMORYMAP_PORT=", _read(START_SH))

    def test_start_bat_sets_the_variable_the_module_reads(self):
        assert 'set "MEMORYMAP_PORT=!MM_PORT!"' in _read(START_BAT)


class TestTheShellScriptsParse:
    @pytest.mark.parametrize(
        "script", ["start.sh", "start-desktop.sh", "uninstall.sh"]
    )
    def test_bash_n(self, script):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_they_are_executable(self):
        for script in (START_SH, START_DESKTOP_SH, UNINSTALL_SH):
            assert os.access(script, os.X_OK), script


# --- the two launchers, read as one contract -------------------------------

FLAG_ORDER = [
    "desktop",
    "--port",
    "--no-browser",
    "--no-update",
    "--reinstall",
    "--doctor",
    "--logs",
    "--shortcut",
    "--version",
    "--help",
]


def _help_flags(text: str, start: str, end: str) -> list[str]:
    """The flags named in a help block, in the order they are printed."""
    at = text.index(start)
    body = text[at : text.index(end, at)]
    found = []
    for line in body.splitlines():
        # The flag, its optional single-letter argument placeholder, then
        # the column of description text.
        m = re.match(r"^\s*(?:echo\s+)?(--?[a-zA-Z-]+|desktop)(?:\s[A-Z])?\s{2,}\S", line)
        if m:
            found.append(m.group(1))
    return found


class TestOneLauncherTwoSpellings:
    """`start --doctor` has to be the same sentence on both platforms."""

    def test_the_help_texts_list_the_same_flags_in_the_same_order(self):
        sh = _help_flags(_read(START_SH), "MemoryMap AI launcher", "MM_HELP\n}")
        bat = _help_flags(_read(START_BAT), "echo MemoryMap AI launcher", "\n:log")
        assert sh == FLAG_ORDER, sh
        assert bat == FLAG_ORDER, bat

    def test_both_print_where_the_notes_are(self):
        assert "Your notes: $MM_DATA_DIR" in _read(START_SH)
        assert "Your notes: !MM_DATA_DIR!" in _read(START_BAT)

    def test_both_reject_an_unknown_flag_with_exit_2(self):
        assert "exit 2" in _read(START_SH)
        assert "exit /b 2" in _read(START_BAT)

    def test_both_point_at_their_own_uninstaller(self):
        assert "./uninstall.sh --help" in _read(START_SH)
        assert "uninstall.bat --help" in _read(START_BAT)


class TestStatusProtocol:
    """Every phase writes a `step|total|title|detail|state` line, or the
    splash renders a step list with a hole in it."""

    def test_the_two_scripts_use_the_same_phase_titles(self):
        sh = set(re.findall(r'mm_status "\$MM_STEP_\w+" "([^"]+)"', _read(START_SH)))
        bat = set(re.findall(r'call :status \S+ "([^"]+)"', _read(START_BAT)))
        assert sh, "start.sh writes no status lines at all"
        assert sh == bat, sh ^ bat

    def test_every_phase_is_covered(self):
        expected = {"Update", "Python", "Dependencies", "Desktop window", "Start"}
        sh = set(re.findall(r'mm_status "\$MM_STEP_\w+" "([^"]+)"', _read(START_SH)))
        assert expected <= sh, expected - sh

    def test_both_scripts_carry_the_same_step_totals(self):
        for text in (_read(START_SH), _read(START_BAT)):
            assert "MM_STEP_TOTAL=5" in text and "MM_STEP_TOTAL=4" in text

    def test_the_line_shape_is_the_one_the_parser_expects(self):
        from memorymap.core.launch_status import parse_line

        assert parse_line("2|5|Python|Building the environment|active") is not None

    def test_both_poll_the_same_cancel_file(self):
        assert "__cancel__" in _read(START_SH)
        assert "__cancel__" in _read(START_BAT)
        assert "${MM_SPLASH_FILE}.cancel" in _read(START_SH)
        assert "!MM_SPLASH_FILE!.cancel" in _read(START_BAT)


class TestBatchFileRules:
    """The cmd rules start.bat's own header records, checked rather than
    trusted: PowerShell and cmd cannot run in this suite, so a structural
    read is the only gate there is.
    """

    def _lines(self, path: Path = START_BAT):
        return _read(path).splitlines()

    @staticmethod
    def _unquoted(ln: str) -> str:
        out = re.sub(r'"[^"]*"', "", ln)
        # `echo(` is cmd's empty-safe echo, not an opening bracket, and `^(`
        # is an escaped literal.
        out = re.sub(r"(?i)\becho\(", "echo ", out)
        return out.replace("^(", "").replace("^)", "")

    @pytest.mark.parametrize("name", ["start.bat", "uninstall.bat", "start-desktop.bat"])
    def test_no_parenthesis_inside_an_echo_within_a_block(self, name):
        """cmd reads the ) as the end of the block and the script dies."""
        depth = 0
        offenders = []
        for i, ln in enumerate(self._lines(ROOT / name), 1):
            if re.match(r"(?i)^\s*(rem\b|::)", ln):
                continue
            unquoted = self._unquoted(ln)
            if depth > 0 and re.match(r"(?i)^\s*echo[ (.]", ln.strip()):
                body = re.sub(r"(?i)^\s*echo\(", "", unquoted)
                if "(" in body or ")" in body:
                    offenders.append((i, ln.strip()[:80]))
            depth += unquoted.count("(") - unquoted.count(")")
        assert not offenders, offenders

    @pytest.mark.parametrize("name", ["start.bat", "uninstall.bat", "start-desktop.bat"])
    def test_the_blocks_balance(self, name):
        depth = 0
        for ln in self._lines(ROOT / name):
            if re.match(r"(?i)^\s*(rem\b|::)", ln):
                continue
            depth += self._unquoted(ln).count("(") - self._unquoted(ln).count(")")
            assert depth >= 0, ln
        assert depth == 0

    @pytest.mark.parametrize("name", ["start.bat", "uninstall.bat"])
    def test_every_goto_and_call_target_exists(self, name):
        text = _read(ROOT / name)
        labels = {
            m.group(1).lower() for m in re.finditer(r"(?m)^\s*:([A-Za-z_0-9]+)", text)
        }
        targets = {
            m.group(1).lower()
            for m in re.finditer(r"(?:^|\s)(?:goto|call)\s+:([A-Za-z_0-9]+)", text, re.I)
        }
        assert targets - labels - {"eof"} == set()

    def test_the_relaunch_guard_survives_the_new_flags(self):
        """A running .bat is read by byte offset, so the self-update has to
        relaunch a fresh copy; MM_CHILD is what stops that looping. It must
        also pass the flags on, which SHIFT would otherwise have eaten."""
        text = _read(START_BAT)
        assert 'set "MM_ARGS=%*"' in text
        assert 'call "!MM_SELF!" !MM_ARGS!' in text
        relaunch = text.index('call "!MM_SELF!"')
        assert "if defined MM_CHILD goto :after_update" in text[:relaunch]
        assert 'set "MM_CHILD=1"' in text[:relaunch]

    def test_the_port_flag_reads_its_value_before_shifting(self):
        """%1 inside a block is expanded when the block is parsed, so a
        SHIFT earlier in the same block does not move it."""
        text = _read(START_BAT)
        block = text[text.index('if /i "%~1"=="--port" (') :]
        block = block[: block.index("\n)")]
        assert block.index('set "MM_PORT=%~2"') < block.index("shift")

    def test_nothing_after_the_parser_reads_its_own_path_from_percent_zero(self):
        """SHIFT moves %0 with the rest, so after start-desktop.bat had passed
        --desktop, "%~f0" in the self-update relaunch expanded to
        "...\\MemoryMap-AI\\--desktop" and cmd reported it "is not recognized as
        an internal or external command". The path is captured once, before
        :parse_args, and only the captured copy is used after it."""
        text = _read(START_BAT)
        before, after = text.split("\n:parse_args\n", 1)
        assert 'set "MM_HOME=%~dp0"' in before and 'set "MM_SELF=%~f0"' in before
        offenders = [
            line for line in after.splitlines()
            if ("%~f0" in line or "%~dp0" in line) and not line.strip().upper().startswith("REM")
        ]
        assert offenders == [], offenders
        assert 'call "!MM_SELF!" !MM_ARGS!' in after

    def test_the_status_write_puts_the_redirect_first(self):
        """A value ending in a digit turns `echo !VAR!>>file` into a
        numbered stream redirect."""
        text = _read(START_BAT)
        assert '>>"!MM_SPLASH_FILE!" echo(!MM_ST_LINE!' in text
        assert '>>"!MM_LOG!" echo(' in text

    def test_python_one_liners_with_apostrophes_use_backquotes(self):
        """FOR /F ends a single-quoted command at the next apostrophe, so a
        Python one-liner full of them needs `usebackq` and backticks."""
        for ln in self._lines():
            m = re.search(r"for /f [^(]*\('(.*)'\)", ln)
            if m and "'" in m.group(1):
                pytest.fail(f"apostrophe inside a single-quoted FOR /F: {ln.strip()}")


class TestDesktopWrappers:
    """Item 4: both wrappers exist and pass their arguments through, so
    `start-desktop --port 8010` is not silently a plain `desktop`."""

    def test_the_shell_wrapper_execs_the_launcher_with_its_arguments(self):
        text = _read(START_DESKTOP_SH)
        assert 'cd "$(dirname "$0")"' in text
        assert './start.sh --desktop "$@"' in text

    def test_the_batch_wrapper_passes_everything_through(self):
        assert 'start.bat" --desktop %*' in _read(START_DESKTOP_BAT)


class TestUninstallers:
    """Item 5: the same flag set, and the guards that stop an uninstall
    deleting under a running app."""

    UNINSTALL_FLAGS = [
        "--dry-run",
        "--export",
        "--delete-data",
        "--shortcuts",
        "--yes",
        "--help",
    ]

    def test_both_take_the_same_flags(self):
        sh, bat = _read(UNINSTALL_SH), _read(UNINSTALL_BAT)
        for flag in self.UNINSTALL_FLAGS:
            assert flag in sh, flag
            assert flag in bat, flag

    def test_both_check_the_port_before_deleting(self):
        assert "mm_port_open" in _read(UNINSTALL_SH)
        assert ":port_check" in _read(UNINSTALL_BAT)

    def test_env_is_only_removed_with_delete_data(self):
        """.env carries settings someone chose; a reinstall should find them
        again unless the notes are going too."""
        sh = _read(UNINSTALL_SH)
        # The only rm of .env sits inside the DELETE confirmation, after the
        # notes have gone: .env carries the path to the notebook, so
        # removing it while the notes survive loses them.
        removals = [
            ln for ln in sh.splitlines() if re.search(r'rm -f "\.env"', ln)
        ]
        assert len(removals) == 1, removals
        at = sh.index(removals[0])
        assert sh.index('if [ "$DELETE_DATA" = "1" ]; then', sh.index("--- 3.")) < at
        assert sh.index('reply" = "DELETE"') < at

        bat = _read(UNINSTALL_BAT)
        bat_removals = [ln for ln in bat.splitlines() if 'del /q ".env"' in ln]
        assert len(bat_removals) == 1, bat_removals
        assert bat.index('if not "!REPLY!"=="DELETE"') < bat.index(bat_removals[0])

    def test_the_export_entry_point_exists(self):
        text = (ROOT / "src" / "memorymap" / "__main__.py").read_text(encoding="utf-8")
        assert "--export" in text


class TestTheDoctorRunsHere:
    """`./start.sh --doctor` is run for real: it is the one part of this
    contract Linux CI can actually execute."""

    def test_it_exits_0_or_1_and_prints_the_table(self, tmp_path):
        env = dict(os.environ, MEMORYMAP_DATA_DIR=str(tmp_path / "data"))
        env.pop("MEMORYMAP_PORT", None)
        result = subprocess.run(
            ["./start.sh", "--doctor"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode in (0, 1), result.stdout + result.stderr
        out = result.stdout
        # Every assertion below carries the whole table: this failed once,
        # under a full suite running beside it, and did not reproduce in
        # forty runs afterwards, so the next occurrence needs to arrive
        # with its own evidence rather than a bare label name.
        assert "MemoryMap AI - checks" in out, out + result.stderr
        for label in ("Python", ".venv", "Disk", "Port", "Updates", "Notes", "Last run"):
            assert label in out, f"{label} missing from:\n{out}"
        assert "[ok]" in out or "[x]" in out, out

    def test_an_unknown_flag_exits_2_with_the_help(self, tmp_path):
        env = dict(os.environ, MEMORYMAP_DATA_DIR=str(tmp_path / "data"))
        result = subprocess.run(
            ["./start.sh", "--no-browsr"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 2
        assert "Unknown option: --no-browsr" in result.stdout
        assert "--no-browser" in result.stdout

    @pytest.mark.parametrize("bad", ["abc", "0", "70000"])
    def test_a_bad_port_exits_2(self, bad, tmp_path):
        env = dict(os.environ, MEMORYMAP_DATA_DIR=str(tmp_path / "data"))
        result = subprocess.run(
            ["./start.sh", "--port", bad],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 2, result.stdout

    def test_version_prints_the_version_and_the_paths(self, tmp_path):
        env = dict(os.environ, MEMORYMAP_DATA_DIR=str(tmp_path / "data"))
        result = subprocess.run(
            ["./start.sh", "--version"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "MemoryMap AI" in result.stdout
        assert "Your notes:" in result.stdout


class TestTheWindowsSplash:
    """scripts/splash.ps1 cannot be run here: no PowerShell, no WinForms, no
    display. So it is read instead, for the things Brief 17 asks it to draw
    and for the regressions its own comments record.
    """

    @property
    def text(self) -> str:
        return _read(ROOT / "scripts" / "splash.ps1")

    def test_the_braces_balance(self):
        """The one structural error a read can catch. Counted outside
        strings and comments, which is where every brace in this file that
        is not a block actually lives."""
        depth = 0
        for raw in self.text.splitlines():
            line = re.sub(r"'[^']*'", "", raw)
            line = re.sub(r'"[^"]*"', "", line)
            line = re.sub(r"#.*$", "", line)
            depth += line.count("{") - line.count("}")
            assert depth >= 0, raw
        assert depth == 0

    def test_it_parses_the_protocol_not_the_last_line_as_text(self):
        """Between the protocol landing and this, the window showed a raw
        `1|5|Update|...|active` line as its status text."""
        t = self.text
        assert "-split '\\|'" in t
        assert "$parts.Count -lt 5" in t
        assert '$state -ne "active"' in t

    def test_it_draws_a_step_list_with_marks(self):
        t = self.text
        assert "0x2713" in t  # tick, done
        assert "0x00D7" in t  # cross, failed
        assert "0x25CF" in t  # dot, active
        assert "$rowName" in t and "$rowDetail" in t

    def test_the_real_bar_counts_finished_steps_not_the_current_one(self):
        t = self.text
        assert '$progress.Style    = "Continuous"' in t
        assert '$_.State -eq "done"' in t
        assert "$pct = [int](($done * 100) / $total)" in t

    def test_the_marquee_is_only_inside_the_active_step(self):
        """Both bars exist for different reasons: see $bar and $progress."""
        t = self.text
        assert '$bar.Style    = "Marquee"' in t
        assert "$bar.Visible = $false" in t
        assert "$bar.Visible = $true" in t

    def test_the_active_step_shows_its_elapsed_seconds(self):
        assert "TotalSeconds" in self.text
        assert '$($secs)s' in self.text

    def test_there_are_five_tips_and_they_rotate_every_six_seconds(self):
        t = self.text
        block = t[t.index("$tips = @(") : t.index("$tip  ", t.index("$tips = @("))]
        quoted = re.findall(r'^\s*"[^"]+",?\s*$', block, re.M)
        assert len(quoted) == 4, quoted  # the fifth is the data folder, below
        assert "as plain files you can copy" in t
        assert "TotalSeconds -ge 6" in t

    def test_the_footer_has_all_three_buttons(self):
        t = self.text
        assert '"Details"' in t
        assert '"Copy diagnostics"' in t
        assert '"Cancel"' in t

    def test_cancel_writes_the_control_file_the_launcher_polls(self):
        t = self.text
        assert '$StatusFile + ".cancel"' in t
        assert '"__cancel__"' in t

    def test_the_slow_step_hints_name_both_steps_and_their_budgets(self):
        t = self.text
        assert '$s.Title -eq "Dependencies" -and $secs -gt 300' in t
        assert '$s.Title -eq "Update" -and $secs -gt 30' in t

    def test_the_error_card_offers_the_log_and_a_retry(self):
        t = self.text
        assert "function Show-ErrorCard" in t
        assert '$btnDetails.Text = "Open log"' in t
        assert '$btnRetry.Text         = "Try again"' in t
        assert "Start-Process -FilePath $LauncherPath" in t

    def test_the_three_ways_to_die_survive(self):
        t = self.text
        assert "MaxMinutes" in t
        assert "Test-Path -LiteralPath $StatusFile" in t
        assert "__done__" in t

    def test_one_click_handler_per_button(self):
        """WinForms runs every handler on a button: a second Add_Click added
        later fires alongside the first, so "Open log" would also toggle the
        details panel."""
        t = self.text
        for name in ("$btnDetails", "$btnCancel", "$btnCopy"):
            assert t.count(f"{name}.Add_Click(") == 1, name

    def test_the_launcher_passes_the_new_arguments(self):
        bat = _read(START_BAT)
        for flag in ("-StatusFile", "-IconPath", "-LogPath", "-LauncherPath", "-DataDir"):
            assert flag in bat, flag


class TestTheBrowserBootSplash:
    def test_it_carries_a_tip_line_in_the_markup(self):
        """In the markup, not built by boot-guard.js: it has to be there
        before first paint and survive a script that never runs, which is
        the case boot-guard.js itself exists for."""
        html = _read(ROOT / "frontend" / "index.html")
        assert 'class="boot-splash-tip"' in html
        assert "Your notes never leave this machine." in html

    def test_the_tip_line_is_styled_in_the_first_stylesheet(self):
        css = _read(ROOT / "frontend" / "css" / "00-tokens-shell.css")
        assert ".boot-splash-tip {" in css

    def test_still_loading_appears_at_eight_seconds_with_the_way_out(self):
        js = _read(ROOT / "frontend" / "boot-guard.js")
        at = js.index("}, 8000);")
        block = js[js.rindex("setTimeout(", 0, at) : at]
        assert "Still loading" in block
        assert "offerReload(splash)" in block
        # And the 12-second notice is still there, saying something else.
        assert "}, 12000);" in js
        assert "taking longer than it should" in js


class TestOneDesignThreeSurfaces:
    """The tips and the marks are the same on all three, or a first run
    reads as three different programs."""

    def test_the_same_tips_appear_on_every_surface(self):
        main = _read(ROOT / "src" / "memorymap" / "__main__.py")
        ps1 = _read(ROOT / "scripts" / "splash.ps1")
        html = _read(ROOT / "frontend" / "index.html")
        shared = "Your notes never leave this machine."
        assert shared in main and shared in ps1 and shared in html
        for tip in (
            "Ctrl+K opens the command palette.",
            "The first run installs about 300 MB once. Later starts take seconds.",
        ):
            assert tip in main, tip
            assert tip in ps1, tip

    def test_the_loading_window_seeds_itself_from_the_launcher(self):
        main = _read(ROOT / "src" / "memorymap" / "__main__.py")
        assert "def _loading_html" in main
        assert "launch_status.read_file" in main
        # Read before _close_launch_splash deletes the file: create_window's
        # own argument list is the only place that is guaranteed.
        assert main.index("html=_loading_html()") < main.index("_close_launch_splash()\n    #")

    def test_reduced_motion_is_respected_on_the_python_window(self):
        main = _read(ROOT / "src" / "memorymap" / "__main__.py")
        assert "prefers-reduced-motion: reduce" in main
        assert "animation: none" in main


class TestTheSplashLayoutDoesNotOverlap:
    """The one thing a read can check about a window nothing here can draw.

    Every control in splash.ps1 is absolutely positioned, so a band that
    starts before the one above it ends is a control drawn on top of
    another. It happened once already: the status label was 34px tall at
    y=306 and ran under the footer buttons at y=336.
    """

    HEIGHTS = {  # control -> its own height, from the Size line beside it
        "hint": 18,
        "tip": 18,
        "progress": 8,
        "status": 26,
    }

    def _ps1(self) -> str:
        return _read(ROOT / "scripts" / "splash.ps1")

    def _y(self, name: str) -> int:
        m = re.search(
            r"\$" + name + r"\.Location\s*=\s*New-Object System\.Drawing\.Point\(\d+, (\d+)\)",
            self._ps1(),
        )
        assert m, name
        return int(m.group(1))

    def _int(self, pattern: str) -> int:
        m = re.search(pattern, self._ps1())
        assert m, pattern
        return int(m.group(1))

    def test_the_bands_are_in_order_and_do_not_touch(self):
        rows = self._int(r"\$MAX_ROWS\s*=\s*(\d+)")
        top = self._int(r"\$ROW_TOP\s*=\s*(\d+)")
        step = self._int(r"\$ROW_STEP\s*=\s*(\d+)")
        buttons = self._int(
            r"\$b\.Location\s*=\s*New-Object System\.Drawing\.Point\(\$x, (\d+)\)"
        )
        collapsed = self._int(r"\$COLLAPSED_HEIGHT\s*=\s*(\d+)")
        expanded = self._int(r"\$EXPANDED_HEIGHT\s*=\s*(\d+)")

        bands = [("steps", top, top + rows * step)]
        for name in ("hint", "tip", "progress", "status"):
            y = self._y(name)
            bands.append((name, y, y + self.HEIGHTS[name]))
        bands.append(("buttons", buttons, buttons + 26))

        for (name_a, _, end_a), (name_b, start_b, _) in zip(bands, bands[1:]):
            assert end_a <= start_b, name_a + " runs into " + name_b

        # The footer has to fit inside the collapsed window, and the details
        # box inside the expanded one.
        assert bands[-1][2] <= collapsed
        details_y = self._y("details")
        details_h = self._int(
            r"\$details\.Size\s*=\s*New-Object System\.Drawing\.Size\(\d+, (\d+)\)"
        )
        assert details_y >= collapsed
        assert details_y + details_h <= expanded

    def test_the_retry_button_shares_the_footer_row(self):
        footer = self._int(
            r"\$b\.Location\s*=\s*New-Object System\.Drawing\.Point\(\$x, (\d+)\)"
        )
        assert self._y("btnRetry") == footer

    def test_rows_past_the_end_are_blanked_not_left_stale(self):
        """The marquee is moved to the active row, and a list longer than
        MAX_ROWS would otherwise park it beyond the last row that exists."""
        ps1 = self._ps1()
        assert "$ROW_TOP + $BAR_DROP + $i * $ROW_STEP" in ps1
        assert "$i -ge $count" in ps1


class TestAFlagMissingItsValue:
    """A flag that takes a value shifts once inside its own branch, so
    `--port` or `--export` typed as the last argument leaves nothing for the
    loop's own shift to consume. Under `set -e` that failing shift killed
    the script with exit 1 and no message at all, instead of reaching the
    validation that prints the help and exits 2. Found by running it.
    """

    def _run(self, script: str, args: list[str], tmp_path):
        env = dict(os.environ, MEMORYMAP_DATA_DIR=str(tmp_path / "data"))
        env.pop("MEMORYMAP_PORT", None)
        # The uninstaller runs in a scratch copy even for a flag that should
        # fail before it removes anything: "should" is the word this module
        # once got wrong (see `_repo_venv_is_not_a_fixture`).
        cwd = _scratch_repo(tmp_path) if script == "uninstall.sh" else ROOT
        return subprocess.run(
            ["./" + script, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_start_sh_port_with_no_value(self, tmp_path):
        result = self._run("start.sh", ["--port"], tmp_path)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--port needs a number" in result.stdout
        assert "MemoryMap AI launcher" in result.stdout

    def test_uninstall_sh_export_with_no_value(self, tmp_path):
        result = self._run("uninstall.sh", ["--export"], tmp_path)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--export needs a path" in result.stdout

    def test_uninstall_sh_export_swallowing_the_next_flag(self, tmp_path):
        """`--export --yes` used to export to a file called "--yes"."""
        result = self._run("uninstall.sh", ["--export", "--yes"], tmp_path)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--export needs a path" in result.stdout

    def test_both_loops_tolerate_the_empty_shift(self):
        for script in (START_SH, UNINSTALL_SH):
            assert "shift || break" in _read(script), script


class TestTheDesktopShortcut:
    """`./start.sh --shortcut` is run for real against a scratch HOME, and
    `./uninstall.sh --shortcuts` has to remove exactly what it wrote.
    """

    def _env(self, home, tmp_path):
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["MEMORYMAP_DATA_DIR"] = str(tmp_path / "data")
        # Nothing must be able to look like a running MemoryMap and stop the
        # uninstaller half way through this test.
        env["MEMORYMAP_PORT"] = "9"
        return env

    def test_it_writes_an_entry_and_the_uninstaller_removes_it(self, tmp_path):
        home = tmp_path / "home"
        (home / "Desktop").mkdir(parents=True)
        env = self._env(home, tmp_path)
        repo = _scratch_repo(tmp_path)

        made = subprocess.run(
            ["./start.sh", "--shortcut"], cwd=repo, env=env,
            capture_output=True, text=True, timeout=60,
        )
        assert made.returncode == 0, made.stdout + made.stderr
        entry = home / ".local" / "share" / "applications" / "memorymap-ai.desktop"
        copy = home / "Desktop" / "memorymap-ai.desktop"
        assert entry.exists() and copy.exists()

        body = entry.read_text(encoding="utf-8")
        assert "Exec=" in body and "--desktop" in body
        assert "Terminal=false" in body  # the case the splash exists for
        icon = re.search(r"^Icon=(.+)$", body, re.M).group(1)
        # Icon=frontend/icon.png was written for a file that has never
        # existed in this repo, so both entries fell back to a generic icon.
        assert Path(icon).exists(), icon

        removed = subprocess.run(
            ["./uninstall.sh", "--shortcuts", "--yes"], cwd=repo, env=env,
            capture_output=True, text=True, timeout=60,
        )
        assert removed.returncode == 0, removed.stdout + removed.stderr
        assert not entry.exists() and not copy.exists()

    def test_the_dry_run_lists_the_shortcut_and_removes_nothing(self, tmp_path):
        home = tmp_path / "home"
        (home / "Desktop").mkdir(parents=True)
        env = self._env(home, tmp_path)
        repo = _scratch_repo(tmp_path)
        subprocess.run(
            ["./start.sh", "--shortcut"], cwd=repo, env=env,
            capture_output=True, text=True, timeout=60,
        )
        entry = home / ".local" / "share" / "applications" / "memorymap-ai.desktop"
        dry = subprocess.run(
            ["./uninstall.sh", "--shortcuts", "--dry-run"], cwd=repo, env=env,
            capture_output=True, text=True, timeout=60,
        )
        assert dry.returncode == 0, dry.stdout + dry.stderr
        assert str(entry) in dry.stdout
        assert "dry run" in dry.stdout
        assert entry.exists()


class TestBothUninstallersRejectAnExportWithNoPath:
    """`--export` with nothing after it used to fall through as "no export
    asked for": the uninstall then carried on and removed .venv while the
    export nobody noticed was skipped. The shell one is run for this in
    TestAFlagMissingItsValue; cmd cannot be run here, so the batch one is
    read for the same three decisions.
    """

    def test_the_batch_file_separates_absent_from_empty(self):
        bat = _read(UNINSTALL_BAT)
        assert 'set "EXPORT_GIVEN=1"' in bat
        assert "if not defined EXPORT_GIVEN goto :export_ok" in bat
        assert "if not defined EXPORT_TO goto :export_missing" in bat

    def test_the_batch_file_rejects_the_next_flag_as_a_path(self):
        assert 'if "!EXPORT_TO:~0,1!"=="-" goto :export_missing' in _read(UNINSTALL_BAT)

    def test_it_exits_2_before_removing_anything(self):
        bat = _read(UNINSTALL_BAT)
        # The label definitions, not the gotos that jump to them.
        missing = re.search(r"(?m)^:export_missing$", bat).start()
        ok = re.search(r"(?m)^:export_ok$", bat).start()
        # The guard sits above every removal in the file.
        for removal in ('rmdir /s /q ".venv"', 'rmdir /s /q ".pytest_cache"'):
            assert missing < bat.index(removal), removal
        assert "exit /b 2" in bat[missing:ok]

    def test_both_say_the_same_thing(self):
        assert "--export needs a path" in _read(UNINSTALL_SH)
        assert "--export needs a path" in _read(UNINSTALL_BAT)
