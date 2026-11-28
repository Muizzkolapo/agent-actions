"""An MCP server over stdio for tests: `lookup` answers per ticket, `broken` fails.

Each call is appended to the file `FAKE_MCP_LOG` names, so a test sees what was called.
"""

import json
import os
import sys

from agent_actions.tooling.mcp.server import INVALID_PARAMS, McpServer, RpcError

TOOLS = [
    {"name": "lookup", "description": "The owner of a ticket", "inputSchema": {"type": "object"}},
    {"name": "broken", "description": "Always fails", "inputSchema": {"type": "object"}},
]


def _call(params: dict) -> dict:
    name, arguments = params.get("name"), params.get("arguments") or {}
    log = os.environ.get("FAKE_MCP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": name, "arguments": arguments}) + "\n")
    if name == "lookup":
        found = {"owner": f"team-{arguments.get('ticket')}", "tier": arguments.get("tier", "?")}
        return {
            "content": [{"type": "text", "text": json.dumps(found)}],
            "structuredContent": found,
        }
    if name == "broken":
        return {"content": [{"type": "text", "text": "the lookup is down"}], "isError": True}
    raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")


def main() -> None:
    server = McpServer()
    server.handle("tools/list", lambda params: {"tools": TOOLS})
    server.handle("tools/call", _call)
    server.serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
