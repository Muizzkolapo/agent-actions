"""Module for managing and executing agents with different strategies in a workflow."""

import os
import logging
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.core.agent_strategies import (
    InitialStrategy,
    TerminalStrategy,
    IntermediateStrategy
)
from agent_actions.core.errors import (
    ResourceNotFoundError,
    ValidationError,
    ProcessingError,
    handle_errors
)

# Configure logger
logger = logging.getLogger(__name__)

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
            ResourceNotFoundError: If agent folder or input files cannot be found
            ProcessingError: If content processing fails
            ValidationError: If agent configuration is invalid
        """
        current_dir = os.getcwd()
        
        # Find agent folder
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')
        
        if agent_folder is None:
            logger.error(f"Agent folder not found for agent: {agent_name}")
            raise ResourceNotFoundError(f"Agent folder not found for agent: {agent_name}")

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
        os.makedirs(output_directory, exist_ok=True)

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
                except TypeError as e:
                    # Handle the specific case of NoneType unpacking error
                    logger.error(
                        f"Failed to process content for agent {agent_name} with file {file_path}: {str(e)}",
                        exc_info=True
                    )
                    raise ProcessingError(
                        f"Content processing failed for file {file_path}. The staging processor returned invalid data.",
                        original_error=e
                    )
                except Exception as e:
                    logger.error(
                        f"Error executing strategy for agent {agent_name} with file {file_path}: {str(e)}",
                        exc_info=True
                    )
                    raise

        if not files_processed:
            logger.error(f"No files found in directory: {input_directory}")
            raise ResourceNotFoundError(f"No files found in directory: {input_directory}")

        return output_directory

    @handle_errors(ResourceNotFoundError, log_level=logging.ERROR, reraise=True)
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
            ResourceNotFoundError: If agent folder cannot be found
            ValidationError: If agent configuration is invalid
        """
        # Type 1: New Recoverable Error - validate and provide defaults if possible
        if 'agent_type' not in agent_config:
            logger.warning(f"Missing agent_type in configuration for {agent_name}, using 'default'")
            agent_config['agent_type'] = 'default'  # Provide a default value

        # Select strategy based on position
        if idx == 0:
            strategy = self.strategies['initial']
        elif is_last_agent:
            strategy = self.strategies['terminal']
        else:
            strategy = self.strategies['intermediate']

        # Find agent folder
        current_dir = os.getcwd()
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

        if agent_folder is None:
            logger.error(f"Agent folder not found for agent: {agent_name}")
            raise ResourceNotFoundError(f"Agent folder not found for agent: {agent_name}")

        # Process and generate output
        output_folder = self.process_and_generate_for_agent(
            agent_config,
            agent_name,
            previous_agent_type,
            strategy,
            idx
        )
        
        logger.info(f"Successfully processed agent {agent_name} (type: {agent_config['agent_type']})")
        return output_folder