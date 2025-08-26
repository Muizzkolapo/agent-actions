"""Module for managing and executing agents with different strategies in a workflow."""
import os
from pathlib import Path
from typing import Tuple, Dict, Optional
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.core.agent_strategies import (
    InitialStrategy,
    TerminalStrategy,
    IntermediateStrategy,
    AgentStrategy
)
from .dependency_injection import ProcessorFactory


class AgentRunner:
    """
    Manages the execution of agents using different strategies in a workflow.
    
    Handles the selection and application of appropriate strategies (initial,
    intermediate, or terminal) for each agent in the workflow sequence.
    """

    def __init__(self, use_tools: bool, processor_factory: Optional[ProcessorFactory] = None) -> None:
        """
        Initialize the AgentRunner with strategy configurations.

        Args:
            use_tools (bool): Flag indicating whether to use tools during agent execution.
            processor_factory (Optional[ProcessorFactory]): Factory for creating processors with DI.
        """
        self.use_tools: bool = use_tools
        self.processor_factory = processor_factory
        
        # Processor factory is now required for proper DI
        # Use bootstrap.create_agent_runner() to get a properly configured instance
        
        self.strategies: Dict[str, AgentStrategy] = {
            'initial': InitialStrategy(self.processor_factory),
            'terminal': TerminalStrategy(self.processor_factory),
            'intermediate': IntermediateStrategy(self.processor_factory)
        }

    def get_agent_folder(self, agent_name: str) -> str:
        """
        Retrieves the agent folder using FileHandler.
        
        Args:
            agent_name (str): Name of the agent.
        
        Returns:
            str: Path to the agent folder.
        
        Raises:
            ValueError: If the agent folder is not found.
        """
        current_dir: Path = Path.cwd()
        agent_folder: Optional[str] = FileHandler.find_specific_folder(str(current_dir), agent_name, 'agent_io')
        if agent_folder is None:
            raise ValueError(f"Agent folder not found for agent: {agent_name}")
        return agent_folder

    def setup_directories(
        self,
        agent_folder: str,
        agent_config: Dict,
        previous_agent_type: Optional[str],
        idx: int
    ) -> Tuple[str, str]:
        """
        Sets up input and output directories for the agent.
        
        Args:
            agent_folder (str): Path to the agent folder.
            agent_config (dict): Configuration for the agent.
            previous_agent_type (Optional[str]): Type of the previous agent in workflow.
            idx (int): Numeric index to prefix folder names.
        
        Returns:
            Tuple[str, str]: (input_directory, output_directory)
        """
        indexed_agent_type: str = f"node_{idx}_{agent_config['agent_type']}"

        if previous_agent_type:
            prev_idx: int = idx - 1
            indexed_previous_agent_type: str = f"node_{prev_idx}_{previous_agent_type}"
            input_directory: Path = Path(agent_folder) / 'target' / indexed_previous_agent_type
        else:
            input_directory = Path(agent_folder) / 'staging'

        output_directory: Path = Path(agent_folder) / 'target' / indexed_agent_type
        output_directory.mkdir(parents=True, exist_ok=True)

        return str(input_directory), str(output_directory)

    def process_files(
        self,
        agent_config: Dict,
        agent_name: str,
        strategy: AgentStrategy,
        input_directory: str,
        output_directory: str,
        idx: int
    ) -> None:
        """
        Walks through the input directory, processing each file with the given strategy,
        explicitly excluding any directory named 'batch'.
        
        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            strategy (AgentStrategy): Strategy instance to execute.
            input_directory (str): Path to the input directory.
            output_directory (str): Path to the output directory.
            idx (int): Index of the config being processed.
        
        Raises:
            ValueError: If no files are found in the input directory.
        """
        files_processed_count: int = 0
        input_path = Path(input_directory)
        output_path = Path(output_directory)

        for item in input_path.rglob('*'):
            if 'batch' in item.parts:
                continue

            if item.is_file():
                relative_path = item.relative_to(input_path)
                output_file_path = output_path / relative_path
                output_file_path.parent.mkdir(parents=True, exist_ok=True)
                
                strategy.execute(
                    agent_config,
                    agent_name,
                    str(item),
                    input_directory,
                    str(output_file_path.parent),
                    idx
                )
                files_processed_count += 1

        if files_processed_count == 0:
            if not any(input_path.iterdir()): # True if directory is empty (no files, no subdirs)
                print(f"Warning: No files found in directory: {input_directory}, and the directory itself is empty. Processing continues.")
            else: # Directory had subdirectories, which were mirrored.
                print(f"Info: No files found to process in {input_directory}, but directory structure was mirrored. Processing continues.")

    def process_and_generate_for_agent(
        self,
        agent_config: Dict,
        agent_name: str,
        previous_agent_type: Optional[str],
        strategy: AgentStrategy,
        idx: int
    ) -> str:
        """
        Processes and generates data for an agent using the provided strategy.
        
        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (Optional[str]): Type of the previous agent in workflow.
            strategy (AgentStrategy): AgentStrategy instance to execute.
            idx (int): Numeric index to prefix folder names.

        Returns:
            str: Path to the output directory.
        """
        agent_folder: str = self.get_agent_folder(agent_name)
        input_directory, output_directory = self.setup_directories(agent_folder, agent_config, previous_agent_type, idx)
        self.process_files(agent_config, agent_name, strategy, input_directory, output_directory, idx)
        return output_directory

    def run_agent(
        self,
        agent_config: Dict,
        agent_name: str,
        previous_agent_type: Optional[str],
        idx: int,
        is_last_agent: bool = False
    ) -> str:
        """
        Runs an agent with the appropriate strategy based on its position in the workflow.

        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (Optional[str]): Type of the previous agent in workflow.
            idx (int): Current agent's index in workflow.
            is_last_agent (bool): Flag indicating if this is the last agent.

        Returns:
            str: Path to the output directory.
        """
        if idx == 0:
            strategy: AgentStrategy = self.strategies['initial']
        elif is_last_agent:
            strategy = self.strategies['terminal']
        else:
            strategy = self.strategies['intermediate']

        output_folder: str = self.process_and_generate_for_agent(
            agent_config,
            agent_name,
            previous_agent_type,
            strategy,
            idx
        )
        
        return output_folder
