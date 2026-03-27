import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import click

from agent_actions.errors import (
    AgentNotFoundError,
)
from agent_actions.errors import (
    FileSystemError as AgentFileSystemError,
)
from agent_actions.llm.realtime.handlers import AgentManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Cleaner:
    """Encapsulates the cleaning workflow for an agent."""

    agent: str
    force: bool = False
    remove_all: bool = False
    project_root: Path | None = None
    agent_manager: type[AgentManager] = AgentManager

    def run(self) -> None:
        """Run the cleaning workflow and surface meaningful ClickExceptions."""
        try:
            self._run()
        except AgentNotFoundError as exc:
            raise click.ClickException(f"Agent '{self.agent}' was not found.") from exc
        except AgentFileSystemError as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected error while cleaning directories")
            raise click.ClickException(f"Cleaning failed for agent '{self.agent}': {exc}") from exc

    def _run(self) -> None:
        logger.debug("Cleaning directories for agent %s", self.agent)
        _, io_dir_str, _ = self.agent_manager.get_agent_paths(
            self.agent, project_root=self.project_root
        )
        io_dir = Path(io_dir_str)
        directories = []
        for sub in ("source", "target"):
            sub_path = io_dir / sub
            if sub_path.exists():
                directories.append(sub_path)
        if self.remove_all:
            staging_path = io_dir / "staging"
            if staging_path.exists():
                directories.append(staging_path)
        if not directories:
            click.echo(f"No directories to clean for agent '{self.agent}'.")
            return
        if not self.force and (not self._confirm(directories)):
            click.echo("Aborted – nothing was cleaned.")
            return
        for directory in directories:
            self.agent_manager.clean_directory(self.agent, directory)
        click.echo(f"✅  Cleaned {len(directories)} directories for agent '{self.agent}'.")

    def _confirm(self, directories: Iterable[Path]) -> bool:
        """Request user confirmation before executing a destructive action."""
        click.echo(f"The following directories for '{self.agent}' will be removed:")
        for path in directories:
            click.echo(f"  • {path}")
        return click.confirm(click.style("Proceed?", fg="yellow"), default=False)
