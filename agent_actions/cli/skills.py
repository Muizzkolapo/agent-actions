"""Skills management CLI commands."""

import shutil
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.errors import ConfigurationError
from agent_actions.utils.project_root import find_project_root


def get_bundled_skills_path() -> Path:
    """Return the path to bundled skills in the package."""
    return Path(__file__).parent.parent / "skills"


_TOOL_SKILL_PATHS: dict[str, str] = {
    "claude": ".claude/skills",
    "codex": ".codex/skills",
}


def get_target_path(tool: str, project_root: Path) -> Path:
    """Return the target installation path for the given tool."""
    rel = _TOOL_SKILL_PATHS.get(tool)
    if rel is not None:
        return project_root / rel
    raise ConfigurationError(
        f"Unknown tool: {tool}",
        context={"tool": tool, "supported_tools": list(_TOOL_SKILL_PATHS)},
    )


@click.group(name="skills")
def skills():
    """Manage AI coding assistant skills (Claude Code / OpenAI Codex)."""


@skills.command(name="install")
@handles_user_errors("skills install")
@click.option(
    "--claude",
    "tool",
    flag_value="claude",
    help="Install skills for Claude Code (.claude/skills/)",
)
@click.option(
    "--codex",
    "tool",
    flag_value="codex",
    help="Install skills for OpenAI Codex (.codex/skills/)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing skills if they exist",
)
def install(tool: str, force: bool):
    """
    Install bundled skills to your project.

    You must specify either --claude or --codex to indicate which
    AI coding assistant you're using.

    Examples:

        agac skills install --claude

        agac skills install --codex

        agac skills install --claude --force
    """
    if not tool:
        raise click.UsageError(
            "You must specify either --claude or --codex.\n\n"
            "Examples:\n"
            "  agac skills install --claude\n"
            "  agac skills install --codex"
        )

    project_root = find_project_root()
    if not project_root:
        raise click.ClickException(
            "Not in an agent-actions project.\n"
            "Run this command from a directory containing agent_actions.yml"
        )

    bundled_skills = get_bundled_skills_path()
    target_dir = get_target_path(tool, project_root)

    if not bundled_skills.exists():
        raise click.ClickException(
            f"Bundled skills not found at {bundled_skills}.\n"
            "This may indicate a corrupted installation."
        )

    available_skills = [d.name for d in bundled_skills.iterdir() if d.is_dir()]
    if not available_skills:
        raise click.ClickException("No bundled skills found.")

    click.echo(f"Installing skills for {click.style(tool.upper(), bold=True)}...")
    click.echo(f"Target: {target_dir}")
    click.echo()

    target_dir.mkdir(parents=True, exist_ok=True)

    installed = []
    skipped = []

    for skill_name in available_skills:
        source = bundled_skills / skill_name
        dest = target_dir / skill_name

        if dest.exists():
            if force:
                shutil.rmtree(dest)
                shutil.copytree(source, dest)
                installed.append(f"{skill_name} (overwritten)")
            else:
                skipped.append(skill_name)
        else:
            shutil.copytree(source, dest)
            installed.append(skill_name)

    if installed:
        click.echo(click.style("Installed:", fg="green", bold=True))
        for name in installed:
            click.echo(f"  - {name}")

    if skipped:
        click.echo()
        click.echo(click.style("Skipped (already exists):", fg="yellow"))
        for name in skipped:
            click.echo(f"  - {name}")
        click.echo()
        click.echo("Use --force to overwrite existing skills.")

    click.echo()
    click.echo(click.style("Done!", fg="green", bold=True))
    click.echo(f"Skills installed to: {target_dir}")


@skills.command(name="list")
@handles_user_errors("skills list")
def list_skills():
    """List available bundled skills."""
    bundled_skills = get_bundled_skills_path()

    if not bundled_skills.exists():
        raise click.ClickException("Bundled skills not found.")

    available_skills = [d.name for d in bundled_skills.iterdir() if d.is_dir()]

    if not available_skills:
        click.echo("No bundled skills available.")
        return

    click.echo(click.style("Available bundled skills:", bold=True))
    click.echo()

    for skill_name in available_skills:
        skill_path = bundled_skills / skill_name
        skill_md = skill_path / "SKILL.md"

        description = ""
        if skill_md.exists():
            content = skill_md.read_text()
            lines = content.split("\n")
            for line in lines[1:]:
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:60] + "..." if len(line) > 60 else line
                    break

        click.echo(f"  {click.style(skill_name, fg='cyan', bold=True)}")
        if description:
            click.echo(f"    {description}")
        click.echo()

    click.echo("Install with:")
    click.echo("  agac skills install --claude")
    click.echo("  agac skills install --codex")
