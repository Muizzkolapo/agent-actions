"""Documentation commands for the agent-actions CLI."""

import subprocess
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.tooling.docs.generator import generate_docs
from agent_actions.tooling.docs.server import serve_docs

DEFAULT_OUTPUT = "artefact"
DEFAULT_PORT = 8000
DEPRECATION_REMOVAL_VERSION = "v0.3.0"


def _resolve_output_dir(output: str, project_path: Path) -> Path:
    """Resolve *output* against *project_path*, returning an absolute path."""
    output_dir = Path(output)
    if not output_dir.is_absolute():
        output_dir = (project_path / output_dir).resolve()
    else:
        output_dir = output_dir.resolve()
    return output_dir


def _build_catalog(output: str, project_root: Path | None = None) -> Path:
    """Generate ``catalog.json`` (and ``runs.json`` if missing) into *output*.

    Pure I/O: never binds a port and never blocks. Returns the resolved
    output directory. Raises ``click.Abort`` if no workflows are discovered.
    """
    project_path = resolve_project_root(project_root)
    output_dir = _resolve_output_dir(output, project_path)

    success = generate_docs(str(project_path), output_dir)
    if not success:
        click.echo("No workflows found to document.")
        raise click.Abort()
    return output_dir


def _serve_catalog(output_dir: Path, port: int, project_root: Path | None = None) -> None:
    """Start the docs HTTP server on *port*; blocks until Ctrl+C.

    Raises ``click.Abort`` if the underlying server cannot start (missing
    assets, port bind failure, etc.).
    """
    served = serve_docs(port, artefact_path=str(output_dir), project_root=project_root)
    if not served:
        raise click.Abort()


@click.group("docs", invoke_without_command=True)
@click.option(
    "--output",
    "-o",
    default=DEFAULT_OUTPUT,
    help=(
        f"Output directory for generated files (default: {DEFAULT_OUTPUT}). "
        "Used only by the deprecated bare 'agac docs' alias — prefer "
        "'agac docs build -o ...' or 'agac docs serve -o ...'."
    ),
)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_PORT,
    help=(
        f"Port to run the server on (default: {DEFAULT_PORT}). "
        "Used only by the deprecated bare 'agac docs' alias — prefer "
        "'agac docs serve -p ...'."
    ),
)
@click.pass_context
def docs(ctx: click.Context, output: str, port: int) -> None:
    """Build and serve workflow documentation.

    \b
    Subcommands:
      build   Generate catalog.json and exit (CI-friendly, never blocks).
      serve   Generate catalog.json and start a blocking HTTP server.
      test    Run Playwright tests against the documentation site.

    Calling ``agac docs`` with no subcommand is DEPRECATED; it currently
    prints a notice on stderr and delegates to ``serve``. The alias will be
    removed in v0.3.0 — migrate to the explicit subcommands.

    \b
    Examples:
        agac docs build               (CI; exits when done)
        agac docs serve               (interactive; blocks until Ctrl+C)
        agac docs serve --port 3000
    """
    if ctx.invoked_subcommand is not None:
        return

    click.echo(
        "DEPRECATED: 'agac docs' (no subcommand) is deprecated and will be "
        f"removed in {DEPRECATION_REMOVAL_VERSION}. Use 'agac docs serve' "
        "(or 'agac docs build' for CI). Delegating to 'serve' for now.",
        err=True,
    )
    ctx.invoke(serve, output=output, port=port)


@docs.command("build")
@click.option(
    "--output",
    "-o",
    default=DEFAULT_OUTPUT,
    show_default=True,
    help="Output directory for generated files. Exits without serving (CI-friendly).",
)
@handles_user_errors("docs build")
@requires_project
def build(output: str, project_root: Path | None = None) -> None:
    """Generate catalog.json and exit. CI-friendly; does not bind a port."""
    output_dir = _build_catalog(output, project_root=project_root)
    click.echo(f"Wrote catalog to {output_dir / 'catalog.json'}", err=True)


@docs.command("serve")
@click.option(
    "--output",
    "-o",
    default=DEFAULT_OUTPUT,
    show_default=True,
    help="Output directory for generated files before serving.",
)
@click.option(
    "--port",
    "-p",
    default=DEFAULT_PORT,
    show_default=True,
    help="HTTP port to bind. This command BLOCKS until interrupted (Ctrl+C).",
)
@handles_user_errors("docs serve")
@requires_project
def serve(output: str, port: int, project_root: Path | None = None) -> None:
    """Generate catalog.json then start a blocking HTTP server.

    This command BLOCKS until interrupted (Ctrl+C). Not suitable for CI;
    use 'agac docs build' there.
    """
    output_dir = _build_catalog(output, project_root=project_root)
    _serve_catalog(output_dir, port=port, project_root=project_root)


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
