"""Initialize command for the Agent Actions CLI."""

import io
import json
import logging
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import click

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.config.init import ProjectInitializer
from agent_actions.errors import (
    ConfigurationError,
    FileSystemError,
    ValidationError,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ProjectDirectoryCreatedEvent,
    ProjectInitializationStartEvent,
    ProjectInitializedEvent,
    ProjectValidationEvent,
)
from agent_actions.validation.init_validator import InitCommandArgs
from agent_actions.validation.project_validator import ProjectValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Remote examples support  (fetched from GitHub — nothing bundled in wheel)
# ---------------------------------------------------------------------------

_GITHUB_REPO = "Muizzkolapo/agent-actions"
_GITHUB_BRANCH = "main"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_REPO}"

# File patterns and directory names to skip when copying an example project.
_COPY_IGNORE_PATTERNS = shutil.ignore_patterns(
    "*.mp4",
    "*.mp3",
    "*.tape",
    "*.db",
    "__pycache__",
    ".agent_status.json",
    "target",
)


def _github_request(url: str) -> bytes:
    """Make a GET request to the GitHub API with a User-Agent header."""
    req = Request(url, headers={"User-Agent": "agac-cli", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            data: bytes = resp.read()
            return data
    except URLError as exc:
        raise click.ClickException(
            f"Failed to reach GitHub ({exc}). Check your internet connection."
        ) from exc


def _list_remote_examples() -> list[dict[str, str]]:
    """Fetch the list of example directories from the GitHub contents API.

    Returns a list of ``{"name": ..., "description": ...}`` dicts sorted by name.
    """
    url = f"{_GITHUB_API}/contents/examples?ref={_GITHUB_BRANCH}"
    data = json.loads(_github_request(url))
    names = sorted(entry["name"] for entry in data if entry["type"] == "dir")

    results: list[dict[str, str]] = []
    for name in names:
        # Try to fetch the first line of the README for a description
        desc = ""
        readme_url = (
            f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{_GITHUB_BRANCH}"
            f"/examples/{name}/README.md"
        )
        try:
            readme_bytes = _github_request(readme_url)
            first_line = readme_bytes.decode("utf-8", errors="replace").strip().splitlines()[0]
            desc = first_line.lstrip("# ").strip()
        except (click.ClickException, IndexError):
            pass
        results.append({"name": name, "description": desc})
    return results


def _fetch_example(example_name: str, dest: Path, *, force: bool = False) -> None:
    """Download an example from GitHub and extract it to *dest*."""
    if dest.exists() and not force:
        raise click.ClickException(f"Directory already exists: {dest}  (use --force to overwrite)")

    if dest.exists() and force:
        shutil.rmtree(dest)

    click.echo(f"Downloading example '{example_name}' from GitHub...")

    tarball_url = f"{_GITHUB_API}/tarball/{_GITHUB_BRANCH}"
    tarball_data = _github_request(tarball_url)

    with tempfile.TemporaryDirectory() as tmpdir:
        with tarfile.open(fileobj=io.BytesIO(tarball_data), mode="r:gz") as tar:
            tar.extractall(tmpdir, filter="data")

        # The tarball root is a single directory like "Owner-repo-sha/"
        roots = list(Path(tmpdir).iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise click.ClickException("Unexpected tarball structure from GitHub.")

        example_src = roots[0] / "examples" / example_name
        if not example_src.is_dir():
            # Fetch the real list so we can show available names
            try:
                available = _list_remote_examples()
                names = ", ".join(e["name"] for e in available) or "(none found)"
            except click.ClickException:
                names = "(could not fetch list)"
            raise click.BadParameter(
                f"Unknown example '{example_name}'. Available examples: {names}",
                param_hint="'NAME'",
            )

        shutil.copytree(example_src, dest, ignore=_COPY_IGNORE_PATTERNS)


def _print_available_examples() -> None:
    """Fetch and print available example names from GitHub."""
    try:
        examples = _list_remote_examples()
    except click.ClickException as exc:
        click.echo(f"Could not fetch examples: {exc.message}")
        return

    if not examples:
        click.echo("No examples found in the repository.")
        return

    click.echo("Available examples:\n")
    for ex in examples:
        click.echo(f"  {ex['name']:<35s} {ex['description']}")


class InitCommand:
    """Handles project initialization including validation and directory creation."""

    def __init__(self, args: InitCommandArgs):
        self.args = args
        self.output_dir = Path(args.output_dir) if args.output_dir else Path.cwd()

        self._validate_output_dir()

        self.project_dir = self.output_dir / self.args.project_name

    def _validate_output_dir(self) -> None:
        cwd = Path.cwd().resolve()
        resolved = self.output_dir.resolve()

        if self.args.output_dir:
            path_str = str(Path(self.args.output_dir))

            if any(part == ".." for part in Path(self.args.output_dir).parts):
                raise ValidationError(
                    "Path traversal not allowed in output directory",
                    context={
                        "output_dir": path_str,
                        "resolved": str(resolved),
                        "operation": "_validate_output_dir",
                    },
                )

            if not Path(self.args.output_dir).is_absolute():
                try:
                    resolved.relative_to(cwd)
                except ValueError as exc:
                    raise ValidationError(
                        "Output directory must be within current working directory",
                        context={
                            "output_dir": path_str,
                            "resolved": str(resolved),
                            "cwd": str(cwd),
                            "operation": "_validate_output_dir",
                        },
                    ) from exc

        sensitive_prefixes = ("/etc/", "/usr/", "/bin/", "/sbin/", "/var/", "/root/")
        resolved_str = str(resolved)
        for prefix in sensitive_prefixes:
            if resolved_str.startswith(prefix) or resolved_str.rstrip("/") + "/" == prefix:
                raise ValidationError(
                    "Cannot create project in system directory",
                    context={
                        "output_dir": str(self.output_dir),
                        "resolved": resolved_str,
                        "blocked_prefix": prefix,
                        "operation": "_validate_output_dir",
                    },
                )

    def _get_available_templates(self) -> list[str]:
        return ["default", "minimal", "full"]

    def _create_project_directory(self) -> None:
        try:
            backup_dir = None
            if self.project_dir.exists() and self.args.force:
                backup_dir = Path(
                    tempfile.mkdtemp(
                        prefix=f".{self.project_dir.name}_bak_",
                        dir=str(self.project_dir.parent),
                    )
                )
                shutil.rmtree(backup_dir)
                self.project_dir.rename(backup_dir)
            self.project_dir.mkdir(exist_ok=self.args.force)
            if backup_dir and backup_dir.exists():
                try:
                    shutil.rmtree(backup_dir)
                except OSError as cleanup_err:
                    logger.warning("Failed to clean up backup %s: %s", backup_dir, cleanup_err)
        except OSError as e:
            if backup_dir and backup_dir.exists() and not self.project_dir.exists():
                backup_dir.rename(self.project_dir)
            raise FileSystemError(
                "Failed to create project directory",
                context={
                    "project_dir": str(self.project_dir),
                    "project_name": self.args.project_name,
                    "operation": "_create_project_directory",
                    "os_error": str(e),
                },
                cause=e,
            ) from e

    def _initialize_project(self) -> None:
        try:
            initializer = ProjectInitializer(
                project_name=self.args.project_name, base_path=self.output_dir
            )
            initializer.init_project()
        except Exception as e:
            raise ConfigurationError(
                "Failed to initialize project",
                context={
                    "project_name": self.args.project_name,
                    "project_dir": str(self.project_dir),
                    "template": self.args.template,
                    "operation": "_initialize_project",
                },
                cause=e,
            ) from e

    def execute(self) -> None:
        start_time = datetime.now()
        fire_event(ProjectInitializationStartEvent(project_path=str(self.project_dir)))

        validator = ProjectValidator()
        validation_data = {
            "project_name": self.args.project_name,
            "output_dir": self.output_dir,
            "project_dir": self.project_dir,
            "template": self.args.template,
            "available_templates": self._get_available_templates(),
            "force": self.args.force,
        }
        fire_event(
            ProjectValidationEvent(validation_target="project_structure", result="validating")
        )
        if not validator.validate(validation_data):
            fire_event(
                ProjectValidationEvent(validation_target="project_structure", result="failed")
            )
            errors = validator.get_errors()
            raise ValidationError("Project validation failed", context={"errors": errors})
        fire_event(ProjectValidationEvent(validation_target="project_structure", result="passed"))

        self._create_project_directory()
        fire_event(ProjectDirectoryCreatedEvent(directory_path=str(self.project_dir)))

        self._initialize_project()

        elapsed_time = (datetime.now() - start_time).total_seconds()
        fire_event(
            ProjectInitializedEvent(project_path=str(self.project_dir), elapsed_time=elapsed_time)
        )

        click.echo(f"Successfully initialized project: {self.args.project_name}")
        click.echo(f"Project created at: {self.project_dir}")
        click.echo("\nNext steps:")
        click.echo(f"  cd {self.args.project_name}")
        click.echo("  agac run -a sample_agent")


class _InitGroup(click.Group):
    """Route unknown subcommands to ``new`` so ``agac init my_proj`` works."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        cmd_name = args[0] if args else None
        if cmd_name and self.get_command(ctx, cmd_name) is None:
            # Not a known subcommand — treat as ``new <project_name> ...``
            return super().resolve_command(ctx, ["new"] + args)
        return super().resolve_command(ctx, args)


@click.group(cls=_InitGroup)
def init() -> None:
    """
    Initialize a new Agent Actions project.

    \b
    Examples:
        agac init my_project
        agac init my_project --template minimal
        agac init list
        agac init example contract_reviewer my_project
    """


@init.command("new")
@click.argument("project_name")
@click.option(
    "-o", "--output-dir", help="Directory to create the project in (default: current directory)"
)
@click.option(
    "-t", "--template", default="default", help="Template to use for project initialization"
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Force project creation even if directory exists",
)
@handles_user_errors("init")
def init_new(
    project_name: str,
    output_dir: str | None = None,
    template: str = "default",
    force: bool = False,
) -> None:
    """Create a new project from a template.

    \b
    Examples:
        agac init my_project
        agac init new my_project --template minimal
    """
    args = InitCommandArgs(
        project_name=project_name,
        output_dir=Path(output_dir) if output_dir else None,
        template=template,
        force=force,
    )
    command = InitCommand(args)
    command.execute()


@init.command("list")
@handles_user_errors("init list")
def init_list() -> None:
    """List available example projects from GitHub."""
    _print_available_examples()


@init.command("example")
@click.argument("name")
@click.argument("project_name", required=False, default=None)
@click.option(
    "-o", "--output-dir", help="Directory to create the project in (default: current directory)"
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Force project creation even if directory exists",
)
@handles_user_errors("init example")
def init_example(
    name: str,
    project_name: str | None = None,
    output_dir: str | None = None,
    force: bool = False,
) -> None:
    """Create a project from a GitHub example.

    \b
    Examples:
        agac init example contract_reviewer
        agac init example contract_reviewer my_project
    """
    dest_name = project_name or name
    out = Path(output_dir) if output_dir else Path.cwd()
    dest = out / dest_name
    _fetch_example(name, dest, force=force)
    click.echo(f"Created project from example '{name}': {dest}")
    click.echo("\nNext steps:")
    click.echo(f"  cd {dest_name}")
    click.echo("  agac run")
