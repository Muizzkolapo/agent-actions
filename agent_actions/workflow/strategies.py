"""Strategy classes for different agent execution patterns."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, cast

from agent_actions.config.di.container import ProcessorFactory
from agent_actions.config.types import AgentConfigDict
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


@dataclass
class StrategyExecutionParams:
    """Parameters for strategy execution."""

    agent_config: AgentConfigDict
    agent_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int
    agent_configs: dict[str, dict] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    source_relative_path: str | None = None  # For storage backend source lookups
    data: list[dict[str, Any]] | None = None  # Pre-loaded data (skips file read)


class AgentStrategy(ABC):
    """Abstract base class for agent execution strategies."""

    def __init__(self, processor_factory: ProcessorFactory | None = None):
        """Initialize the strategy with optional processor factory."""
        self.processor_factory = processor_factory

    def __repr__(self):
        return f"{self.__class__.__name__}(processor_factory={self.processor_factory})"

    @abstractmethod
    def execute(self, params: StrategyExecutionParams) -> str:
        """Execute the strategy and return the path to the generated output file."""

    def _execute_generate_target(self, params: StrategyExecutionParams) -> str:
        """Process data through pipeline and return path to the generated output file."""
        if self.processor_factory is None:
            raise RuntimeError("BaseAgentStrategy requires processor_factory")
        from agent_actions.workflow.pipeline import (
            create_processing_pipeline_from_params,
        )

        pipeline = create_processing_pipeline_from_params(
            agent_config=params.agent_config,
            agent_name=params.agent_name,
            idx=params.idx,
            processor_factory=self.processor_factory,
            agent_configs=params.agent_configs,
            storage_backend=params.storage_backend,
            source_relative_path=params.source_relative_path,
        )
        return pipeline.process(
            params.file_path,
            params.base_directory,
            params.output_directory,
            data=params.data,
        )


class InitialStrategy(AgentStrategy):
    """Strategy for the initial agent in a workflow."""

    def __eq__(self, other):
        if not isinstance(other, InitialStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """Execute the initial agent strategy and return path to the generated output file."""
        return cast(
            str,
            process_initial_stage(
                InitialStageContext(
                    agent_config=cast(dict[str, Any], params.agent_config),
                    agent_name=params.agent_name,
                    file_path=params.file_path,
                    base_directory=params.base_directory,
                    output_directory=params.output_directory,
                    idx=params.idx,
                    storage_backend=params.storage_backend,
                )
            ),
        )


class StandardStrategy(AgentStrategy):
    """Standard strategy for non-initial agents that read upstream data and generate target output."""

    def __eq__(self, other):
        if not isinstance(other, StandardStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """Execute the standard agent strategy and return path to the generated output file."""
        return self._execute_generate_target(params)
