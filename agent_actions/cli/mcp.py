"""MCP command: serve this project to an AI assistant over the Model Context Protocol."""

import io
import sys
from pathlib import Path

import click

from agent_actions.tooling.mcp.app import build_server
from agent_actions.tooling.mcp.tools import DEFAULT_TIMEOUT_SECONDS, Context
from agent_actions.utils.project_root import find_project_root


@click.command()
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="The project to serve (default: the project that holds the current directory)",
)
@click.option(
    "--allow-real-runs",
    is_flag=True,
    default=False,
    help=(
        "Let the assistant make real runs, retries and exports. Without it, every run is a "
        "sandbox run: no model call, no cost, real output untouched"
    ),
)
@click.option(
    "--timeout",
    type=click.IntRange(min=1),
    default=DEFAULT_TIMEOUT_SECONDS,
    show_default=True,
    metavar="SECONDS",
    help="The most one tool call may take",
)
def mcp(project: Path | None, allow_real_runs: bool, timeout: int) -> None:
    """Start an MCP server for this project, on standard input and output.

    An AI assistant (Claude Code, Claude Desktop, Cursor, any MCP client) starts
    this command and calls its tools: list, inspect, run, retry and check a
    workflow, and read its records, dispositions, traces and usage. Each tool
    runs the `agac` command of the same name.

    \b
    Register it with Claude Code, from the project root:
        claude mcp add agac -- agac mcp

    Standard output carries the protocol, so the command prints nothing else on it.
    """
    start = project or Path.cwd()
    found = find_project_root(str(start))
    if found is None:
        raise click.ClickException(
            f"No Agent Actions project at or above {start}: no agent_actions.yml. "
            "Give its folder with --project."
        )
    context = Context(
        project_root=Path(found), allow_real_runs=allow_real_runs, timeout_seconds=timeout
    )
    click.echo(
        f"agac mcp: serving {context.project_root} "
        f"({'real runs allowed' if allow_real_runs else 'sandbox runs only'})",
        err=True,
    )
    # The protocol is UTF-8 whatever the locale, and a line ends with \n alone.
    reader = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    writer = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    build_server(context).serve(reader, writer)
