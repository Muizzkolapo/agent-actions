import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import click

from agent_actions.agents.handlers.agent_handlers import AgentManager
from agent_actions.core.exceptions import (
    AgentNotFoundError,
    FileSystemError as AgentFileSystemError,
)

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class Cleaner:
    """Encapsulates the cleaning workflow for an agent."""
    agent: str
    force: bool = False
    remove_all: bool = False
    agent_manager: type[AgentManager] = AgentManager  # dependency injection for testing

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
            raise click.ClickException(
                f"Cleaning failed for agent '{self.agent}': {exc}"
            ) from exc

    def _run(self) -> None:
        # Step 1: Get io_dir from agent paths
        logger.info(f"Unexpected error while cleaning directories{self.agent}")
        _, io_dir_str, _ = self.agent_manager.get_agent_paths(self.agent)
        io_dir = Path(io_dir_str)

        # Step 2: Collect existing directories to clean
        directories = []
        # Always clean source and target
        for sub in ("source", "target"):
            sub_path = io_dir / sub
            if sub_path.exists():
                directories.append(sub_path)
                
        # Only include staging if --all flag is used
        if self.remove_all:
            staging_path = io_dir / "staging"
            if staging_path.exists():
                directories.append(staging_path)

        if not directories:
            click.echo(f"No directories to clean for agent '{self.agent}'.")
            return

        # Step 3: Confirm if not forced
        if not self.force and not self._confirm(directories):
            click.echo("Aborted – nothing was cleaned.")
            return

        # Step 4: Clean directories
        for directory in directories:
            self.agent_manager.clean_directory(self.agent, directory)
            
        click.echo(
            f"\u2705  Cleaned {len(directories)} directories for agent '{self.agent}'."
        )

    def _confirm(self, directories: Iterable[Path]) -> bool:
        """Request user confirmation before executing a destructive action."""
        click.echo(f"The following directories for '{self.agent}' will be removed:")
        for path in directories:
            click.echo(f"  • {path}")
        return click.confirm(click.style("Proceed?", fg="yellow"), default=False)
