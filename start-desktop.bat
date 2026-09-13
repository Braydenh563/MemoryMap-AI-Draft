@echo off
REM ===================================================================
REM  MemoryMap AI - open in its own app window (Windows)
REM
REM  Double-click this instead of start.bat to get a real application
REM  window rather than a browser tab. Everything else is identical:
REM  the same setup, the same app, the same data.
REM
REM  The window support (pywebview) installs itself the first time. If
REM  it cannot, the app falls back to a browser tab rather than failing.
REM
REM  %* passes everything through, so every start.bat flag works here
REM  too: start-desktop.bat --port 8010, --doctor, --reinstall and the
REM  rest. Before that it passed a bare "desktop" and silently dropped
REM  whatever else was typed. --desktop rather than the bare word so the
REM  flag survives being read in a help text.
REM ===================================================================
call "%~dp0start.bat" --desktop %*
