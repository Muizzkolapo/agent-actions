"""Module for target data generation based on configuration."""
from pathlib import Path
import json
from typing import Optional
from agent_actions.input_loading.file_reader import FileReader
from agent_actions.llm_invocation.realtime.file_writer import FileWriter
from agent_actions.prompt_generation.target_content_processor import TargetContentProcessor
from agent_actions.llm_invocation.realtime.output_handler import OutputHandler
from agent_actions.shared.exceptions import AgentActionsException, ConfigurationError, DependencyError
from agent_actions.utilities.constants import MODEL_VENDOR_KEY
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.dependency_injection import ProcessorFactory
from agent_actions.utilities.safe_format import safe_format_error
TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'

class TargetGenerator:
    """Responsible for generating target data from input files based on configuration."""

    def __init__(self, agent_config, agent_name, idx, processor_factory: ProcessorFactory, agent_configs: Optional[dict]=None):
        """
        Initialize the target generator.

        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            processor_factory: Required factory for creating processors with DI (must be provided)
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution)

        Raises:
            DependencyError: If processor_factory is not provided
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.idx = idx
        self.agent_configs = agent_configs
        self.model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or '').lower()
        self.granularity = (agent_config.get('granularity') or '').lower()
        self.side_output_enabled = agent_config.get('side_output', False)
        if processor_factory is None:
            raise DependencyError('TargetGenerator', 'processor_factory', context={'component': 'TargetGenerator', 'dependency': 'processor_factory', 'agent_name': agent_name})
        from agent_actions.configuration.bootstrap_factory import create_target_content_processor
        self.content_processor = create_target_content_processor(agent_config=agent_config, agent_name=agent_name, idx=idx, agent_configs=agent_configs)
        self.output_handler = OutputHandler()

    @staticmethod
    def generate(agent_config, agent_name, file_path, base_directory, output_directory, idx, processor_factory=None, agent_configs=None):
        """
        Static method for generating target data.

        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
            idx: Index of the config being processed
            processor_factory: Required ProcessorFactory for dependency injection
            agent_configs: Optional dict mapping agent names to their configs (for dependency resolution)

        Returns:
            Path to the generated output file

        Raises:
            DependencyError: If processor_factory is not provided
        """
        if processor_factory is None:
            raise DependencyError('TargetGenerator.generate', 'processor_factory', context={'method': 'TargetGenerator.generate', 'dependency': 'processor_factory', 'agent_name': agent_name})
        if agent_config.get('run_mode') == 'batch':
            batch_service = BatchService()
            file_reader = FileReader(file_path)
            data = file_reader.read()
            file_name = Path(file_path).name
            result = batch_service.submit_batch_job_from_data(agent_config, file_name, data, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                file_writer = FileWriter(str(output_file_path))
                file_writer.write_target(result['data'])
                passthrough_marker = output_file_path.parent / '.passthrough_processed'
                passthrough_marker.touch()
                return str(output_file_path)
            else:
                placeholder = {'batch_job_id': result, 'status': 'submitted', 'agent': agent_name}
                with open(output_file_path, 'w') as f:
                    json.dump(placeholder, f)
                return str(output_file_path)
        generator = TargetGenerator(agent_config, agent_name, idx, processor_factory, agent_configs)
        return generator.process(file_path, base_directory, output_directory)

    def process(self, file_path, base_directory, output_directory):
        """
        Process input file and generate output.
        
        Args:
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
            
        Returns:
            Path to the generated output file
        """
        try:
            data = self._read_input_data(file_path)
            self._process_by_strategy(data, file_path, base_directory, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            return str(Path(output_directory) / relative_path)
        except (AgentActionsException, ConfigurationError, ValueError) as e:
            raise AgentActionsException(f'Error generating target: {safe_format_error(e)}', context={'file_path': str(file_path), 'base_directory': str(base_directory), 'output_directory': str(output_directory), 'agent_name': self.agent_name}, cause=e) from e
        except Exception as e:
            raise AgentActionsException(f'Unexpected error generating target: {safe_format_error(e)}', context={'file_path': str(file_path), 'base_directory': str(base_directory), 'output_directory': str(output_directory), 'agent_name': self.agent_name}, cause=e) from e

    def _read_input_data(self, file_path):
        """Read data from input file."""
        file_reader = FileReader(file_path)
        return file_reader.read()

    def _process_by_strategy(self, data, file_path, base_directory, output_directory):
        """Select and apply the appropriate processing strategy based on configuration. Async for record granularity."""
        if self.agent_config.get('run_mode') == 'batch':
            batch_service = BatchService()
            file_name = Path(file_path).name
            result = batch_service.submit_batch_job_from_data(self.agent_config, file_name, data, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                file_writer = FileWriter(str(output_file_path))
                file_writer.write_target(result['data'])
                passthrough_marker = output_file_path.parent / '.passthrough_processed'
                passthrough_marker.touch()
            else:
                placeholder = {'batch_job_id': result, 'status': 'submitted', 'agent': self.agent_name}
                with open(output_file_path, 'w') as f:
                    json.dump(placeholder, f)
            return
        if self.model_vendor == TOOL_VENDOR and self.granularity == 'record' and self.side_output_enabled:
            main_output, side_output_data = self.content_processor.process_for_side_output(data, file_path, output_directory)
            self.output_handler.save_main_output(main_output, file_path, base_directory, output_directory)
            if side_output_data:
                self.output_handler.save_side_output(side_output_data, file_path, base_directory, output_directory)
        elif self.model_vendor == TOOL_VENDOR and self.granularity == 'file':
            output = self.content_processor.process_file_level(data, file_path, output_directory)
            self.output_handler.save_main_output(output, file_path, base_directory, output_directory)
        elif self.granularity == 'record':
            output = self.content_processor.process(data, file_path, output_directory)
            self.output_handler.save_main_output(output, file_path, base_directory, output_directory)