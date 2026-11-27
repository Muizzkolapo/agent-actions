"""The agent-actions MCP server: its tools, and the bundled skills as resources."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path, PurePosixPath
from typing import Any

from agent_actions.tooling.mcp.server import INVALID_PARAMS, McpServer, RpcError
from agent_actions.tooling.mcp.tools import (
    TOOLS,
    Context,
    ToolRefused,
    call_tool,
    list_workflows,
    tools_by_name,
)

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
RESOURCE_SCHEME = "agac://skills/"
PROJECT_SCHEME = "agac://project/"
# What defines a workflow, by where it sits in a project. Never `.env` or stored data.
PROJECT_FILES = (
    "agent_actions.yml",
    "sandbox*.yml",
    "sandbox_expected*.yml",
    "agent_workflow/*/agent_config/*.y*ml",
    "prompt_store/*.md",
    "schema/**/*.y*ml",
    "branches/*.y*ml",
    "templates/**/*.j*2",
    "tools/**/*.py",
)

LIST_WORKFLOWS = {
    "name": "list_workflows",
    "description": (
        "The workflows of this project: each name and its config file. Call it first "
        "to learn the names the other tools take."
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True},
}

INSTRUCTIONS = """\
This server runs the `agac` CLI of Agent Actions, a framework for LLM workflows defined in \
YAML, in one project.

How to work:
1. Call list_workflows, then inspect_workflow to validate a workflow before any run.
2. Run in the sandbox first (run_workflow, where sandbox is true by default). A sandbox \
run calls no model and costs nothing: the offline mock answers each LLM action with data \
that matches its schema, tool actions run their own code, and the output is kept apart \
from real output. It tests the wiring, not prompt quality.
3. Read the result with workflow_status, dispositions, records, traces and usage. They \
read sandbox output by default; pass sandbox=false to read what real runs stored.
4. Test failure paths with scenario="chaos", and assert a run with sandbox_check.
5. To answer some records again after a full run, use run_workflow with rerun plus where \
or records, and dry_run first to see the count.
6. A real run (sandbox=false) calls models and costs money. The server refuses it unless \
it was started with --allow-real-runs. Ask the person before you make one.

Exit codes of a run or a retry: 0 success, 3 finished with failed or exhausted records \
(repair with retry_workflow), 4 paused for a batch (call run_workflow again), 1 failed, \
2 usage error, 5 stopped by a provider's quota.

The resources are the files that define this project's workflows (agac://project/...: \
the config, prompts, schemas, tools and sandbox scenario) and the bundled skill guides \
(agac://skills/...: how to write a workflow, context scope, guards, expectations, \
operations and sandbox testing). Read a guide before you write or change a workflow. \
The guides show shell commands: each `agac` command has the tool of the same purpose \
here (the agac-operations guide lists them). This server cannot run the guides' \
scripts/*.py or write a file: check output counts with dispositions and records, and tell \
the person what to change in a workflow.
"""


def build_server(context: Context) -> McpServer:
    """An MCP server whose tools act on the project of *context*."""
    server = McpServer(instructions=INSTRUCTIONS)
    tools = tools_by_name()

    def list_tools(params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": [LIST_WORKFLOWS, *(tool.schema() for tool in TOOLS)]}

    def call(params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise RpcError(INVALID_PARAMS, "'arguments' must be an object")
        if name == "list_workflows":
            found = list_workflows(context.project_root)
            text = (
                json.dumps(found, indent=1)
                if found
                else (
                    f"No workflow in {context.project_root}: it holds no "
                    "agent_workflow/<name>/agent_config/<name>.yml"
                )
            )
            return _text(text, is_error=False)
        tool = tools.get(str(name))
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            outcome = call_tool(tool, arguments, context)
        except ToolRefused as refused:
            # A refusal is the tool's answer, which the model can read and act on.
            return _text(str(refused), is_error=True)
        return _text(outcome.text, is_error=outcome.is_error)

    server.handle("tools/list", list_tools)
    server.handle("tools/call", call)

    def list_resources(params: dict[str, Any]) -> dict[str, Any]:
        return {"resources": [*_project_resources(context.project_root), *_skill_resources()]}

    def read_resource(params: dict[str, Any]) -> dict[str, Any]:
        uri = str(params.get("uri"))
        path = _project_file(context.project_root, uri) or _skill_files().get(uri)
        if path is None:
            raise RpcError(INVALID_PARAMS, f"Unknown resource: {uri}")
        kind = "text/markdown" if path.suffix == ".md" else "text/plain"
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"contents": [{"uri": uri, "mimeType": kind, "text": text}]}

    server.handle("resources/list", list_resources)
    server.handle("resources/read", read_resource)
    return server


def _text(text: str, *, is_error: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _skill_files() -> dict[str, Path]:
    """Each bundled skill guide, by the URI it is read under."""
    files: dict[str, Path] = {}
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")) + sorted(
        SKILLS_DIR.glob("*/references/*.md")
    ):
        files[RESOURCE_SCHEME + path.relative_to(SKILLS_DIR).as_posix()] = path
    return files


def _skill_resources() -> list[dict[str, str]]:
    resources = []
    for uri, path in _skill_files().items():
        skill = path.relative_to(SKILLS_DIR).parts[0]
        title = path.stem if path.name != "SKILL.md" else skill
        resources.append(
            {
                "uri": uri,
                "name": title,
                "description": f"Agent Actions guide: {skill} / {path.name}",
                "mimeType": "text/markdown",
            }
        )
    return resources


def _project_files(root: Path) -> dict[str, Path]:
    """The files that define the project's workflows, by the URI each is read under.

    Listed, never resolved from a URI, so a read cannot leave the project or reach
    a file that is not one of these.
    """
    files: dict[str, Path] = {}
    for pattern in PROJECT_FILES:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and _not_linked(root, path):
                files[PROJECT_SCHEME + path.relative_to(root).as_posix()] = path
    return files


def _project_file(root: Path, uri: str) -> Path | None:
    """The project file *uri* names, when it is one `resources/list` would list."""
    if not uri.startswith(PROJECT_SCHEME):
        return None
    relative = PurePosixPath(uri[len(PROJECT_SCHEME) :])
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = root.joinpath(*relative.parts)
    if not any(_matches(relative.parts, pattern.split("/")) for pattern in PROJECT_FILES):
        return None
    return path if path.is_file() and _not_linked(root, path) else None


def _matches(parts: tuple[str, ...], pattern: list[str]) -> bool:
    """Whether a relative path matches a glob pattern, as `Path.glob` reads it."""
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(_matches(parts[skip:], pattern[1:]) for skip in range(len(parts) + 1))
    return (
        bool(parts)
        and fnmatch.fnmatchcase(parts[0], pattern[0])
        and _matches(parts[1:], pattern[1:])
    )


def _not_linked(root: Path, path: Path) -> bool:
    """Whether *path* is the file it names: no symlink on the way can point elsewhere."""
    try:
        return path.resolve().relative_to(root.resolve()) == path.relative_to(root)
    except ValueError:
        return False


def _project_resources(root: Path) -> list[dict[str, str]]:
    return [
        {
            "uri": uri,
            "name": path.relative_to(root).as_posix(),
            "description": "A file of this project",
            "mimeType": "text/markdown" if path.suffix == ".md" else "text/plain",
        }
        for uri, path in _project_files(root).items()
    ]
