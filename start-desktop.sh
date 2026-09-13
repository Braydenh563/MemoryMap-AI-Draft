#!/usr/bin/env bash
# ===================================================================
#  MemoryMap AI - open in its own app window (macOS / Linux)
#
#  Run ./start-desktop.sh instead of ./start.sh to get a real
#  application window rather than a browser tab. Everything else is
#  identical: the same setup, the same app, the same data.
#
#  The window support (pywebview) installs itself the first time. If it
#  cannot, the app falls back to a browser tab rather than failing.
#
#  "$@" passes everything through, so every start.sh flag works here
#  too: ./start-desktop.sh --port 8010, --doctor, --reinstall and the
#  rest. start-desktop.bat is the same three lines on Windows.
#
#  `cd` first, because a .desktop entry or a Finder double-click runs
#  this from whatever directory it feels like, and start.sh resolves
#  .venv, .env and the data folder relative to itself.
#
#  `exec`, not a plain call: this process has nothing left to do
#  afterwards, and staying alive would leave an idle shell holding the
#  terminal for the whole life of the app.
# ===================================================================
cd "$(dirname "$0")"
exec ./start.sh --desktop "$@"
