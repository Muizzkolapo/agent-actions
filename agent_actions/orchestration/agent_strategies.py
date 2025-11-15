"""
Module defining strategy classes for different agent execution patterns.

These strategies implement various approaches for processing agent inputs
and generating outputs based on the agent's position in a workflow.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio
from agent_actions.preprocessing.staging_loader import generate_staging
from agent_actions.orchestration.target_generator import TargetGenerator
from agent_actions.orchestration.dependency_injection import ProcessorFactory

class AgentStrategy(ABC):
    """
    Abstract base class for agent execution strategies.
    
    Defines the interface that all agent strategies must implement.
    """

    def __init__(self, processor_factory: Optional[ProcessorFactory]=None):
        """
        Initialize the strategy with optional processor factory.
        
        Args:
            processor_factory: Optional factory for creating processors with DI
        """
        self.processor_factory = processor_factory

    @abstractmethod
    def execute(self, agent_config: Dict[str, Any], agent_name: str, file_path: str, base_directory: str, output_directory: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None) -> str:
        """
        Execute the strategy for a specific agent and file.

        Args:
            agent_config: Configuration dictionary for the agent.
            agent_name: Name of the agent.
            file_path: Path to the file being processed.
            base_directory: Base input directory.
            output_directory: Directory where output should be written.
            idx: Index of the config being processed.
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution).

        Returns:
            Path to the generated output file.
        """
        pass

    def _execute_generate_target(self, agent_config: Dict[str, Any], agent_name: str, file_path: str, base_directory: str, output_directory: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None) -> str:
        """
        Helper method to generate target data.

        This method wraps the generate_target function so that it can be
        reused by multiple strategies without duplication.

        Args:
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution).

        Returns:
            Path to the generated output file.
        """
        if self.processor_factory is None:
            from agent_actions.shared.exceptions import DependencyError
            raise DependencyError('BaseAgentStrategy', 'processor_factory')
        generator = TargetGenerator(agent_config, agent_name, idx, self.processor_factory, agent_configs=agent_configs)
        result = generator.process(file_path, base_directory, output_directory)
        if asyncio.iscoroutine(result):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                return loop.run_until_complete(result)
            else:
                return asyncio.run(result)
        return result

class InitialStrategy(AgentStrategy):
    """
    Strategy for the initial agent in a workflow.

    This strategy typically handles the initial loading and processing of data.
    """

    def execute(self, agent_config: Dict[str, Any], agent_name: str, file_path: str, base_directory: str, output_directory: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None) -> str:
        """
        Execute the initial agent strategy.

        Generates staging data from the input file.

        Args:
            agent_config: Configuration dictionary for the agent.
            agent_name: Name of the agent.
            file_path: Path to the file being processed.
            base_directory: Base input directory.
            output_directory: Directory where output should be written.
            idx: Index of the config being processed.
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution).
        Returns:
            Path to the generated output file.
        """
        return generate_staging(agent_config, agent_name, file_path, base_directory, output_directory, idx)

class TerminalStrategy(AgentStrategy):
    """
    Strategy for the terminal (final) agent in a workflow.

    This strategy typically handles the final processing and output generation.
    """

    def execute(self, agent_config: Dict[str, Any], agent_name: str, file_path: str, base_directory: str, output_directory: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None) -> str:
        """
        Execute the terminal agent strategy.

        Generates final target data from the input file.

        Args:
            agent_config: Configuration dictionary for the agent.
            agent_name: Name of the agent.
            file_path: Path to the file being processed.
            base_directory: Base input directory.
            output_directory: Directory where output should be written.
            idx: Index of the config being processed.
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution).
        Returns:
            Path to the generated output file.
        """
        return self._execute_generate_target(agent_config, agent_name, file_path, base_directory, output_directory, idx, agent_configs)

class IntermediateStrategy(AgentStrategy):
    """
    Strategy for intermediate agents in a workflow.

    This strategy handles the processing of data between initial and terminal agents.
    """

    def execute(self, agent_config: Dict[str, Any], agent_name: str, file_path: str, base_directory: str, output_directory: str, idx: int, agent_configs: Optional[Dict[str, Dict]]=None) -> str:
        """
        Execute the intermediate agent strategy.

        Processes input data and generates intermediate target data.

        Args:
            agent_config: Configuration dictionary for the agent.
            agent_name: Name of the agent.
            file_path: Path to the file being processed.
            base_directory: Base input directory.
            output_directory: Directory where output should be written.
            idx: Index of the config being processed.
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution).
        Returns:
            Path to the generated output file.
        """
        return self._execute_generate_target(agent_config, agent_name, file_path, base_directory, output_directory, idx, agent_configs)