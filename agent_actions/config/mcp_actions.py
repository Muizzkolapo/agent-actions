"""Load ``kind: mcp`` actions: each becomes a built-in tool action that calls an MCP server.

``server`` names an entry of ``mcp_servers:`` in agent_actions.yml, ``tool`` the tool
to call, and ``arguments`` maps each argument to a field reference (``<action>.<field>``)
or to a constant (``{value: ...}``). The action then routes as a RECORD tool action does:
online, one record at a time, with an output schema.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from agent_actions.config.path_config import resolve_project_root
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin import BUILTIN_KEY, MCP

MCP_KIND = "mcp"
MCP_IMPL = f"agac.{MCP}"
# The keys only a `kind: mcp` action takes.
MCP_KEYS = ("server", "tool", "arguments")
_REF = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+\Z")


def is_mcp_action(entry: Any) -> bool:
    return isinstance(entry, dict) and str(entry.get("kind") or "").lower() == MCP_KIND


def expand_mcp_actions(data: Any, workflow_file: str, project_root: Path | None = None) -> Any:
    """*data* with each ``kind: mcp`` action written as the built-in tool action it runs."""
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return data
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    if str(defaults.get("kind") or "").lower() == MCP_KIND:
        raise ConfigurationError(
            f"defaults in {workflow_file}: 'kind: mcp' names one server tool per action; "
            "set it on each action."
        )
    if not any(is_mcp_action(entry) for entry in actions):
        return data
    from agent_actions.llm.providers.mcp.client import declared_servers

    servers = declared_servers(resolve_project_root(project_root))
    names = {e["name"] for e in actions if isinstance(e, dict) and isinstance(e.get("name"), str)}
    data = copy.deepcopy(data)
    data["actions"] = [
        _tool_action(entry, servers, names | {"source"}, workflow_file)
        if is_mcp_action(entry)
        else entry
        for entry in data["actions"]
    ]
    return data


def _tool_action(
    entry: dict[str, Any], servers: dict[str, Any], names: set[str], workflow_file: str
) -> dict[str, Any]:
    where = f"Action '{entry.get('name')}' in {workflow_file}"
    server = entry.get("server")
    if not isinstance(server, str) or not server:
        raise ConfigurationError(f"{where}: a 'kind: mcp' action needs 'server:'.")
    if server not in servers:
        known = ", ".join(sorted(servers)) or "none"
        raise ConfigurationError(
            f"{where}: no MCP server named '{server}' in agent_actions.yml "
            f"(declared: {known}). Declare it under 'mcp_servers:' with a command.",
            context={"server": server},
        )
    tool = entry.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ConfigurationError(f"{where}: a 'kind: mcp' action needs 'tool:', the tool to call.")
    for key, why in (
        ("impl", "the server's tool is named by 'tool:'"),
        ("prompt", "it calls a tool, not a model"),
        (BUILTIN_KEY, "agac writes it"),
    ):
        if key in entry:
            raise ConfigurationError(f"{where}: a 'kind: mcp' action takes no '{key}': {why}.")
    if str(entry.get("granularity") or "record").lower() != "record":
        raise ConfigurationError(
            f"{where}: a 'kind: mcp' action calls its tool once for each record, so its "
            "granularity is Record."
        )
    if str(entry.get("run_mode") or "online").lower() != "online":
        raise ConfigurationError(f"{where}: a 'kind: mcp' action runs online, not in a batch.")
    arguments = _arguments(entry.get("arguments"), names, where)
    action = {key: value for key, value in entry.items() if key not in MCP_KEYS}
    action.update(
        {
            "kind": "tool",
            "impl": MCP_IMPL,
            "granularity": "record",
            BUILTIN_KEY: {"tool": MCP, "server": server, "name": tool, "arguments": arguments},
        }
    )
    refs = [ref for ref in arguments.values() if isinstance(ref, str)]
    if refs:
        scope = dict(action.get("context_scope") or {})
        observe = list(scope.get("observe") or [])
        scope["observe"] = [*observe, *(ref for ref in refs if ref not in observe)]
        action["context_scope"] = scope
    return action


def _arguments(raw: Any, names: set[str], where: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"{where}: 'arguments:' maps each argument of the tool to a field reference, "
            "such as source.table, or to {value: <constant>}."
        )
    found: dict[str, Any] = {}
    for name, value in raw.items():
        label = f"{where}: 'arguments: {{{name}: ...}}'"
        if isinstance(value, dict):
            if set(value) != {"value"}:
                raise ConfigurationError(
                    f"{label} must be a field reference or {{value: <constant>}}."
                )
            found[str(name)] = {"value": value["value"]}
        elif isinstance(value, str) and _REF.match(value) and value.split(".")[0] in names:
            found[str(name)] = value
        else:
            found[str(name)] = {"value": value}
    return found
