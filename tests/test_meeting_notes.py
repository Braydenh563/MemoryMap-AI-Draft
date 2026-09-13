"""The meeting recorder (§ voice).

Two reports, one session apart:

    "there is still no line animation that visually picks up the user's voice
     when recording in the meeting notes section."
    "I would also like the meeting notes popup to be expanded as a proper
     feature with more capabilities and expansion which is also accessible
     throughout the app, not just from the dashboard."

The first one is the interesting one. There *was* a meter, `startMicLevelMeter`
appends six small bars to the Record button, so "already exists" was true and
beside the point: at that size, on a button, next to a word, it does not read
as a response to your voice, and a recording with no visible response is
indistinguishable from a broken microphone. That is what was being reported,
and it is why the answer is a second, prominent meter rather than a tweak to
the first.

Lints, plus what a browser confirmed: with a fake capture device the canvas
un-hides, sizes to its box and paints (measured 1,920 non-transparent pixels),
the timer runs, and Pause flips to Resume.
"""

from __future__ import annotations

from pathlib import Path

JS = Path("frontend/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")
WAVE = JS.split("function startMeetingWave(")[1].split("\nfunction stopMeetingTimer")[0]


def test_the_waveform_is_a_canvas_not_a_row_of_elements():
    """~120 points at 60fps. That many DOM nodes each taking a style write per
    frame is a layout cost for no benefit."""
    assert '<canvas id="meeting-wave"' in HTML


def test_it_reads_loudness_not_frequency():
    """The button meter uses a 256-bin frequency analyser; a level *line* wants
    the time domain and an RMS, which is steadier than a peak, a peak flickers
    on consonants."""
    assert "fftSize = 2048" in WAVE
    assert "getByteTimeDomainData" in WAVE
    assert "Math.sqrt(sum / samples.length)" in WAVE


def test_quiet_speech_still_moves_the_line():
    """Ordinary speaking volume sits low in the range; a linear map leaves it
    near the floor. Same curve the bar meter documents."""
    assert "Math.sqrt(rms)" in WAVE


def test_it_survives_a_suspended_audio_context():
    """Chrome creates one suspended even inside a click handler, and the
    analyser reads all-zero until it is running, the trap the bar meter
    already documents."""
    assert "ctx.resume().then(tick, tick)" in WAVE


def test_it_follows_the_theme():
    """Read from the live stylesheet, so a custom accent works too."""
    assert 'getPropertyValue("--accent")' in WAVE


def test_the_canvas_is_sized_to_its_box_after_it_is_shown():
    """A hidden element has no width to read, and the markup's fallback size
    stretches the line and softens it on any HiDPI screen."""
    assert WAVE.index('classList.remove("hidden")') < WAVE.index("getBoundingClientRect()")
    assert "devicePixelRatio" in WAVE


def test_stopping_and_closing_both_tear_it_down():
    """A live AudioContext with nothing drawing it is a microphone nobody is
    looking at: the same reasoning `closeMeetingRecorder` already applies to
    the MediaRecorder."""
    for fn in ("function closeMeetingRecorder()",):
        block = JS.split(fn)[1].split("\n}")[0]
        assert "stopMeetingWave()" in block
    stop_handler = JS.split('meetingRecorder.addEventListener("stop"')[1].split("});")[0]
    assert "stopMeetingWave()" in stop_handler


# --- a proper feature ------------------------------------------------------------


def test_it_is_reachable_without_going_to_the_dashboard():
    """"accessible throughout the app, not just from the dashboard", a
    recording is started the moment a meeting starts, and navigating first is
    what makes it not get started at all."""
    assert '"ph:microphone Record a meeting or lecture"' in JS
    assert "recordMeeting: { keys:" in JS
    assert "recordMeeting: openMeetingRecorder," in JS
    launcher = Path("src/memorymap/__main__.py").read_text(encoding="utf-8")
    assert '"Record a meeting"' in launcher


def test_pause_keeps_one_recording_instead_of_two():
    """Someone leaves the room. Without pause the alternative is stopping and
    starting again, which transcribes as a separate transcript."""
    block = JS.split("function toggleMeetingPause()")[1].split("\n}\n")[0]
    assert "meetingRecorder.pause()" in block
    assert "meetingRecorder.resume()" in block


def test_the_timer_measures_the_audio_not_the_sitting():
    block = JS.split("function toggleMeetingPause()")[1].split("\n}\n")[0]
    assert "meetingStartedAt += Date.now() - meetingPausedAt" in block


def test_a_long_recording_can_be_a_document():
    """An hour of transcript in the Notes list is one enormous card nobody can
    scroll past."""
    assert 'id="meeting-save-doc"' in HTML
    block = JS.split("async function saveMeetingDocument()")[1].split("\n}\n")[0]
    assert '"/documents"' in block
    assert "openDocument(" in block


def test_the_title_names_the_note_it_saves():
    """Every list in this app shows a note's first line as its name; without a
    title a saved recording is named by whatever word the transcript opens
    on."""
    assert 'id="meeting-title"' in HTML
    block = JS.split("async function saveMeetingNote()")[1].split("\n}\n")[0]
    assert 'meeting-title' in block
