@echo off
title MemoryMap AI
REM ===================================================================
REM  MemoryMap AI - one-click launcher for Windows
REM
REM  Double-click this file, or run "start.bat" in a terminal. It sets
REM  everything up the first time, then just runs the app after that:
REM
REM    1. use the app's own .venv Python (only needs a system Python the
REM       very first time, to build that .venv)
REM    2. install / update dependencies + the app itself
REM    3. copy .env.example to .env the first time
REM    4. start the server and open your browser at localhost:8000
REM
REM  Flags: see "start.bat --help". start.sh takes the same set in the
REM  same order, on purpose - one launcher contract on both platforms, so
REM  a support answer "run start --doctor" is the same sentence whoever is
REM  asking. tests\test_launcher_scripts.py fails the build if the two
REM  help texts ever drift apart.
REM
REM  Editors beware. Each of these is a failure this file has already had:
REM
REM    * never put ( or ) inside an ECHO that sits within an IF ( ... )
REM      block - cmd reads the ) as the end of the block and the script
REM      dies. Keep echoed text paren-free. The doctor rows and the help
REM      text below are written paren-free for this reason alone. Parens
REM      inside a DOUBLE-QUOTED argument are counted correctly and are
REM      safe, which is why the Python one-liners below can have them.
REM    * %1 inside a parenthesized block is expanded when the block is
REM      PARSED, so a SHIFT earlier in the same block does not move it.
REM      The flag parser below reads %~2 before it shifts, never after.
REM    * every SET in cmd.exe makes a real environment variable that the
REM      child processes inherit, so a name that collides with something
REM      pip or git reads is a live hazard - see the long MM_PIP_LOG note
REM      in step 2.
REM    * ECHO of a delayed-expansion variable puts the redirect FIRST,
REM      >>"file" echo !VAR!, because a value ending in a digit turns
REM      "echo !VAR!>>file" into a numbered stream redirect instead.
REM ===================================================================

setlocal enabledelayedexpansion

REM Generate the ESC character to allow ANSI color codes in Windows CMD
for /F %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

cd /d "%~dp0"

REM  This script's own path, captured before the argument parser below runs.
REM  SHIFT moves %0 along with the rest, so after `start-desktop.bat` had
REM  passed --desktop, "%~f0" further down expanded to
REM  "C:\...\MemoryMap-AI\--desktop" and the self-update relaunch failed with
REM  "is not recognized as an internal or external command". Reported
REM  exactly that way. Nothing after :parse_args may use %~f0 or %~dp0
REM  (tests\test_launcher_scripts.py holds that line).
set "MM_HOME=%~dp0"
set "MM_SELF=%~f0"

REM  The arguments this run was given, captured before the parser below
REM  starts shifting them away: SHIFT does not rewrite %*, so this is the
REM  one chance to keep them for the self-update relaunch further down.
REM  Without it every flag was silently dropped by that relaunch, a bug
REM  that only ever showed on a machine with an update waiting.
set "MM_ARGS=%*"

REM --- Where the data actually is --------------------------------------
REM  The same precedence the app itself uses, see core\config.py: an
REM  explicit MEMORYMAP_DATA_DIR in the environment, else one set in .env,
REM  else the "data" folder beside this script. Resolved this early because
REM  three separate things below need it before any Python exists to be
REM  asked: the launcher log, the doctor's disk and size rows, and the line
REM  that tells someone where their notes actually are.
set "MM_DATA_DIR=%MEMORYMAP_DATA_DIR%"
if not defined MM_DATA_DIR if exist ".env" (
  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"MEMORYMAP_DATA_DIR=" ".env" 2^>nul') do set "MM_DATA_DIR=%%B"
)
if not defined MM_DATA_DIR set "MM_DATA_DIR=data"
REM  Unquoted SET on purpose: the replacement removes double quotes, and a
REM  bare " inside set "VAR=..." ends the quoting early and takes the rest
REM  of the line with it.
set MM_DATA_DIR=!MM_DATA_DIR:"=!

REM --- Flags -----------------------------------------------------------
REM  Parsed before anything touches the network, the venv or the screen, so
REM  --help, --version and --doctor are always instant and always work,
REM  including on a machine where the install is broken - which is exactly
REM  the machine someone runs --doctor on.
REM
REM  Both forms of the desktop flag are accepted: the bare word "desktop"
REM  is what start-desktop.bat has always passed, and --desktop is what
REM  anyone who has read --help will type.
set "MM_PORT=%MEMORYMAP_PORT%"
if not defined MM_PORT set "MM_PORT=8000"
set "MM_NO_BROWSER=0"
set "MM_NO_UPDATE=0"
set "MM_REINSTALL=0"
set "MM_ACTION="
set "MM_BAD_FLAG="

:parse_args
if "%~1"=="" goto :parse_done
set "MM_ARG=%~1"
if /i "%~1"=="desktop" (
  set "MM_DESKTOP=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--desktop" (
  set "MM_DESKTOP=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--port" (
  REM  %~2 is read here, before either SHIFT runs: see the header note.
  set "MM_PORT=%~2"
  shift
  shift
  goto :parse_args
)
if /i "!MM_ARG:~0,7!"=="--port=" (
  set "MM_PORT=!MM_ARG:~7!"
  shift
  goto :parse_args
)
if /i "%~1"=="--no-browser" (
  set "MM_NO_BROWSER=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--no-update" (
  set "MM_NO_UPDATE=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--reinstall" (
  set "MM_REINSTALL=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--doctor" (
  set "MM_ACTION=doctor"
  shift
  goto :parse_args
)
if /i "%~1"=="--logs" (
  set "MM_ACTION=logs"
  shift
  goto :parse_args
)
if /i "%~1"=="--shortcut" (
  set "MM_ACTION=shortcut"
  shift
  goto :parse_args
)
if /i "%~1"=="--version" (
  set "MM_ACTION=version"
  shift
  goto :parse_args
)
if /i "%~1"=="-V" (
  set "MM_ACTION=version"
  shift
  goto :parse_args
)
if /i "%~1"=="--help" (
  set "MM_ACTION=help"
  shift
  goto :parse_args
)
if /i "%~1"=="-h" (
  set "MM_ACTION=help"
  shift
  goto :parse_args
)
set "MM_BAD_FLAG=%~1"
shift
goto :parse_args
:parse_done

REM  An unknown flag is a typo, and a typo that silently starts the app
REM  anyway is how someone spends ten minutes wondering why --no-browsr
REM  still opened a browser. Exit 2, not 1: 1 already means "the app tried
REM  and failed", and a script wrapping this one needs to tell those apart.
if defined MM_BAD_FLAG (
  echo Unknown option: !MM_BAD_FLAG!
  echo.
  call :help
  endlocal
  exit /b 2
)

REM  Validated with cmd's own tools, because this runs before any Python is
REM  guaranteed to exist. A FOR /F whose delims are the ten digits yields no
REM  token at all for an all-digit string and one token for anything else,
REM  which is the whole numeric test in one line. The length check comes
REM  first because a twelve-digit "port" would overflow the 32-bit
REM  arithmetic IF uses for LSS and GTR.
set "MM_PORT_BAD="
if not defined MM_PORT set "MM_PORT_BAD=1"
if not defined MM_PORT_BAD if not "!MM_PORT:~5!"=="" set "MM_PORT_BAD=1"
if not defined MM_PORT_BAD for /f "delims=0123456789" %%C in ("!MM_PORT!") do set "MM_PORT_BAD=1"
if not defined MM_PORT_BAD if !MM_PORT! LSS 1 set "MM_PORT_BAD=1"
if not defined MM_PORT_BAD if !MM_PORT! GTR 65535 set "MM_PORT_BAD=1"
if defined MM_PORT_BAD (
  echo --port needs a number between 1 and 65535, not !MM_PORT!
  echo.
  call :help
  endlocal
  exit /b 2
)

REM  Set rather than passed on the command line: it has to survive the
REM  relaunch below AND reach "python -m memorymap", which reads it in
REM  __main__.py. One variable, two readers, no argument plumbing.
set "MEMORYMAP_PORT=!MM_PORT!"
set "MM_URL=http://localhost:!MM_PORT!"

if /i "!MM_ACTION!"=="help" (
  call :help
  endlocal
  exit /b 0
)
if /i "!MM_ACTION!"=="version" goto :do_version
goto :after_version
:do_version
call :read_version MM_VERSION
set MM_VERSION=!MM_VERSION:"=!
if not defined MM_VERSION set "MM_VERSION=unknown"
echo MemoryMap AI !MM_VERSION!
echo Installed at: !CD!
echo Your notes:   !MM_DATA_DIR!
endlocal
exit /b 0
:after_version

REM --- The launcher log ------------------------------------------------
REM  Asked for as part of one launcher contract: every run leaves a file, so
REM  "it did not start" can be answered by reading something rather than by
REM  asking someone to reproduce it with a terminal open. Same path on both
REM  platforms, <data>\logs\launcher-<date>.log, so the doctor row and the
REM  --logs flag below can both find it without being told.
REM
REM  cmd has no tee, so this is not a copy of the console: the phase
REM  headlines, the failures, and git's and pip's own output are appended
REM  here as they happen, which is the part that answers "what stopped".
REM
REM  %DATE% is locale-formatted and can carry a weekday prefix, so the
REM  separators are normalised and the last ten characters taken: that is
REM  one file per day whatever the regional order turns out to be. Nothing
REM  reads the date back out of the name - the doctor picks the newest log
REM  by modification time - so the order of the fields does not matter.
set "MM_LOG_DIR=!MM_DATA_DIR!\logs"
set "MM_LOG="
if not exist "!MM_LOG_DIR!" mkdir "!MM_LOG_DIR!" >nul 2>nul
if exist "!MM_LOG_DIR!" (
  set "MM_LOG_DATE=%DATE%"
  set "MM_LOG_DATE=!MM_LOG_DATE:/=-!"
  set "MM_LOG_DATE=!MM_LOG_DATE:.=-!"
  set "MM_LOG_DATE=!MM_LOG_DATE: =-!"
  set "MM_LOG_DATE=!MM_LOG_DATE:~-10!"
  set "MM_LOG=!MM_LOG_DIR!\launcher-!MM_LOG_DATE!.log"
)
REM  Written straight rather than through :log because MM_ARGS is whatever
REM  the user typed: delayed expansion is not re-parsed, so an ampersand in
REM  it lands in the file instead of splitting this line into two commands.
if defined MM_LOG >>"!MM_LOG!" echo(--- %DATE% %TIME% start.bat !MM_ARGS! ---
REM  Ten days of launches is plenty to answer "what changed since it last
REM  worked", and this folder is inside the user's notebook - it must never
REM  be the thing that fills a disk.
if defined MM_LOG (
  for /f "skip=10 delims=" %%F in ('dir /b /o-d "!MM_LOG_DIR!\launcher-*.log" 2^>nul') do del /q "!MM_LOG_DIR!\%%F" >nul 2>nul
)

REM --- The status protocol ---------------------------------------------
REM  step, total, title, detail and state separated by vertical bars, one
REM  line per transition, appended so the file is a history rather than a
REM  single current value: a window that opens late - the Python loading
REM  window, handed the same file - can then render every step that already
REM  happened with a tick beside it, instead of showing an empty list and
REM  only learning about the steps still to come. See scripts\splash.ps1
REM  for the Windows renderer and src\memorymap\core\launch_status.py for
REM  the parser both Python surfaces share. state is active, done or failed.
set "MM_STEP_UPDATE=1"
set "MM_STEP_PYTHON=2"
set "MM_STEP_DEPS=3"
if defined MM_DESKTOP (
  set "MM_STEP_WINDOW=4"
  set "MM_STEP_START=5"
  set "MM_STEP_TOTAL=5"
) else (
  set "MM_STEP_WINDOW=0"
  set "MM_STEP_START=4"
  set "MM_STEP_TOTAL=4"
)

REM --- Launch splash ---------------------------------------------------
REM  Everything below this line - the git pull, building .venv, and a pip
REM  install that can run to several hundred megabytes - happens before
REM  Python exists, so before __main__.py can show its own loading window.
REM  Reported directly: those pre-processes "take a while to actually open
REM  the window so the user doesn't think the application didn't start
REM  properly because they didn't have access to the terminal logs".
REM
REM  So a splash goes up first, within a second of the double-click, and
REM  the phases below write the protocol above into MM_SPLASH_FILE for it
REM  to display. Deleting the file closes the window.
REM
REM  Entirely best-effort: launched detached, errorlevel never checked, and
REM  every path out of this script deletes the file. A machine with no
REM  PowerShell, a locked-down execution policy or no desktop session just
REM  does not get a splash, exactly as before.
REM
REM  Not shown for --doctor, --logs, --shortcut or --version: those print a
REM  table or a path and exit, and a borderless window over the top of a
REM  console someone is deliberately reading is noise.
REM
REM  MM_CHILD guards it the same way it guards the self-update: the child
REM  process inherits MM_SPLASH_FILE and keeps writing to the splash the
REM  parent already opened, instead of opening a second one on top of it.
if not defined MM_CHILD if "!MM_ACTION!"=="" (
  set "MM_SPLASH_FILE=%TEMP%\mm_splash_%RANDOM%.txt"
  REM  -IconPath so the splash window and its taskbar button carry the app's
  REM  icon rather than PowerShell's. splash.ps1 works this out for itself
  REM  from its own location too; passing it explicitly means the packaged
  REM  layout, where scripts\ and frontend\ may not be siblings, does not
  REM  have to match the checkout's.
  REM  -LogPath so Details can show the tail of this run's log and the error
  REM  card can offer to open it; -LauncherPath so Try again re-runs this
  REM  exact script; -DataDir for the tip that answers "where are my notes".
  REM  All three are optional on the splash's side: it degrades to saying so.
  if exist "scripts\splash.ps1" start "" /b powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "scripts\splash.ps1" -StatusFile "!MM_SPLASH_FILE!" -IconPath "!MM_HOME!frontend\icon.ico" -LogPath "!MM_LOG!" -LauncherPath "!MM_SELF!" -DataDir "!MM_DATA_DIR!" >nul 2>nul
)
REM  The seed line, so the splash has a step list to draw the moment it
REM  opens rather than an empty panel for the first second.
REM
REM  **Not in the relaunched child, and that is the "3 of 5" report.** After
REM  the update step finishes, this script re-invokes itself with MM_CHILD set
REM  (see the update block below) so the new code runs rather than the code
REM  that was on disk when the launch started. The child re-runs this line,
REM  and `launch_status.summarise` keeps the *last* state written for each
REM  step: so the parent's "Update ... done" was overwritten with "Getting
REM  ready ... active", and the child then jumps straight past the update
REM  block without ever writing a done for it again. The screenshot in the
REM  report shows exactly that, Update sitting on "Getting ready" with a blue
REM  dot while Python, Dependencies and Desktop window are all ticked: three
REM  of five, on a launch where the update had already succeeded.
REM
REM  The child inherits the parent's status file and the parent already put a
REM  real answer in it, so there is nothing to seed.
if not defined MM_CHILD if "!MM_ACTION!"=="" call :status !MM_STEP_UPDATE! "Update" "Getting ready" "active"

if /i "!MM_ACTION!"=="doctor" goto :do_doctor
if /i "!MM_ACTION!"=="logs" goto :do_logs
if /i "!MM_ACTION!"=="shortcut" goto :do_shortcut

REM --- Preflight --------------------------------------------------------
REM  The three commonest ways a launch dies, checked in the second before it
REM  starts rather than left to surface as a traceback four minutes in. A
REM  subset of --doctor on purpose: the rest of that table costs network
REM  round trips, and nobody wants to wait for an Ollama probe to open their
REM  notebook.
call :port_check
if defined MM_PORT_MINE goto :already_running
if defined MM_PORT_BUSY (
  set "MM_FAIL_MSG=Port !MM_PORT! is already in use by another program."
  set "MM_FAIL_FIX=Close it, or start on another port: start.bat --port 8010"
  goto :fail
)

REM  Disk is only checked once there is a Python to ask. cmd's own way of
REM  reading free space is DIR's English "bytes free" footer, which is the
REM  wrong thing to fail a launch on: on a localised Windows it would read
REM  as "no space" and stop a launch that was fine.
if not exist ".venv\Scripts\python.exe" goto :preflight_disk_done
set "MM_FREE_MB="
for /f "delims=" %%F in ('".venv\Scripts\python.exe" -c "import shutil,sys;print(shutil.disk_usage(sys.argv[1]).free//1048576)" "!MM_DATA_DIR!" 2^>nul') do set "MM_FREE_MB=%%F"
if not defined MM_FREE_MB goto :preflight_disk_done
if !MM_FREE_MB! GEQ 200 goto :preflight_disk_done
set "MM_FAIL_MSG=Less than 200 MB free on the drive holding your notes."
set "MM_FAIL_FIX=Free some space and run this again. start.bat --doctor shows the exact figure."
goto :fail
:preflight_disk_done

REM  --reinstall is the one-line answer to every "delete .venv and try
REM  again" support reply this project has ever sent. Done here, before the
REM  venv check below, so the rebuild is the ordinary first-run path rather
REM  than a second code path that can rot.
if "!MM_REINSTALL!"=="1" if exist ".venv" (
  echo  !ESC![1;38;5;73m[..]!ESC![0m Removing .venv to rebuild it from scratch...
  call :log "removing .venv for --reinstall"
  rmdir /s /q ".venv" >nul 2>nul
)

REM --- 0. Self-update, then re-launch a FRESH copy --------------------
REM  A running .bat is read from disk by byte offset, so a git pull that
REM  rewrites this file mid-run would corrupt it. To stay safe we pull,
REM  then re-launch the (possibly updated) script in a child process and
REM  stop this one. The MM_CHILD guard prevents an endless loop.
REM
REM  `http.lowSpeedLimit`/`http.lowSpeedTime` are git's own "abort a
REM  connection that has gone quiet" option - the same flags start.sh
REM  uses, and the same ones that turned a black-holed connection (a
REM  listener that accepts and never answers) into a five-second failure
REM  instead of a long stall when tested against one. They don't bound the
REM  very first connect, so a proxy that never completes even a handshake
REM  still falls back to git's own much longer default - rare next to "no
REM  internet" or "a slow/stalled proxy", which is what these are for.
REM
REM  Output is captured to a temp file rather than left to print live, so
REM  a failure can be told apart from a real internet connection - but the
REM  same file is shown either way (see below), so nothing that used to
REM  print here goes missing.
REM
REM  Written flat rather than as one nested IF block: every ECHO below would
REM  otherwise sit inside parentheses, which is the trap the header names,
REM  and the flags now make the entry conditions three questions rather
REM  than one.
if defined MM_CHILD goto :after_update
if "!MM_NO_UPDATE!"=="1" goto :no_update
REM  **A skipped step is still a step, and these two jumps are the whole of
REM  the "only loads up to step 3/5 and then it loads" report.** The splash's
REM  bar is a count of steps that reached `done` over the total
REM  (`launch_status.percent`, and it counts `done` on purpose so the bar
REM  cannot claim 100% while the last and longest phase is running). Both
REM  lines below leave before anything is written for step 1, so on a machine
REM  with no git, or an install that is a downloaded copy rather than a
REM  checkout, the history holds steps 2, 3 and 4 done with 5 active: three of
REM  five, for ever, and then the app opens. Nothing was wrong with the launch;
REM  the bar was counting a step nobody had told it about.
REM
REM  Ticked with the reason instead. "Skipped" is a real outcome for this step
REM  and the list has always shown the others that way ("Offline, skipped",
REM  "Skipped, --no-update"); these two were the only exits that said nothing
REM  at all.
where git >nul 2>nul || (
  call :status !MM_STEP_UPDATE! "Update" "Skipped, git is not installed" "done"
  goto :after_update
)
if not exist ".git" (
  call :status !MM_STEP_UPDATE! "Update" "Skipped, not a git checkout" "done"
  goto :after_update
)
set "MM_CHILD=1"
echo  Checking for updates...
call :status !MM_STEP_UPDATE! "Update" "Checking for updates on GitHub" "active"
REM Read before the pull so a real version change can be reported to
REM the app after relaunch, the same way start.sh's own self-update
REM block does - this script's update runs and finishes before the
REM server (and browser tab) exist, so nothing else can tell "was I
REM just updated?" without this.
call :read_version MM_VERSION_BEFORE
set "MM_GIT_LOG=%TEMP%\mm_git_update_%RANDOM%.log"
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 pull --ff-only > "!MM_GIT_LOG!" 2>&1
set "MM_GIT_STATUS=!errorlevel!"
if "!MM_GIT_STATUS!"=="0" type "!MM_GIT_LOG!"
if defined MM_LOG type "!MM_GIT_LOG!" >> "!MM_LOG!" 2>nul
if "!MM_GIT_STATUS!"=="0" call :read_version MM_VERSION_AFTER
if "!MM_GIT_STATUS!"=="0" if not "!MM_VERSION_AFTER!"=="" if not "!MM_VERSION_AFTER!"=="!MM_VERSION_BEFORE!" (
  REM Picked up by routes_update.py's GET /update/source-status, purely
  REM from these two env vars - no network call on the app's own side,
  REM so this stays offline-safe like everything else update-related.
  set "MM_UPDATED_FROM=!MM_VERSION_BEFORE!"
  set "MM_UPDATED_TO=!MM_VERSION_AFTER!"
)
if "!MM_GIT_STATUS!"=="0" call :status !MM_STEP_UPDATE! "Update" "Up to date" "done"
set "MM_GIT_NET=0"
if not "!MM_GIT_STATUS!"=="0" findstr /I /C:"could not resolve" /C:"unable to access" /C:"timed out" /C:"connection refused" /C:"connection reset" /C:"network is unreachable" /C:"could not connect" /C:"bytes/sec" /C:"proxy" /C:"ssl certificate" /C:"getaddrinfo" "!MM_GIT_LOG!" >nul 2>nul
if not "!MM_GIT_STATUS!"=="0" if not errorlevel 1 set "MM_GIT_NET=1"
if not "!MM_GIT_STATUS!"=="0" if "!MM_GIT_NET!"=="1" echo         No internet - skipping update check.
if not "!MM_GIT_STATUS!"=="0" if "!MM_GIT_NET!"=="1" call :status !MM_STEP_UPDATE! "Update" "Offline, skipped" "done"
if not "!MM_GIT_STATUS!"=="0" if "!MM_GIT_NET!"=="0" echo  !ESC![1;31m[X]!ESC![0m Update failed - staying on the current version:
if not "!MM_GIT_STATUS!"=="0" if "!MM_GIT_NET!"=="0" type "!MM_GIT_LOG!" 2>nul
if not "!MM_GIT_STATUS!"=="0" if "!MM_GIT_NET!"=="0" call :status !MM_STEP_UPDATE! "Update" "Skipped, staying on this version" "done"
del /q "!MM_GIT_LOG!" >nul 2>nul
call :bail_if_cancelled
if defined MM_CANCELLED goto :cancelled
REM  !MM_ARGS! rather than nothing: the child re-parses the flags this run
REM  was given, so --port, --no-browser and the rest survive the relaunch.
call "!MM_SELF!" !MM_ARGS!
set "MM_RC=!errorlevel!"
endlocal & exit /b %MM_RC%
:no_update
call :status !MM_STEP_UPDATE! "Update" "Skipped, --no-update" "done"
:after_update

echo.
echo !ESC![1;38;5;73m    __  ___                                __  ___               ___    ____
echo    /  ^|/  /__  ____ ___  ____  _______  __/  ^|/  /___ _____    /   ^|  /  _/
echo   / /^|_/ / _ \/ __ `__ \/ __ \/ ___/ / / / /^|_/ / __ `/ __ \  / /^| ^|  / /
echo  / /  / /  __/ / / / / / /_/ / /  / /_/ / /  / / /_/ / /_/ / / ___ ^|_/ /
echo /_/  /_/\___/_/ /_/ /_/\____/_/   \__, /_/  /_/\__,_/ .___/ /_/  ^|_/___/
echo                                  /____/            /_/
echo             your notebook, on your machine!ESC![0m
echo.

set "VENV_PY=.venv\Scripts\python.exe"

REM --- 1. Build the venv if it doesn't exist yet ----------------------
REM  Only the FIRST run needs a system Python; after that the app uses
REM  its own .venv, so a flaky PATH can't stop later launches.
if not exist "%VENV_PY%" (
  call :status !MM_STEP_PYTHON! "Python" "Building the environment" "active"
  echo  !ESC![1;38;5;73m[1/4]!ESC![0m First-time setup - looking for Python to build the environment...
  set "PYTHON="
  py -3 --version >nul 2>nul && set "PYTHON=py -3"
  if not defined PYTHON (
    python --version >nul 2>nul && set "PYTHON=python"
  )
  if not defined PYTHON (
    python3 --version >nul 2>nul && set "PYTHON=python3"
  )
  if not defined PYTHON (
    call :status !MM_STEP_PYTHON! "Python" "Not found on PATH" "failed"
    set "MM_FAIL_MSG=No Python was found."
    set "MM_FAIL_FIX=Install Python 3.11, 3.12 or 3.13 from https://www.python.org/downloads/, tick Add python.exe to PATH, then run this again."
    goto :fail
  )
  REM  Caught here, not left to surface later as a confusing pip/import
  REM  failure deep into step 2 - pyproject.toml requires 3.11+, and
  REM  building a venv with an older interpreter would "succeed" and only
  REM  fail once something actually needs a 3.11-only feature.
  !PYTHON! -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if errorlevel 1 (
    for /f "delims=" %%V in ('!PYTHON! --version 2^>^&1') do set "PYVER=%%V"
    call :status !MM_STEP_PYTHON! "Python" "Too old" "failed"
    set "MM_FAIL_MSG=Found !PYVER!, but MemoryMap AI needs Python 3.11 or newer."
    set "MM_FAIL_FIX=Install a newer Python from https://www.python.org/downloads/ and run this again."
    goto :fail
  )
  echo        Using !PYTHON! to create the virtual environment...
  !PYTHON! -m venv .venv
  if errorlevel 1 (
    call :status !MM_STEP_PYTHON! "Python" "Could not create .venv" "failed"
    set "MM_FAIL_MSG=Could not create the virtual environment."
    set "MM_FAIL_FIX=Check there is disk space and that antivirus is not blocking .venv, then run start.bat --reinstall."
    goto :fail
  )
  call :status !MM_STEP_PYTHON! "Python" "Environment ready" "done"
) else (
  echo  !ESC![1;38;5;73m[1/4]!ESC![0m Using the app's virtual environment.
  call :status !MM_STEP_PYTHON! "Python" "Using the existing environment" "done"
)

if not exist "%VENV_PY%" (
  set "MM_FAIL_MSG=The virtual environment looks incomplete."
  set "MM_FAIL_FIX=Run start.bat --reinstall to rebuild it."
  goto :fail
)
call :bail_if_cancelled
if defined MM_CANCELLED goto :cancelled

REM --- 2. Install / update dependencies -------------------------------
REM  A marker file skips the slow reinstall unless requirements.txt has
REM  changed since the last good install.
set "NEED_INSTALL=1"
if exist ".venv\.mm_installed" (
  for %%A in ("requirements.txt") do set "REQ_TIME=%%~tA"
  set /p LAST_TIME=<".venv\.mm_installed"
  if "!REQ_TIME!"=="!LAST_TIME!" set "NEED_INSTALL=0"
)

REM  The marker only answers "have requirements.txt changed?". The question
REM  that matters at launch is "can this venv actually import the app?", and
REM  those come apart the moment the project folder is renamed or moved:
REM  `pip install -e .` records an ABSOLUTE path into the venv, so the old
REM  path stops resolving while requirements.txt keeps its timestamp. The
REM  marker then says "up to date", the reinstall is skipped, and the launch
REM  dies with "No module named memorymap" - reported after a rename from
REM  MemoryMap-AI-v0 to MemoryMap-AI. Asking the venv directly costs one
REM  interpreter start and catches a move, a rename, and a half-deleted venv.
if "!NEED_INSTALL!"=="0" (
  "%VENV_PY%" -c "import memorymap" >nul 2>nul
  if errorlevel 1 (
    echo  !ESC![1;38;5;73m[2/4]!ESC![0m The app folder moved since it was installed - relinking it...
    set "NEED_INSTALL=1"
  )
)

if "!NEED_INSTALL!"=="1" (
  call :status !MM_STEP_DEPS! "Dependencies" "Installing, this can take a few minutes" "active"
  echo  !ESC![1;38;5;73m[2/4]!ESC![0m Installing dependencies - this can take a few minutes for heavy AI models.
  echo         pip's own progress prints below as it happens:

  REM  `--timeout 5 --retries 0` makes pip give up on a dead connection in
  REM  seconds instead of its default (a 15s socket timeout retried 5
  REM  times per package - several minutes of silence on a dead network).
  REM
  REM  `--quiet` and a full `> log 2>&1` redirect used to hide pip's own
  REM  progress entirely - reported directly ("I hate that I can't see
  REM  what's going on and why it is taking so long"), and this is a real
  REM  multi-minute install (sentence-transformers, and torch on Windows).
  REM  Dropping `--quiet` and only redirecting stderr lets pip's own
  REM  "Collecting X / Downloading X (NN%%)" lines print live to the
  REM  console while errors still land in the log for the network-vs-real
  REM  check below - and because nothing here is piped, `errorlevel` still
  REM  reads directly off each pip command with no extra plumbing needed.
  REM
  REM  Named MM_PIP_LOG, not PIP_LOG - every `set` in cmd.exe becomes a real
  REM  environment variable, inherited by the pip subprocess below, and pip
  REM  reads any PIP_<OPTION> env var as if it were that CLI flag. `--log`
  REM  becomes PIP_LOG, so a variable of that exact name made pip try to
  REM  write its OWN verbose log to this same path - the one cmd.exe already
  REM  has open for the `2>>` redirect below. Two writers on one handle, and
  REM  when pip's RotatingFileHandler tried to rotate it mid-install, Windows'
  REM  exclusive locking turned that into a PermissionError logged to stderr
  REM  (reported: "Successfully installed Mako-1.4.1 alembic-1.19.1" followed
  REM  by a `--- Logging error ---` traceback from `logging.handlers`). The
  REM  install itself still succeeded - only pip's own incidental debug
  REM  logging failed - but the traceback reads as a real crash.
  set "MM_PIP_LOG=%TEMP%\mm_pip_install_%RANDOM%.log"
  set "PIP_FAILED=0"
  "%VENV_PY%" -m pip install --upgrade pip --timeout 5 --retries 0 2>"!MM_PIP_LOG!"
  if errorlevel 1 set "PIP_FAILED=1"
  "%VENV_PY%" -m pip install -r requirements.txt --prefer-binary --timeout 5 --retries 0 2>>"!MM_PIP_LOG!"
  if errorlevel 1 set "PIP_FAILED=1"

  "%VENV_PY%" -m pip install -e . --timeout 5 --retries 0 2>>"!MM_PIP_LOG!"
  if errorlevel 1 set "PIP_FAILED=1"

  if "!PIP_FAILED!"=="1" (
    if defined MM_LOG type "!MM_PIP_LOG!" >> "!MM_LOG!" 2>nul
    set "MM_PIP_NET=0"
    findstr /I /C:"could not resolve" /C:"unable to access" /C:"timed out" /C:"connection refused" /C:"connection reset" /C:"network is unreachable" /C:"could not connect" /C:"newconnectionerror" /C:"max retries exceeded" /C:"proxy" /C:"ssl" /C:"getaddrinfo" "!MM_PIP_LOG!" >nul 2>nul
    if not errorlevel 1 set "MM_PIP_NET=1"
    if "!MM_PIP_NET!"=="1" echo  !ESC![1;33m[!]!ESC![0m No internet - skipping dependency update.
    if "!MM_PIP_NET!"=="0" echo  !ESC![1;33m[!]!ESC![0m Could not update dependencies:
    if "!MM_PIP_NET!"=="0" type "!MM_PIP_LOG!" 2>nul
    del /q "!MM_PIP_LOG!" >nul 2>nul
    "%VENV_PY%" -c "import memorymap" >nul 2>nul
    if errorlevel 1 (
      call :status !MM_STEP_DEPS! "Dependencies" "Could not install" "failed"
      set "MM_FAIL_MSG=First-time setup needs an internet connection to install dependencies."
      set "MM_FAIL_FIX=Connect and run this again. start.bat --doctor shows what could not be reached."
      goto :fail
    ) else (
      echo         Launching with existing installation...
      call :status !MM_STEP_DEPS! "Dependencies" "Kept the existing install" "done"
    )
  ) else (
    del /q "!MM_PIP_LOG!" >nul 2>nul
    for %%A in ("requirements.txt") do echo %%~tA>".venv\.mm_installed"
    call :status !MM_STEP_DEPS! "Dependencies" "Installed" "done"
  )
) else (
  echo  !ESC![1;38;5;73m[2/4]!ESC![0m Dependencies already up to date - skipping install.
  call :status !MM_STEP_DEPS! "Dependencies" "Already up to date" "done"
)
call :bail_if_cancelled
if defined MM_CANCELLED goto :cancelled

REM  pywebview is optional and only needed for the app window, so it is
REM  installed on demand rather than for everyone. Cheap after the first
REM  time - pip exits immediately when it is already present. Same
REM  `--timeout`/`--retries` as step 2, since this runs even when
REM  NEED_INSTALL was 0 - it's the one bit of network work that isn't
REM  skipped just because everything else is already installed.
if defined MM_DESKTOP (
  call :status !MM_STEP_WINDOW! "Desktop window" "Checking window support" "active"
  echo        Checking desktop window support...
  "%VENV_PY%" -m pip install --quiet --timeout 5 --retries 0 pywebview
  if errorlevel 1 (
    echo  !ESC![1;33m[!]!ESC![0m pywebview would not install - offline, or a real error - opening a browser tab instead.
    call :status !MM_STEP_WINDOW! "Desktop window" "Not available, using a browser tab" "done"
    set "MM_DESKTOP="
  ) else (
    call :status !MM_STEP_WINDOW! "Desktop window" "Ready" "done"
  )
)

REM --- 3. First-run .env ----------------------------------------------
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo  !ESC![1;38;5;73m[3/4]!ESC![0m Created .env from .env.example.
  )
) else (
  echo  !ESC![1;38;5;73m[3/4]!ESC![0m Configuration found.
)

REM --- 4. Launch -------------------------------------------------------
REM  The splash's handoff. In desktop mode __main__.py opens its own loading
REM  window with a real progress bar, and passes MM_SPLASH_FILE straight
REM  through to it - see _close_launch_splash there - so the two never overlap
REM  and never leave a gap. In browser mode nothing else appears, so the file
REM  is deleted below once the tab is opening.
call :bail_if_cancelled
if defined MM_CANCELLED goto :cancelled
call :status !MM_STEP_START! "Start" "Starting the app" "active"

if defined MM_DESKTOP (
  echo  !ESC![1;38;5;73m[4/4]!ESC![0m Starting MemoryMap AI in its own window.
  echo        Close the app window to stop it.
  echo.
  REM Asked for directly: "guide the user to where the application location
  REM is and what files to run" - !CD!, not %CD%, since this line sits
  REM inside a parenthesized if/else block under enabledelayedexpansion set
  REM at the top of this script. %CD% there would resolve once at the
  REM block's own parse time rather than when this line actually runs, the
  REM same trap !ESC! already exists to avoid. Safe to print as the
  REM install location specifically because "cd /d %~dp0" at the top of
  REM this script means it is always this script's own folder.
  echo  !ESC![1;38;5;73mInstalled at:!ESC![0m !CD!
  echo  !ESC![1;38;5;73mYour notes:!ESC![0m   !MM_DATA_DIR!
  echo  !ESC![1;38;5;73mNext time:!ESC![0m    open a terminal there and run start-desktop.bat again
  echo.
  "%VENV_PY%" -m memorymap --desktop
  REM  Exit code 42 (RELAUNCHED_HIDDEN_EXIT_CODE, __main__.py) means "User
  REM  view" handed off to a separate, console-less pythonw.exe process and
  REM  this one exited on purpose - its job here is done. Falling through to
  REM  the shared "has stopped" message and `pause` below would leave this
  REM  window sitting on a keypress prompt forever, which is exactly the
  REM  visible terminal "User view" exists to avoid - exit here instead so
  REM  it closes itself the same way a normal double-click launch would.
  if !errorlevel! equ 42 (
    endlocal
    exit /b 0
  )
) else (
  echo  !ESC![1;38;5;73m[4/4]!ESC![0m Starting MemoryMap AI at !MM_URL!
  if "!MM_NO_BROWSER!"=="1" echo        No browser will be opened, --no-browser. Close THIS window to stop the app.
  if "!MM_NO_BROWSER!"=="0" echo        A browser tab opens in a moment. Close THIS window, or press Ctrl+C in it, to stop the app.
  echo.
  echo  !ESC![1;38;5;73mInstalled at:!ESC![0m !CD!
  echo  !ESC![1;38;5;73mYour notes:!ESC![0m   !MM_DATA_DIR!
  echo  !ESC![1;38;5;73mNext time:!ESC![0m    open a terminal there and run start.bat again
  echo.
  REM  Wait a moment, then open the browser - done with the venv Python
  REM  rather than `timeout` and `start`.
  REM
  REM  `timeout` is an EXTERNAL program (System32\timeout.exe), not a cmd
  REM  builtin, so it fails with "'timeout' is not recognized as an internal
  REM  or external command" on any machine whose PATH has lost System32 -
  REM  which a badly-behaved installer or a hand-edited PATH does more often
  REM  than you would think. It also refuses to run at all when its input is
  REM  redirected. Reported in use.
  REM
  REM  `%VENV_PY%` is an absolute path this script has already created and
  REM  checked, so it needs nothing on PATH at all, and `webbrowser` picks the
  REM  default browser the same way `start` does.
  if "!MM_NO_BROWSER!"=="0" start "" /b "%VENV_PY%" -c "import time, webbrowser; time.sleep(3); webbrowser.open('!MM_URL!')"
  REM  The last step, ticked. In desktop mode this line is deliberately
  REM  absent: __main__.py's loading window inherits the same file and owns
  REM  the Start step until the server answers, so ticking it here would put
  REM  two Starts in one list. In browser mode nothing else narrates it, and
  REM  leaving it active was why the splash, the console and the log all
  REM  ended one step short of their own total, reported as a bar that "only
  REM  ever goes to 3/5 and then it loads". The launcher really has
  REM  finished: the app starts on the next line.
  call :status !MM_STEP_START! "Start" "Handed over to the app" "done"
  REM  No second window is coming in browser mode - the tab is the app - so
  REM  the splash closes here rather than being handed on.
  if defined MM_SPLASH_FILE del /q "!MM_SPLASH_FILE!" >nul 2>nul
  "%VENV_PY%" -m memorymap
)

echo.
REM  The backstop. Every ordinary path already deleted this, but an error
REM  path that exits through here must not leave a borderless always-on-top
REM  window with no owner sitting on the user's desktop. splash.ps1 also
REM  gives up on its own after MaxMinutes for the case where this script is
REM  killed outright and never runs this line at all.
if defined MM_SPLASH_FILE del /q "!MM_SPLASH_FILE!" >nul 2>nul
call :log "the app has stopped"
echo  MemoryMap AI has stopped.
pause
endlocal
goto :eof

REM ====================================================================
REM  Everything that prints something and exits
REM ====================================================================

:already_running
REM  The commonest support message in this whole project, "it says the
REM  address is in use", turned into an answer rather than an error: the
REM  right thing to do about a MemoryMap that is already running is to open
REM  it, not to report a conflict.
echo  !ESC![1;38;5;73m[ok]!ESC![0m MemoryMap is already running on port !MM_PORT! - opening it.
call :log "already running on port !MM_PORT!, opened it"
if "!MM_NO_BROWSER!"=="0" start "" "!MM_URL!"
if defined MM_SPLASH_FILE del /q "!MM_SPLASH_FILE!" >nul 2>nul
endlocal
exit /b 0

:cancelled
echo  !ESC![1;33m[!]!ESC![0m Cancelled - stopping before the next step.
call :log "cancelled from the splash"
endlocal
exit /b 0

:fail
REM  Every hard stop in this script comes through here, so a failure always
REM  carries the same three things: what happened, what to try - the wording
REM  the matching --doctor row uses, so the two never contradict each other
REM  - and where the log is.
echo.
echo  !ESC![1;31m[x]!ESC![0m !MM_FAIL_MSG!
if defined MM_FAIL_FIX echo         What to try: !MM_FAIL_FIX!
if defined MM_LOG echo         Log: !MM_LOG!
echo         Checks: start.bat --doctor
call :log "FAILED: !MM_FAIL_MSG!"
if defined MM_SPLASH_FILE del /q "!MM_SPLASH_FILE!" >nul 2>nul
pause
endlocal
exit /b 1

:do_logs
if not exist "!MM_LOG_DIR!" mkdir "!MM_LOG_DIR!" >nul 2>nul
echo Launcher logs: !MM_LOG_DIR!
start "" explorer "!MM_LOG_DIR!"
endlocal
exit /b 0

:do_shortcut
REM  A real .lnk rather than a copy of this file: it carries the icon, the
REM  working directory and the --desktop argument, which a copy cannot.
REM  uninstall.bat --shortcuts removes this exact path.
set "MM_LNK=%USERPROFILE%\Desktop\MemoryMap AI.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('!MM_LNK!'); $s.TargetPath='!MM_HOME!start.bat'; $s.Arguments='--desktop'; $s.WorkingDirectory='!MM_HOME!'; $s.IconLocation='!MM_HOME!frontend\icon.ico'; $s.Description='MemoryMap AI'; $s.Save()" >nul 2>nul
if exist "!MM_LNK!" goto :do_shortcut_ok
set "MM_FAIL_MSG=Could not create the shortcut on your Desktop."
set "MM_FAIL_FIX=Check that your Desktop folder exists and that PowerShell is allowed to run."
goto :fail
:do_shortcut_ok
echo  !ESC![1;38;5;73m[done]!ESC![0m Shortcut created: !MM_LNK!
endlocal
exit /b 0

REM ====================================================================
REM  The doctor
REM
REM  One row per thing that can stop a launch, each with a tick or a cross
REM  and, for a cross, one line saying what to do about it. This is the
REM  launcher's doctor and not the app's: it has to work on a machine with
REM  no Python at all, which is why cmd answers the first rows itself and
REM  only asks the venv for the things that genuinely need an interpreter.
REM
REM  [ok] and [x] rather than the tick and cross characters: the same table
REM  is printed by start.sh, and cmd.exe's default code page, 437 or 850 on
REM  most Windows installs, renders those as mojibake. One table, both
REM  platforms, means the ASCII pair wins. Same row order and the same fix
REM  wording as start.sh so the two read as one table.
REM
REM  Written as a chain of labels rather than nested IF blocks: the rows
REM  carry paths and URLs, and a label chain keeps every ECHO out of
REM  parentheses where a bracket in a path cannot end a block early.
REM ====================================================================
:do_doctor
echo !ESC![1;38;5;73mMemoryMap AI - checks!ESC![0m
echo.
set "MM_DOCTOR_FAILED="

REM  1. Python. Version AND path: "I installed Python" and "this script can
REM  find Python" are different facts, and the second is the one that matters.
set "MM_PY="
py -3 --version >nul 2>nul && set "MM_PY=py -3"
if not defined MM_PY (
  python --version >nul 2>nul && set "MM_PY=python"
)
if not defined MM_PY (
  python3 --version >nul 2>nul && set "MM_PY=python3"
)
if defined MM_PY goto :doctor_python_found
call :row x "Python" "not found on PATH" "Install Python 3.11, 3.12 or 3.13, then run this again."
goto :doctor_venv
:doctor_python_found
set "MM_PYVER="
set "MM_PYPATH="
for /f "delims=" %%V in ('!MM_PY! -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "MM_PYVER=%%V"
for /f "delims=" %%P in ('!MM_PY! -c "import sys;print(sys.executable)" 2^>nul') do set "MM_PYPATH=%%P"
if not defined MM_PYVER set "MM_PYVER=unknown"
!MM_PY! -c "import sys;sys.exit(0 if (3,11)<=sys.version_info<(3,14) else 1)" >nul 2>nul
if errorlevel 1 goto :doctor_python_wrong
call :row ok "Python" "!MM_PYVER! at !MM_PYPATH!"
goto :doctor_venv
:doctor_python_wrong
call :row x "Python" "!MM_PYVER! at !MM_PYPATH!" "This app is tested on 3.11 to 3.13. Install one of those and run --reinstall."

REM  2. The venv, asked the only question that matters: can it import the
REM  things the server cannot start without. A .venv folder that exists and
REM  a .venv that works are not the same thing after a move, a rename or a
REM  half-finished pip.
:doctor_venv
if exist ".venv\Scripts\python.exe" goto :doctor_venv_present
call :row warn ".venv" "not built yet" "Normal before the first run. start.bat builds it."
goto :doctor_disk
:doctor_venv_present
".venv\Scripts\python.exe" -c "import fastapi, sqlalchemy, memorymap" >nul 2>nul
if errorlevel 1 goto :doctor_venv_broken
call :row ok ".venv" "fastapi, sqlalchemy and memorymap all import"
goto :doctor_disk
:doctor_venv_broken
call :row x ".venv" "cannot import fastapi, sqlalchemy or memorymap" "Run start.bat --reinstall to rebuild it."

REM  3. Free disk on the drive the notes are on, not the drive the code is
REM  on: they are often different, and the one that fills up first is the
REM  one taking uploads and embeddings. Asked of Python when there is one,
REM  because cmd's only answer is DIR's "bytes free" footer, which is
REM  English-only and would report nothing on a localised Windows.
:doctor_disk
set "MM_FREE_MB="
if not exist ".venv\Scripts\python.exe" goto :doctor_disk_unknown
for /f "delims=" %%F in ('".venv\Scripts\python.exe" -c "import shutil,sys;print(shutil.disk_usage(sys.argv[1]).free//1048576)" "!MM_DATA_DIR!" 2^>nul') do set "MM_FREE_MB=%%F"
if not defined MM_FREE_MB goto :doctor_disk_unknown
if !MM_FREE_MB! LSS 1024 goto :doctor_disk_low
call :row ok "Disk" "!MM_FREE_MB! MB free on !MM_DATA_DIR!"
goto :doctor_port
:doctor_disk_low
call :row x "Disk" "!MM_FREE_MB! MB free on !MM_DATA_DIR!" "Under 1 GB. Free some space before the first install, which needs about 300 MB."
goto :doctor_port
:doctor_disk_unknown
call :row warn "Disk" "could not read free space on !MM_DATA_DIR!"

REM  4. The port. "Already running" is a success, not a failure.
:doctor_port
call :port_check
if defined MM_PORT_UNKNOWN goto :doctor_port_unknown
if defined MM_PORT_BUSY goto :doctor_port_busy
call :row ok "Port !MM_PORT!" "free"
goto :doctor_updates
:doctor_port_unknown
call :row warn "Port !MM_PORT!" "could not check, netstat is not on PATH"
goto :doctor_updates
:doctor_port_busy
if defined MM_PORT_MINE goto :doctor_port_mine
call :row x "Port !MM_PORT!" "in use by something else" "Close that program, or start on another port: start.bat --port 8010"
goto :doctor_updates
:doctor_port_mine
call :row ok "Port !MM_PORT!" "MemoryMap is already running, open !MM_URL!"

REM  5. The update path. The same low-speed flags the pull itself uses, so
REM  this row cannot be slower than the thing it describes. cmd has no
REM  wall-clock timeout to wrap it in, which start.sh does have, so those
REM  flags are the whole bound here.
:doctor_updates
if not exist ".git" goto :doctor_updates_nogit
where git >nul 2>nul
if errorlevel 1 goto :doctor_updates_nobin
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 ls-remote --exit-code origin HEAD >nul 2>nul
if errorlevel 1 goto :doctor_updates_quiet
call :row ok "Updates" "the git remote answered"
goto :doctor_provider
:doctor_updates_nogit
call :row warn "Updates" "not a git checkout, so start.bat cannot self-update"
goto :doctor_provider
:doctor_updates_nobin
call :row warn "Updates" "git is not installed, so start.bat cannot self-update"
goto :doctor_provider
:doctor_updates_quiet
call :row warn "Updates" "the git remote did not answer" "Offline, or behind a proxy. The app still runs: use --no-update to skip the check."

REM  6/7. The model provider. Read straight out of preferences.json rather
REM  than through the app, because this has to work when the app is exactly
REM  what will not start. JSON is not something cmd can parse, so the file
REM  needs the venv; without one this falls back to the same defaults the
REM  app itself uses rather than skipping the row.
:doctor_provider
set "MM_PROVIDER=ollama"
set "MM_LLM_URL="
if exist ".env" (
  for /f "tokens=1,* delims==" %%A in ('findstr /B /C:"OLLAMA_URL=" ".env" 2^>nul') do set "MM_LLM_URL=%%B"
)
if defined MM_LLM_URL set MM_LLM_URL=!MM_LLM_URL:"=!
if not defined MM_LLM_URL set "MM_LLM_URL=http://localhost:11434"
if not exist ".venv\Scripts\python.exe" goto :doctor_provider_probe
set "MM_BASE=-"
REM  usebackq and backticks, not the usual 'quoted' form: FOR /F ends a
REM  single-quoted command at the next apostrophe, and Python one-liners are
REM  full of them. Backticks leave the quotes alone.
for /f "usebackq tokens=1,2" %%A in (`".venv\Scripts\python.exe" -c "import json,os,sys;p=os.path.join(sys.argv[1],'preferences.json');d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};print(d.get('llm_provider') or 'ollama', d.get('llm_base_url') or '-')" "!MM_DATA_DIR!" 2^>nul`) do (
  set "MM_PROVIDER=%%A"
  set "MM_BASE=%%B"
)
if not "!MM_BASE!"=="-" set "MM_LLM_URL=!MM_BASE!"
:doctor_provider_probe
if /i "!MM_PROVIDER!"=="ollama" goto :doctor_ollama
call :row ok "Provider" "!MM_PROVIDER! at !MM_LLM_URL!"
goto :doctor_notes
:doctor_ollama
where curl >nul 2>nul
if errorlevel 1 goto :doctor_ollama_nocurl
set "MM_MODELS="
if not exist ".venv\Scripts\python.exe" goto :doctor_ollama_nocount
for /f "usebackq delims=" %%M in (`curl -fsS --max-time 4 "!MM_LLM_URL!/api/tags" 2^>nul ^| ".venv\Scripts\python.exe" -c "import json,sys;print(len(json.load(sys.stdin).get('models',[])))" 2^>nul`) do set "MM_MODELS=%%M"
if not defined MM_MODELS goto :doctor_ollama_quiet
call :row ok "Ollama" "!MM_LLM_URL!, models installed: !MM_MODELS!"
goto :doctor_notes
:doctor_ollama_nocount
curl -fsS --max-time 4 "!MM_LLM_URL!/api/tags" >nul 2>nul
if errorlevel 1 goto :doctor_ollama_quiet
call :row ok "Ollama" "!MM_LLM_URL! answered"
goto :doctor_notes
:doctor_ollama_nocurl
call :row warn "Ollama" "cannot check !MM_LLM_URL! without curl"
goto :doctor_notes
:doctor_ollama_quiet
call :row warn "Ollama" "nothing answered at !MM_LLM_URL!" "Start Ollama, or switch provider in Settings. Notes and search work without it."

REM  8. Where the notes are, and how big. The path is the answer to more
REM  support questions than anything else in this table.
:doctor_notes
set "MM_NOTES_SIZE=size unknown until .venv is built"
if not exist ".venv\Scripts\python.exe" goto :doctor_notes_row
for /f "usebackq delims=" %%S in (`".venv\Scripts\python.exe" -c "import os,sys;p=sys.argv[1];t=sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(p) for f in fs) if os.path.isdir(p) else 0;print(str(t//1048576)+' MB')" "!MM_DATA_DIR!" 2^>nul`) do set "MM_NOTES_SIZE=%%S"
:doctor_notes_row
if not exist "!MM_DATA_DIR!" goto :doctor_notes_missing
for %%D in ("!MM_DATA_DIR!") do call :row ok "Notes" "%%~fD, !MM_NOTES_SIZE!"
goto :doctor_last
:doctor_notes_missing
call :row ok "Notes" "!MM_DATA_DIR!, not created yet"

REM  9. The last thing that went wrong, from the log this script writes. A
REM  cross here is history, not a live fault, so it is a warn: it says
REM  "this is what failed last time", which is the sentence someone needs
REM  when the failure does not reproduce while they are watching.
:doctor_last
set "MM_LAST_LOG="
for /f "delims=" %%F in ('dir /b /o-d "!MM_LOG_DIR!\launcher-*.log" 2^>nul') do (
  if not defined MM_LAST_LOG set "MM_LAST_LOG=!MM_LOG_DIR!\%%F"
)
if defined MM_LAST_LOG goto :doctor_last_read
call :row ok "Last run" "no launcher log yet"
goto :doctor_done
:doctor_last_read
REM  SET /P from a file, not a FOR /F over findstr's output. The line comes
REM  out of a log that carries git's and pip's own text verbatim, and
REM  `set "VAR=%%E"` on a line containing a double quote and an ampersand
REM  ends the SET early and runs the rest as a command. SET /P assigns the
REM  line with no parsing at all, which is the only cmd construct that
REM  does. It reads the FIRST match rather than the last, which is usually
REM  the cause rather than the cascade; the row names the log either way.
set "MM_LAST_ERR="
set "MM_ERR_TMP=%TEMP%\mm_lasterr_%RANDOM%.txt"
findstr /I /C:"FAILED" /C:"error" /C:"traceback" "!MM_LAST_LOG!" > "!MM_ERR_TMP!" 2>nul
set /p MM_LAST_ERR=<"!MM_ERR_TMP!"
del /q "!MM_ERR_TMP!" >nul 2>nul
if not defined MM_LAST_ERR goto :doctor_last_clean
REM  Unquoted SET, so the replacement can remove the double quotes: they are
REM  the one character that could still shift CALL :row's argument
REM  boundaries below. Delayed-expanded text is never re-scanned for
REM  operators, so an ampersand in the line is already harmless here.
set MM_LAST_ERR=!MM_LAST_ERR:"=!
set "MM_LAST_ERR=!MM_LAST_ERR:~0,100!"
call :row warn "Last run" "!MM_LAST_ERR!" "From !MM_LAST_LOG!"
goto :doctor_done
:doctor_last_clean
for %%L in ("!MM_LAST_LOG!") do call :row ok "Last run" "no errors in %%~nxL"

:doctor_done
echo.
if defined MM_DOCTOR_FAILED goto :doctor_failed
echo  !ESC![1;38;5;73mEverything checks out.!ESC![0m
endlocal
exit /b 0
:doctor_failed
echo  !ESC![1;31mSomething above needs fixing before the app will start.!ESC![0m
endlocal
exit /b 1

REM ====================================================================
REM  Subroutines
REM ====================================================================

:help
echo MemoryMap AI launcher
echo.
echo Usage: start.bat [options]
echo.
echo   desktop         Start in the app's own window instead of a browser tab
echo   --port N        Serve on port N instead of 8000
echo   --no-browser    Start the server but do not open a browser
echo   --no-update     Skip the update check and run the code that is here now
echo   --reinstall     Rebuild .venv from scratch, then start
echo   --doctor        Check this machine, print a table and exit
echo   --logs          Open the launcher log folder and exit
echo   --shortcut      Create a desktop shortcut for this launcher and exit
echo   --version       Print the version and exit
echo   --help          Show this message and exit
echo.
echo What it does: builds .venv on first run, installs and updates dependencies
echo whenever requirements.txt changes, pulls the latest code first, skipped
echo silently if offline, then starts the server.
echo.
echo Your notes: !MM_DATA_DIR!
echo Set MEMORYMAP_DATA_DIR, in the environment or in .env, to move them.
echo.
echo To remove what this script installed, see uninstall.bat --help.
exit /b 0

REM  One line appended to the launcher log. Never echoes to the console:
REM  that already said its piece in colour, and the log wants the plain text.
:log
if not defined MM_LOG exit /b 0
>>"!MM_LOG!" echo(%~1
exit /b 0

REM  mm_status's twin. The redirect goes first because a value ending in a
REM  digit would turn "echo !VAR!>>file" into a numbered stream redirect.
REM  The line is built into a variable first so the bars in it are never
REM  re-parsed as pipes: delayed expansion happens after the command line
REM  has already been split on its operators.
:status
if not defined MM_STEP_TOTAL exit /b 0
set "MM_ST_LINE=%~1|!MM_STEP_TOTAL!|%~2|%~3|%~4"
if defined MM_SPLASH_FILE >>"!MM_SPLASH_FILE!" echo(!MM_ST_LINE!
call :log "step %~1 of !MM_STEP_TOTAL! - %~2: %~3 [%~4]"
exit /b 0

REM  Polled between phases only. __cancel__ is written by the splash's
REM  Cancel button, see scripts\splash.ps1; anything else in the file is
REM  ignored so a stray write cannot stop a launch. Between phases and not
REM  during one, because killing a pip mid-install leaves a half-written
REM  venv, which is a worse outcome than one more minute of waiting.
:bail_if_cancelled
set "MM_CANCELLED="
if not defined MM_SPLASH_FILE exit /b 0
if not exist "!MM_SPLASH_FILE!.cancel" exit /b 0
findstr /C:"__cancel__" "!MM_SPLASH_FILE!.cancel" >nul 2>nul
if errorlevel 1 exit /b 0
set "MM_CANCELLED=1"
del /q "!MM_SPLASH_FILE!.cancel" >nul 2>nul
del /q "!MM_SPLASH_FILE!" >nul 2>nul
exit /b 0

REM  Two questions, not one: "is the port busy" and "is it busy with US".
REM  The second turns the commonest support message in this project into an
REM  answer rather than an error. netstat rather than a socket, because cmd
REM  has no equivalent of bash's /dev/tcp; it lives in System32, which a
REM  hand-edited PATH can lose, so its absence is reported rather than read
REM  as "the port is free".
:port_check
set "MM_PORT_BUSY="
set "MM_PORT_MINE="
set "MM_PORT_UNKNOWN="
where netstat >nul 2>nul
if errorlevel 1 (
  set "MM_PORT_UNKNOWN=1"
  exit /b 0
)
REM  LISTENING narrows this to a server socket, so a remote address that
REM  happens to end in the same port number cannot be mistaken for one.
for /f "delims=" %%L in ('netstat -an -p TCP 2^>nul ^| findstr /C:":!MM_PORT! " ^| findstr /I /C:"LISTENING"') do set "MM_PORT_BUSY=1"
if not defined MM_PORT_BUSY exit /b 0
where curl >nul 2>nul
if errorlevel 1 exit /b 0
for /f "delims=" %%H in ('curl -fsS --max-time 3 "http://127.0.0.1:!MM_PORT!/health" 2^>nul ^| findstr /C:"MemoryMap AI"') do set "MM_PORT_MINE=1"
exit /b 0

REM  One doctor row: %1 ok, x or warn, %2 label, %3 value, %4 what to try.
REM  The label is padded by hand because cmd has no printf. Every value is
REM  echoed through a delayed-expansion variable so a path with an ampersand
REM  or a bracket in it cannot be re-parsed as a command separator.
:row
set "MM_ROW_MARK=  !ESC![1;38;5;73m[ok]!ESC![0m"
if /i "%~1"=="x" set "MM_ROW_MARK=  !ESC![1;31m[x] !ESC![0m"
if /i "%~1"=="x" set "MM_DOCTOR_FAILED=1"
if /i "%~1"=="warn" set "MM_ROW_MARK=  !ESC![1;33m[!]!ESC![0m "
set "MM_ROW_LABEL=%~2              "
set "MM_ROW_LABEL=!MM_ROW_LABEL:~0,14!"
set "MM_ROW_VALUE=%~3"
echo(!MM_ROW_MARK! !MM_ROW_LABEL! !MM_ROW_VALUE!
call :log "  [%~1] %~2: %~3"
if /i "%~1"=="ok" exit /b 0
if "%~4"=="" exit /b 0
set "MM_ROW_FIX=%~4"
echo(                      !MM_ROW_FIX!
call :log "       what to try: %~4"
exit /b 0

REM --- Subroutine: read __version__ out of src\memorymap\__init__.py ----
REM  Called with the name of the variable to set (e.g. `call :read_version
REM  MM_VERSION_BEFORE`) - batch has no return value, only "set a variable
REM  in the caller's scope", which `set "%~1=..."` under
REM  enabledelayedexpansion (set at the top of this script) does.
REM
REM  Deliberately left quoted (token 3 of `__version__ = "0.1.3"`, split on
REM  spaces, is `"0.1.3"` with the quotes still on) rather than stripped
REM  here - putting a literal double-quote character inside a batch
REM  `set "VAR=..."` line is exactly the kind of thing this project's own
REM  start.bat has already been bitten by once (see the top-of-file note
REM  on parens inside IF blocks). routes_update.py strips the quotes on
REM  the Python side instead, where it's one `.strip('"')` and not a
REM  cmd.exe quoting puzzle.
:read_version
set "MM_VER_TMP="
for /f "tokens=1,2,* delims= " %%A in ('findstr /B "__version__" "src\memorymap\__init__.py" 2^>nul') do set "MM_VER_TMP=%%C"
set "%~1=!MM_VER_TMP!"
exit /b 0
