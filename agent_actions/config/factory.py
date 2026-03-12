"""Factory functions for creating components with dependency injection."""

from contextlib import contextmanager
from typing import Optional, TYPE_CHECKING

from agent_actions.workflow.runner import AgentRunner
from agent_actions.config.di.application import ApplicationContainer
from agent_actions.config.di.types import DIConfig

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


@contextmanager
def application_container_context(config: Optional[DIConfig] = None):
    """Context manager for DI container lifecycle management.

    Yields:
        ApplicationContainer instance.
    """
    if config is None:
        container = ApplicationContainer.create_for_environment("development")
    else:
        container = ApplicationContainer(config)

    yield container


def create_agent_runner(
    config: Optional[DIConfig] = None,
    use_tools: bool = True,
    storage_backend: Optional["StorageBackend"] = None,
) -> AgentRunner:
    """Create an AgentRunner with proper dependency injection."""
    with application_container_context(config) as container:
        runner: AgentRunner = container.get_agent_runner(use_tools, storage_backend=storage_backend)
        return runner
