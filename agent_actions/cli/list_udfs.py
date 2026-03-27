"""list-udfs command for the Agent Actions CLI."""

import json as json_lib
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.utils.udf_management.registry import clear_registry, list_udfs


class ListUDFsCommand:
    def __init__(self, user_code: str, json_output: bool, verbose: bool):
        self.user_code = Path(user_code)
        self.json_output = json_output
        self.verbose = verbose
        self.console = Console()

    def execute(self) -> None:
        clear_registry()
        if not self.json_output:
            self.console.print("[cyan]🔍 Discovering Tools...[/cyan]")
        registry = discover_udfs(self.user_code)
        if not self.json_output:
            self.console.print(f"[green]✅ Discovered {len(registry)} Tools[/green]\n")
        udfs = list_udfs()
        if not udfs:
            if self.json_output:
                click.echo(json_lib.dumps([]))
            else:
                self.console.print("[yellow]No UDFs found in the specified directory.[/yellow]")
            return
        if self.json_output:
            self._output_json(udfs)
        else:
            self._output_table(udfs)

    def _output_json(self, udfs: list[dict[str, Any]]) -> None:
        output = []
        for udf in udfs:
            entry = {
                "name": udf["name"],
                "module": udf["module"],
                "file": udf["file"],
                "signature": udf["signature"],
            }
            if self.verbose or udf.get("docstring"):
                entry["docstring"] = udf.get("docstring") or ""
            output.append(entry)
        click.echo(json_lib.dumps(output, indent=2))

    def _output_table(self, udfs: list[dict[str, Any]]) -> None:
        table = Table(title="Available User-Defined Functions")
        table.add_column("Function", style="cyan", no_wrap=True)
        table.add_column("Location", style="green")
        table.add_column("File", style="yellow")
        if self.verbose:
            table.add_column("Signature", style="blue")
            table.add_column("Description", style="white")
        for udf in udfs:
            docstring = udf.get("docstring") or ""
            description = docstring.split("\n")[0].strip() if docstring else ""
            if self.verbose:
                table.add_row(
                    udf["name"], udf["module"], udf["file"], udf["signature"], description
                )
            else:
                file_info = udf["file"]
                if description:
                    file_info += f"\n{description}"
                table.add_row(udf["name"], udf["module"], file_info)
        self.console.print(table)
        self.console.print(f"\n[bold]Total: {len(udfs)} function(s)[/bold]")


@click.command(name="list-udfs")
@click.option(
    "-u",
    "--user-code",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to user code directory containing UDFs",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON for programmatic use")
@click.option("--verbose", is_flag=True, help="Show full signatures and docstrings")
@handles_user_errors("list-udfs")
def list_udfs_cmd(user_code: str, json_output: bool, verbose: bool) -> None:
    """
    List all discovered User-Defined Functions (UDFs).

    Scans the user code directory for Python files decorated with @udf_tool
    and displays their metadata including location, file path, and documentation.
    """
    command = ListUDFsCommand(user_code, json_output, verbose)
    command.execute()
