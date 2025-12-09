"""
Documentation commands for agent-actions CLI.

Provides commands for generating and serving interactive workflow documentation.
"""
import click
from pathlib import Path

from agent_actions.docs.generator import generate_docs
from agent_actions.docs.server import serve_docs


@click.group()
def docs():
    """Generate and serve workflow documentation."""
    pass


@docs.command()
@click.option('--output', '-o', default='artefact',
              help='Output directory for generated files (default: artefact)')
def generate(output: str):
    """
    Generate documentation data files.

    Scans the current project directory for workflows and generates
    catalog.json and runs.json in the artefact/ directory.

    \b
    Examples:
        agent-actions docs generate
        agent-actions docs generate --output ./custom-artefact
    """
    # Use current working directory as project path
    project_path = Path.cwd()
    output_dir = Path(output)

    success = generate_docs(str(project_path), output_dir)

    if not success:
        click.echo("No workflows found to document.")
        raise click.Abort()


@docs.command()
@click.option('--port', '-p', default=8000,
              help='Port to run server on (default: 8000)')
def serve(port: int):
    """
    Start HTTP server to view documentation.

    Serves the documentation site from the built-in docs_site directory.
    Requires that 'docs generate' has been run first.

    \b
    Examples:
        agent-actions docs serve
        agent-actions docs serve --port 3000
    """
    success = serve_docs(port)
    if not success:
        raise click.Abort()
