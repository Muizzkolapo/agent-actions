"""Run the tool call of a ``kind: mcp`` action for one record."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_actions.config.path_config import load_project_config, resolve_project_root
from agent_actions.errors import AgentActionsError, ConfigurationError
from agent_actions.llm.providers.mcp.session import POOL, McpError, result_records
from agent_actions.llm.providers.tools.builtin import field_value

SERVERS_KEY = "mcp_servers"
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def declared_servers(project_root: Path) -> dict[str, Any]:
    """The ``mcp_servers:`` block of agent_actions.yml, each name to its settings."""
    declared = load_project_config(project_root).get(SERVERS_KEY) or {}
    if not isinstance(declared, dict):
        raise ConfigurationError(
            f"'{SERVERS_KEY}:' in agent_actions.yml must map each server name to its settings."
        )
    return declared


def server_settings(name: str, project_root: Path) -> dict[str, Any]:
    """How to start MCP server *name*: its command, arguments, environment and folder.

    A ``${NAME}`` in an argument or an environment value is read from the environment,
    so a credential never has to be written in the project.
    """
    declared = declared_servers(project_root)
    raw = declared.get(name)
    if not isinstance(raw, dict):
        known = ", ".join(sorted(declared)) or "none"
        raise ConfigurationError(
            f"No MCP server named '{name}' in agent_actions.yml (declared: {known}). "
            f"Declare it under '{SERVERS_KEY}:' with a command.",
            context={"server": name},
        )
    unknown = sorted(set(raw) - {"command", "args", "env", "cwd"})
    if unknown:
        raise ConfigurationError(
            f"MCP server '{name}' takes no {', '.join(unknown)}; it takes command, args, "
            "env and cwd.",
            context={"server": name},
        )
    command = raw.get("command")
    if not isinstance(command, str) or not command:
        raise ConfigurationError(
            f"MCP server '{name}' needs 'command': the program that starts it, such as uvx.",
            context={"server": name},
        )
    args = raw.get("args") or []
    env = raw.get("env") or {}
    if not isinstance(args, list) or not isinstance(env, dict):
        raise ConfigurationError(
            f"MCP server '{name}': 'args' is a list and 'env' maps names to values.",
            context={"server": name},
        )
    cwd = raw.get("cwd")
    return {
        "command": _expanded(command, name),
        "args": [_expanded(str(arg), name) for arg in args],
        "env": {str(key): _expanded(str(value), name) for key, value in env.items()},
        "cwd": project_root / cwd if isinstance(cwd, str) else project_root,
    }


def _expanded(text: str, server: str) -> str:
    def value(match: re.Match[str]) -> str:
        found = os.environ.get(match.group(1))
        if found is None:
            raise ConfigurationError(
                f"MCP server '{server}' reads ${{{match.group(1)}}}, which is not set in "
                "the environment (or .env).",
                context={"server": server, "variable": match.group(1)},
            )
        return found

    return _VARIABLE.sub(value, text)


def arguments_for(spec: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """The tool's arguments for one record: each reference read from the record."""
    found: dict[str, Any] = {}
    for name, ref in spec["arguments"].items():
        if isinstance(ref, dict):
            found[name] = ref.get("value")
        else:
            found[name] = field_value(data, ref, "; observe it on the action")
    return found


def called(spec: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """What tool ``spec['name']`` of server ``spec['server']`` answers for one record.

    One object is the output as it is; anything else is kept under ``result``.
    """
    project_root = resolve_project_root(None)
    settings = server_settings(spec["server"], project_root)
    try:
        session = POOL.get(spec["server"], settings, settings["cwd"])
        result = session.call_tool(spec["name"], arguments_for(spec, data))
    except McpError as error:
        # A failed call fails the record, as an exception of a UDF does.
        raise AgentActionsError(
            str(error),
            context={"server": spec["server"], "tool": spec["name"], "operation": "mcp_call"},
            cause=error,
        ) from error
    records = result_records(result)
    return records[0] if len(records) == 1 else {"result": records}
