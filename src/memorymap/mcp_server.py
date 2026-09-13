"""A stdio MCP (Model Context Protocol) server over this app's own tool
registry (ROADMAP.md item 38, ANALYSIS.md §60).

Why expose rather than consume: this app already has a local-process trust
boundary: anyone who can run a process on this machine can already open
`memorymap.db` directly: so a *stdio* server needs no new trust model, it's
the same boundary the app's own SQLite file already sits behind. Consuming
an external MCP server is the harder half (BACKLOG.md §29's missing trust
model for tool calls arriving *from* somewhere else) and is deliberately
not attempted here.

Only non-destructive, currently-enabled tools are offered. `ai.tools`'s own
`destructive` flag exists because a destructive tool needs a human to see
and confirm it before it runs, the chat UI does that with a confirm card
(`agent.py`'s tool loop parks it rather than running it), but a bare
`execute_tool()` call has no such gate built in, and an MCP client (Claude
Desktop, or anything else) has no confirm card to show. So the safe default
here is to never even list `delete_note`/`delete_tag`/`delete_category`/
`delete_document`/`delete_skill`/`merge_categories`, rather than run one
unconfirmed. `tool_enabled()` is reused as-is, so a tool the user turned off
in Settings -> Tools (including the `web_search`/`read_url` online opt-in)
is invisible here too, the same as it already is to the in-app chat model.

Run with `python -m memorymap.mcp_server`, with `MEMORYMAP_DATA_DIR` set the
same way the main app expects, it operates on the same notebook, not a
second one.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from memorymap.ai import tools
from memorymap.core import deps

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "memorymap-ai"
SERVER_VERSION = "0.1.0"


def offered_tools() -> list[tools.ToolSpec]:
    """Every tool this server will list and run: not destructive, and not
    turned off in Settings -> Tools."""
    return [
        spec for spec in tools.TOOLS.values() if not spec.destructive and tools.tool_enabled(spec.name)
    ]


def _tool_list_payload() -> list[dict]:
    return [
        {"name": spec.name, "description": spec.description, "inputSchema": spec.parameters}
        for spec in offered_tools()
    ]


def _call_tool(name: str, arguments: dict) -> dict:
    """Runs one tool call against a fresh session, in MCP's own result
    shape (a `content` list plus `isError`, not this app's own
    `{"error": ...}` convention `execute_tool` returns internally)."""
    if name not in {spec.name for spec in offered_tools()}:
        return {
            "content": [{"type": "text", "text": f"Unknown or unavailable tool '{name}'"}],
            "isError": True,
        }
    session = deps.get_db().session()
    try:
        result = tools.execute_tool(session, name, arguments or {})
    finally:
        session.close()
    is_error = isinstance(result, dict) and "error" in result
    return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": is_error}


def handle_request(message: dict) -> dict | None:
    """One JSON-RPC message in, one response out, or `None` for a
    notification, which gets no reply at all (a bare `id`-less message, per
    JSON-RPC 2.0). Kept pure, no stdio touched here, so the protocol
    logic is directly testable without a real subprocess or a live client.
    """
    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method in ("notifications/initialized", "notifications/cancelled"):
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list_payload()}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = _call_tool(params.get("name", ""), params.get("arguments") or {})
    else:
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method '{method}'"},
        }

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """The stdio loop: one JSON-RPC message per line in, one per line out, 
    MCP's stdio transport, no `Content-Length` framing. A line that isn't
    valid JSON is dropped rather than crashing the server; a client sending
    garbage shouldn't take down an otherwise-working session.
    """
    deps.init_app_state()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
