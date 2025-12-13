"""Module for managing and executing agents with different strategies in a workflow."""
import logging
from pathlib import Path
from typing import Tuple, Dict, Optional, List
from agent_actions.io.file_handler import FileHandler
from agent_actions.orchestration.agent_strategies import InitialStrategy, StandardStrategy, AgentStrategy
from agent_actions.orchestration.dependency_injection import ProcessorFactory

logger = logging.getLogger(__name__)

class AgentRunner:
    """
    Manages the execution of agents using different strategies in a workflow.
    
    Handles the selection and application of appropriate strategies (initial,
    intermediate, or terminal) for each agent in the workflow sequence.
    """

    def __init__(self, use_tools: bool, processor_factory: Optional[ProcessorFactory]=None) -> None:
        """
        Initialize the AgentRunner with strategy configurations.

        Args:
            use_tools (bool): Flag indicating whether to use tools during agent execution.
            processor_factory (Optional[ProcessorFactory]): Factory for creating processors with DI.
        """
        self.use_tools: bool = use_tools
        self.processor_factory = processor_factory
        self.agent_configs: Optional[Dict[str, Dict]] = None
        self.workflow_name: Optional[str] = None  # Set by AgentWorkflow for agent_io folder lookups
        self.strategies: Dict[str, AgentStrategy] = {
            'initial': InitialStrategy(processor_factory),
            'intermediate': StandardStrategy(processor_factory),
            'terminal': StandardStrategy(processor_factory)
        }
    def get_agent_folder(self, agent_name: str) -> str:
        """
        Retrieves the agent folder using FileHandler.

        Args:
            agent_name (str): Name of the agent (or workflow name if workflow_name is not set).

        Returns:
            str: Path to the agent folder.

        Raises:
            ValueError: If the agent folder is not found.
        """
        from agent_actions.errors import FileSystemError  # New modular pattern!
        current_dir: Path = Path.cwd()
        # Use workflow_name if set (for multi-agent workflows), otherwise use agent_name (for single-agent or legacy)
        folder_name = self.workflow_name if self.workflow_name else agent_name
        agent_folder: Optional[str] = FileHandler.find_specific_folder(str(current_dir), folder_name, 'agent_io')
        if agent_folder is None:
            raise FileSystemError(f'Agent folder not found for agent: {agent_name}', context={'agent_name': agent_name, 'workflow_name': folder_name, 'current_dir': str(current_dir), 'operation': 'get_agent_folder'})
        return agent_folder

    def setup_directories(self, agent_folder: str, agent_config: Dict, previous_agent_type: Optional[str], idx: int) -> Tuple[List[str], str]:
        """
        Sets up input and output directories for the agent.

        Args:
            agent_folder (str): Path to the agent folder.
            agent_config (dict): Configuration for the agent.
            previous_agent_type (Optional[str]): Type of the previous agent in workflow.
            idx (int): Numeric index to prefix folder names.

        Returns:
            Tuple[List[str], str]: (upstream_data_dirs, output_directory)
        """
        indexed_agent_type: str = f"node_{idx}_{agent_config['agent_type']}"
        dependencies = agent_config.get('dependencies', [])
        upstream_data_dirs: List[Path] = []

        # 1. Start Node: Always reads from Staging
        if idx == 0:
             upstream_data_dirs.append(Path(agent_folder) / 'staging')
        
        # 2. Explicit Dependencies (DAG/Diamond)
        elif dependencies and hasattr(self, 'agent_indices') and self.agent_indices:
            for dep_name in dependencies:
                dep_idx = self.agent_indices.get(dep_name)
                if dep_idx is not None:
                     indexed_previous_agent_type: str = f'node_{dep_idx}_{dep_name}'
                     upstream_data_dirs.append(Path(agent_folder) / 'target' / indexed_previous_agent_type)
                else:
                    # Fallback for missing index (shouldn't happen in valid workflow)
                    logger.warning(f'Dependency {dep_name} index not found.')

        # 3. Default Linear Behavior
        elif previous_agent_type:
             prev_idx: int = idx - 1
             indexed_previous_agent_type: str = f'node_{prev_idx}_{previous_agent_type}'
             upstream_data_dirs.append(Path(agent_folder) / 'target' / indexed_previous_agent_type)
        else:
             # Fallback if no previous agent and not index 0 (rare edge case)
             upstream_data_dirs.append(Path(agent_folder) / 'staging')

        output_directory: Path = Path(agent_folder) / 'target' / indexed_agent_type
        output_directory.mkdir(parents=True, exist_ok=True)
        return ([str(d) for d in upstream_data_dirs], str(output_directory))

    def process_files(self, agent_config: Dict, agent_name: str, strategy: AgentStrategy, upstream_data_dirs: List[str], output_directory: str, idx: int) -> None:
        """
        Walks through the upstream data directories, processing each file with the given strategy,
        explicitly excluding:
        - Any directory named 'batch'
        - Hidden files (starting with '.')
        - Marker files (e.g., .passthrough_processed)

        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            strategy (AgentStrategy): Strategy instance to execute.
            upstream_data_dirs (List[str]): List of paths to upstream data directories.
            output_directory (str): Path to the output directory.
            idx (int): Index of the config being processed.

        Raises:
            ValueError: If no files are found in the input directory.
        """
        files_processed_count: int = 0
        output_path = Path(output_directory)
        
        for input_directory in upstream_data_dirs:
            input_path = Path(input_directory)
            if not input_path.exists():
                logger.warning(f"Upstream directory not found: {input_directory}")
                continue
                
            for item in input_path.rglob('*'):
                if 'batch' in item.parts:
                    continue
                if item.is_file():
                    # Skip hidden files and marker files (e.g., .passthrough_processed)
                    if item.name.startswith('.'):
                        logger.debug(f"Skipping hidden/marker file: {item.name}")
                        continue

                    relative_path = item.relative_to(input_path)
                    output_file_path = output_path / relative_path
                    output_file_path.parent.mkdir(parents=True, exist_ok=True)
                    strategy.execute(agent_config, agent_name, str(item), str(input_directory), str(output_file_path.parent), idx, agent_configs=self.agent_configs)
                    files_processed_count += 1
                    
        if files_processed_count == 0:
            # Check if any input path has content
            has_content = any(Path(d).exists() and any(Path(d).iterdir()) for d in upstream_data_dirs)
            
            if not has_content:
                logger.warning(
                    'No files found in upstream directories: %s. Processing continues.',
                    upstream_data_dirs,
                    extra={
                        'upstream_data_dirs': upstream_data_dirs,
                        'agent_name': agent_name,
                        'operation': 'directory_processing'
                    }
                )
            else:
                logger.info(
                    'No files to process in %s (potentially filtered), but directory structure was mirrored. Processing continues.',
                    upstream_data_dirs,
                    extra={
                        'upstream_data_dirs': upstream_data_dirs,
                        'agent_name': agent_name,
                        'operation': 'directory_processing'
                    }
                )

    def process_and_generate_for_agent(self, agent_config: Dict, agent_name: str, previous_agent_type: Optional[str], strategy: AgentStrategy, idx: int) -> str:
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
        input_directories, output_directory = self.setup_directories(agent_folder, agent_config, previous_agent_type, idx)
        self.process_files(agent_config, agent_name, strategy, input_directories, output_directory, idx)
        return output_directory

    def run_agent(self, agent_config: Dict, agent_name: str, previous_agent_type: Optional[str], idx: int, is_last_agent: bool=False) -> str:
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
            strategy_name = 'initial'
        else:
            strategy_name = 'intermediate'

        strategy = self.strategies[strategy_name]
        output_folder: str = self.process_and_generate_for_agent(agent_config, agent_name, previous_agent_type, strategy, idx)
        return output_folder