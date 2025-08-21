"""Module for processing target content with specialized components."""
from typing import Dict, List, Tuple, Optional
import asyncio
from agent_actions.common.transformers.data_transformer import DataTransformer

from agent_actions.common.interfaces.interfaces import IContentProcessor, IDataLoader, IDataProcessor, IGenerator, ProcessingMode
from agent_actions.services.batch_service import BatchService
from ...core.dependency_injection import registry
from agent_actions.common.utils.processor_utils import ProcessorUtils
from agent_actions.common.interfaces.base_async_processor import BaseAsyncProcessor

@registry.register_processor("target_content")
class TargetContentProcessor(BaseAsyncProcessor, IContentProcessor):
    """Orchestrates the target content processing workflow."""

    def __init__(self, 
                 agent_config: Dict, 
                 agent_name: str, 
                 idx: int,
                 source_loader: IDataLoader = None,
                 data_generator: IGenerator = None,
                 data_processor: IDataProcessor = None,
                 batch_service: BatchService = None,
                 concurrency_limit: Optional[int] = None):
        """
        Initialize the target content processor with injected dependencies.
        
        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            source_loader: Injected data loader service
            data_generator: Injected data generator service
            data_processor: Injected data processor service
            batch_service: Injected batch service
            concurrency_limit: Maximum number of concurrent operations
        """
        # Initialize base async processor
        super().__init__(concurrency_limit)
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.idx = idx
        
        # Store injected dependencies or create defaults for backward compatibility
        if source_loader is None:
            from agent_actions.loaders.data_loaders.source_data_loader import SourceDataLoader
            from agent_actions.core.path_manager import PathManager
            self.source_loader = SourceDataLoader(agent_name, PathManager())
        else:
            self.source_loader = source_loader
            
        if data_generator is None:
            from .data_generator import DataGenerator
            self.data_generator = DataGenerator(agent_config, agent_name)
        else:
            self.data_generator = data_generator
            
        if data_processor is None:
            from .data_processor import DataProcessor
            self.data_processor = DataProcessor(agent_config)
        else:
            self.data_processor = data_processor
            
        if batch_service is None:
            self.batch_service = BatchService()
        else:
            self.batch_service = batch_service

    async def process_async(self, data: List[Dict], file_path: str, output_directory: str = None) -> List[Dict]:
        """
        Async version: process a list of data items in parallel using proper async patterns.
        """
        if self.agent_config.get('run_mode') == 'batch':
            # Extract source file info from aggregated data for proper file naming
            source_file_info = self._extract_source_file_info(data)
            # TODO: Make batch service async in future iteration
            result = await asyncio.to_thread(
                self.batch_service.submit_batch_job_from_data, 
                self.agent_config, self.agent_name, data, output_directory,
                source_file_info=source_file_info
            )
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                return result['data']
            return []
        
        try:
            # Load source data asynchronously
            source_data = await self._load_source_data_async(file_path)
            
            # Process items in parallel with proper async patterns
            results = await self.process_items_parallel(
                data, 
                self._process_single_item_async, 
                source_data
            )
            
            # Flatten results
            processed_data = []
            for result in results:
                processed_data.extend(result)
            return processed_data
            
        except Exception as e:
            raise RuntimeError(f"Failed to process content: {str(e)}")

    def process(self, data: List[Dict], file_path: str, output_directory: str = None) -> List[Dict]:
        """
        Process a list of data items with WHERE clause filtering support.
        
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
            # Extract source file info from aggregated data for proper file naming
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job_from_data(
                self.agent_config, self.agent_name, data, output_directory,
                source_file_info=source_file_info
            )
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                return result['data']
            return [] # Return empty list to signify batch submission

        try:
            source_data = self.source_loader.load_source_data(file_path)
            
            # Apply WHERE clause filtering for item-level scope
            filtered_data = self._apply_where_clause_filtering(data)
            
            processed_data = []

            for item in filtered_data:
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
            # Extract source file info from aggregated data for proper file naming
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job_from_data(
                self.agent_config, self.agent_name, data, output_directory,
                source_file_info=source_file_info
            )
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                # Separate main and side outputs for passthrough data
                return self.data_processor.separate_side_output(result['data'])
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
            # Extract source file info from aggregated data for proper file naming
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job_from_data(
                self.agent_config, self.agent_name, data, output_directory,
                source_file_info=source_file_info
            )
            # Handle passthrough data when no batch is submitted
            if isinstance(result, dict) and result.get('type') == 'passthrough':
                return result['data']
            return []

        try:
            contents, source_guid = data[0]['content'], data[0]['source_guid']
            generated_data, _ = self.data_generator.create_agent_with_data(data)
            
            # For tool vendor with file granularity, return generated_data directly
            # to match the bypass behavior in agent_builder.py
            model_vendor = self.agent_config.get('model_vendor', '').lower()
            granularity = self.agent_config.get('granularity', 'record').lower()
            
            if model_vendor == 'tool' and granularity == 'file':
                # File-level tools should bypass the normal processing pipeline
                # If generated_data is already a list, return it directly
                # If it's a single item, wrap it in a list
                if isinstance(generated_data, list):
                    return generated_data
                else:
                    return [generated_data]
            
            return self.data_processor.process_item(contents, generated_data, source_guid)
        except Exception as e:
            raise RuntimeError(f"Failed to process at file level: {str(e)}")

    async def _load_source_data_async(self, file_path: str) -> List[Dict]:
        """
        Load source data asynchronously.
        
        Args:
            file_path: Path to the file containing processed data
            
        Returns:
            List of source data items
        """
        # Check if source loader supports async
        if hasattr(self.source_loader, 'load_source_data_async'):
            return await self.source_loader.load_source_data_async(file_path)
        else:
            # Fallback to thread-based async for backward compatibility
            return await asyncio.to_thread(self.source_loader.load_source_data, file_path)
    
    async def _process_single_item_async(
        self, 
        item: Dict, 
        source_data: List[Dict]
    ) -> List[Dict]:
        """
        Process a single data item asynchronously using proper async patterns.
        
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
            
            # Get corresponding source content (this is CPU-bound, can be sync)
            source_content = DataTransformer.get_content_by_source_guid(source_data, source_guid)
            
            # Generate data asynchronously if supported
            if hasattr(self.data_generator, 'create_agent_with_data_async'):
                generated_data, executed = await self.data_generator.create_agent_with_data_async(
                    contents, source_content
                )
            else:
                # Fallback for backward compatibility
                generated_data, executed = await asyncio.to_thread(
                    self.data_generator.create_agent_with_data, contents, source_content
                )

            if executed:
                # Process data asynchronously if supported
                if hasattr(self.data_processor, 'process_item_async'):
                    processed = await self.data_processor.process_item_async(
                        contents, generated_data, source_guid
                    )
                else:
                    # Fallback for backward compatibility
                    processed = await asyncio.to_thread(
                        self.data_processor.process_item, contents, generated_data, source_guid
                    )
                
                # Common processing for executed path (CPU-bound operations)
                node_id = ProcessorUtils.generate_node_id(self.idx)
                for i, obj in enumerate(processed):
                    obj = ProcessorUtils.ensure_required_fields(obj, source_guid, self.idx)
                    obj = ProcessorUtils.add_lineage_tracking(obj, item, node_id)
                    processed[i] = obj
            else:
                # When conditional clause is False, return the original data unchanged
                # Create a single item with the original content structure
                node_id = ProcessorUtils.generate_node_id(self.idx)
                lineage = ProcessorUtils.build_lineage(item, node_id)
                    
                processed = [ProcessorUtils.create_processed_item(
                    source_guid=source_guid,
                    content=generated_data,  # This is the original context
                    node_id=node_id,
                    lineage=lineage
                )]
            return processed
        except Exception as e:
            raise ValueError(f"Failed to process item: {str(e)}")

    def _extract_source_file_info(self, data: List[Dict]) -> Dict:
        """
        Extract source file information from aggregated data.
        Groups data by source_guid to determine which items belong to which source files.
        """
        source_file_info = {}
        
        # Group data by source_guid to identify source files
        source_groups = {}
        for item in data:
            source_guid = item.get('source_guid')
            if source_guid:
                if source_guid not in source_groups:
                    source_groups[source_guid] = []
                source_groups[source_guid].append(item)
        
        # Try to find source file names by looking at previous agent outputs
        try:
            # In workflows, we can try to infer file names from the data structure
            # This is a heuristic approach that may need refinement
            from pathlib import Path
            
            # If we only have one source_guid, we might be dealing with a single file
            if len(source_groups) == 1:
                source_file_info['single_file'] = True
                source_file_info['source_guids'] = list(source_groups.keys())
            else:
                # Multiple source files - we need to map them
                source_file_info['multiple_files'] = True
                source_file_info['source_guid_groups'] = {
                    guid: len(items) for guid, items in source_groups.items()
                }
                
        except Exception:
            # Fallback: just note that we have source file info
            source_file_info['extracted'] = True
            source_file_info['source_groups_count'] = len(source_groups)
        
        return source_file_info

    def _apply_where_clause_filtering(self, data: List[Dict]) -> List[Dict]:
        """
        Apply WHERE clause filtering at item level if configured.
        
        Args:
            data: List of data items to filter
            
        Returns:
            Filtered list of data items
        """
        where_clause_config = self.agent_config.get('where_clause')
        
        # Only apply filtering if WHERE clause is configured for item scope
        if not where_clause_config or where_clause_config.get('scope') != 'item':
            return data
        
        try:
            from agent_actions.common.filters.where_filter import get_global_filter
            
            filter_service = get_global_filter()
            filtered_data = []
            
            for item in data:
                # Extract content for filtering - handle both wrapped and unwrapped formats
                content = item.get('content', item)
                
                filter_result = filter_service.filter_item(
                    content,
                    where_clause_config['clause'],
                    timeout=self.agent_config.get('max_execution_time', 5)
                )
                
                if filter_result.success and filter_result.matched:
                    filtered_data.append(item)
                elif not filter_result.success:
                    # Handle filter error based on configuration
                    passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                    if passthrough_on_error:
                        filtered_data.append(item)
                    # Otherwise skip this item
                # If filter_result.matched is False, skip the item
                
            return filtered_data
            
        except Exception as e:
            # On unexpected error, check passthrough behavior
            passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
            if passthrough_on_error:
                return data  # Return original data
            else:
                raise RuntimeError(f"WHERE clause filtering failed: {str(e)}")
    
    def _process_single_item(
        self, 
        item: Dict, 
        source_data: List[Dict]
    ) -> List[Dict]:
        """
        Process a single data item synchronously (kept for backward compatibility).
        
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
                
                # Common processing for executed path
                node_id = ProcessorUtils.generate_node_id(self.idx)
                for i, obj in enumerate(processed):
                    obj = ProcessorUtils.ensure_required_fields(obj, source_guid, self.idx)
                    obj = ProcessorUtils.add_lineage_tracking(obj, item, node_id)
                    processed[i] = obj
            else:
                # When conditional clause is False, return the original data unchanged
                # Create a single item with the original content structure
                node_id = ProcessorUtils.generate_node_id(self.idx)
                lineage = ProcessorUtils.build_lineage(item, node_id)
                    
                processed = [ProcessorUtils.create_processed_item(
                    source_guid=source_guid,
                    content=generated_data,  # This is the original context
                    node_id=node_id,
                    lineage=lineage
                )]
            return processed
        except Exception as e:
            raise ValueError(f"Failed to process item: {str(e)}")

