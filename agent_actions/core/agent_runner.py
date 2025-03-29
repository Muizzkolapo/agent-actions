"""Module for managing and executing agents with different strategies in a workflow."""

import os
from typing import Tuple, Dict, Optional
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.core.agent_strategies import (
    InitialStrategy,
    TerminalStrategy,
    IntermediateStrategy,
    AgentStrategy  # assuming AgentStrategy is the base class for all strategies
)


class AgentRunner:
    """
    Manages the execution of agents using different strategies in a workflow.
    
    Handles the selection and application of appropriate strategies (initial,
    intermediate, or terminal) for each agent in the workflow sequence.
    """

    def __init__(self, use_tools: bool) -> None:
        """
        Initialize the AgentRunner with strategy configurations.

        Args:
            use_tools (bool): Flag indicating whether to use tools during agent execution.
        """
        self.use_tools: bool = use_tools
        self.strategies: Dict[str, AgentStrategy] = {
            'initial': InitialStrategy(),
            'terminal': TerminalStrategy(),
            'intermediate': IntermediateStrategy()
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
        current_dir: str = os.getcwd()
        agent_folder: Optional[str] = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')
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
            input_directory: str = os.path.join(agent_folder, 'target', indexed_previous_agent_type)
        else:
            input_directory = os.path.join(agent_folder, 'staging')

        output_directory: str = os.path.join(agent_folder, 'target', indexed_agent_type)
        os.makedirs(output_directory, exist_ok=True)

        return input_directory, output_directory

    def process_files(
        self,
        agent_config: Dict,
        agent_name: str,
        strategy: AgentStrategy,
        input_directory: str,
        output_directory: str
    ) -> None:
        """
        Walks through the input directory, processing each file with the given strategy.
        
        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            strategy (AgentStrategy): Strategy instance to execute.
            input_directory (str): Path to the input directory.
            output_directory (str): Path to the output directory.
        
        Raises:
            ValueError: If no files are found in the input directory.
        """
        files_processed: bool = False
        for root, _, files in os.walk(input_directory):
            if files:
                files_processed = True
            for file in files:
                file_path: str = os.path.join(root, file)
                strategy.execute(
                    agent_config,
                    agent_name,
                    file_path,
                    input_directory,
                    output_directory
                )

        if not files_processed:
            raise ValueError(f"No files found in directory: {input_directory}")

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
        self.process_files(agent_config, agent_name, strategy, input_directory, output_directory)
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
        # Select strategy based on position in the workflow
        if idx == 0:
            strategy: AgentStrategy = self.strategies['initial']
        elif is_last_agent:
            strategy = self.strategies['terminal']
        else:
            strategy = self.strategies['intermediate']

        # Process agent data and generate output
        output_folder: str = self.process_and_generate_for_agent(
            agent_config,
            agent_name,
            previous_agent_type,
            strategy,
            idx
        )
        
        return output_folder
