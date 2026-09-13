#!/usr/bin/env bash
# ====================================================================
#  MemoryMap AI - one-click launcher for macOS / Linux
#
#  Run ./start.sh - it sets everything up the first time, then just runs
#  the app after that:
#
#    1. use the app's own .venv Python (only needs a system Python the
#       very first time, to build that .venv)
#    2. install / update dependencies + the app itself
#    3. copy .env.example to .env the first time
#    4. start the server and open your browser at localhost:8000
#
#  Flags: see `./start.sh --help`. start.bat takes the same set in the
#  same order, on purpose - one launcher contract on both platforms, so a
#  support answer ("run start --doctor") is the same sentence whoever is
#  asking. tests/test_launcher_scripts.py fails the build if the two help
#  texts ever drift apart.
# ====================================================================
set -e
# The pip install below is piped through `tee` so its own progress prints
# live instead of vanishing into a log file until either done or failed -
# reported directly ("I hate that I can't see what's going on and why it
# is taking so long"). Without `pipefail`, `cmd | tee file` reports tee's
# exit status (always 0), not the command's, which would silently turn
# every pip failure into a false success.
set -o pipefail
cd "$(dirname "$0")"

# Whether stdout is a real terminal, answered ONCE, here, before anything
# redirects it. Everything downstream that used to ask `[ -t 1 ]` asks this
# variable instead, because the launcher log further down replaces stdout
# with a pipe into `tee`: after that point `[ -t 1 ]` is false on a machine
# that plainly does have a terminal, which would drop the colours and, much
# worse, put the zenity splash up over a console that is already narrating
# every phase.
MM_TTY=0
[ -t 1 ] && MM_TTY=1

# Colour, only when talking to a real terminal - a redirected/piped run
# (a log file, a CI step) should never end up with raw escape codes in it.
if [ "$MM_TTY" = "1" ]; then
  TEAL=$'\033[1;38;5;73m'
  RED=$'\033[1;31m'
  YELLOW=$'\033[1;33m'
  RESET=$'\033[0m'
else
  TEAL="" ; RED="" ; YELLOW="" ; RESET=""
fi

# --- Where the data actually is --------------------------------------
# The same precedence the app itself uses (core/config.py): an explicit
# MEMORYMAP_DATA_DIR in the environment, else one set in .env, else the
# "data" folder beside this script. Resolved this early because three
# separate things below need it before any Python exists to be asked: the
# launcher log, the doctor's disk and size rows, and the line that tells
# someone where their notes actually are.
MM_DATA_DIR="${MEMORYMAP_DATA_DIR:-}"
if [ -z "$MM_DATA_DIR" ] && [ -f ".env" ]; then
  MM_DATA_DIR="$(grep -E '^MEMORYMAP_DATA_DIR=' ".env" 2>/dev/null | tail -n 1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
fi
[ -n "$MM_DATA_DIR" ] || MM_DATA_DIR="data"

# --- Flags -----------------------------------------------------------
# Parsed before anything touches the network, the venv or the screen, so
# `--help`, `--version` and `--doctor` are always instant and always work,
# including on a machine where the install is broken - which is exactly the
# machine someone runs `--doctor` on.
#
# Both forms of the desktop flag are accepted: the bare word `desktop` is
# what start-desktop.bat has always passed, and `--desktop` is what anyone
# who has read `--help` will type.
MM_PORT="${MEMORYMAP_PORT:-8000}"
MM_NO_BROWSER=0
MM_NO_UPDATE=0
MM_REINSTALL=0
MM_ACTION=""
MM_BAD_FLAG=""

mm_help() {
  cat <<MM_HELP
MemoryMap AI launcher

Usage: ./start.sh [options]

  desktop         Start in the app's own window instead of a browser tab
  --port N        Serve on port N instead of 8000
  --no-browser    Start the server but do not open a browser
  --no-update     Skip the update check and run the code that is here now
  --reinstall     Rebuild .venv from scratch, then start
  --doctor        Check this machine, print a table and exit
  --logs          Open the launcher log folder and exit
  --shortcut      Create a desktop shortcut for this launcher and exit
  --version       Print the version and exit
  --help          Show this message and exit

What it does: builds .venv on first run, installs and updates dependencies
whenever requirements.txt changes, pulls the latest code first (skipped
silently if offline), then starts the server.

Your notes: $MM_DATA_DIR
Set MEMORYMAP_DATA_DIR, in the environment or in .env, to move them.

To remove what this script installed, see ./uninstall.sh --help.
MM_HELP
}

while [ $# -gt 0 ]; do
  case "$1" in
    desktop|--desktop) export MM_DESKTOP=1 ;;
    --port) shift; MM_PORT="${1:-}" ;;
    --port=*) MM_PORT="${1#*=}" ;;
    --no-browser) MM_NO_BROWSER=1 ;;
    --no-update) MM_NO_UPDATE=1 ;;
    --reinstall) MM_REINSTALL=1 ;;
    --doctor) MM_ACTION="doctor" ;;
    --logs) MM_ACTION="logs" ;;
    --shortcut) MM_ACTION="shortcut" ;;
    --version|-V) MM_ACTION="version" ;;
    -h|--help) MM_ACTION="help" ;;
    "") ;;
    *) MM_BAD_FLAG="$1" ;;
  esac
  # `shift || break`, not a bare `shift`: a flag that takes a value shifts
  # once inside its own branch, so `--port` or `--export` typed as the last
  # argument leaves nothing for this one to consume. Under `set -e` at the
  # top of this script, that failing shift killed the launcher outright with
  # exit 1 and no message, instead of reaching the validation below that
  # prints the help and exits 2.
  shift || break
done

# An unknown flag is a typo, and a typo that silently starts the app anyway
# is how someone spends ten minutes wondering why `--no-browsr` still opened
# a browser. Exit 2, not 1: 1 already means "the app tried and failed", and a
# script wrapping this one needs to tell those two apart.
if [ -n "$MM_BAD_FLAG" ]; then
  echo "Unknown option: $MM_BAD_FLAG"
  echo
  mm_help
  exit 2
fi

case "$MM_PORT" in
  ''|*[!0-9]*)
    echo "--port needs a number, not '$MM_PORT'."
    echo
    mm_help
    exit 2
    ;;
esac
if [ "$MM_PORT" -lt 1 ] || [ "$MM_PORT" -gt 65535 ]; then
  echo "--port must be between 1 and 65535, not $MM_PORT."
  echo
  mm_help
  exit 2
fi
# Exported rather than passed on the command line: it has to survive the
# re-exec below AND reach `python -m memorymap`, which reads it in
# __main__.py. One variable, two readers, no argument plumbing.
export MEMORYMAP_PORT="$MM_PORT"
MM_URL="http://localhost:$MM_PORT"

if [ "$MM_ACTION" = "help" ]; then
  mm_help
  exit 0
fi

if [ "$MM_ACTION" = "version" ]; then
  MM_VERSION="$(sed -n 's/__version__ = "\(.*\)"/\1/p' src/memorymap/__init__.py 2>/dev/null | head -1)"
  echo "MemoryMap AI ${MM_VERSION:-unknown}"
  echo "Installed at: $(pwd)"
  echo "Your notes:   $MM_DATA_DIR"
  exit 0
fi

# --- The launcher log ------------------------------------------------
# Asked for as part of one launcher contract: every run leaves a file, so
# "it did not start" can be answered by reading something rather than by
# asking someone to reproduce it with a terminal open. Same path on both
# platforms, <data>/logs/launcher-<date>.log, so the doctor row and the
# --logs flag below can both find it without being told.
#
# `exec > >(tee -a ...)` rather than wrapping the whole script in a pipe:
# a pipe would put this script in a subshell, and the `exec` at the very
# bottom (which is what hands the terminal to uvicorn) would then replace
# the subshell instead of this process, leaving an idle parent behind for
# the life of the app.
#
# MM_LOG_ACTIVE is the guard for the self-update re-exec further down: the
# child inherits the redirected stdout already, so a second `tee` in the
# child would write every line twice into the same file.
MM_LOG_DIR="$MM_DATA_DIR/logs"
MM_LOG=""
if [ -z "${MM_LOG_ACTIVE:-}" ]; then
  if mkdir -p "$MM_LOG_DIR" 2>/dev/null && [ -w "$MM_LOG_DIR" ]; then
    MM_LOG="$MM_LOG_DIR/launcher-$(date +%Y-%m-%d).log"
    export MM_LOG_ACTIVE="$MM_LOG"
    # errexit off across the redirection, and only here. `>(tee ...)` forks
    # a process, and a fork can fail for reasons that have nothing to do
    # with this app: a machine out of memory, a hit process limit. Under
    # `set -e` that turned "could not open my own log" into "the launcher
    # exited non-zero with no message", which is the worst possible trade -
    # the log exists to explain failures, and it was causing one. Seen
    # twice here, both times while the machine was thrashing.
    #
    # MM_LOG is cleared if the redirection did not take, so nothing
    # downstream tells the reader to go and look at a file that will not be
    # written; the launch then carries on unlogged, which is what it did
    # before this block existed at all.
    set +e
    exec > >(tee -a "$MM_LOG") 2>&1
    if [ $? -ne 0 ]; then
      MM_LOG=""
      unset MM_LOG_ACTIVE
    fi
    set -e
    [ -n "$MM_LOG" ] && echo "--- $(date '+%Y-%m-%d %H:%M:%S') ./start.sh ${*:-} (pid $$) ---"
    # Ten days of launches is plenty to answer "what changed since it last
    # worked", and this folder is inside the user's notebook - it must never
    # be the thing that fills a disk.
    ls -1t "$MM_LOG_DIR"/launcher-*.log 2>/dev/null | tail -n +11 | while read -r old; do
      rm -f "$old" 2>/dev/null || true
    done
  fi
else
  MM_LOG="$MM_LOG_ACTIVE"
fi

# --- Launch splash ---------------------------------------------------
# The same gap start.bat's splash covers: the git pull, building .venv and a
# pip install all happen before Python exists, so before __main__.py can show
# its own loading window. Reported as the app appearing not to start at all.
#
# Gated on MM_TTY being 0 - stdout not being a terminal - which is exactly the
# case the report is about: launched from a file manager or a .desktop entry,
# with no console to read. Run from a terminal this script already narrates
# every phase, and a second window over the top would be noise.
#
# zenity for a real progress dialog on Linux. kdialog's own progress dialog
# needs DBus plumbing to update, so it's skipped - this only ever helps
# someone who has zenity, not everyone GTK-adjacent.
#
# macOS ships no equivalent progress *dialog* that isn't a modal stealing
# focus (osascript's `display dialog`), and a splash the user has to click
# past isn't worth building. `display notification` is a different thing:
# it's the native banner in the top-right corner, never steals focus, and
# needs no window to manage or clean up - asked for directly ("can there be
# an equivalent for linux and mac"), and this is the one the "not worth it"
# reasoning above never actually ruled out. No progress bar or pulsing, just
# the same phase text zenity gets, which is the part that answers "did this
# actually start" - the report this whole splash exists for.
MM_SPLASH_MODE=""
MM_SPLASH_PID=""
MM_SPLASH_FIFO=""
if [ "$MM_TTY" = "0" ] && [ "$MM_ACTION" = "" ] && command -v zenity >/dev/null 2>&1; then
  MM_SPLASH_FIFO="$(mktemp -u "${TMPDIR:-/tmp}/mm_splash_XXXXXX")"
  if mkfifo "$MM_SPLASH_FIFO" 2>/dev/null; then
    # No --pulsate any more: the status protocol carries `step` and `total`,
    # so there is a real fraction to show, and a bar that moves a fifth of the
    # way each time a step finishes is more informative than one that pulses
    # identically whether the launcher is working or wedged. The pulse is not
    # lost, it moved inside the active step on the Windows splash, which can
    # draw both at once; zenity cannot.
    zenity --progress --no-cancel --auto-close \
           --title="MemoryMap AI" --text="Starting" --percentage=0 \
           < "$MM_SPLASH_FIFO" >/dev/null 2>&1 &
    MM_SPLASH_PID=$!
    # Held open on fd 9 for the life of the script: closing it is what tells
    # zenity the job is over, so it must not close between phases.
    exec 9>"$MM_SPLASH_FIFO"
    MM_SPLASH_MODE="zenity"
  else
    MM_SPLASH_FIFO=""
  fi
elif [ "$MM_TTY" = "0" ] && [ "$MM_ACTION" = "" ] && [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
  MM_SPLASH_MODE="notify"
fi

# One line of text into the dialog/notification.
mm_splash() {
  case "$MM_SPLASH_MODE" in
    zenity)
      # zenity reads "#text" as a label update and a bare number as a
      # percentage. $2 is the percentage, already worked out by mm_status.
      printf '#%s\n' "$1" >&9 2>/dev/null || true
      [ -n "${2:-}" ] && printf '%s\n' "$2" >&9 2>/dev/null || true
      ;;
    notify)
      # osascript's own quoting, not the shell's: a title/note with a
      # double quote or backslash in it would otherwise end the AppleScript
      # string early or corrupt the script rather than just failing to show
      # - a cosmetic notification is not worth a shell-out that could break
      # on a phase string nobody chose. Every `mm_splash` call site in this
      # file is a fixed literal, but this guards the mechanism itself, not
      # today's call sites.
      osascript -e "display notification $(printf '%s' "$1" | sed 's/[\\"]/\\&/g; s/^/"/; s/$/"/') with title \"MemoryMap AI\"" \
        >/dev/null 2>&1 || true
      ;;
  esac
}

# Must run on every exit - a pulsating dialog left with no owner is worse than
# no dialog. Note this does NOT cover the `exec`s at the end of this script:
# exec replaces the shell without firing EXIT, and fd 9 is inherited by the
# new process, which would hold the fifo open and leave zenity on screen for
# the entire life of the app. Both of those call mm_splash_done by hand.
# A no-op in "notify" mode: each call already fired and cleared on its own,
# nothing is left running to own or close.
mm_splash_done() {
  [ -n "$MM_SPLASH_PID" ] || return 0
  exec 9>&- 2>/dev/null || true
  kill "$MM_SPLASH_PID" 2>/dev/null || true
  [ -n "$MM_SPLASH_FIFO" ] && rm -f "$MM_SPLASH_FIFO" 2>/dev/null
  MM_SPLASH_PID=""
}
trap mm_splash_done EXIT INT TERM

# --- The status protocol ---------------------------------------------
# `step|total|title|detail|state`, one line per transition, appended so the
# file is a history rather than a single current value: a window that opens
# late (the Python loading window, handed the same file) can then render
# every step that already happened with a tick beside it, instead of showing
# an empty list and only learning about the steps still to come. See
# scripts/splash.ps1 for the Windows renderer and
# src/memorymap/core/launch_status.py for the parser both Python surfaces
# share. `state` is active, done or failed.
#
# On this side it also feeds the zenity dialog and the macOS notification,
# so there is exactly one place that decides what a phase is called on all
# three surfaces.
MM_STEP_UPDATE=1
MM_STEP_PYTHON=2
MM_STEP_DEPS=3
if [ -n "${MM_DESKTOP:-}" ]; then
  MM_STEP_WINDOW=4
  MM_STEP_START=5
  MM_STEP_TOTAL=5
else
  MM_STEP_WINDOW=0
  MM_STEP_START=4
  MM_STEP_TOTAL=4
fi

# The control file the splash's Cancel button writes to. Named off the status
# file so nothing has to agree on a second variable, and polled between
# phases only: killing a pip mid-install leaves a half-written venv, which is
# a worse outcome than one more minute of waiting.
MM_CANCEL_FILE=""
[ -n "${MM_SPLASH_FILE:-}" ] && MM_CANCEL_FILE="${MM_SPLASH_FILE}.cancel"

# mm_status <step> <title> <detail> <state>
mm_status() {
  local step="$1" title="$2" detail="$3" state="$4" pct=0
  # Steps *finished*, over total. The active step counts as not yet done,
  # which is why this is step-1 and not step: a bar that jumps to 100% while
  # the last and longest phase is still running is the lie the old marquee
  # existed to avoid.
  pct=$(( (step - 1) * 100 / MM_STEP_TOTAL ))
  [ "$state" = "done" ] && pct=$(( step * 100 / MM_STEP_TOTAL ))
  if [ -n "${MM_SPLASH_FILE:-}" ]; then
    printf '%s|%s|%s|%s|%s\n' "$step" "$MM_STEP_TOTAL" "$title" "$detail" "$state" \
      >> "$MM_SPLASH_FILE" 2>/dev/null || true
  fi
  # The step list, in the terminal and in the log, one line per transition,
  # with the same marks the Windows splash and the Python loading window
  # draw. Asked for as part of one splash design on every surface: a
  # terminal is a surface too, and before this it narrated four numbered
  # phases that did not match the five-step list every other surface drew.
  #
  # Printed on every run, not only on a terminal. This is also the launcher
  # log's narrative, and the log is the whole answer to "it did not start"
  # for the runs that have no terminal at all - a .desktop entry, a Finder
  # double-click. A first version of this was gated on MM_TTY, in the same
  # commit that removed the [n/4] echoes it replaced, which left a
  # redirected run's log with a header, a logo and pip's output and nothing
  # saying which phase any of it belonged to.
  #
  # Ticks on a terminal, the doctor's ASCII pair everywhere else. A log file
  # gets opened in whatever editor and code page someone has, and start.bat
  # prints the same table through cmd's own 437; the terminal is the one
  # place the nicer characters are certain to render.
  local mark=" ${TEAL}*${RESET}"
  case "$state" in
    done) mark=" ${TEAL}\xe2\x9c\x93${RESET}" ;;
    failed) mark=" ${RED}\xc3\x97${RESET}" ;;
  esac
  if [ "$MM_TTY" != "1" ]; then
    mark=" [..]"
    case "$state" in
      done) mark=" [ok]" ;;
      failed) mark=" [x] " ;;
    esac
  fi
  printf '%b [%s/%s] %-15s %s\n' "$mark" "$step" "$MM_STEP_TOTAL" "$title" "$detail"
  # Only the active step is worth a banner or a label change; a "done" line
  # is immediately followed by the next step's "active" one.
  [ "$state" = "done" ] && return 0
  mm_splash "$title: $detail" "$pct"
}

# Polled between phases. `__cancel__` is written by the splash's Cancel
# button (scripts/splash.ps1); anything else in the file is ignored so a
# stray write cannot stop a launch.
mm_cancelled() {
  [ -n "$MM_CANCEL_FILE" ] || return 1
  [ -f "$MM_CANCEL_FILE" ] || return 1
  grep -q '__cancel__' "$MM_CANCEL_FILE" 2>/dev/null
}

mm_bail_if_cancelled() {
  mm_cancelled || return 0
  echo " ${YELLOW}[!]${RESET} Cancelled - stopping before the next step."
  rm -f "$MM_CANCEL_FILE" 2>/dev/null || true
  [ -n "${MM_SPLASH_FILE:-}" ] && rm -f "$MM_SPLASH_FILE" 2>/dev/null
  mm_splash_done
  exit 0
}

# --- Failure, said once, with the fix --------------------------------
# Every hard stop in this script goes through here, so a failure always
# carries the same three things: what happened, what to try (the wording the
# matching --doctor row uses, so the two never contradict each other), and
# where the log is.
mm_fail() {
  echo
  echo " ${RED}[x]${RESET} $1"
  [ -n "${2:-}" ] && echo "        What to try: $2"
  [ -n "$MM_LOG" ] && echo "        Log: $MM_LOG"
  echo "        Checks: ./start.sh --doctor"
  exit 1
}

# --- Network helpers --------------------------------------------------
# Every network call in this script (the self-update `git pull` below, and
# pip in step 2) goes through these two so "no internet" behaves the same
# way everywhere: a short, bounded wait, a one-line explanation, and the
# launch continues. Nothing here may ever be allowed to hang - a DNS lookup
# that never returns or a proxy that accepts the connection and then says
# nothing both stall past any timeout a well-behaved server would need,
# which is exactly why a hard wall-clock timeout (not just pip's own
# `--timeout`, which only bounds a single socket read) wraps every call.
#
# `timeout`/`gtimeout` (GNU coreutils) cover Linux and a Homebrew-equipped
# Mac; the manual fallback below covers a stock macOS with neither, using a
# background watcher that SIGTERMs the job if it outlives its budget.
run_with_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
    return $?
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
    return $?
  fi
  "$@" &
  local cmd_pid=$!
  ( sleep "$secs" 2>/dev/null; kill -TERM "$cmd_pid" 2>/dev/null ) &
  local watcher_pid=$!
  local status=0
  wait "$cmd_pid" 2>/dev/null || status=$?
  kill "$watcher_pid" 2>/dev/null || true
  wait "$watcher_pid" 2>/dev/null || true
  return "$status"
}

# Recognises the shapes "no internet" actually takes on the command line -
# DNS failure, connection refused/timed out, a proxy that errors or hangs,
# TLS failing to negotiate - so those get a calm one-liner instead of a wall
# of the tool's own retry/traceback text. Anything that does NOT match this
# (a real dependency conflict, a corrupt requirements.txt, disk full) falls
# through to printing the tool's actual error, on purpose - CLAUDE.md is
# explicit that swallowing a genuine failure behind "offline?" costs the
# next session an hour finding out it wasn't.
is_network_error() {
  grep -qiE \
    'could not resolve host|temporary failure in name resolution|name or service not known|nodename nor servname|node name.*not known|connection timed out|connection refused|network is unreachable|failed to establish a new connection|read timed out|newconnectionerror|max retries exceeded|no route to host|could not connect to server|couldn.t connect to server|ssl.*(handshake|certificate)|proxy (error|authentication)|getaddrinfo failed|unable to connect|connection reset by peer|no address associated with hostname|could not fetch url|unreachable network|operation too slow|bytes/sec transferred|unable to access|could not resolve proxy|empty reply from server|timed out waiting' \
    "$1" 2>/dev/null
}

# --- Is something already on the port? --------------------------------
# Two questions, not one: "is the port busy" and "is it busy with US". The
# second one turns the commonest support message in this whole project ("it
# says the address is in use") into an answer rather than an error, because
# the right thing to do about a MemoryMap that is already running is to open
# it, not to report a conflict.
#
# bash's own /dev/tcp rather than lsof/ss/netstat, none of which are reliably
# present, and all of which need a different incantation per platform. The
# subshell around `exec` matters: a redirection failure in `exec` at the top
# level makes a non-interactive shell exit outright, which would turn "the
# port is free" into "the launcher died".
mm_port_open() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

# Empty output means "nothing answered like MemoryMap".
mm_port_is_memorymap() {
  local body=""
  if command -v curl >/dev/null 2>&1; then
    body="$(curl -fsS --max-time 3 "http://127.0.0.1:$1/health" 2>/dev/null || true)"
  else
    body="$( (exec 3<>"/dev/tcp/127.0.0.1/$1"; \
              printf 'GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n' >&3; \
              cat <&3) 2>/dev/null || true )"
  fi
  case "$body" in
    *"MemoryMap AI"*) return 0 ;;
  esac
  return 1
}

# $2 names what to open it with, for the machine that has neither `open` nor
# `xdg-open` and gets told to do it by hand. It exists because this function
# has two callers and they open different kinds of thing: telling someone to
# open their launcher log folder "in your browser" is the sort of line that
# makes a reader doubt the rest of the message.
mm_open_url() {
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else echo "        Open $1 in your ${2:-browser}."
  fi
}

# --- The doctor -------------------------------------------------------
# One row per thing that can stop a launch, each with a tick or a cross and,
# for a cross, one line saying what to do about it. This is the launcher's
# doctor and not the app's: it has to work on a machine with no Python at
# all, which is why the rows are shell first and only ask the venv for the
# things that genuinely need an interpreter.
#
# `[ok]` and `[x]` rather than U+2713/U+2717: the same table is printed by
# start.bat, and cmd.exe's default code page (437 or 850 on most Windows
# installs) renders those as mojibake. One table, both platforms, means the
# ASCII pair wins.
MM_DOCTOR_FAILED=0

mm_row() {
  # $1 ok|x|warn, $2 label, $3 value, $4 what to try (crosses only)
  local mark="  ${TEAL}[ok]${RESET}"
  case "$1" in
    x) mark="  ${RED}[x] ${RESET}"; MM_DOCTOR_FAILED=1 ;;
    warn) mark="  ${YELLOW}[!] ${RESET}" ;;
  esac
  printf '%s %-14s %s\n' "$mark" "$2" "$3"
  [ "$1" = "ok" ] || [ -z "${4:-}" ] || printf '       %-14s %s\n' "" "$4"
}

mm_dir_size() {
  [ -d "$1" ] || { echo "not created yet"; return 0; }
  du -sh "$1" 2>/dev/null | awk '{print $1}' || echo "unknown"
}

mm_doctor() {
  echo "${TEAL}MemoryMap AI - checks${RESET}"
  echo

  # 1. Python. Version AND path: "I installed Python" and "this script can
  # find Python" are different facts, and the second is the one that matters.
  local py="" pyver="" pypath=""
  if command -v python3 >/dev/null 2>&1; then py=python3
  elif command -v python >/dev/null 2>&1; then py=python
  fi
  if [ -z "$py" ]; then
    mm_row x "Python" "not found on PATH" "Install Python 3.11, 3.12 or 3.13, then run this again."
  else
    pyver="$("$py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo "unknown")"
    pypath="$(command -v "$py")"
    if "$py" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
      mm_row ok "Python" "$pyver at $pypath"
    else
      mm_row x "Python" "$pyver at $pypath" "This app is tested on 3.11 to 3.13. Install one of those and run --reinstall."
    fi
  fi

  # 2. The venv, asked the only question that matters: can it import the
  # things the server cannot start without. A .venv folder that exists and a
  # .venv that works are not the same thing after a move, a rename or a
  # half-finished pip.
  if [ ! -x ".venv/bin/python" ]; then
    mm_row warn ".venv" "not built yet" "Normal before the first run. ./start.sh builds it."
  elif .venv/bin/python -c "import fastapi, sqlalchemy, memorymap" >/dev/null 2>&1; then
    mm_row ok ".venv" "fastapi, sqlalchemy and memorymap all import"
  else
    mm_row x ".venv" "cannot import fastapi, sqlalchemy or memorymap" "Run ./start.sh --reinstall to rebuild it."
  fi

  # 3. Free disk on the drive the notes are on, not the drive the code is on:
  # they are often different, and the one that fills up first is the one
  # taking uploads and embeddings.
  local disk_target="$MM_DATA_DIR"
  [ -d "$disk_target" ] || disk_target="$(dirname "$MM_DATA_DIR")"
  [ -d "$disk_target" ] || disk_target="."
  local free_kb free_h
  free_kb="$(df -Pk "$disk_target" 2>/dev/null | awk 'NR==2 {print $4}')"
  free_h="$(df -Ph "$disk_target" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -z "$free_kb" ]; then
    mm_row warn "Disk" "could not read free space on $disk_target"
  elif [ "$free_kb" -lt 1048576 ]; then
    mm_row x "Disk" "$free_h free on $disk_target" "Under 1 GB. Free some space before the first install, which needs about 300 MB."
  else
    mm_row ok "Disk" "$free_h free on $disk_target"
  fi

  # 4. The port. "Already running" is a success, not a failure: see
  # mm_port_is_memorymap.
  if ! mm_port_open "$MM_PORT"; then
    mm_row ok "Port $MM_PORT" "free"
  elif mm_port_is_memorymap "$MM_PORT"; then
    mm_row ok "Port $MM_PORT" "MemoryMap is already running, open $MM_URL"
  else
    mm_row x "Port $MM_PORT" "in use by something else" "Close that program, or start on another port: ./start.sh --port 8010"
  fi

  # 5. The update path. Bounded at 5s with the same low-speed flags the pull
  # itself uses, so this row cannot be slower than the thing it describes.
  if [ ! -d ".git" ]; then
    mm_row warn "Updates" "not a git checkout, so ./start.sh cannot self-update"
  elif ! command -v git >/dev/null 2>&1; then
    mm_row warn "Updates" "git is not installed, so ./start.sh cannot self-update"
  elif run_with_timeout 5 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 \
         ls-remote --exit-code origin HEAD >/dev/null 2>&1; then
    mm_row ok "Updates" "the git remote answered"
  else
    mm_row warn "Updates" "the git remote did not answer in 5 seconds" "Offline, or behind a proxy. The app still runs: use --no-update to skip the check."
  fi

  # 6/7. The model provider. Read straight out of preferences.json rather
  # than through the app, because this has to work when the app is exactly
  # what will not start.
  local prefs="$MM_DATA_DIR/preferences.json"
  local provider="ollama" base_url=""
  if [ -f "$prefs" ]; then
    provider="$(sed -n 's/.*"llm_provider"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$prefs" | head -1)"
    base_url="$(sed -n 's/.*"llm_base_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$prefs" | head -1)"
    [ -n "$provider" ] || provider="ollama"
  fi
  local ollama_url="${OLLAMA_URL:-}"
  if [ -z "$ollama_url" ] && [ -f ".env" ]; then
    ollama_url="$(grep -E '^OLLAMA_URL=' ".env" 2>/dev/null | tail -n 1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
  fi
  [ -n "$base_url" ] && ollama_url="$base_url"
  [ -n "$ollama_url" ] || ollama_url="http://localhost:11434"
  if [ "$provider" = "ollama" ]; then
    local tags=""
    if command -v curl >/dev/null 2>&1; then
      tags="$(curl -fsS --max-time 4 "$ollama_url/api/tags" 2>/dev/null || true)"
    fi
    if [ -n "$tags" ]; then
      local count
      count="$(printf '%s' "$tags" | grep -o '"name"' | wc -l | tr -d ' ')"
      mm_row ok "Ollama" "$ollama_url, models installed: $count"
    elif ! command -v curl >/dev/null 2>&1; then
      mm_row warn "Ollama" "cannot check $ollama_url without curl"
    else
      mm_row warn "Ollama" "nothing answered at $ollama_url" "Start Ollama, or switch provider in Settings. Notes and search work without it."
    fi
  else
    mm_row ok "Provider" "$provider at ${ollama_url}"
  fi

  # 8. Where the notes are, and how big. The path is the answer to more
  # support questions than anything else in this table.
  local resolved="$MM_DATA_DIR"
  [ -d "$MM_DATA_DIR" ] && resolved="$(cd "$MM_DATA_DIR" && pwd)"
  mm_row ok "Notes" "$resolved, $(mm_dir_size "$MM_DATA_DIR")"

  # 9. The last thing that went wrong, from the log this script writes. A
  # cross here is history, not a live fault, so it is a warn: it says "this
  # is what failed last time", which is the sentence someone needs when the
  # failure does not reproduce while they are watching.
  local last_log=""
  last_log="$(ls -1t "$MM_LOG_DIR"/launcher-*.log 2>/dev/null | head -1 || true)"
  if [ -z "$last_log" ]; then
    mm_row ok "Last run" "no launcher log yet"
  else
    local last_error
    last_error="$(grep -aiE '\[x\]|error|traceback|failed' "$last_log" 2>/dev/null | tail -1 | cut -c1-100)"
    if [ -n "$last_error" ]; then
      mm_row warn "Last run" "$last_error" "From $last_log"
    else
      mm_row ok "Last run" "no errors in $(basename "$last_log")"
    fi
  fi

  echo
  if [ "$MM_DOCTOR_FAILED" = "1" ]; then
    echo " ${RED}Something above needs fixing before the app will start.${RESET}"
    return 1
  fi
  echo " ${TEAL}Everything checks out.${RESET}"
  return 0
}

if [ "$MM_ACTION" = "doctor" ]; then
  mm_splash_done
  if mm_doctor; then exit 0; else exit 1; fi
fi

# --- The log folder ---------------------------------------------------
if [ "$MM_ACTION" = "logs" ]; then
  mkdir -p "$MM_LOG_DIR" 2>/dev/null || true
  echo "Launcher logs: $(cd "$MM_LOG_DIR" 2>/dev/null && pwd || echo "$MM_LOG_DIR")"
  mm_open_url "$MM_LOG_DIR" "file manager"
  exit 0
fi

# --- The desktop shortcut ---------------------------------------------
# Linux gets a .desktop entry in the per-user applications folder, which is
# what makes it show up in the launcher menu as well as on the desktop;
# macOS gets a Finder alias, which is the thing a Mac user recognises as a
# shortcut. Both are removable by ./uninstall.sh --shortcuts, which knows
# these same two paths.
#
# The .desktop entry runs the launcher with no terminal (Terminal=false),
# which is exactly the case the splash above exists for.
mm_shortcut() {
  local here; here="$(pwd)"
  if [ "$(uname)" = "Darwin" ]; then
    local desktop="$HOME/Desktop"
    [ -d "$desktop" ] || mm_fail "No Desktop folder at $desktop." "Create it, or start the app from this folder."
    if osascript -e "tell application \"Finder\" to make alias file to POSIX file \"$here/start.sh\" at POSIX file \"$desktop\"" >/dev/null 2>&1; then
      echo " ${TEAL}[done]${RESET} Alias to start.sh created on your Desktop."
    else
      # A symlink is not a Finder alias, but it opens the same file and it
      # works when Finder scripting is refused (a locked-down Mac, or a
      # first run before Automation permission has been granted).
      ln -sf "$here/start.sh" "$desktop/MemoryMap AI" 2>/dev/null \
        && echo " ${TEAL}[done]${RESET} Link to start.sh created on your Desktop." \
        || mm_fail "Could not create the shortcut on your Desktop." "Check that $desktop is writable."
    fi
    return 0
  fi
  local apps="$HOME/.local/share/applications"
  mkdir -p "$apps" 2>/dev/null || mm_fail "Could not create $apps." "Check your home folder is writable."
  local entry="$apps/memorymap-ai.desktop"
  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=MemoryMap AI"
    echo "Comment=Your notebook, on your own machine"
    echo "Exec=$here/start.sh --desktop"
    echo "Path=$here"
    # icon-512.png, not icon.png, which has never existed in this repo: the
    # entry was written with a path to a missing file, so the menu item and
    # the Desktop copy both fell back to a generic icon. This is the same
    # file __main__.py hands GTK on Linux, and for the same reason - ICO
    # decoding through GdkPixbuf was never confirmed there.
    echo "Icon=$here/frontend/icon-512.png"
    echo "Terminal=false"
    echo "Categories=Office;Utility;"
  } > "$entry"
  chmod +x "$entry" 2>/dev/null || true
  echo " ${TEAL}[done]${RESET} Menu entry created: $entry"
  if [ -d "$HOME/Desktop" ]; then
    cp "$entry" "$HOME/Desktop/memorymap-ai.desktop" 2>/dev/null || true
    chmod +x "$HOME/Desktop/memorymap-ai.desktop" 2>/dev/null || true
    echo "        A copy is on your Desktop. Some desktops ask you to allow it the first time."
  fi
}

if [ "$MM_ACTION" = "shortcut" ]; then
  mm_splash_done
  mm_shortcut
  exit 0
fi

# --- Preflight --------------------------------------------------------
# The three commonest ways a launch dies, checked in the second before it
# starts rather than left to surface as a traceback four minutes in. This is
# a subset of --doctor on purpose: the rest of that table costs network
# round trips, and nobody wants to wait for an Ollama probe to open their
# notebook.
if mm_port_open "$MM_PORT"; then
  if mm_port_is_memorymap "$MM_PORT"; then
    echo " ${TEAL}[ok]${RESET} MemoryMap is already running on port $MM_PORT - opening it."
    [ "$MM_NO_BROWSER" = "1" ] || mm_open_url "$MM_URL"
    mm_splash_done
    exit 0
  fi
  mm_fail "Port $MM_PORT is already in use by another program." \
          "Close it, or start on another port: ./start.sh --port 8010"
fi

MM_FREE_KB="$(df -Pk "$(dirname "$MM_DATA_DIR")" 2>/dev/null | awk 'NR==2 {print $4}')"
if [ -n "$MM_FREE_KB" ] && [ "$MM_FREE_KB" -lt 204800 ]; then
  mm_fail "Less than 200 MB free on the drive holding your notes." \
          "Free some space and run this again. ./start.sh --doctor shows the exact figure."
fi

# --reinstall is the one-line answer to every "delete .venv and try again"
# support reply this project has ever sent. Done here, before the venv check
# below, so the rebuild is the ordinary first-run path rather than a second
# code path that can rot.
if [ "$MM_REINSTALL" = "1" ] && [ -d ".venv" ]; then
  echo " ${TEAL}[..]${RESET} Removing .venv to rebuild it from scratch..."
  rm -rf ".venv"
fi

# --- 0. Self-update, then re-exec a fresh copy ----------------------
# Pull first so a launch always runs the latest code, then re-exec the
# (possibly updated) script so a changed file can't corrupt this run.
# The MM_CHILD guard prevents an endless loop.
if [ -z "${MM_CHILD:-}" ] && [ "$MM_NO_UPDATE" = "0" ] && command -v git >/dev/null 2>&1 && [ -d .git ]; then
  mm_status "$MM_STEP_UPDATE" "Update" "Checking for updates on GitHub" "active"
  echo " Checking for updates..."
  GIT_LOG="$(mktemp 2>/dev/null || echo "/tmp/mm_git_$$.log")"
  # Read before the pull so a real version change can be reported to the
  # app after relaunch (below) - the whole point of this script's own
  # update mechanism being invisible otherwise: it runs and finishes
  # before the server (and the browser tab) even exist, so nothing else
  # in the app can tell "was I just updated?" without this.
  MM_VERSION_BEFORE="$(sed -n 's/__version__ = "\(.*\)"/\1/p' src/memorymap/__init__.py 2>/dev/null | head -1)"
  # `http.lowSpeedLimit`/`http.lowSpeedTime` abort a connection that has
  # gone quiet mid-transfer (a proxy that stalls after accepting bytes);
  # `run_with_timeout` is the hard wall-clock backstop for a connect phase
  # that never gets that far - a DNS query or a proxy handshake that hangs
  # before a single byte comes back, which the low-speed options don't see.
  if run_with_timeout 8 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 \
       pull --ff-only >"$GIT_LOG" 2>&1; then
    # git's own progress line ("Already up to date." / "Fast-forward...") is
    # genuinely useful - captured above only so a *failure* can be
    # classified, not to hide it on the success path.
    cat "$GIT_LOG"
    MM_VERSION_AFTER="$(sed -n 's/__version__ = "\(.*\)"/\1/p' src/memorymap/__init__.py 2>/dev/null | head -1)"
    if [ -n "$MM_VERSION_AFTER" ] && [ "$MM_VERSION_BEFORE" != "$MM_VERSION_AFTER" ]; then
      # Picked up by routes_update.py's GET /update/source-status, purely
      # from these two env vars - no network call needed on the app's own
      # side, so this stays offline-safe the same way everything else that
      # touches "was there an update" in this app is required to be.
      export MM_UPDATED_FROM="$MM_VERSION_BEFORE"
      export MM_UPDATED_TO="$MM_VERSION_AFTER"
    fi
    mm_status "$MM_STEP_UPDATE" "Update" "Up to date" "done"
  else
    if is_network_error "$GIT_LOG"; then
      echo "        No internet - skipping update check."
      mm_status "$MM_STEP_UPDATE" "Update" "Offline, skipped" "done"
    else
      echo "        (skipped update - staying on the current version)"
      tail -n 5 "$GIT_LOG" | sed 's/^/        /'
      mm_status "$MM_STEP_UPDATE" "Update" "Skipped, staying on this version" "done"
    fi
  fi
  rm -f "$GIT_LOG" 2>/dev/null || true
  mm_bail_if_cancelled
  export MM_CHILD=1
  exec "$0" "$@"
fi
if [ "$MM_NO_UPDATE" = "1" ]; then
  mm_status "$MM_STEP_UPDATE" "Update" "Skipped, --no-update" "done"
fi

echo
printf '%s' "$TEAL"
cat <<'MM_LOGO'
    __  ___                                __  ___               ___    ____
   /  |/  /___  ____ ___  ____  _______  __/  |/  /___ _____    /   |  / _/
  / /|_/ / _ \/ __ `__ \/ __ \/ ___/ / / / /|_/ / __ `/ __ \  / /| |  / /
 / /  / /  __/ / / / / / /_/ / /  / /_/ / /  / / /_/ / /_/ / / ___ |_/ /
/_/  /_/\___/_/ /_/ /_/\____/_/   \__, /_/  /_/\__,_/ .___/ /_/  |_/___/
                                 /____/            /_/
MM_LOGO
printf '            your notebook, on your machine%s\n\n' "$RESET"

VENV_PY=".venv/bin/python"

# --- 1. Build the venv if it doesn't exist yet ----------------------
# Only the first run needs a system Python; later launches use .venv.
if [ ! -x "$VENV_PY" ]; then
  mm_status "$MM_STEP_PYTHON" "Python" "Building the environment" "active"
  PYTHON=""
  if command -v python3 >/dev/null 2>&1; then PYTHON=python3
  elif command -v python >/dev/null 2>&1; then PYTHON=python
  fi
  if [ -z "$PYTHON" ]; then
    mm_status "$MM_STEP_PYTHON" "Python" "Not found on PATH" "failed"
    mm_fail "No Python found." "Install Python 3.11, 3.12 or 3.13, then run this again."
  fi
  # Caught here, not left to surface later as a confusing pip/import
  # failure deep into step 2 - `pyproject.toml` requires 3.11+, and
  # building a venv with an older interpreter would "succeed" and only
  # fail once something actually needs a 3.11-only feature.
  if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    mm_status "$MM_STEP_PYTHON" "Python" "Too old" "failed"
    mm_fail "Found $($PYTHON --version 2>&1), but MemoryMap AI needs Python 3.11 or newer." \
            "Install a newer Python and run this again."
  fi
  echo "        Using $($PYTHON --version) to create the virtual environment..."
  if ! "$PYTHON" -m venv .venv; then
    mm_status "$MM_STEP_PYTHON" "Python" "Could not create .venv" "failed"
    echo "        On Debian and Ubuntu this is usually a missing package:"
    echo "        sudo apt install python3-venv"
    mm_fail "Could not create the virtual environment (see the error above)." \
            "On Debian and Ubuntu: sudo apt install python3-venv"
  fi
  mm_status "$MM_STEP_PYTHON" "Python" "Environment ready" "done"
else
  mm_status "$MM_STEP_PYTHON" "Python" "Using the existing environment" "done"
fi

if [ ! -x "$VENV_PY" ]; then
  mm_fail "The virtual environment looks incomplete." "Run ./start.sh --reinstall to rebuild it."
fi
mm_bail_if_cancelled

# --- 2. Install / update dependencies --------------------------------
NEED_INSTALL=1
if [ -f ".venv/.mm_installed" ]; then
  REQ_HASH=$(cksum requirements.txt | awk '{print $1}')
  LAST_HASH=$(cat ".venv/.mm_installed" 2>/dev/null || echo "")
  [ "$REQ_HASH" = "$LAST_HASH" ] && NEED_INSTALL=0
fi

if [ "$NEED_INSTALL" = "0" ] && ! "$VENV_PY" -c "import memorymap" >/dev/null 2>&1; then
  echo "        The app folder moved since it was installed - relinking it..."
  NEED_INSTALL=1
fi

if [ "$NEED_INSTALL" = "1" ]; then
  mm_status "$MM_STEP_DEPS" "Dependencies" "Installing, this can take a few minutes" "active"
  echo "        pip's own progress prints below as it happens:"
  # `--timeout 5 --retries 0` makes pip fail fast per-connection instead of
  # its default (a 15s socket timeout retried 5 times, which is several
  # minutes of silence on a dead network before the venv check even runs);
  # `run_with_timeout` is still the outer backstop for the one phase pip's
  # own flags don't bound - resolving the index host in the first place.
  #
  # Piped through `tee` rather than redirected: pip's own "Collecting X /
  # Downloading X / Installing collected packages" lines are real progress
  # information, and hiding them behind a static "installing..." message
  # with nothing moving for minutes is exactly what was reported. The log
  # file still gets a full copy for the network-vs-real-error check below,
  # `pipefail` (set at the top of this script) makes `$?` reflect pip's
  # exit status rather than tee's.
  PIP_LOG="$(mktemp 2>/dev/null || echo "/tmp/mm_pip_$$.log")"
  # Retries only a network-*shaped* failure, and only automatically - a real
  # one (bad requirements.txt, a wrong platform wheel, disk full) is retried
  # zero times on purpose. Looping the same failing command against a broken
  # requirements.txt would just waste the user's time and bandwidth instead
  # of saving it (ROADMAP Priority 0 #9); is_network_error is the same
  # classifier the (non-retrying) reporting below already trusted, not a new
  # one built for this. `tee "$PIP_LOG"` (no -a) on the first command of each
  # attempt already truncates the log fresh, so a retry's own is_network_error
  # check never sees the previous attempt's output.
  PIP_ATTEMPT=1
  PIP_MAX_ATTEMPTS=3
  PIP_DELAY=5
  while true; do
    if run_with_timeout 20 "$VENV_PY" -m pip install --upgrade pip --timeout 5 --retries 0 2>&1 | tee "$PIP_LOG" && \
       run_with_timeout 180 "$VENV_PY" -m pip install -r requirements.txt --timeout 5 --retries 0 2>&1 | tee -a "$PIP_LOG" && \
       run_with_timeout 60 "$VENV_PY" -m pip install -e . --timeout 5 --retries 0 2>&1 | tee -a "$PIP_LOG"; then
      cksum requirements.txt | awk '{print $1}' > ".venv/.mm_installed"
      mm_status "$MM_STEP_DEPS" "Dependencies" "Installed" "done"
      break
    fi
    if [ "$PIP_ATTEMPT" -ge "$PIP_MAX_ATTEMPTS" ] || ! is_network_error "$PIP_LOG"; then
      if is_network_error "$PIP_LOG"; then
        echo " ${YELLOW}[!]${RESET} No internet - skipping dependency update."
      else
        # Not a network shape - show the real reason rather than guessing.
        # A silently-mislabelled dependency failure is the trap CLAUDE.md
        # calls out: it reads as "offline" and costs the next session an hour
        # finding out the real cause was a broken requirements.txt.
        echo " ${YELLOW}[!]${RESET} Could not update dependencies:"
        tail -n 8 "$PIP_LOG" | sed 's/^/        /'
      fi
      rm -f "$PIP_LOG" 2>/dev/null || true
      if "$VENV_PY" -c "import memorymap" >/dev/null 2>&1; then
        echo "        Launching with existing installation..."
        mm_status "$MM_STEP_DEPS" "Dependencies" "Kept the existing install" "done"
      else
        mm_status "$MM_STEP_DEPS" "Dependencies" "Could not install" "failed"
        mm_fail "First-time setup needs an internet connection to install dependencies." \
                "Connect and run this again. ./start.sh --doctor shows what could not be reached."
      fi
      break
    fi
    echo " ${YELLOW}[!]${RESET} Looked like a network hiccup (attempt $PIP_ATTEMPT/$PIP_MAX_ATTEMPTS) - retrying in ${PIP_DELAY}s..."
    sleep "$PIP_DELAY"
    PIP_ATTEMPT=$((PIP_ATTEMPT + 1))
    PIP_DELAY=$((PIP_DELAY * 2))
  done
  rm -f "$PIP_LOG" 2>/dev/null || true
else
  mm_status "$MM_STEP_DEPS" "Dependencies" "Already up to date" "done"
fi
mm_bail_if_cancelled

# pywebview is optional and only the app window needs it, so it installs
# on demand rather than for everyone. A failure is not fatal - the app
# falls back to a browser tab, and it needs the same timeout treatment as
# the rest of step 2: this can run even when NEED_INSTALL was 0, so it is
# the one bit of network work that isn't skipped just because the venv
# already has everything else.
if [ -n "${MM_DESKTOP:-}" ]; then
  mm_status "$MM_STEP_WINDOW" "Desktop window" "Checking window support" "active"
  echo "        Checking desktop window support..."
  if ! run_with_timeout 20 "$VENV_PY" -m pip install --quiet --timeout 5 --retries 0 pywebview; then
    echo " ${YELLOW}[!]${RESET} pywebview would not install (offline, or a real error) - opening a browser tab instead."
    mm_status "$MM_STEP_WINDOW" "Desktop window" "Not available, using a browser tab" "done"
    unset MM_DESKTOP
  else
    mm_status "$MM_STEP_WINDOW" "Desktop window" "Ready" "done"
  fi
fi

# --- 3. First-run .env ----------------------------------------------
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp ".env.example" ".env"
  echo "        Created .env from .env.example."
else
  echo "        Configuration found."
fi

# --- 4. Launch -------------------------------------------------------
mm_bail_if_cancelled
mm_status "$MM_STEP_START" "Start" "Starting the app" "active"

if [ -n "${MM_DESKTOP:-}" ]; then
  echo "        MemoryMap AI is opening in its own window."
  echo "        Close the window to stop it."
  echo
  echo " ${TEAL}Installed at:${RESET} $(pwd)"
  echo " ${TEAL}Your notes:${RESET}   $MM_DATA_DIR"
  echo " ${TEAL}Next time:${RESET}    open a terminal there and run ./start-desktop.sh again"
  echo
  mm_splash_done
  exec "$VENV_PY" -m memorymap --desktop
fi

echo "        MemoryMap AI is at $MM_URL"
if [ "$MM_NO_BROWSER" = "1" ]; then
  echo "        No browser will be opened (--no-browser). Press Ctrl+C to stop."
else
  echo "        A browser tab opens in a moment. Press Ctrl+C to stop."
fi
echo
# Asked for directly: "guide the user to where the application location is
# and what files to run" - a fresh install is easy to lose track of once the
# terminal window closes and there's no shortcut or icon involved. $(pwd) is
# safe here specifically because of the `cd "$(dirname "$0")"` at the top of
# this script - it is always this script's own folder, not wherever the
# terminal happened to be launched from.
echo " ${TEAL}Installed at:${RESET} $(pwd)"
echo " ${TEAL}Your notes:${RESET}   $MM_DATA_DIR"
echo " ${TEAL}Next time:${RESET}    open a terminal there and run ./start.sh again"
echo

if [ "$MM_NO_BROWSER" = "0" ]; then
  (
    sleep 3
    if command -v open >/dev/null 2>&1; then open "$MM_URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$MM_URL"
    fi
  ) >/dev/null 2>&1 &
fi

# The last step, ticked. In desktop mode this line is deliberately absent:
# the Python loading window inherits the same file and owns the Start step
# until the server answers, so ticking it here would put two Starts in one
# list. In browser mode nothing else narrates it, and leaving it active was
# why the splash, the terminal and the log all ended one step short of their
# own total, reported as a bar that "only ever goes to 3/5 and then it
# loads". The launcher really has finished: the exec is the next line.
mm_status "$MM_STEP_START" "Start" "Handed over to the app" "done"

# Nothing else is coming in browser mode - the tab is the app - so the
# splash file goes here rather than being handed on to a Python window that
# will never open.
[ -n "${MM_SPLASH_FILE:-}" ] && rm -f "$MM_SPLASH_FILE" 2>/dev/null
mm_splash_done

exec "$VENV_PY" -m memorymap
