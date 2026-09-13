#!/usr/bin/env bash
# Start the stand-in OpenAI server (scratchpad/fake_openai_server.py) detached,
# on its own port, with its log beside the sweep's data dir.
#
#   scratchpad/ui-sweeps/fake.sh 8879 /tmp/mm-chat-b
#
# `setsid`, not `&`, for the same reason serve.sh uses it (CLAUDE.md section 5).
set -euo pipefail
PORT="${1:?port}"; DIR="${2:?log dir}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${VENV:-/home/user/MemoryMap-AI/.venv}"
mkdir -p "$DIR"
if curl -s -o /dev/null "http://127.0.0.1:$PORT/v1/models"; then
  echo "something already answers on :$PORT" >&2; exit 1
fi
cd "$ROOT"
setsid "$VENV/bin/python" scratchpad/fake_openai_server.py --port "$PORT" \
  > "$DIR/fake-$PORT.log" 2>&1 < /dev/null &
for _ in $(seq 1 20); do
  sleep 0.5
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/v1/models"; then
    echo "fake model server on http://127.0.0.1:$PORT/v1 (log $DIR/fake-$PORT.log)"; exit 0
  fi
done
echo "fake server did not come up; see $DIR/fake-$PORT.log" >&2; exit 1
