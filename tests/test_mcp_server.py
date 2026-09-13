"""The stdio MCP server (mcp_server.py, ROADMAP.md item 38).

`handle_request` is pure, no stdio touched, so every case here calls it
directly rather than spawning a subprocess. `serve()`'s own line-reading
loop gets one end-to-end test over real StringIO streams.
"""

from __future__ import annotations

import io
import json

from memorymap.ai import tools
from memorymap.mcp_server import handle_request, offered_tools, serve


def test_offered_tools_excludes_every_destructive_tool():
    names = {spec.name for spec in offered_tools()}
    for spec in tools.TOOLS.values():
        if spec.destructive:
            assert spec.name not in names


def test_offered_tools_excludes_a_tool_disabled_in_settings(app_state):
    from memorymap.core import deps

    deps.get_config().set_preference("disabled_tools", ["count_notes"])
    names = {spec.name for spec in offered_tools()}
    assert "count_notes" not in names


def test_initialize_returns_protocol_info():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["id"] == 1
    assert response["result"]["protocolVersion"]
    assert response["result"]["serverInfo"]["name"] == "memorymap-ai"


def test_a_notification_gets_no_response():
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/cancelled"}) is None


def test_ping():
    response = handle_request({"jsonrpc": "2.0", "id": "abc", "method": "ping"})
    assert response == {"jsonrpc": "2.0", "id": "abc", "result": {}}


def test_an_unknown_method_is_a_json_rpc_error():
    response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "not/a/real/method"})
    assert response["error"]["code"] == -32601


def test_an_unknown_method_notification_gets_no_response():
    assert handle_request({"jsonrpc": "2.0", "method": "not/a/real/method"}) is None


def test_tools_list_shape():
    response = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    listed = response["result"]["tools"]
    assert listed  # the registry is never empty
    for entry in listed:
        assert set(entry) == {"name", "description", "inputSchema"}


def test_tools_call_runs_a_real_tool(app_state):
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "count_notes", "arguments": {}},
        }
    )
    result = response["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert "total" in payload or "count" in payload or isinstance(payload, dict)


def test_tools_call_rejects_an_unknown_tool(app_state):
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "not_a_real_tool", "arguments": {}},
        }
    )
    result = response["result"]
    assert result["isError"] is True
    assert "Unknown or unavailable" in result["content"][0]["text"]


def test_tools_call_rejects_a_destructive_tool_even_by_name(app_state):
    destructive = next(name for name, spec in tools.TOOLS.items() if spec.destructive)
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": destructive, "arguments": {}},
        }
    )
    result = response["result"]
    assert result["isError"] is True


def test_serve_reads_one_line_writes_one_line(app_state):
    request = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    stdin = io.StringIO(request + "\n")
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["result"] == {}


def test_serve_skips_blank_and_malformed_lines(app_state):
    stdin = io.StringIO("\n   \nnot json at all\n" + json.dumps({"jsonrpc": "2.0", "id": 8, "method": "ping"}) + "\n")
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == 8
