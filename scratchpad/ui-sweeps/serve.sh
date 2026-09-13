#!/usr/bin/env bash
# Start one MemoryMap server with its OWN data dir and log, detached.
#
#   scratchpad/ui-sweeps/serve.sh 8797 /tmp/mm-map3
#
# Why this exists (HANDOVER.md, "Traps found this session"): two servers on
# one SQLite file — a subagent's and the parent's — produced `no such table`
# and `Could not refresh instance` 500s hours later, from a connection pool
# split across two inodes. Every server gets its own directory here, and the
# log goes beside the data so a traceback can never land in someone else's
# file. `setsid`, not `&`: `pkill -f uvicorn` kills your own shell otherwise
# (CLAUDE.md). Run from the checkout whose code you want served.
set -euo pipefail
PORT="${1:?port}"; DIR="${2:?data dir}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${VENV:-/home/user/MemoryMap-AI/.venv}"
mkdir -p "$DIR"
if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "something already answers on :$PORT — pick another port" >&2; exit 1
fi
cd "$ROOT"
setsid env PYTHONPATH=src MEMORYMAP_DATA_DIR="$DIR" "$VENV/bin/python" -m uvicorn \
  memorymap.api.app:create_app --factory --port "$PORT" > "$DIR/server.log" 2>&1 < /dev/null &
for _ in $(seq 1 40); do
  sleep 0.5
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
    echo "serving $ROOT on http://127.0.0.1:$PORT (data $DIR, log $DIR/server.log)"; exit 0
  fi
done
echo "server did not come up; see $DIR/server.log" >&2; exit 1
