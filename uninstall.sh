#!/usr/bin/env bash
# ====================================================================
#  MemoryMap AI - uninstaller for macOS / Linux
#
#  Removes the virtual environment (.venv) that start.sh built, plus the
#  caches that came with it, so the app stops being runnable from this
#  folder. Your notes live in a separate data directory and are NEVER
#  touched unless you explicitly pass --delete-data.
#
#  Flags: see `./uninstall.sh --help`. uninstall.bat takes the same set
#  in the same order, the same way start.sh and start.bat do.
#
#  This script does not delete the project folder itself (the source
#  code and this script). Delete the folder by hand afterwards if you
#  want it gone completely - re-running start.sh at any point rebuilds
#  .venv and picks up right where you left off, notes included.
# ====================================================================
set -e
cd "$(dirname "$0")"

if [ -t 1 ]; then
  TEAL=$'\033[1;38;5;73m'
  RED=$'\033[1;31m'
  YELLOW=$'\033[1;33m'
  RESET=$'\033[0m'
else
  TEAL="" ; RED="" ; YELLOW="" ; RESET=""
fi

# --- Where the data actually is --------------------------------------
# The same precedence start.sh uses, and for the same reason: this script
# has to be able to name, measure and (only if asked) delete the right
# folder on a machine where MEMORYMAP_DATA_DIR moved the notebook
# somewhere else entirely.
DATA_DIR="${MEMORYMAP_DATA_DIR:-}"
if [ -z "$DATA_DIR" ] && [ -f ".env" ]; then
  DATA_DIR="$(grep -E '^MEMORYMAP_DATA_DIR=' ".env" 2>/dev/null | tail -n 1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
fi
[ -n "$DATA_DIR" ] || DATA_DIR="data"

MM_PORT="${MEMORYMAP_PORT:-8000}"

# --- Flags -----------------------------------------------------------
DRY_RUN=0
DELETE_DATA=0
SHORTCUTS=0
ASSUME_YES=0
EXPORT_TO=""
EXPORT_MISSING=0
BAD_FLAG=""

mm_help() {
  cat <<MM_HELP
MemoryMap AI uninstaller

Usage: ./uninstall.sh [options]

  --dry-run       List what would be removed, with sizes, and change nothing
  --export PATH   Write your notes to PATH as a Markdown zip first
  --delete-data   Also delete your notes and .env (asks separately)
  --shortcuts     Also remove the desktop shortcut start.sh --shortcut made
  --yes           Skip the "remove .venv?" prompts
  --help          Show this message and exit

Your notes are never deleted unless you pass --delete-data AND then type
DELETE at its own confirmation prompt - --yes does not skip that one.

Your notes: $DATA_DIR

This does not delete the project folder itself. Re-run ./start.sh any
time afterwards to reinstall and pick up right where you left off.
MM_HELP
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    # `--export` with nothing after it, or with the next flag after it, used
    # to be silently ignored: the uninstall then ran and removed .venv, and
    # the export someone asked for never happened. Now it stops.
    --export)
      shift
      EXPORT_TO="${1:-}"
      case "$EXPORT_TO" in
        ""|-*) EXPORT_MISSING=1; EXPORT_TO="" ;;
      esac
      ;;
    --export=*)
      EXPORT_TO="${1#*=}"
      [ -n "$EXPORT_TO" ] || EXPORT_MISSING=1
      ;;
    --delete-data) DELETE_DATA=1 ;;
    --shortcuts) SHORTCUTS=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) mm_help; exit 0 ;;
    "") ;;
    *) BAD_FLAG="$1" ;;
  esac
  # `shift || break`, not a bare `shift`: a flag that takes a value shifts
  # once inside its own branch, so `--port` or `--export` typed as the last
  # argument leaves nothing for this one to consume. Under `set -e` at the
  # top of this script, that failing shift killed the launcher outright with
  # exit 1 and no message, instead of reaching the validation below that
  # prints the help and exits 2.
  shift || break
done

# Exit 2 for a typo, the same code start.sh uses, so a wrapper script can
# tell "you typed it wrong" apart from "the uninstall failed".
if [ -n "$BAD_FLAG" ]; then
  echo "Unknown option: $BAD_FLAG"
  echo
  mm_help
  exit 2
fi

if [ "$EXPORT_MISSING" = "1" ]; then
  echo "--export needs a path: ./uninstall.sh --export ~/my-notes.zip"
  echo
  mm_help
  exit 2
fi

# --- Sizes ------------------------------------------------------------
# Printed before and after, because "removed .venv" means nothing next to
# "freed 412M": the reason someone runs an uninstaller is usually space.
mm_size() {
  [ -e "$1" ] || { echo "not present"; return 0; }
  du -sh "$1" 2>/dev/null | awk '{print $1}' || echo "unknown"
}

mm_size_kb() {
  # Always a bare integer: this feeds $(( )) arithmetic, where an empty
  # string or a "-" is a syntax error rather than a zero.
  [ -e "$1" ] || { echo 0; return 0; }
  local kb
  kb="$(du -sk "$1" 2>/dev/null | awk 'NR==1 {print $1}')"
  case "$kb" in
    ''|*[!0-9]*) echo 0 ;;
    *) echo "$kb" ;;
  esac
}

mm_human_kb() {
  # A whole number of MB or GB. `du -sh` cannot be summed, so the total
  # has to be worked out in KB and formatted here.
  local kb="${1:-0}"
  if [ "$kb" -ge 1048576 ]; then
    echo "$((kb / 1048576)) GB"
  elif [ "$kb" -ge 1024 ]; then
    echo "$((kb / 1024)) MB"
  else
    echo "$kb KB"
  fi
}

# --- Is the app running? ----------------------------------------------
# Deleting .venv out from under a live server leaves a process with no
# interpreter files, a half-working app and a support message that makes
# no sense. The same two-part check start.sh does: is the port busy, and
# is it busy with us. Only "busy with us" stops this script; a stranger on
# the port is none of an uninstaller's business.
mm_port_open() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

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

echo "${TEAL}MemoryMap AI - uninstall${RESET}"
echo

if mm_port_open "$MM_PORT" && mm_port_is_memorymap "$MM_PORT"; then
  echo " ${RED}[x]${RESET} MemoryMap is still running on port $MM_PORT."
  echo "        Close the app window, or press Ctrl+C in the terminal running it,"
  echo "        then run this again. Nothing was changed."
  exit 1
fi

# --- What would go ----------------------------------------------------
# One list, built once, used by both the dry run and the real run, so the
# two can never disagree about what is about to happen.
#
# The caches go with .venv rather than being left behind: __pycache__ is
# bytecode for an interpreter that is about to stop existing, and
# .venv/.mm_installed is the marker start.sh reads to decide whether a
# reinstall is needed - leaving it would be harmless only because .venv
# goes with it.
CACHE_PATHS=""
for path in "__pycache__" ".pytest_cache" ".ruff_cache"; do
  if [ -e "$path" ]; then
    CACHE_PATHS="$CACHE_PATHS $path"
  fi
done
# Bytecode under src/ and tests/ as well as the top level, which is where
# most of it actually is.
NESTED_PYCACHE="$(find . -type d -name "__pycache__" -not -path "./.venv/*" 2>/dev/null | head -200 || true)"

SHORTCUT_PATHS=""
if [ "$SHORTCUTS" = "1" ]; then
  # Exactly the paths ./start.sh --shortcut writes, and nothing else: an
  # uninstaller that guesses at desktop files is one that deletes somebody
  # else's launcher.
  for path in "$HOME/.local/share/applications/memorymap-ai.desktop" \
              "$HOME/Desktop/memorymap-ai.desktop" \
              "$HOME/Desktop/MemoryMap AI"; do
    # -L as well as -e: the macOS fallback is a symlink, and a symlink
    # whose target is already gone fails -e while still being a file on
    # someone's Desktop.
    if [ -e "$path" ] || [ -L "$path" ]; then
      SHORTCUT_PATHS="$SHORTCUT_PATHS
$path"
    fi
  done
fi

BEFORE_KB=0
BEFORE_KB=$((BEFORE_KB + $(mm_size_kb ".venv")))
for path in $CACHE_PATHS; do
  BEFORE_KB=$((BEFORE_KB + $(mm_size_kb "$path")))
done
# The bytecode folders under src/ and tests/ count too: on a checkout that
# has run the suite they are most of what a "freed" figure is made of.
if [ -n "$NESTED_PYCACHE" ]; then
  while read -r path; do
    [ -n "$path" ] || continue
    BEFORE_KB=$((BEFORE_KB + $(mm_size_kb "$path")))
  done <<NESTED_LIST
$NESTED_PYCACHE
NESTED_LIST
fi
DATA_KB="$(mm_size_kb "$DATA_DIR")"

# One column width for every row, set by printf rather than by counting
# spaces: a data directory path can be any length, and a hand-padded
# column silently turns into a ragged one the first time it is long.
mm_line() {
  printf '   %-28s %s\n' "$1" "$2"
}

echo " Would remove:"
if [ -d ".venv" ]; then
  mm_line ".venv" "$(mm_size ".venv")"
else
  mm_line ".venv" "not present"
fi
for path in $CACHE_PATHS; do
  mm_line "$path" "$(mm_size "$path")"
done
if [ -n "$NESTED_PYCACHE" ]; then
  mm_line "__pycache__ folders" "$(echo "$NESTED_PYCACHE" | wc -l | tr -d ' ') under this folder"
fi
if [ "$SHORTCUTS" = "1" ]; then
  if [ -n "$SHORTCUT_PATHS" ]; then
    echo "$SHORTCUT_PATHS" | sed '/^$/d' | while read -r path; do
      mm_line "shortcut" "$path"
    done
  else
    mm_line "shortcut" "none found"
  fi
fi
if [ "$DELETE_DATA" = "1" ]; then
  mm_line "$DATA_DIR" "$(mm_size "$DATA_DIR")  ${RED}your notes${RESET}"
  mm_line ".env" "settings"
else
  echo
  echo " ${TEAL}[kept]${RESET} Your notes in $DATA_DIR, $(mm_size "$DATA_DIR"). Pass --delete-data to remove them."
  echo " ${TEAL}[kept]${RESET} .env, so a reinstall finds your settings again."
fi
echo
echo " That frees about $(mm_human_kb "$BEFORE_KB")."

if [ "$DRY_RUN" = "1" ]; then
  echo
  echo " ${TEAL}[dry run]${RESET} Nothing was changed. Run without --dry-run to do it."
  exit 0
fi

# --- Export first -----------------------------------------------------
# Before anything is removed, and before the confirmation prompts, because
# an export that runs after .venv is gone has no interpreter to run in.
if [ -n "$EXPORT_TO" ]; then
  echo
  if [ ! -x ".venv/bin/python" ]; then
    echo " ${RED}[x]${RESET} Cannot export: .venv is already gone, so there is no Python to run."
    echo "        Run ./start.sh once to rebuild it, export, then uninstall."
    exit 1
  fi
  echo " ${TEAL}[..]${RESET} Exporting your notes to $EXPORT_TO..."
  if ! .venv/bin/python -m memorymap --export "$EXPORT_TO"; then
    echo " ${RED}[x]${RESET} The export failed, so nothing was removed."
    exit 1
  fi
fi

# A double-click (or a typo for start.sh) shouldn't be able to reach the
# actual removal steps below without a clear, explicit "yes" first -
# asked for directly. This is separate from, and in addition to, the
# per-step confirmations further down.
if [ "$ASSUME_YES" != "1" ]; then
  echo
  read -r -p "Continue? [y/N] " reply
  case "$reply" in
    y|Y) ;;
    *)
      echo "Cancelled - nothing was changed."
      exit 0
      ;;
  esac
  echo
fi

confirm() {
  # $1 = prompt. Returns success (0) only on an explicit "y".
  [ "$ASSUME_YES" = "1" ] && return 0
  local reply
  read -r -p "$1 [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ]
}

# --- 1. Remove the virtual environment and its caches -----------------
if [ -d ".venv" ]; then
  if confirm "Remove the .venv folder, all installed dependencies?"; then
    rm -rf ".venv"
    echo " ${TEAL}[done]${RESET} Removed .venv."
  else
    echo " ${YELLOW}[skipped]${RESET} .venv left in place."
  fi
else
  echo " ${TEAL}[skip]${RESET} No .venv found - nothing to remove there."
fi

for path in $CACHE_PATHS; do
  rm -rf "$path" 2>/dev/null || true
done
if [ -n "$NESTED_PYCACHE" ]; then
  echo "$NESTED_PYCACHE" | while read -r path; do
    [ -n "$path" ] && rm -rf "$path" 2>/dev/null || true
  done
fi
echo " ${TEAL}[done]${RESET} Removed the build caches."

# --- 2. The shortcuts -------------------------------------------------
if [ "$SHORTCUTS" = "1" ]; then
  if [ -n "$SHORTCUT_PATHS" ]; then
    echo "$SHORTCUT_PATHS" | sed '/^$/d' | while read -r path; do
      rm -f "$path" 2>/dev/null || true
      echo " ${TEAL}[done]${RESET} Removed $path"
    done
  else
    echo " ${TEAL}[skip]${RESET} No shortcut found to remove."
  fi
fi

# --- 3. Your notes: opt-in only, asked again even with --yes unless -----
#        --delete-data was passed explicitly. A stray "uninstall" is not
#        consent to lose a notebook.
if [ "$DELETE_DATA" = "1" ]; then
  if [ -d "$DATA_DIR" ]; then
    echo
    echo " ${RED}This deletes your notes, documents, images and settings in:${RESET}"
    echo "   $(cd "$DATA_DIR" 2>/dev/null && pwd || echo "$DATA_DIR")"
    read -r -p " Type DELETE to confirm: " reply
    if [ "$reply" = "DELETE" ]; then
      rm -rf "$DATA_DIR"
      # .env goes with the notes and not before them: it carries the path
      # to the notebook and the settings that reach it, so removing it
      # while the notes survive is how someone loses track of where their
      # own notes are.
      rm -f ".env" 2>/dev/null || true
      echo " ${TEAL}[done]${RESET} Deleted $DATA_DIR and .env."
    else
      echo " ${YELLOW}[skipped]${RESET} Data left in place - confirmation text didn't match."
    fi
  else
    echo " ${TEAL}[skip]${RESET} No data directory found at $DATA_DIR."
  fi
fi

# --- Sizes after ------------------------------------------------------
AFTER_KB=0
AFTER_KB=$((AFTER_KB + $(mm_size_kb ".venv")))
for path in $CACHE_PATHS; do
  AFTER_KB=$((AFTER_KB + $(mm_size_kb "$path")))
done
FREED_KB=$((BEFORE_KB - AFTER_KB))
# The notes count towards the figure only if they actually went: with
# --delete-data and a typed DELETE this is most of what was freed, and
# reporting "0 KB" after removing a notebook reads as "nothing happened".
if [ "$DELETE_DATA" = "1" ] && [ ! -d "$DATA_DIR" ]; then
  FREED_KB=$((FREED_KB + DATA_KB))
fi
[ "$FREED_KB" -lt 0 ] && FREED_KB=0

echo
echo " ${TEAL}Freed:${RESET} $(mm_human_kb "$FREED_KB")"
if [ "$DELETE_DATA" != "1" ] && [ "$DATA_KB" -gt 0 ]; then
  echo " ${TEAL}Kept:${RESET}  $(mm_human_kb "$DATA_KB") of notes in $DATA_DIR"
fi
echo
echo "Uninstall finished. This folder's source code is still here -"
echo "delete it by hand if you want it fully gone, or run ./start.sh"
echo "any time to reinstall and pick up right where you left off."
