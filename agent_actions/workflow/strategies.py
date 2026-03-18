"""Strategy classes for different action execution patterns."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, cast

from agent_actions.config.di.container import ProcessorFactory
from agent_actions.config.types import ActionConfigDict
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


@dataclass
class StrategyExecutionParams:
    """Parameters for strategy execution."""

    action_config: ActionConfigDict
    action_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int
    action_configs: dict[str, dict] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    source_relative_path: str | None = None  # For storage backend source lookups
    data: list[dict[str, Any]] | None = None  # Pre-loaded data (skips file read)


class ActionStrategy(ABC):
    """Abstract base class for action execution strategies."""

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
            raise RuntimeError("BaseActionStrategy requires processor_factory")
        from agent_actions.workflow.pipeline import (
            create_processing_pipeline_from_params,
        )

        pipeline = create_processing_pipeline_from_params(
            action_config=params.action_config,
            action_name=params.action_name,
            idx=params.idx,
            processor_factory=self.processor_factory,
            action_configs=params.action_configs,
            storage_backend=params.storage_backend,
            source_relative_path=params.source_relative_path,
        )
        return pipeline.process(
            params.file_path,
            params.base_directory,
            params.output_directory,
            data=params.data,
        )


class InitialStrategy(ActionStrategy):
    """Strategy for the initial action in a workflow."""

    def __eq__(self, other):
        if not isinstance(other, InitialStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """Execute the initial action strategy and return path to the generated output file."""
        return cast(
            str,
            process_initial_stage(
                InitialStageContext(
                    agent_config=cast(dict[str, Any], params.action_config),
                    agent_name=params.action_name,
                    file_path=params.file_path,
                    base_directory=params.base_directory,
                    output_directory=params.output_directory,
                    idx=params.idx,
                    storage_backend=params.storage_backend,
                )
            ),
        )


class StandardStrategy(ActionStrategy):
    """Standard strategy for non-initial actions that read upstream data and generate target output."""

    def __eq__(self, other):
        if not isinstance(other, StandardStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """Execute the standard action strategy and return path to the generated output file."""
        return self._execute_generate_target(params)
