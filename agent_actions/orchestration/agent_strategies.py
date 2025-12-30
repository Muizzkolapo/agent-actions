"""
Module defining strategy classes for different agent execution patterns.

These strategies implement various approaches for processing agent inputs
and generating outputs based on the agent's position in a workflow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, TYPE_CHECKING
import asyncio
from agent_actions.preprocessing.staging.staging_loader import generate_staging, StagingContext
from agent_actions.orchestration.dependency_injection import ProcessorFactory

if TYPE_CHECKING:
    from agent_actions.orchestration.target_generator import TargetGenerator, GeneratorConfig


@dataclass
class StrategyExecutionParams:
    """Parameters for strategy execution."""

    agent_config: Dict[str, Any]
    agent_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int
    agent_configs: Optional[Dict[str, Dict]] = None


class AgentStrategy(ABC):
    """
    Abstract base class for agent execution strategies.

    Defines the interface that all agent strategies must implement.
    """

    def __init__(self, processor_factory: Optional[ProcessorFactory] = None):
        """
        Initialize the strategy with optional processor factory.

        Args:
            processor_factory: Optional factory for creating processors with DI
        """
        self.processor_factory = processor_factory

    def __repr__(self):
        """Return string representation."""
        return f"{self.__class__.__name__}(processor_factory={self.processor_factory})"

    @abstractmethod
    def execute(self, params: StrategyExecutionParams) -> str:
        """
        Execute the strategy for a specific agent and file.

        Args:
            params: StrategyExecutionParams with all required parameters

        Returns:
            Path to the generated output file.
        """

    def _execute_generate_target(self, params: StrategyExecutionParams) -> str:
        """
        Helper method to generate target data.

        Args:
            params: StrategyExecutionParams with all required parameters

        Returns:
            Path to the generated output file.
        """
        if self.processor_factory is None:
            raise RuntimeError("BaseAgentStrategy requires processor_factory")
        # Import here to avoid circular dependency
        from agent_actions.orchestration.target_generator import create_target_generator_from_params  # pylint: disable=import-outside-toplevel

        generator = create_target_generator_from_params(
            agent_config=params.agent_config,
            agent_name=params.agent_name,
            idx=params.idx,
            processor_factory=self.processor_factory,
            agent_configs=params.agent_configs,
        )
        result = generator.process(params.file_path, params.base_directory, params.output_directory)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                return loop.run_until_complete(result)
            return asyncio.run(result)
        return result


class InitialStrategy(AgentStrategy):
    """
    Strategy for the initial agent in a workflow.

    This strategy typically handles the initial loading and processing of data.
    """

    def __eq__(self, other):
        """Check equality based on class type and processor factory."""
        if not isinstance(other, InitialStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """
        Execute the initial agent strategy.

        Args:
            params: StrategyExecutionParams with all required parameters

        Returns:
            Path to the generated output file.
        """
        return generate_staging(
            StagingContext(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                file_path=params.file_path,
                base_directory=params.base_directory,
                output_directory=params.output_directory,
                idx=params.idx,
            )
        )


class StandardStrategy(AgentStrategy):
    """
    Standard strategy for executing agents (formerly Intermediate/Terminal).

    This strategy handles the processing of data for all agents except the initial one.
    It reads input from upstream directories and generates target output.
    """

    def __eq__(self, other):
        """Check equality based on class type and processor factory."""
        if not isinstance(other, StandardStrategy):
            return False
        return self.processor_factory == other.processor_factory

    def execute(self, params: StrategyExecutionParams) -> str:
        """
        Execute the standard agent strategy.

        Args:
            params: StrategyExecutionParams with all required parameters

        Returns:
            Path to the generated output file.
        """
        return self._execute_generate_target(params)
