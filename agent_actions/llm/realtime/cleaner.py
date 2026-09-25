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
    remove_target: bool = False
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

    def _release_batch_records(self, io_dir: Path) -> bool:
        """Reclaim what a provider recorded about this workflow's batches.

        The store about to be wiped holds the registry, and the registry is what
        names a batch: afterwards nothing could find these records to reclaim,
        and each holds the payload its batch was submitted with.

        Reported and not raised if it fails; False says the store has to stay,
        since removing it would put the payload out of reach of every command.
        """
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.llm.providers.local_batch_records import (
            discard_partial_batch_records,
            release_local_batch_record,
        )
        from agent_actions.storage import get_storage_backend

        discard_partial_batch_records()
        released = True
        try:
            backend = get_storage_backend(
                workflow_path=str(io_dir.parent), workflow_name=self.agent
            )
            try:
                backend.initialize()
                for action_name in BatchRegistryManager.list_action_names(backend):
                    for batch_id in BatchRegistryManager.batch_ids(backend, action_name):
                        released = release_local_batch_record(batch_id) and released
            finally:
                backend.close()
        except Exception as e:
            logger.warning("Could not reclaim local batch records before cleaning: %s", e)
            click.echo(
                click.style(
                    f"⚠️  Could not reclaim what a provider recorded locally for "
                    f"'{self.agent}' ({e}). The store naming those batches is about to "
                    f"go, so nothing will be able to reach them afterwards.",
                    fg="yellow",
                )
            )
            return False
        return released

    def _run(self) -> None:
        logger.debug("Cleaning directories for agent %s", self.agent)
        _, io_dir_str, _ = self.agent_manager.get_agent_paths(
            self.agent, project_root=self.project_root
        )
        io_dir = Path(io_dir_str)
        include_target = self.remove_target or self.remove_all
        directories: list[Path] = []
        for sub in ("source", "target") if include_target else ("source",):
            sub_path = io_dir / sub
            if sub_path.exists():
                directories.append(sub_path)
        if self.remove_all:
            staging_path = io_dir / "staging"
            if staging_path.exists():
                directories.append(staging_path)
            from agent_actions.storage import BACKENDS

            seen = set(directories)
            for backend_cls in BACKENDS.values():
                for path in backend_cls.paths_to_wipe(io_dir):
                    if path not in seen:
                        directories.append(path)
                        seen.add(path)
        if not directories:
            click.echo(f"No directories to clean for agent '{self.agent}'.")
            return
        reclaims_records = self.remove_all and (io_dir / "store").is_dir()
        if not self.force and (not self._confirm(directories, reclaims_records)):
            click.echo("Aborted – nothing was cleaned.")
            return
        if reclaims_records:
            # Only when there is a store to read: opening a backend creates the
            # directory, and `directories` was settled before this line.
            if not self._release_batch_records(io_dir):
                store = io_dir / "store"
                directories = [d for d in directories if d != store]
                click.echo(
                    click.style(
                        "   Keeping the store: it is what names those batches, and removing "
                        "it now would put their payloads out of reach for good.",
                        fg="yellow",
                    )
                )
        failures = []
        for directory in directories:
            try:
                self.agent_manager.clean_directory(self.agent, directory)
            except OSError as e:
                failures.append((directory, e))
                logger.warning("Failed to clean %s: %s", directory, e)
        if failures:
            click.echo(
                f"⚠️  Cleaned {len(directories) - len(failures)}/{len(directories)} "
                f"directories for agent '{self.agent}' "
                f"({len(failures)} failed)."
            )
        else:
            click.echo(f"✅  Cleaned {len(directories)} directories for agent '{self.agent}'.")

    def _confirm(self, directories: Iterable[Path], reclaims_records: bool = False) -> bool:
        """Request user confirmation before executing a destructive action."""
        click.echo(f"The following directories for '{self.agent}' will be removed:")
        for path in directories:
            click.echo(f"  • {path}")
        if reclaims_records:
            click.echo("  • what a provider recorded locally about this workflow's batches")
        return bool(click.confirm(click.style("Proceed?", fg="yellow"), default=False))
