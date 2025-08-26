"""Module for target data generation based on configuration."""
from pathlib import Path
import json
from typing import Optional
from agent_actions.handlers.file_reader import FileReader
from agent_actions.handlers.file_writer import FileWriter
from agent_actions.processors.target_processor import TargetContentProcessor
from .output_handler import OutputHandler
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError
from agent_actions.constants import MODEL_VENDOR_KEY
from agent_actions.services.batch_service import BatchService
from ...core.dependency_injection import ProcessorFactory

# Constants
TOOL_VENDOR = 'tool'
SOURCE_FOLDER = 'source'


class TargetGenerator:
    """Responsible for generating target data from input files based on configuration."""
    
    def __init__(self, agent_config, agent_name, idx, processor_factory: Optional[ProcessorFactory] = None):
        """
        Initialize the target generator.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            processor_factory: Optional factory for creating processors with DI
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.idx = idx
        self.model_vendor = agent_config.get(MODEL_VENDOR_KEY, '').lower()
        self.granularity = agent_config.get('granularity', '').lower()
        self.side_output_enabled = agent_config.get('side_output', False)
        
        # Use processor factory with proper DI
        if processor_factory:
            # Use bootstrap.create_target_content_processor() for proper DI setup
            from ...bootstrap import create_target_content_processor
            self.content_processor = create_target_content_processor(
                agent_config=agent_config,
                agent_name=agent_name,
                idx=idx
            )
        else:
            # Direct instantiation when no DI is available
            self.content_processor = TargetContentProcessor(agent_config, agent_name, idx)
        
        self.output_handler = OutputHandler()
    
    @staticmethod
    def generate(agent_config, agent_name, file_path, base_directory, output_directory, idx):
        """
        Static method for generating target data (maintains original function signature).
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
            idx: Index of the config being processed
        
        Returns:
            Path to the generated output file for compatibility
        """
        if agent_config.get('run_mode') == 'batch':
            batch_service = BatchService()
            file_reader = FileReader(file_path)
            data = file_reader.read()
            file_name = Path(file_path).name
            result = batch_service.submit_batch_job_from_data(agent_config, file_name, data, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                # Write passthrough data directly to output
                file_writer = FileWriter(str(output_file_path))
                file_writer.write_target(result['data'])
                
                # Create a marker file to indicate this was passthrough processing
                passthrough_marker = output_file_path.parent / ".passthrough_processed"
                passthrough_marker.touch()
                
                return str(output_file_path)
            else:
                # Create batch placeholder as before
                placeholder = {
                    "batch_job_id": result,
                    "status": "submitted",
                    "agent": agent_name
                }
                with open(output_file_path, 'w') as f:
                    json.dump(placeholder, f)
                return str(output_file_path)

        generator = TargetGenerator(agent_config, agent_name, idx)
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
        """Select and apply the appropriate processing strategy based on configuration. Async for record granularity."""
        # Handle batch mode first - it needs special handling for all strategies
        if self.agent_config.get('run_mode') == 'batch':
            batch_service = BatchService()
            file_name = Path(file_path).name
            result = batch_service.submit_batch_job_from_data(self.agent_config, file_name, data, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                # Write passthrough data directly to output
                file_writer = FileWriter(str(output_file_path))
                file_writer.write_target(result['data'])
                
                # Create a marker file to indicate this was passthrough processing
                passthrough_marker = output_file_path.parent / ".passthrough_processed"
                passthrough_marker.touch()
            else:
                # Create batch placeholder
                placeholder = {
                    "batch_job_id": result,
                    "status": "submitted",
                    "agent": self.agent_name
                }
                with open(output_file_path, 'w') as f:
                    json.dump(placeholder, f)
            return  # Early return for batch mode
        
        # Non-batch mode processing
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