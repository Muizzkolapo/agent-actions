"""Factory functions for creating components with dependency injection."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Optional

from agent_actions.config.di.application import ApplicationContainer
from agent_actions.config.di.types import DIConfig

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
    from agent_actions.workflow.runner import ActionRunner


@contextmanager
def application_container_context(config: DIConfig | None = None):
    """Context manager for DI container lifecycle management.

    Yields:
        ApplicationContainer instance.
    """
    if config is None:
        container = ApplicationContainer.create_for_environment("development")
    else:
        container = ApplicationContainer(config)

    yield container


def create_action_runner(
    config: DIConfig | None = None,
    use_tools: bool = True,
    storage_backend: Optional["StorageBackend"] = None,
) -> "ActionRunner":
    """Create an ActionRunner with proper dependency injection."""
    from agent_actions.workflow.runner import ActionRunner

    with application_container_context(config) as container:
        runner: ActionRunner = container.get_action_runner(
            use_tools, storage_backend=storage_backend
        )
        return runner
