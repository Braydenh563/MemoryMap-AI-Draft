"""`memorymap.core.launch_status`: the launcher status protocol, parsed.

The file it reads is written by a shell script and a batch file, appended a
line at a time, and deleted underneath the reader the moment the loading
window is on screen. So the interesting half of this module is what it
does with input that is not a clean protocol line.
"""

from __future__ import annotations

import pytest

from memorymap.core import launch_status as ls


class TestParseLine:
    def test_a_good_line(self):
        step = ls.parse_line("2|5|Python|Building the environment|active")
        assert step is not None
        assert (step.step, step.total) == (2, 5)
        assert step.title == "Python"
        assert step.detail == "Building the environment"
        assert step.state == "active"
        assert not step.done and not step.failed

    def test_done_and_failed_are_flagged(self):
        assert ls.parse_line("1|4|Update|Up to date|done").done
        assert ls.parse_line("3|4|Dependencies|Could not install|failed").failed

    def test_a_bar_in_the_detail_survives(self):
        """Detail is free text, and the launcher does not escape it: a
        rejected line would blank a step for no good reason."""
        step = ls.parse_line("3|4|Dependencies|pip said a|b|c|active")
        assert step is not None
        assert step.detail == "pip said a|b|c"

    def test_an_empty_detail_is_allowed(self):
        step = ls.parse_line("1|4|Update||active")
        assert step is not None and step.detail == ""

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "not a protocol line at all",
            "Starting...",  # the plain text the old protocol wrote
            "1|4|Update|detail",  # too few fields
            "1|4|Update|detail|running",  # not a known state
            "x|4|Update|detail|active",  # step is not a number
            "1|y|Update|detail|active",  # total is not a number
            "0|4|Update|detail|active",  # steps are one-based
            "5|4|Update|detail|active",  # past the end
            "1|0|Update|detail|active",  # no steps at all
            "1|999|Update|detail|active",  # a nonsense total
            "1|4||detail|active",  # no title
            "1|4|   |detail|active",  # a whitespace title
        ],
    )
    def test_malformed_lines_are_rejected(self, line):
        assert ls.parse_line(line) is None

    def test_a_half_written_line_is_rejected_not_raised_on(self):
        """The launcher appends; a reader can catch a line mid-write."""
        assert ls.parse_line("2|5|Pyth") is None


class TestParseAndSummarise:
    HISTORY = "\n".join(
        [
            "1|5|Update|Checking for updates on GitHub|active",
            "1|5|Update|Up to date|done",
            "2|5|Python|Using the existing environment|done",
            "rubbish that should be skipped",
            "3|5|Dependencies|Installing, this can take a few minutes|active",
        ]
    )

    def test_unparseable_lines_are_skipped_not_fatal(self):
        assert len(ls.parse(self.HISTORY)) == 4

    def test_summarise_keeps_the_last_state_of_each_step(self):
        rows = ls.summarise(ls.parse(self.HISTORY))
        assert [r.step for r in rows] == [1, 2, 3]
        assert rows[0].detail == "Up to date"
        assert rows[0].done
        assert rows[2].state == "active"

    def test_latest_is_the_line_currently_current(self):
        assert ls.latest(ls.parse(self.HISTORY)).step == 3
        assert ls.latest([]) is None

    def test_percent_counts_finished_steps_not_the_active_one(self):
        """A bar that reaches 100% while the longest phase is still running
        is the lie the marquee existed to avoid."""
        assert ls.percent(ls.parse(self.HISTORY)) == 40  # 2 of 5 done
        assert ls.percent([]) == 0

    def test_a_failed_step_does_not_count_as_finished(self):
        steps = ls.parse("1|4|Update|Up to date|done\n2|4|Python|Too old|failed")
        assert ls.percent(steps) == 25


class TestReadFile:
    def test_it_reads_a_real_file(self, tmp_path):
        path = tmp_path / "splash.txt"
        path.write_text("1|4|Update|Up to date|done\n", encoding="utf-8")
        assert len(ls.read_file(str(path))) == 1

    def test_a_missing_path_is_not_an_error(self, tmp_path):
        """The launcher deletes this file the instant the window is up."""
        assert ls.read_file(str(tmp_path / "gone.txt")) == []
        assert ls.read_file(None) == []
        assert ls.read_file("") == []

    def test_a_directory_is_not_an_error(self, tmp_path):
        assert ls.read_file(str(tmp_path)) == []

    def test_undecodable_bytes_do_not_raise(self, tmp_path):
        path = tmp_path / "splash.txt"
        path.write_bytes(b"\xff\xfe|4|Update|x|done\n1|4|Update|Up to date|done\n")
        assert len(ls.read_file(str(path))) >= 1


class TestTheBarReachesTheEnd:
    """Reported: *"the splash ps1 graphic still only loads up to step 3/5 and
    then it loads, the bar doesnt actually reacy 5/5"*.

    `percent` counts steps that reached `done`, deliberately, so the bar
    cannot claim 100% while the last and longest phase is still running. That
    makes a step nobody writes indistinguishable from a step that never
    finished, and start.bat had two exits from the update step that wrote
    nothing at all: no git on PATH, and an install that is a downloaded copy
    rather than a checkout. Either one leaves steps 2, 3 and 4 done with 5
    active: three of five, for ever, on a launch where nothing went wrong.
    """

    def test_a_step_that_is_never_written_holds_the_bar_back(self):
        from memorymap.core import launch_status as ls

        without_update = ls.parse(
            "\n".join(
                [
                    "2|5|Python|Using the existing environment|done",
                    "3|5|Dependencies|Already up to date|done",
                    "4|5|Desktop window|Ready|done",
                    "5|5|Start|Starting the app|active",
                ]
            )
        )
        assert ls.percent(without_update) == 60, (
            "three of five, which is the reported symptom: the arithmetic is "
            "right and the history is missing a step"
        )

        with_update = ls.parse(
            "\n".join(
                [
                    "1|5|Update|Skipped, git is not installed|done",
                    "2|5|Python|Using the existing environment|done",
                    "3|5|Dependencies|Already up to date|done",
                    "4|5|Desktop window|Ready|done",
                    "5|5|Start|Starting the app|active",
                ]
            )
        )
        assert ls.percent(with_update) == 80
        finished = ls.parse(
            "\n".join(
                [
                    "1|5|Update|Skipped, git is not installed|done",
                    "2|5|Python|Using the existing environment|done",
                    "3|5|Dependencies|Already up to date|done",
                    "4|5|Desktop window|Ready|done",
                    "5|5|Start|Handed over to the app|done",
                ]
            )
        )
        assert ls.percent(finished) == 100

    def test_every_exit_from_the_update_step_ticks_it(self):
        """The launcher half, read from the script, because there is no
        Windows here to run it on. Every `goto :after_update` that leaves the
        update block must tick step 1 first; the one exception is the
        relaunched child, whose parent already wrote it into the same file."""
        import re
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "start.bat").read_text(encoding="utf-8")
        block = script[script.index("if defined MM_CHILD goto :after_update") : script.index(":after_update\n")]
        untick = []
        for match in re.finditer(r"^(.*goto :after_update.*)$", block, re.M):
            line = match.group(1)
            if "MM_CHILD" in line:
                continue  # the parent wrote step 1 before relaunching
            before = block[: match.start()]
            # The tick has to be the statement immediately before the jump.
            if "MM_STEP_UPDATE!" not in before[-400:]:
                untick.append(line.strip())
        assert not untick, (
            "these exits from the update step leave without marking it done, "
            "so the splash bar counts one step fewer than the total for the "
            "whole launch: " + "; ".join(untick)
        )


class TestEveryLaunchPathFinishesItsSteps:
    """The owner, after the first fix did not hold: *"the splash graphic still
    only goes to 3/5, make sure it works for ALL INSTANCES, if it is running
    normally, if there is no internet connection, if there are new dependancy
    updates, id the app is being updated, if there is an error for some reason
    etc"*, with a screenshot of Update sitting on "Getting ready" with a blue
    dot while Python, Dependencies and Desktop window were all ticked.

    That screenshot names the cause. `summarise` keeps the *last* state written
    for each step, and after the update succeeds start.bat re-invokes itself
    with `MM_CHILD` set so the new code runs. The child re-ran the seed line,
    overwriting the parent's "Update ... done" with "Getting ready ... active",
    then jumped past the update block without writing a done again.

    Each case below is the status history a launch produces, and the assertion
    is the same one every time: when the launcher hands over, every step before
    Start has finished.
    """

    CASES = {
        "normal, updated, then relaunched as the child": [
            "1|5|Update|Getting ready|active",
            "1|5|Update|Checking for updates on GitHub|active",
            "1|5|Update|Up to date|done",
            # the child re-runs: with the fix it writes no seed line at all
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ],
        "no internet": [
            "1|5|Update|Getting ready|active",
            "1|5|Update|Checking for updates on GitHub|active",
            "1|5|Update|Offline, skipped|done",
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Not available, using a browser tab|done",
            "5|5|Start|Starting the app|active",
        ],
        "dependencies actually installed": [
            "1|5|Update|Up to date|done",
            "2|5|Python|Environment ready|done",
            "3|5|Dependencies|Installing, this can take a few minutes|active",
            "3|5|Dependencies|Installed|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ],
        "no git on the machine": [
            "1|5|Update|Getting ready|active",
            "1|5|Update|Skipped, git is not installed|done",
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ],
        "not a git checkout": [
            "1|5|Update|Skipped, not a git checkout|done",
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ],
        "--no-update": [
            "1|5|Update|Skipped, --no-update|done",
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ],
        "browser mode, four steps": [
            "1|4|Update|Up to date|done",
            "2|4|Python|Using the existing environment|done",
            "3|4|Dependencies|Already up to date|done",
            "4|4|Start|Handed over to the app|done",
        ],
    }

    def test_every_step_before_start_is_finished_at_handover(self):
        from memorymap.core import launch_status as ls

        for name, lines in self.CASES.items():
            rows = ls.summarise(ls.parse("\n".join(lines)))
            unfinished = [r for r in rows if not r.done and r.title != "Start"]
            assert not unfinished, (
                f"{name}: these steps never finished, so the bar stops short "
                "for the whole launch: " + ", ".join(f"{r.title} ({r.detail})" for r in unfinished)
            )

    def test_a_failure_stops_the_bar_where_it_failed(self):
        """The one case that must *not* reach the end: a real error is the bar
        telling the truth, and `percent` counts a failed step as not done."""
        from memorymap.core import launch_status as ls

        failed = ls.parse(
            "\n".join(
                [
                    "1|5|Update|Up to date|done",
                    "2|5|Python|Too old|failed",
                ]
            )
        )
        assert ls.percent(failed) == 20
        assert any(row.failed for row in ls.summarise(failed))

    def test_the_child_does_not_reopen_a_step_its_parent_finished(self):
        """The regression itself, as arithmetic: the seed line in the child is
        what took a finished launch back to three of five."""
        from memorymap.core import launch_status as ls

        rest = [
            "2|5|Python|Using the existing environment|done",
            "3|5|Dependencies|Already up to date|done",
            "4|5|Desktop window|Ready|done",
            "5|5|Start|Starting the app|active",
        ]
        reopened = ls.parse("\n".join(["1|5|Update|Up to date|done", "1|5|Update|Getting ready|active", *rest]))
        assert ls.percent(reopened) == 60, "this is the reported symptom"
        left_alone = ls.parse("\n".join(["1|5|Update|Up to date|done", *rest]))
        assert ls.percent(left_alone) == 80

    def test_the_seed_line_is_skipped_in_the_child(self):
        """The script half, read from start.bat, because there is no Windows
        here to run it on."""
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "start.bat").read_text(encoding="utf-8")
        seed = [line for line in script.splitlines() if '"Update" "Getting ready" "active"' in line]
        assert len(seed) == 1, f"expected one seed line, found {len(seed)}"
        assert "if not defined MM_CHILD" in seed[0], (
            "the seed line runs in the relaunched child again, which overwrites "
            "the parent's finished Update step with an active one"
        )


class TestTheSplashEndsOnAFinishedList:
    """Reported three times, the last with a screenshot of the splash itself:
    Update, Python, Dependencies and Desktop window ticked, Start on a blue
    dot, "4 of 5 steps done", and then the app.

    The two rounds before were real bugs in start.bat. This is not one.
    start.bat leaves Start active in desktop mode on purpose, because the
    app's own loading window inherits the same list and owns that step until
    the server answers; ticking it in both would put two Starts in one list.
    Correct, and still a bar that gives up a step from the end.

    The launcher's own Start step is finished at the handover, which is what
    browser mode has always written. `_finish_splash_start_step` says the same
    thing in desktop mode, to the same file, *after* `_loading_html` has read
    it, so the window this process seeds still shows Start active and finishes
    it itself.
    """

    def _history(self, tmp_path, lines):
        path = tmp_path / "splash.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_the_last_step_is_ticked_before_the_file_goes(self, tmp_path, monkeypatch):
        from memorymap import __main__ as main
        from memorymap.core import launch_status as ls

        monkeypatch.setattr(main.time, "sleep", lambda _s: None)
        path = self._history(
            tmp_path,
            [
                "1|5|Update|Up to date|done",
                "2|5|Python|Using the existing environment|done",
                "3|5|Dependencies|Already up to date|done",
                "4|5|Desktop window|Ready|done",
                "5|5|Start|Starting the app|active",
            ],
        )
        assert ls.percent(ls.parse(path.read_text(encoding="utf-8"))) == 80

        main._finish_splash_start_step(str(path))

        after = ls.parse(path.read_text(encoding="utf-8"))
        assert ls.percent(after) == 100, "the splash still ends short of its own total"
        last = ls.summarise(after)[-1]
        assert last.title == "Start" and last.done
        assert last.detail == "Handed over to the app"

    def test_a_failed_launch_is_not_quietly_completed(self, tmp_path, monkeypatch):
        """The one thing this must never do: a launch that broke has to keep
        showing where it broke."""
        from memorymap import __main__ as main
        from memorymap.core import launch_status as ls

        monkeypatch.setattr(main.time, "sleep", lambda _s: None)
        path = self._history(
            tmp_path,
            [
                "1|5|Update|Up to date|done",
                "2|5|Python|Too old|failed",
            ],
        )
        main._finish_splash_start_step(str(path))
        rows = ls.summarise(ls.parse(path.read_text(encoding="utf-8")))
        assert rows[-1].failed
        assert ls.percent(ls.parse(path.read_text(encoding="utf-8"))) == 20

    def test_an_already_finished_list_is_left_alone(self, tmp_path, monkeypatch):
        """Browser mode already ticks its own last step. Appending a second
        done row for it would be harmless but dishonest about what happened."""
        from memorymap import __main__ as main

        monkeypatch.setattr(main.time, "sleep", lambda _s: None)
        lines = [
            "1|4|Update|Up to date|done",
            "2|4|Python|Using the existing environment|done",
            "3|4|Dependencies|Already up to date|done",
            "4|4|Start|Handed over to the app|done",
        ]
        path = self._history(tmp_path, lines)
        before = path.read_text(encoding="utf-8")
        main._finish_splash_start_step(str(path))
        assert path.read_text(encoding="utf-8") == before

    def test_a_missing_file_is_not_an_error(self, tmp_path, monkeypatch):
        """A launch that got this far must not fail on a splash that is
        already gone."""
        from memorymap import __main__ as main

        monkeypatch.setattr(main.time, "sleep", lambda _s: None)
        main._finish_splash_start_step(str(tmp_path / "never-existed.txt"))
