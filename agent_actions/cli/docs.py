"""
Documentation commands for agent-actions CLI.

Provides commands for generating and serving interactive workflow documentation.
"""
import subprocess
from pathlib import Path

import click

from agent_actions.docs.generator import generate_docs
from agent_actions.docs.server import serve_docs


@click.group()
def docs():
    """Generate and serve workflow documentation."""


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

    # Resolve output_dir relative to project path if not absolute
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
@click.option('--port', '-p', default=8000,
              help='Port to run server on (default: 8000)')
@click.option('--artefact', '-a', default=None,
              help='Path to artefact directory (default: ./artefact)')
def serve(port: int, artefact: str):
    """
    Start HTTP server to view documentation.

    Serves the documentation site from the built-in docs_site directory.
    Requires that 'docs generate' has been run first.

    \b
    Examples:
        agent-actions docs serve
        agent-actions docs serve --port 3000
        agent-actions docs serve --artefact ./my-docs
    """
    success = serve_docs(port, artefact_path=artefact)
    if not success:
        raise click.Abort()


@docs.command(name='test')
@click.option('--test', '-t', 'test_suite', type=click.Choice(['schemas', 'actions', 'all']),
              default='all',
              help='Which test suite to run (default: all)')
@click.option('--port', '-p', default=8890,
              help='Port where docs server is running (default: 8890)')
def run_tests(test_suite: str, port: int):
    """
    Run Playwright tests to verify documentation site.

    Requires Playwright and documentation server to be running.
    Tests verify schema display, action breakdowns, and navigation.

    \b
    Examples:
        agent-actions docs test
        agent-actions docs test --test schemas
        agent-actions docs test --port 3000
    """
    # Check if playwright is available
    try:
        subprocess.run(['node', '--version'],
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        click.echo("❌ Error: Node.js is not installed!")
        click.echo("   Install from: https://nodejs.org/")
        raise click.Abort() from exc

    # Check if test files exist
    project_root = Path.cwd()
    test_dir = project_root

    # Map test types to files
    test_files = {
        'schemas': ['test-all-schemas.js'],
        'actions': ['test-run-actions-complete.js', 'test-actions-specific.js'],
        'all': ['test-all-schemas.js', 'test-run-actions-complete.js']
    }

    files_to_run = test_files.get(test_suite, test_files['all'])

    # Check if test files exist
    missing_files = [f for f in files_to_run if not (test_dir / f).exists()]
    if missing_files:
        click.echo(f"⚠️  Warning: Test files not found: {', '.join(missing_files)}")
        click.echo(f"   Expected in: {test_dir}")
        click.echo("\n   Run tests from project root or create test files.")
        raise click.Abort()

    # Run each test file
    click.echo(f"\n🧪 Running {test_suite} tests against http://localhost:{port}\n")

    failed = []
    for test_file in files_to_run:
        click.echo(f"▶️  Running {test_file}...")
        try:
            subprocess.run(
                ['node', str(test_dir / test_file)],
                capture_output=False,
                check=True
            )
            click.echo(f"✅ {test_file} passed\n")
        except subprocess.CalledProcessError:
            click.echo(f"❌ {test_file} failed\n")
            failed.append(test_file)

    if failed:
        click.echo(f"\n❌ {len(failed)} test(s) failed: {', '.join(failed)}")
        raise click.Abort()
    click.echo("\n✅ All tests passed!")


@docs.command()
def dev():
    """
    Start development environment.

    Watches for changes and regenerates documentation automatically.
    Serves the docs site with live reload.

    \b
    Example:
        agent-actions docs dev
    """
    click.echo("🚧 Development mode coming soon!")
    click.echo("\nFor now, use:")
    click.echo("  Terminal 1: agac docs generate && agac docs serve")
    click.echo("  Terminal 2: agac docs test")
    raise click.Abort()
