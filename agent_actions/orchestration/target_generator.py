"""Module for target data generation based on configuration."""
from dataclasses import dataclass
from pathlib import Path
import json
from typing import Optional, Dict, Any

from agent_actions.input_loading.file_reader import FileReader
from agent_actions.io.file_writer import FileWriter
from agent_actions.llm_invocation.realtime.output_handler import OutputHandler
from agent_actions.errors import (
    AgentActionsException,
    ConfigurationError,
    DependencyError
)
from agent_actions.utilities.constants import MODEL_VENDOR_KEY
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.dependency_injection import ProcessorFactory
from agent_actions.utilities.safe_format import safe_format_error
from agent_actions.configuration.factory import create_target_content_processor

TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'


@dataclass
class GeneratorConfig:
    """Configuration for TargetGenerator."""
    agent_config: Dict[str, Any]
    agent_name: str
    idx: int
    agent_configs: Optional[Dict[str, Any]] = None


@dataclass
class BatchGenerationParams:
    """Parameters for batch generation."""
    generator_agent_config: Dict[str, Any]
    generator_agent_name: str
    batch_file_path: str
    batch_base_directory: str
    batch_output_directory: str
    batch_agent_configs: Optional[Dict[str, Any]] = None


@dataclass
class FilePathsConfig:
    """File paths configuration."""
    file_path: str
    base_directory: str
    output_directory: str


@dataclass
class GenerateParams:
    """Parameters for target generation."""
    agent_config: Dict[str, Any]
    agent_name: str
    paths: FilePathsConfig
    idx: int
    processor_factory: Optional[ProcessorFactory]
    agent_configs: Optional[Dict[str, Any]] = None

class TargetGenerator:
    """
    Responsible for generating target data from input files based on
    configuration.
    """

    def __init__(self, config: GeneratorConfig, processor_factory: ProcessorFactory):
        """
        Initialize the target generator.

        Args:
            config: GeneratorConfig with agent configuration
            processor_factory: Required factory for creating processors with DI

        Raises:
            DependencyError: If processor_factory is not provided
            ConfigurationError: If agent_config is None or invalid
        """
        if config.agent_config is None:
            raise ConfigurationError(
                f"agent_config is None for agent '{config.agent_name}'. "
                f"This usually means the agent is not defined in the "
                f"workflow configuration or the configuration failed to "
                f"load properly. Please check your workflow YAML file.",
                context={'agent_name': config.agent_name, 'idx': config.idx}
            )

        self.config = config
        self.model_vendor = (config.agent_config.get(MODEL_VENDOR_KEY) or '').lower()
        self.granularity = (config.agent_config.get('granularity') or '').lower()
        self.side_output_enabled = config.agent_config.get('side_output', False)
        if processor_factory is None:
            raise DependencyError(
                'TargetGenerator requires processor_factory',
                {
                    'component': 'TargetGenerator',
                    'dependency': 'processor_factory',
                    'agent_name': config.agent_name
                }
            )
        self.content_processor = create_target_content_processor(
            agent_config=config.agent_config,
            agent_name=config.agent_name,
            idx=config.idx,
            agent_configs=config.agent_configs
        )
        self.output_handler = OutputHandler()

    @staticmethod
    def _handle_batch_generation(params: BatchGenerationParams) -> str:
        """Handle batch mode generation."""
        agent_indices = None
        if params.batch_agent_configs:
            agent_indices = {
                name: config.get('idx', 999)
                for name, config in params.batch_agent_configs.items()
                if config is not None and 'idx' in config
            }

        batch_service = BatchService(
            agent_indices=agent_indices,
            dependency_configs=params.batch_agent_configs
        )
        file_reader = FileReader(params.batch_file_path)
        data = file_reader.read()
        file_name = Path(params.batch_file_path).name
        result = batch_service.submit_batch_job(
            params.generator_agent_config, file_name, data, params.batch_output_directory
        )
        relative_path = Path(params.batch_file_path).relative_to(params.batch_base_directory)
        output_file_path = Path(params.batch_output_directory) / relative_path
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(result, dict) and result.get('type') == 'passthrough':
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(result['data'])
            marker = output_file_path.parent / '.passthrough_processed'
            marker.touch()
            return str(output_file_path)

        placeholder = {
            'batch_job_id': result,
            'status': 'submitted',
            'agent': params.generator_agent_name
        }
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(placeholder, f)
        return str(output_file_path)

    @staticmethod
    def generate(params: GenerateParams):
        """
        Static method for generating target data.

        Args:
            params: GenerateParams containing all generation parameters

        Returns:
            Path to the generated output file

        Raises:
            DependencyError: If processor_factory is not provided
        """
        if params.processor_factory is None:
            raise DependencyError(
                'TargetGenerator.generate requires processor_factory',
                {
                    'method': 'TargetGenerator.generate',
                    'dependency': 'processor_factory',
                    'agent_name': params.agent_name
                }
            )
        if params.agent_config.get('run_mode') == 'batch':
            return TargetGenerator._handle_batch_generation(
                BatchGenerationParams(
                    generator_agent_config=params.agent_config,
                    generator_agent_name=params.agent_name,
                    batch_file_path=params.paths.file_path,
                    batch_base_directory=params.paths.base_directory,
                    batch_output_directory=params.paths.output_directory,
                    batch_agent_configs=params.agent_configs
                )
            )
        generator = create_target_generator_from_params(
            agent_config=params.agent_config,
            agent_name=params.agent_name,
            idx=params.idx,
            processor_factory=params.processor_factory,
            agent_configs=params.agent_configs
        )
        return generator.process(
            params.paths.file_path,
            params.paths.base_directory,
            params.paths.output_directory
        )

    def process(
        self, file_path: str, base_directory: str, output_directory: str
    ) -> str:
        """
        Process input file and generate output.

        Args:
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be
                saved

        Returns:
            Path to the generated output file
        """
        try:
            data = self._read_input_data(file_path)
            self._process_by_strategy(
                data, file_path, base_directory, output_directory
            )
            relative_path = Path(file_path).relative_to(base_directory)
            return str(Path(output_directory) / relative_path)
        except (AgentActionsException, ConfigurationError, ValueError) as e:
            raise AgentActionsException(
                f'Error generating target: {safe_format_error(e)}',
                context={
                    'file_path': str(file_path),
                    'base_directory': str(base_directory),
                    'output_directory': str(output_directory),
                    'agent_name': self.config.agent_name
                },
                cause=e
            ) from e
        except (OSError, IOError, TypeError, KeyError) as e:
            raise AgentActionsException(
                f'Unexpected error generating target: {safe_format_error(e)}',
                context={
                    'file_path': str(file_path),
                    'base_directory': str(base_directory),
                    'output_directory': str(output_directory),
                    'agent_name': self.config.agent_name
                },
                cause=e
            ) from e

    def _read_input_data(self, file_path):
        """Read data from input file."""
        file_reader = FileReader(file_path)
        return file_reader.read()

    def _handle_batch_mode(
        self, _data: Any, file_path: str, base_directory: str, output_directory: str
    ):
        """Handle batch mode processing.

        Args:
            _data: Input data (unused, kept for interface consistency)
            file_path: Path to the input file
            base_directory: Base directory for processing
            output_directory: Directory for output files
        """
        result_path = self._handle_batch_generation(
            BatchGenerationParams(
                generator_agent_config=self.config.agent_config,
                generator_agent_name=self.config.agent_name,
                batch_file_path=file_path,
                batch_base_directory=base_directory,
                batch_output_directory=output_directory,
                batch_agent_configs=self.config.agent_configs
            )
        )
        return result_path

    def _process_by_strategy(
        self,
        data: Any,
        file_path: str,
        base_directory: str,
        output_directory: str,
    ):
        """
        Select and apply the appropriate processing strategy based on
        configuration. Async for record granularity.
        """
        if self.config.agent_config.get('run_mode') == 'batch':
            self._handle_batch_mode(data, file_path, base_directory, output_directory)
            return

        if (
            self.model_vendor == TOOL_VENDOR and
            self.granularity == 'record' and
            self.side_output_enabled
        ):
            main_output, side_output_data = (
                self.content_processor.process_for_side_output(
                    data, file_path, output_directory
                )
            )
            self.output_handler.save_main_output(
                main_output, file_path, base_directory, output_directory
            )
            if side_output_data:
                self.output_handler.save_side_output(
                    side_output_data, file_path, base_directory,
                    output_directory
                )
        elif self.model_vendor == TOOL_VENDOR and self.granularity == 'file':
            output = self.content_processor.process_file_level(
                data, file_path, output_directory
            )
            self.output_handler.save_main_output(
                output, file_path, base_directory, output_directory
            )
        elif self.granularity == 'record':
            output = self.content_processor.process(
                data, file_path, output_directory
            )
            self.output_handler.save_main_output(
                output, file_path, base_directory, output_directory
            )


def create_target_generator(
    config: GeneratorConfig,
    processor_factory: ProcessorFactory
) -> TargetGenerator:
    """
    Factory function for creating a TargetGenerator instance.

    Args:
        config: GeneratorConfig with agent configuration
        processor_factory: Required factory for creating processors with DI

    Returns:
        TargetGenerator instance
    """
    return TargetGenerator(config, processor_factory)


def create_target_generator_from_params(
    agent_config: Dict[str, Any],
    agent_name: str,
    idx: int,
    processor_factory: ProcessorFactory,
    agent_configs: Optional[Dict[str, Any]] = None
) -> TargetGenerator:
    """
    Factory function for creating a TargetGenerator instance from individual parameters.

    Args:
        agent_config: Configuration for the agent
        agent_name: Name of the agent
        idx: Index of the agent
        processor_factory: Required factory for creating processors with DI
        agent_configs: Optional dictionary of all agent configurations

    Returns:
        TargetGenerator instance
    """
    config = GeneratorConfig(
        agent_config=agent_config,
        agent_name=agent_name,
        idx=idx,
        agent_configs=agent_configs
    )
    return TargetGenerator(config, processor_factory)
