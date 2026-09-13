#!/usr/bin/env bash
# Run every UI sweep against a running app and write the tables to one file,
# so a phase's before/after is one `diff`.
#
#   SCRATCH=<dir> BASE=http://127.0.0.1:8781 scratchpad/ui-sweeps/all.sh [label]
#
# Writes $SCRATCH/sweeps/<label>.txt (label defaults to a timestamp) and
# prints the path. Needs the app running (CLAUDE.md has the setsid recipe)
# and Chromium at $PLAYWRIGHT_BROWSERS_PATH (default /opt/pw-browsers).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${SCRATCH:-$HERE/../../.sweeps}"
export SCRATCH
export BASE="${BASE:-http://127.0.0.1:8781}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
LABEL="${1:-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$SCRATCH/sweeps"
OUT="$SCRATCH/sweeps/$LABEL.txt"
: > "$OUT"
for sweep in space rows heads buttons borders caps segs; do
  echo "######## $sweep" >> "$OUT"
  if ! node "$HERE/$sweep.js" >> "$OUT" 2>&1; then
    echo "!! $sweep failed" >> "$OUT"
  fi
done

# The component sweeps above measure at their own default width. Phase 9 made
# the widths themselves a design, so the run also records the shell at each
# band boundary: 1440 desktop, 1024 and 820 the two tablet bands, 390 the
# phone. **820 is the one that was missing**, and it was missing because
# nothing was designed for it: it is the width where an iPad in landscape
# meets a small laptop, and where the docks were found wrapping to two rows.
for WIDTH in 1440 1024 820 390; do
  echo "######## shell @ $WIDTH" >> "$OUT"
  if ! WIDTHS="$WIDTH" node "$HERE/chrome.js" >> "$OUT" 2>&1; then
    echo "!! chrome @ $WIDTH failed" >> "$OUT"
  fi
done

echo "######## errors (1440/1024/820/390)" >> "$OUT"
if ! node "$HERE/errors.js" >> "$OUT" 2>&1; then
  echo "!! errors failed" >> "$OUT"
fi

echo "######## touch @ 390" >> "$OUT"
if ! node "$HERE/touch.js" >> "$OUT" 2>&1; then
  echo "!! touch failed" >> "$OUT"
fi

echo "$OUT"
