"""Module for processing target content with specialized components."""
from typing import Dict, List, Tuple
import json
import uuid
from agent_actions.services.batch_service import BatchService
from agent_actions.transformers.data_transformer import DataTransformer

from .interfaces import IContentProcessor
from agent_actions.processors.source_processor.source_data_loader import SourceDataLoader
from .data_generator import DataGenerator
from .data_processor import DataProcessor


import asyncio  # For async processing

class TargetContentProcessor(IContentProcessor):
    """Orchestrates the target content processing workflow."""

    def __init__(self, agent_config: Dict, agent_name: str, idx: int):
        """
        Initialize the target content processor.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.idx = idx
        
        # Initialize component services
        self.source_loader = SourceDataLoader(agent_name)
        self.data_generator = DataGenerator(agent_config, agent_name)
        self.data_processor = DataProcessor(agent_config)
        self.batch_service = BatchService()

    async def process_async(self, data: List[Dict], file_path: str, output_directory: str = None) -> List[Dict]:
        """
        Async version: process a list of data items in parallel using asyncio.
        """
        if self.agent_config.get('run_mode') == 'batch':
            self.batch_service.submit_batch_job_from_data(self.agent_config, self.agent_name, data, output_directory)
            return []
        try:
            source_data = self.source_loader.load_source_data(file_path)
            async def process_one(item):
                try:
                    # _process_single_item is sync, so run in thread
                    return await asyncio.to_thread(self._process_single_item, item, source_data)
                except Exception as e:
                    source_guid = item.get('source_guid', 'unknown')
                    raise ValueError(f"Failed to process item with source_guid {source_guid}: {str(e)}")
            results = await asyncio.gather(*(process_one(item) for item in data))
            processed_data = []
            for result in results:
                processed_data.extend(result)
            return processed_data
        except Exception as e:
            raise RuntimeError(f"Failed to process content: {str(e)}")

    def process(self, data: List[Dict], file_path: str, output_directory: str = None) -> List[Dict]:
        """
        Process a list of data items.
        
        Args:
            data: List of data items to process
            file_path: Path to the file containing the data
            output_directory: Directory where batch files should be created
            
        Returns:
            List of processed data items
            
        Raises:
            RuntimeError: If processing fails
        """
        if self.agent_config.get('run_mode') == 'batch':
            self.batch_service.submit_batch_job_from_data(self.agent_config, self.agent_name, data, output_directory)
            return [] # Return empty list to signify batch submission

        try:
            source_data = self.source_loader.load_source_data(file_path)
            processed_data = []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    processed_data.extend(processed_item)
                except Exception as e:
                    source_guid = item.get('source_guid', 'unknown')
                    raise ValueError(f"Failed to process item with source_guid {source_guid}: {str(e)}")

            return processed_data
        except Exception as e:
            raise RuntimeError(f"Failed to process content: {str(e)}")

    def process_for_side_output(
        self, 
        data: List[Dict], 
        file_path: str,
        output_directory: str = None
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Process data and separate into main and side outputs.
        
        Args:
            data: List of data items to process
            file_path: Path to the file containing the data
            output_directory: Directory where batch files should be created
            
        Returns:
            Tuple of (main_output, side_output)
            
        Raises:
            RuntimeError: If processing fails
        """
        if self.agent_config.get('run_mode') == 'batch':
            self.batch_service.submit_batch_job_from_data(self.agent_config, self.agent_name, data, output_directory)
            return [], [] # Return empty lists for main and side output

        try:
            source_data = self.source_loader.load_source_data(file_path)
            all_processed_items = []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    all_processed_items.extend(processed_item)
                except Exception as e:
                    source_guid = item.get('source_guid', 'unknown')
                    raise ValueError(f"Failed to process item with source_guid {source_guid}: {str(e)}")

            # Separate main and side outputs
            return self.data_processor.separate_side_output(all_processed_items)
        except Exception as e:
            raise RuntimeError(f"Failed to process for side output: {str(e)}")

    def process_file_level(self, data: List[Dict], output_directory: str = None) -> List[Dict]:
        """
        Process data at the file level.
        
        Args:
            data: List of data items to process
            output_directory: Directory where batch files should be created
            
        Returns:
            Processed data
            
        Raises:
            RuntimeError: If processing fails
        """
        if self.agent_config.get('run_mode') == 'batch':
            self.batch_service.submit_batch_job_from_data(self.agent_config, self.agent_name, data, output_directory)
            return []

        try:
            contents, source_guid = data[0]['content'], data[0]['source_guid']
            generated_data, _ = self.data_generator.create_agent_with_data(data)
            return self.data_processor.process_item(contents, generated_data, source_guid)
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
            contents, source_guid = item['content'], item['source_guid']
            
            # Get corresponding source content
            source_content = DataTransformer.get_content_by_source_guid(source_data, source_guid)  
            # Generate data through the shared utility
            generated_data, executed = self.data_generator.create_agent_with_data(
                contents, source_content
            )

            if executed:
                processed = self.data_processor.process_item(contents, generated_data, source_guid)
            else:
                # When conditional clause is False, generated_data is the original context
                # We need to wrap it in the expected format for transform_structure
                wrapped_data = [generated_data] if not isinstance(generated_data, list) else generated_data
                processed = self.data_processor.process_item(contents, wrapped_data, source_guid)
            
            # Common processing for both executed and non-executed paths
            node_id = f"node_{self.idx}_{uuid.uuid4()}"
            for obj in processed:
                if 'target_id' not in obj or not obj['target_id']:
                    obj['target_id'] = str(uuid.uuid4())
                if 'source_guid' not in obj or not obj['source_guid']:
                    obj['source_guid'] = source_guid
                obj['node_id'] = node_id
                # Add lineage tracking
                if 'lineage' in item and isinstance(item['lineage'], list):
                    filtered_lineage = [nid for nid in item['lineage'] if isinstance(nid, str) and nid.startswith('node_')]
                    obj['lineage'] = filtered_lineage + [node_id]
                else:
                    obj['lineage'] = [node_id]
            return processed
        except Exception as e:
            raise ValueError(f"Failed to process item: {str(e)}")
