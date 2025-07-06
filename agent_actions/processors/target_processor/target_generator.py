"""Module for target data generation based on configuration."""
from pathlib import Path
import json
from agent_actions.handlers.file_reader import FileReader
from agent_actions.processors.target_processor import TargetContentProcessor
from .output_handler import OutputHandler
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError
from agent_actions.constants import MODEL_VENDOR_KEY
from agent_actions.services.batch_service import BatchService

# Constants
TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'


class TargetGenerator:
    """Responsible for generating target data from input files based on configuration."""
    
    def __init__(self, agent_config, agent_name):
        """
        Initialize the target generator.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.model_vendor = agent_config.get(MODEL_VENDOR_KEY, '').lower()
        self.granularity = agent_config.get('granularity', '').lower()
        self.side_output_enabled = agent_config.get('side_output', False)
        self.content_processor = TargetContentProcessor(agent_config, agent_name)
        self.output_handler = OutputHandler()
    
    @staticmethod
    def generate(agent_config, agent_name, file_path, base_directory, output_directory):
        """
        Static method for generating target data (maintains original function signature).
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
            
        Returns:
            Path to the generated output file for compatibility
        """
        if agent_config.get('run_mode') == 'batch':
            batch_service = BatchService()
            file_reader = FileReader(file_path)
            data = file_reader.read()
            batch_id = batch_service.submit_batch_job_from_data(agent_config, agent_name, data, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            placeholder = {
                "batch_job_id": batch_id,
                "status": "submitted",
                "agent": agent_name
            }
            with open(output_file_path, 'w') as f:
                json.dump(placeholder, f)
            return str(output_file_path)

        generator = TargetGenerator(agent_config, agent_name)
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
            # Read input data
            data = self._read_input_data(file_path)
            
            # Process according to configuration
            self._process_by_strategy(data, file_path, base_directory, output_directory)
            
            # Return the output file path for compatibility
            relative_path = Path(file_path).relative_to(base_directory)
            return str(Path(output_directory) / relative_path)
        except (AgentActionsError, ConfigurationError, ValueError) as e: # Catch known specific errors
            # Log e if necessary, or let it propagate if it's already informative
            raise AgentActionsError(f"Error generating target for {file_path}: {str(e)}") from e
        except Exception as e:
            raise AgentActionsError(f"Unexpected error generating target for {file_path}: {str(e)}") from e
    
    def _read_input_data(self, file_path):
        """Read data from input file."""
        file_reader = FileReader(file_path)
        return file_reader.read()
    
    def _process_by_strategy(self, data, file_path, base_directory, output_directory):
        """Select and apply the appropriate processing strategy based on configuration."""
        # Tool vendor with record granularity and side output
        if self.model_vendor == TOOL_VENDOR and self.granularity == 'record' and self.side_output_enabled:
            main_output, side_output_data = self.content_processor.process_for_side_output(data, file_path, output_directory)
            self.output_handler.save_main_output(main_output, file_path, base_directory, output_directory)
            
            if side_output_data:
                self.output_handler.save_side_output(side_output_data, file_path, base_directory, output_directory)
        
        # Tool vendor with file granularity
        elif self.model_vendor == TOOL_VENDOR and self.granularity == 'file':
            output = self.content_processor.process_file_level(data, output_directory)
            self.output_handler.save_main_output(output, file_path, base_directory, output_directory)
        
        # Record granularity (default)
        elif self.granularity == 'record':
            output = self.content_processor.process(data, file_path, output_directory)
            self.output_handler.save_main_output(output, file_path, base_directory, output_directory)