"""Module for processing target content with specialized components."""
from typing import Dict, Any, List, Tuple, Optional

from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.transformers.data_transformer import DataTransformer

from .interfaces import IContentProcessor
from agent_actions.processors.source_processor.source_data_loader import SourceDataLoader
from .few_shot_sample_manager import FewShotSampleManager
from .data_generator import DataGenerator
from .data_processor import DataProcessor


class TargetContentProcessor(IContentProcessor):
    """Orchestrates the target content processing workflow."""

    def __init__(self, agent_config: Dict, agent_name: str):
        """
        Initialize the target content processor.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        
        # Initialize component services
        self.source_loader = SourceDataLoader(agent_name)
        self.sample_manager = FewShotSampleManager(agent_config, agent_name)
        self.data_generator = DataGenerator(agent_config, agent_name)
        self.data_processor = DataProcessor(agent_config)

    def process(self, data: List[Dict], file_path: str) -> List[Dict]:
        """
        Process a list of data items.
        
        Args:
            data: List of data items to process
            file_path: Path to the file containing the data
            
        Returns:
            List of processed data items
            
        Raises:
            RuntimeError: If processing fails
        """
        try:
            source_data = self.source_loader.load_source_data(file_path)
            processed_data = []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    processed_data.extend(processed_item)
                except Exception as e:
                    guid = item.get('guid', 'unknown')
                    raise ValueError(f"Failed to process item with GUID {guid}: {str(e)}")

            return processed_data
        except Exception as e:
            raise RuntimeError(f"Failed to process content: {str(e)}")

    def process_for_side_output(
        self, 
        data: List[Dict], 
        file_path: str
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Process data and separate into main and side outputs.
        
        Args:
            data: List of data items to process
            file_path: Path to the file containing the data
            
        Returns:
            Tuple of (main_output, side_output)
            
        Raises:
            RuntimeError: If processing fails
        """
        try:
            source_data = self.source_loader.load_source_data(file_path)
            all_processed_items = []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    all_processed_items.extend(processed_item)
                except Exception as e:
                    guid = item.get('guid', 'unknown')
                    raise ValueError(f"Failed to process item with GUID {guid}: {str(e)}")

            # Separate main and side outputs
            return self.data_processor.separate_side_output(all_processed_items)
        except Exception as e:
            raise RuntimeError(f"Failed to process for side output: {str(e)}")

    def process_file_level(self, data: List[Dict]) -> List[Dict]:
        """
        Process data at the file level.
        
        Args:
            data: List of data items to process
            
        Returns:
            Processed data
            
        Raises:
            RuntimeError: If processing fails
        """
        try:
            contents, guid = data[0]['content'], data[0]['guid']
            generated_data = self.data_generator.create_agent_with_data(data)
            return self.data_processor.process_item(contents, generated_data, guid)
        except Exception as e:
            raise RuntimeError(f"Failed to process at file level: {str(e)}")

    def _process_single_item(
        self, 
        item: Dict, 
        source_data: List[Dict]
    ) -> List[Dict]:
        """
        Process a single data item.
        
        Args:
            item: Data item to process
            source_data: Source data for reference
            
        Returns:
            Processed data item
            
        Raises:
            ValueError: If item processing fails
        """
        try:
            contents, guid = item['content'], item['guid']
            
            # Get corresponding source content
            source_content = DataTransformer.get_content_by_guid(source_data, guid)
            
            # Add few-shot samples
            contents = self.sample_manager.add_few_shot_samples(contents)
            
            # Check conditional clause
            conditional_clause = self.agent_config.get('conditional_clause', '').lower()
            if conditional_clause:
                # For conditional_clause UDFs, only pass the primary 'contents' data.
                # This prevents TypeErrors for UDFs not defined to accept extra context kwargs.
                if execute_user_defined_function(conditional_clause, contents):
                    # Generate data with agent
                    generated_data = self.data_generator.create_agent_with_data(
                        contents, source_content
                    )
                else:
                    # Skip agent generation, use contents directly
                    generated_data = [contents]
            else:
                # No conditional clause, always generate
                generated_data = self.data_generator.create_agent_with_data(
                    contents, source_content
                )
            
            # Process the generated data
            return self.data_processor.process_item(contents, generated_data, guid)
        except Exception as e:
            raise ValueError(f"Failed to process item: {str(e)}")