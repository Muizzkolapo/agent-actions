"""Module for managing and executing agents with different strategies in a workflow."""

import os
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.core.exceptions import (
    FileProcessingError,
    NoFilesFoundError,
    DirectoryError,
    FileSystemError
)
from agent_actions.core.agent_strategies import (
    InitialStrategy,
    TerminalStrategy,
    IntermediateStrategy
)
from agent_actions.core.error_utils import try_operation, handle_errors


class AgentRunner:
    """
    Manages the execution of agents using different strategies in a workflow.
    
    Handles the selection and application of appropriate strategies (initial,
    intermediate, or terminal) for each agent in the workflow sequence.
    """

    def __init__(self, use_tools):
        """
        Initialize the AgentRunner with strategy configurations.

        Args:
            use_tools (bool): Flag indicating whether to use tools during agent execution
        """
        self.use_tools = use_tools
        self.strategies = {
            'initial': InitialStrategy(),
            'terminal': TerminalStrategy(),
            'intermediate': IntermediateStrategy()
        }

    @handle_errors()
    def process_and_generate_for_agent(self,
                                   agent_config,
                                   agent_name,
                                   previous_agent_type,
                                   strategy,
                                   idx):
        """
        Processes and generates data for an agent using the provided strategy.
        
        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (str): Type of the previous agent in workflow.
            strategy (AgentStrategy): AgentStrategy instance to execute.
            idx (int): Numeric index to prefix folder names.

        Returns:
            str: Path to the output directory.

        Raises:
            FileSystemError: If there are issues with file system operations.
        """
        current_dir = os.getcwd()
        
        # Find agent folder
        agent_folder = try_operation(
            lambda: FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io'),
            f"Failed to find agent folder for agent {agent_name}",
            DirectoryError,
            directory=f"agent_io/{agent_name}"
        )
        
        if agent_folder is None:
            raise DirectoryError(
                directory=f"agent_io/{agent_name}",
                reason=f"Agent folder not found for agent: {agent_name}"
            )

        # Set up directories
        indexed_agent_type = f"node_{idx}_{agent_config['agent_type']}"

        if previous_agent_type:
            prev_idx = idx - 1
            indexed_previous_agent_type = f"node_{prev_idx}_{previous_agent_type}"
            input_directory = os.path.join(agent_folder, 'target', indexed_previous_agent_type)
        else:
            input_directory = os.path.join(agent_folder, 'staging')

        output_directory = os.path.join(
            agent_folder, 'target', indexed_agent_type
        )

        # Create output directory if it doesn't exist
        try_operation(
            lambda: os.makedirs(output_directory, exist_ok=True),
            f"Failed to create output directory: {output_directory}",
            DirectoryError,
            directory=output_directory
        )

        # Process files
        files_processed = False

        for root, _, files in os.walk(input_directory):
            if files:
                files_processed = True
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    strategy.execute(
                        agent_config,
                        agent_name,
                        file_path,
                        input_directory,
                        output_directory
                    )
                except Exception as e:
                    raise FileProcessingError(
                        file_path=file_path, 
                        reason=str(e)
                    )

        if not files_processed:
            raise NoFilesFoundError(directory=input_directory)

        return output_directory

    @handle_errors()
    def run_agent(self, agent_config, agent_name, previous_agent_type, idx, is_last_agent=False):
        """
        Runs an agent with the appropriate strategy based on its position in the workflow.

        Args:
            agent_config (dict): Configuration for the agent
            agent_name (str): Name of the agent
            previous_agent_type (str): Type of the previous agent in workflow
            idx (int): Current agent's index in workflow
            is_last_agent (bool): Flag indicating if this is the last agent

        Returns:
            str: Path to the output directory
            
        Raises:
            FileSystemError: If there are issues with file system operations.
        """
        # Select strategy based on position
        if idx == 0:
            strategy = self.strategies['initial']
        elif is_last_agent:
            strategy = self.strategies['terminal']
        else:
            strategy = self.strategies['intermediate']

        # Find agent folder
        current_dir = os.getcwd()
        agent_folder = try_operation(
            lambda: FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io'),
            f"Failed to find agent folder for agent {agent_name}",
            DirectoryError,
            directory=f"agent_io/{agent_name}"
        )

        if agent_folder is None:
            raise DirectoryError(
                directory=f"agent_io/{agent_name}",
                reason=f"Agent folder not found for agent: {agent_name}"
            )

        # Process and generate output
        output_folder = self.process_and_generate_for_agent(
            agent_config,
            agent_name,
            previous_agent_type,
            strategy,
            idx
        )
        
        return output_folder