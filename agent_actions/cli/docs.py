"""Documentation commands for the agent-actions CLI."""

import subprocess
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.tooling.docs.generator import generate_docs
from agent_actions.tooling.docs.server import serve_docs


@click.group()
def docs():
    """Generate and serve workflow documentation."""


@docs.command()
@click.option(
    "--output",
    "-o",
    default="artefact",
    help="Output directory for generated files (default: artefact)",
)
@handles_user_errors("docs generate")
@requires_project
def generate(output: str, project_root: Path | None = None):
    """
    Generate documentation data files.

    Scans the current project directory for workflows and generates
    catalog.json and runs.json in the artefact/ directory.

    \b
    Examples:
        agac docs generate
        agac docs generate --output ./custom-artefact
    """
    project_path = resolve_project_root(project_root)

    output_dir = Path(output)
    if not output_dir.is_absolute():
        output_dir = (project_path / output_dir).resolve()
    else:
        output_dir = output_dir.resolve()

    success = generate_docs(str(project_path), output_dir)

    if not success:
        click.echo("No workflows found to document.")
        raise click.Abort()


@docs.command()
@click.option("--port", "-p", default=8000, help="Port to run server on (default: 8000)")
@click.option(
    "--artefact", "-a", default=None, help="Path to artefact directory (default: ./artefact)"
)
@handles_user_errors("docs serve")
@requires_project
def serve(port: int, artefact: str | None, project_root: Path | None = None):
    """
    Start HTTP server to view documentation.

    Serves the documentation site from the built-in docs_site directory.
    Requires that 'docs generate' has been run first.

    \b
    Examples:
        agac docs serve
        agac docs serve --port 3000
        agac docs serve --artefact ./my-docs
    """
    success = serve_docs(port, artefact_path=artefact, project_root=project_root)
    if not success:
        raise click.Abort()


@docs.command(name="test")
@click.option(
    "--test",
    "-t",
    "test_suite",
    type=click.Choice(["schemas", "actions", "all"]),
    default="all",
    help="Which test suite to run (default: all)",
)
@click.option(
    "--port", "-p", default=8890, help="Port where docs server is running (default: 8890)"
)
@handles_user_errors("docs test")
@requires_project
def run_tests(test_suite: str, port: int, project_root: Path | None = None):
    """
    Run Playwright tests to verify documentation site.

    Requires Playwright and documentation server to be running.
    Tests verify schema display, action breakdowns, and navigation.

    \b
    Examples:
        agac docs test
        agac docs test --test schemas
        agac docs test --port 3000
    """
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        click.echo("❌ Error: Node.js is not installed!")
        click.echo("   Install from: https://nodejs.org/")
        raise click.Abort() from exc

    project_root = resolve_project_root(project_root)
    test_dir = project_root

    test_files = {
        "schemas": ["test-all-schemas.js"],
        "actions": ["test-run-actions-complete.js", "test-actions-specific.js"],
        "all": ["test-all-schemas.js", "test-run-actions-complete.js", "test-actions-specific.js"],
    }

    files_to_run = test_files.get(test_suite, test_files["all"])

    missing_files = [f for f in files_to_run if not (test_dir / f).exists()]
    if missing_files:
        click.echo(f"⚠️  Warning: Test files not found: {', '.join(missing_files)}")
        click.echo(f"   Expected in: {test_dir}")
        click.echo("\n   Run tests from project root or create test files.")
        raise click.Abort()

    click.echo(f"\n🧪 Running {test_suite} tests against http://localhost:{port}\n")

    failed = []
    for test_file in files_to_run:
        click.echo(f"▶️  Running {test_file}...")
        try:
            subprocess.run(["node", str(test_dir / test_file)], capture_output=False, check=True)
            click.echo(f"✅ {test_file} passed\n")
        except subprocess.CalledProcessError:
            click.echo(f"❌ {test_file} failed\n")
            failed.append(test_file)

    if failed:
        click.echo(f"\n❌ {len(failed)} test(s) failed: {', '.join(failed)}")
        raise click.Abort()
    click.echo("\n✅ All tests passed!")


@docs.command(hidden=True)
@handles_user_errors("docs dev")
def dev():
    """
    Start development environment.

    Watches for changes and regenerates documentation automatically.
    Serves the docs site with live reload.

    \b
    Example:
        agac docs dev
    """
    click.echo("🚧 Development mode coming soon!")
    click.echo("\nFor now, use:")
    click.echo("  Terminal 1: agac docs generate && agac docs serve")
    click.echo("  Terminal 2: agac docs test")
    raise click.Abort()
