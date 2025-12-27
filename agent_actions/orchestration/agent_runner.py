# pylint: disable=duplicate-code
"""Module for managing and executing agents with different strategies in a workflow."""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Dict, Optional, List
from agent_actions.errors import FileSystemError
from agent_actions.io.file_handler import FileHandler
from agent_actions.orchestration.agent_strategies import (
    InitialStrategy,
    StandardStrategy,
    AgentStrategy,
    StrategyExecutionParams
)
from agent_actions.orchestration.artifact_linker import ArtifactLinker
from agent_actions.orchestration.dependency_injection import ProcessorFactory

logger = logging.getLogger(__name__)


@dataclass
class FileProcessParams:
    """Parameters for processing files."""
    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    upstream_data_dirs: List[str]
    output_directory: str
    idx: int


@dataclass
class FileLocationParams:
    """File location parameters."""
    item: Path
    input_path: Path
    output_path: Path
    input_directory: str


@dataclass
class SingleFileProcessParams:
    """Parameters for processing a single file."""
    locations: FileLocationParams
    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    idx: int


@dataclass
class ProcessGenerateParams:
    """Parameters for process_and_generate_for_agent method."""
    agent_config: Dict
    agent_name: str
    strategy: AgentStrategy
    previous_agent_type: Optional[str]
    idx: int


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
        current_dir: Path = Path.cwd()
        # Use workflow_name if set (for multi-agent workflows),
        # otherwise use agent_name (for single-agent or legacy)
        folder_name = self.workflow_name if self.workflow_name else agent_name
        agent_folder: Optional[str] = FileHandler.find_specific_folder(
            str(current_dir), folder_name, 'agent_io'
        )
        if agent_folder is None:
            raise FileSystemError(
                f'Agent folder not found for agent: {agent_name}',
                context={
                    'agent_name': agent_name,
                    'workflow_name': folder_name,
                    'current_dir': str(current_dir),
                    'operation': 'get_agent_folder'
                }
            )
        return agent_folder

    def _resolve_upstream_from_manifest(self, agent_folder: Path) -> Optional[List[Path]]:
        """
        Resolve upstream directories from manifest file.

        When a workflow depends on an upstream workflow, the artifact linker
        writes a manifest file pointing to the upstream's output. This method
        reads that manifest and returns the upstream path(s).

        Args:
            agent_folder: Path to the agent's folder (contains agent_io).

        Returns:
            List of upstream paths from manifest, or None if no manifest exists.
        """
        agent_io_dir = (
            agent_folder / 'agent_io' if 'agent_io' not in str(agent_folder) else agent_folder
        )
        manifest = ArtifactLinker.read_manifest(agent_io_dir)
        if manifest is None:
            return None

        upstream_path = Path(manifest['upstream_path'])
        if not upstream_path.exists():
            logger.warning(
                "Manifest upstream path doesn't exist: %s",
                upstream_path
            )
            return None

        logger.debug(
            "Resolved upstream from manifest: %s",
            upstream_path
        )
        return [upstream_path]

    def setup_directories(
        self,
        agent_folder: str,
        agent_config: Dict,
        previous_agent_type: Optional[str],
        idx: int
    ) -> Tuple[List[str], str]:
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

        # 1. Start Node: Check manifest first, fall back to staging
        if idx == 0:
            # Try manifest-based resolution first (for inter-workflow dependencies)
            manifest_dirs = self._resolve_upstream_from_manifest(Path(agent_folder))
            if manifest_dirs:
                upstream_data_dirs.extend(manifest_dirs)
            else:
                # Fall back to staging for direct file input
                staging_dir = Path(agent_folder) / 'staging'
                upstream_data_dirs.append(staging_dir)

        # 2. Explicit Dependencies (DAG/Diamond)
        elif dependencies and hasattr(self, 'agent_indices') and self.agent_indices:
            for dep_name in dependencies:
                dep_idx = self.agent_indices.get(dep_name)
                if dep_idx is not None:
                    indexed_previous_agent_type: str = f'node_{dep_idx}_{dep_name}'
                    upstream_data_dirs.append(
                        Path(agent_folder) / 'target' / indexed_previous_agent_type
                    )
                else:
                    # Fallback for missing index (shouldn't happen)
                    logger.warning(
                        'Dependency %s index not found.', dep_name
                    )

        # 3. Default Linear Behavior
        elif previous_agent_type:
            prev_idx: int = idx - 1
            indexed_previous_agent_type: str = f'node_{prev_idx}_{previous_agent_type}'
            upstream_data_dirs.append(
                Path(agent_folder) / 'target' / indexed_previous_agent_type
            )
        else:
            # Fallback if no previous agent and not index 0 (rare edge case)
            upstream_data_dirs.append(Path(agent_folder) / 'staging')

        output_directory: Path = Path(agent_folder) / 'target' / indexed_agent_type
        output_directory.mkdir(parents=True, exist_ok=True)
        return ([str(d) for d in upstream_data_dirs], str(output_directory))

    def _process_single_file(self, params: SingleFileProcessParams):
        """Process a single file with the strategy."""
        relative_path = params.locations.item.relative_to(params.locations.input_path)
        output_file_path = params.locations.output_path / relative_path
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        params.strategy.execute(
            StrategyExecutionParams(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                file_path=str(params.locations.item),
                base_directory=str(params.locations.input_directory),
                output_directory=str(output_file_path.parent),
                idx=params.idx,
                agent_configs=self.agent_configs
            )
        )

    def _should_skip_file(self, item: Path, processed_paths: set) -> bool:
        """Check if file should be skipped."""
        if item.name.startswith('.'):
            logger.debug("Skipping hidden/marker file: %s", item.name)
            return True
        relative_path = item.relative_to(item.parent)
        if relative_path in processed_paths:
            logger.debug("Skipping duplicate file: %s", relative_path)
            return True
        return False

    def process_files(self, params: FileProcessParams) -> None:
        """
        Walks through the upstream data directories, processing each file with the given strategy,
        explicitly excluding:
        - Any directory named 'batch'
        - Hidden files (starting with '.')
        - Marker files (e.g., .passthrough_processed)

        Args:
            params: FileProcessParams containing all processing parameters

        Raises:
            ValueError: If no files are found in the input directory.
        """
        files_processed_count: int = 0
        output_path = Path(params.output_directory)
        processed_relative_paths: set = set()

        for input_directory in params.upstream_data_dirs:
            input_path = Path(input_directory)
            if not input_path.exists():
                logger.warning(
                    "Upstream directory not found: %s", input_directory
                )
                continue

            for item in input_path.rglob('*'):
                if 'batch' in item.parts:
                    continue
                if item.is_file():
                    relative_path = item.relative_to(input_path)
                    if relative_path in processed_relative_paths:
                        continue
                    if item.name.startswith('.'):
                        continue

                    processed_relative_paths.add(relative_path)
                    self._process_single_file(
                        SingleFileProcessParams(
                            locations=FileLocationParams(
                                item=item,
                                input_path=input_path,
                                output_path=output_path,
                                input_directory=input_directory
                            ),
                            agent_config=params.agent_config,
                            agent_name=params.agent_name,
                            strategy=params.strategy,
                            idx=params.idx
                        )
                    )
                    files_processed_count += 1

        if files_processed_count == 0:
            # Check if any input path has content
            has_content = any(
                Path(d).exists() and any(Path(d).iterdir())
                for d in params.upstream_data_dirs
            )

            if not has_content:
                logger.warning(
                    'No files found in upstream directories: %s. Processing continues.',
                    params.upstream_data_dirs,
                    extra={
                        'upstream_data_dirs': params.upstream_data_dirs,
                        'agent_name': params.agent_name,
                        'operation': 'directory_processing'
                    }
                )
            else:
                logger.info(
                    'No files to process in %s (potentially filtered), '
                    'but directory structure was mirrored. '
                    'Processing continues.',
                    params.upstream_data_dirs,
                    extra={
                        'upstream_data_dirs': params.upstream_data_dirs,
                        'agent_name': params.agent_name,
                        'operation': 'directory_processing'
                    }
                )

    def process_and_generate_for_agent(self, params: ProcessGenerateParams) -> str:
        """
        Processes and generates data for an agent using the provided strategy.

        Args:
            params: ProcessGenerateParams containing all required parameters

        Returns:
            str: Path to the output directory.
        """
        agent_folder: str = self.get_agent_folder(params.agent_name)
        input_directories, output_directory = self.setup_directories(
            agent_folder, params.agent_config, params.previous_agent_type, params.idx
        )
        self.process_files(
            FileProcessParams(
                agent_config=params.agent_config,
                agent_name=params.agent_name,
                strategy=params.strategy,
                upstream_data_dirs=input_directories,
                output_directory=output_directory,
                idx=params.idx
            )
        )
        return output_directory

    def run_agent(
        self,
        agent_config: Dict,
        agent_name: str,
        previous_agent_type: Optional[str],
        idx: int,
        _is_last_agent: bool = False
    ) -> str:
        """
        Runs an agent with the appropriate strategy based on its position.

        Args:
            agent_config (dict): Configuration for the agent.
            agent_name (str): Name of the agent.
            previous_agent_type (Optional[str]): Type of previous agent.
            idx (int): Current agent's index in workflow.
            _is_last_agent (bool): Flag indicating if this is the last agent.

        Returns:
            str: Path to the output directory.
        """
        if idx == 0:
            strategy_name = 'initial'
        else:
            strategy_name = 'intermediate'

        strategy = self.strategies[strategy_name]
        output_folder: str = self.process_and_generate_for_agent(
            ProcessGenerateParams(
                agent_config=agent_config,
                agent_name=agent_name,
                strategy=strategy,
                previous_agent_type=previous_agent_type,
                idx=idx
            )
        )
        return output_folder
