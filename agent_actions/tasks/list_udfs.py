"""
list-udfs command for the Agent Actions CLI.

This module provides the implementation of the 'list-udfs' command,
which displays all discovered UDFs with their metadata.
"""

import click
import json as json_lib
from pathlib import Path
from typing import List, Dict, Any

from rich.console import Console
from rich.table import Table

from agent_actions.core.udf_loader import discover_udfs
from agent_actions.core.udf_registry import list_udfs, clear_registry


class ListUDFsCommand:
    """Implementation of the list-udfs command."""

    def __init__(self, user_code: str, json_output: bool, verbose: bool):
        """
        Initialize the list-udfs command.

        Args:
            user_code: Path to user code directory containing UDFs
            json_output: Whether to output as JSON
            verbose: Whether to show full docstrings and signatures
        """
        self.user_code = Path(user_code)
        self.json_output = json_output
        self.verbose = verbose
        self.console = Console()

    def execute(self) -> None:
        """Execute the list-udfs command."""
        try:
            # Clear registry to ensure fresh discovery
            clear_registry()

            # Discover UDFs
            if not self.json_output:
                self.console.print("[cyan]🔍 Discovering UDFs...[/cyan]")

            registry = discover_udfs(self.user_code)

            if not self.json_output:
                self.console.print(f"[green]✅ Discovered {len(registry)} UDF(s)[/green]\n")

            # Get UDF list
            udfs = list_udfs()

            if not udfs:
                if self.json_output:
                    click.echo(json_lib.dumps([]))
                else:
                    self.console.print("[yellow]No UDFs found in the specified directory.[/yellow]")
                return

            # Output based on format
            if self.json_output:
                self._output_json(udfs)
            else:
                self._output_table(udfs)

        except Exception as e:
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {
                'command': 'list-udfs',
                'user_code': str(self.user_code)
            })
            raise click.ClickException(error_message)

    def _output_json(self, udfs: List[Dict[str, Any]]) -> None:
        """
        Output UDFs as JSON.

        Args:
            udfs: List of UDF metadata dictionaries
        """
        output = []
        for udf in udfs:
            entry = {
                'name': udf['name'],
                'module': udf['module'],
                'file': udf['file'],
                'signature': udf['signature']
            }

            # Add docstring if verbose or if it exists
            if self.verbose or udf.get('docstring'):
                entry['docstring'] = udf.get('docstring') or ''

            output.append(entry)

        click.echo(json_lib.dumps(output, indent=2))

    def _output_table(self, udfs: List[Dict[str, Any]]) -> None:
        """
        Output UDFs as a formatted table.

        Args:
            udfs: List of UDF metadata dictionaries
        """
        table = Table(title="Available User-Defined Functions")
        table.add_column("Function", style="cyan", no_wrap=True)
        table.add_column("Location", style="green")
        table.add_column("File", style="yellow")

        if self.verbose:
            table.add_column("Signature", style="blue")
            table.add_column("Description", style="white")

        for udf in udfs:
            # Get first line of docstring as description
            docstring = udf.get('docstring') or ''
            description = docstring.split('\n')[0].strip() if docstring else ''

            if self.verbose:
                table.add_row(
                    udf['name'],
                    udf['module'],
                    udf['file'],
                    udf['signature'],
                    description
                )
            else:
                # In non-verbose mode, combine file and description in File column
                file_info = udf['file']
                if description:
                    file_info += f"\n{description}"

                table.add_row(
                    udf['name'],
                    udf['module'],
                    file_info
                )

        self.console.print(table)
        self.console.print(f"\n[bold]Total: {len(udfs)} function(s)[/bold]")


@click.command(name='list-udfs')
@click.option('-u', '--user-code', required=True,
              type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help="Path to user code directory containing UDFs")
@click.option('--json', 'json_output', is_flag=True,
              help="Output as JSON for programmatic use")
@click.option('--verbose', is_flag=True,
              help="Show full signatures and docstrings")
def list_udfs_cmd(user_code: str, json_output: bool, verbose: bool) -> None:
    """
    List all discovered User-Defined Functions (UDFs).

    Scans the user code directory for Python files decorated with @udf_tool
    and displays their metadata including location, file path, and documentation.
    """
    command = ListUDFsCommand(user_code, json_output, verbose)
    command.execute()
