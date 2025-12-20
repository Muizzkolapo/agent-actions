"""Module for processing target content with specialized components."""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from agent_actions.configuration.base_async_processor import BaseAsyncProcessor
from agent_actions.configuration.interfaces import (
    IContentProcessor,
    IDataLoader,
    IDataProcessor,
    IGenerator,
)
from agent_actions.errors import DependencyError, ProcessingError
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.dependency_injection import registry
from agent_actions.preprocessing.filtering.where_clause_handler import (
    get_where_clause_handler,
)
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from agent_actions.utilities.correlation import LoopIdGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.utilities.passthrough_item_builder import PassthroughItemBuilder

logger = logging.getLogger(__name__)

@registry.register_processor('target_content')
class TargetContentProcessor(BaseAsyncProcessor, IContentProcessor):
    """Orchestrates the target content processing workflow."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        agent_config: Dict,
        agent_name: str,
        idx: int,
        source_loader: IDataLoader,
        data_generator: IGenerator,
        data_processor: IDataProcessor,
        batch_service: BatchService,
        concurrency_limit: Optional[int] = None,
    ):
        """
        Initialize the target content processor with injected dependencies.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            idx: Index of the config being processed
            source_loader: Required data loader service (must be provided)
            data_generator: Required data generator service (must be provided)
            data_processor: Required data processor service (must be provided)
            batch_service: Required batch service (must be provided)
            concurrency_limit: Maximum number of concurrent operations

        Raises:
            DependencyError: If any required dependency is not provided
        """
        super().__init__(concurrency_limit)
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.idx = idx
        if source_loader is None:
            raise DependencyError("TargetContentProcessor", "source_loader")
        if data_generator is None:
            raise DependencyError("TargetContentProcessor", "data_generator")
        if data_processor is None:
            raise DependencyError("TargetContentProcessor", "data_processor")
        if batch_service is None:
            raise DependencyError("TargetContentProcessor", "batch_service")
        self.source_loader = source_loader
        self.data_generator = data_generator
        self.data_processor = data_processor
        self.batch_service = batch_service

    def _get_config_value(self, key: str, default=None):
        """Get configuration value, supporting both AgentConfig models and dicts."""
        if hasattr(self.agent_config, key):
            return getattr(self.agent_config, key, default)
        if hasattr(self.agent_config, "get"):
            return self.agent_config.get(key, default)
        return default

    async def process_async(
        self,
        data: List[Dict],
        file_path: str,
        output_directory: str = None,
    ) -> List[Dict]:
        """
        Async version: process items in parallel using proper async patterns.
        """
        if self._get_config_value("run_mode") == "batch":
            source_file_info = self._extract_source_file_info(data)
            result = await asyncio.to_thread(
                self.batch_service.submit_batch_job,
                self.agent_config,
                self.agent_name,
                data,
                output_directory,
                source_file_info=source_file_info,
            )
            if isinstance(result, dict) and result.get("type") == "passthrough":
                return result["data"]
            return []
        try:
            source_data = await self._load_source_data_async(file_path)
            results = await self.process_items_parallel(
                data,
                self._process_single_item_async,
                source_data,
                file_path=file_path,
            )
            processed_data = []
            for result in results:
                processed_data.extend(result)
            return processed_data
        except Exception as ex:
            raise ProcessingError(
                f"Failed to process content: {str(ex)}", cause=ex
            ) from ex

    def process(
        self,
        data: List[Dict],
        file_path: str,
        output_directory: str = None,
    ) -> List[Dict]:
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
        if self._get_config_value("run_mode") == "batch":
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job(
                self.agent_config,
                self.agent_name,
                data,
                output_directory,
                source_file_info=source_file_info,
            )
            if isinstance(result, dict) and result.get("type") == "passthrough":
                return result["data"]
            return []
        try:
            source_data = self.source_loader.load_source_data(file_path)
            filtered_data = self._apply_where_clause_filtering(data)
            processed_data = []
            for idx, item in enumerate(filtered_data):
                try:
                    processed_item = self._process_single_item(
                        item,
                        source_data,
                        file_path=file_path,
                        record_index=idx,
                    )
                    processed_data.extend(processed_item)
                except Exception as ex:
                    source_guid = item.get("source_guid", "unknown")
                    raise ProcessingError(
                        "Failed to process item",
                        context={
                            "source_guid": source_guid,
                            "agent_name": self.agent_name,
                        },
                        cause=ex,
                    ) from ex
            return processed_data
        except Exception as ex:
            raise ProcessingError(
                f"Failed to process content: {str(ex)}", cause=ex
            ) from ex

    def process_for_side_output(
        self,
        data: List[Dict],
        file_path: str,
        output_directory: str = None,
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
        if self._get_config_value("run_mode") == "batch":
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job(
                self.agent_config,
                self.agent_name,
                data,
                output_directory,
                source_file_info=source_file_info,
            )
            if isinstance(result, dict) and result.get("type") == "passthrough":
                return self.data_processor.separate_side_output(result["data"])
            return ([], [])
        try:
            source_data = self.source_loader.load_source_data(file_path)
            all_processed_items = []
            for item in data:
                try:
                    processed_item = self._process_single_item(
                        item, source_data, file_path=file_path
                    )
                    all_processed_items.extend(processed_item)
                except Exception as ex:
                    source_guid = item.get("source_guid", "unknown")
                    raise ProcessingError(
                        "Failed to process item",
                        context={
                            "source_guid": source_guid,
                            "agent_name": self.agent_name,
                        },
                        cause=ex,
                    ) from ex
            return self.data_processor.separate_side_output(all_processed_items)
        except Exception as ex:
            raise ProcessingError(
                f"Failed to process for side output: {str(ex)}", cause=ex
            ) from ex

    def process_file_level(
        self,
        data: List[Dict],
        file_path: str = None,
        output_directory: str = None,
    ) -> List[Dict]:
        """
        Process data at the file level.

        Args:
            data: List of data items to process
            file_path: Path to the file containing the data
            output_directory: Directory where batch files should be created

        Returns:
            Processed data

        Raises:
            RuntimeError: If processing fails
        """
        if self._get_config_value("run_mode") == "batch":
            source_file_info = self._extract_source_file_info(data)
            result = self.batch_service.submit_batch_job(
                self.agent_config,
                self.agent_name,
                data,
                output_directory,
                source_file_info=source_file_info,
            )
            if isinstance(result, dict) and result.get("type") == "passthrough":
                return result["data"]
            return []
        try:
            source_guid = data[0]["source_guid"] if data else None
            source_data = (
                self.source_loader.load_source_data(file_path) if file_path else []
            )
            source_content = (
                DataTransformer.get_content_by_source_guid(source_data, source_guid)
                if source_guid
                else None
            )
            generated_data, _, passthrough_fields = (
                self.data_generator.create_agent_with_data(data, source_content)
            )
            model_vendor = (self._get_config_value("model_vendor") or "").lower()
            granularity = (self._get_config_value("granularity") or "record").lower()
            if model_vendor == "tool" and granularity == "file":
                # File-level tools need lineage tracking too (issue #529)
                return self._process_file_level_tool(generated_data, data, source_guid)
            contents = data[0]["content"] if data else {}
            return self.data_processor.process_item(
                contents,
                generated_data,
                source_guid,
                passthrough_fields=passthrough_fields,
            )
        except Exception as ex:
            raise ProcessingError(
                f"Failed to process at file level: {str(ex)}", cause=ex
            ) from ex

    def _process_file_level_tool(
        self,
        generated_data,
        data: List[Dict],
        source_guid: Optional[str]
    ) -> List[Dict]:
        """
        Process file-level tool output with lineage tracking.

        Args:
            generated_data: Data generated by the tool
            data: Original input data
            source_guid: Source GUID for tracking

        Returns:
            List of tracked data items
        """
        data_list = (
            generated_data if isinstance(generated_data, list)
            else [generated_data]
        )

        # Get the first item from input data for lineage inheritance
        source_item = data[0] if data else {}

        # Add lineage tracking to each item with unique node_ids
        base_node_id = IDGenerator.generate_node_id(self.idx)
        tracked_data = []

        # Create FieldManager once outside loop for better performance
        field_manager = FieldManager()

        for i, item in enumerate(data_list):
            if isinstance(item, dict):
                # Explicitly copy to prevent mutation of original data
                item_copy = item.copy()

                # Ensure required fields on the copy
                item_copy = field_manager.ensure_required_fields(
                    item_copy, source_guid, self.idx
                )

                # Generate unique node_id per item
                node_id = f"{base_node_id}_{i}"

                # Add lineage tracking to the copy
                item_copy = LineageBuilder.add_lineage_tracking(
                    item_copy, source_item, node_id
                )

                tracked_data.append(item_copy)
            else:
                tracked_data.append(item)

        return tracked_data

    async def _load_source_data_async(self, file_path: str) -> List[Dict]:
        """
        Load source data asynchronously.

        Args:
            file_path: Path to the file containing processed data

        Returns:
            List of source data items
        """
        if hasattr(self.source_loader, "load_source_data_async"):
            return await self.source_loader.load_source_data_async(file_path)
        return await asyncio.to_thread(
            self.source_loader.load_source_data, file_path
        )

    # pylint: disable=too-many-locals
    async def _process_single_item_async(
        self,
        item: Dict,
        *args,
        **kwargs
    ) -> List[Dict]:
        """
        Process a single data item asynchronously using proper async patterns.

        Args:
            item: Data item to process
            *args: Positional arguments (source_data)
            **kwargs: Additional arguments (file_path, record_index)

        Returns:
            Processed data item

        Raises:
            ValueError: If item processing fails
        """
        source_data = args[0] if args else []
        file_path = kwargs.get('file_path')
        record_index = kwargs.get('record_index')

        try:
            contents, source_guid = (item["content"], item["source_guid"])
            source_content = DataTransformer.get_content_by_source_guid(
                source_data, source_guid
            )
            if hasattr(self.data_generator, "create_agent_with_data_async"):
                generated_data, executed, passthrough_fields = (
                    await self.data_generator.create_agent_with_data_async(
                        contents,
                        source_content,
                        current_item=item,
                        file_path=file_path,
                    )
                )
            else:
                generated_data, executed, passthrough_fields = (
                    await asyncio.to_thread(
                        self.data_generator.create_agent_with_data,
                        contents,
                        source_content,
                        current_item=item,
                        file_path=file_path,
                    )
                )
            if executed:
                if hasattr(self.data_processor, "process_item_async"):
                    processed = await self.data_processor.process_item_async(
                        contents,
                        generated_data,
                        source_guid,
                        passthrough_fields=passthrough_fields,
                    )
                else:
                    processed = await asyncio.to_thread(
                        self.data_processor.process_item,
                        contents,
                        generated_data,
                        source_guid,
                        passthrough_fields=passthrough_fields,
                    )
                base_node_id = IDGenerator.generate_node_id(self.idx)
                for i, obj in enumerate(processed):
                    obj = FieldManager().ensure_required_fields(
                        obj, source_guid, self.idx
                    )
                    # For split records, append sub-index to node_id
                    node_id = (
                        f"{base_node_id}_{i}" if len(processed) > 1 else
                        base_node_id
                    )
                    obj = LineageBuilder.add_lineage_tracking(obj, item, node_id)
                    obj = LoopIdGenerator.add_loop_correlation_id(
                        obj, self.agent_config, record_index=record_index
                    )
                    processed[i] = obj
            else:
                # Agent was not executed (skipped by guard or filtered out)
                if generated_data is None:
                    # Filtered out entirely (behavior: 'filter')
                    return []
                # Skipped but passed through (behavior: 'skip')
                processed_item = PassthroughItemBuilder.build_item(
                    row={**item, "content": generated_data, "source_guid": source_guid},
                    reason="where_clause_not_matched",
                    idx=self.idx,
                    source_guid=source_guid,
                    mode="online",
                )

                # CRITICAL: Merge passthrough fields into skipped item
                # This ensures fields from context_scope.passthrough are
                # carried forward
                if passthrough_fields:
                    if (
                        "content" in processed_item
                        and isinstance(processed_item["content"], dict)
                    ):
                        processed_item["content"].update(passthrough_fields)
                    else:
                        processed_item.update(passthrough_fields)

                processed = [processed_item]
            return processed
        except Exception as ex:
            raise ProcessingError(
                "Failed to process item",
                context={
                    "agent_name": self.agent_name,
                    "item_source_guid": item.get("source_guid", "unknown"),
                },
                cause=ex,
            ) from ex

    def _extract_source_file_info(self, data: List[Dict]) -> Dict:
        """
        Extract source file information from aggregated data.

        Groups data by source_guid to determine which items belong to which
        source files.
        """
        source_file_info = {}
        source_groups = {}
        for item in data:
            source_guid = item.get("source_guid")
            if source_guid:
                if source_guid not in source_groups:
                    source_groups[source_guid] = []
                source_groups[source_guid].append(item)
        try:
            if len(source_groups) == 1:
                source_file_info["single_file"] = True
                source_file_info["source_guids"] = list(source_groups.keys())
            else:
                source_file_info["multiple_files"] = True
                source_file_info["source_guid_groups"] = {
                    guid: len(items) for guid, items in source_groups.items()
                }
        except Exception:  # pylint: disable=broad-exception-caught
            # Fallback: If metadata extraction fails for any reason,
            # provide minimal source group info
            source_file_info["extracted"] = True
            source_file_info["source_groups_count"] = len(source_groups)
        return source_file_info

    def _apply_where_clause_filtering(self, data: List[Dict]) -> List[Dict]:
        """
        Apply WHERE clause filtering at item level if configured.

        IMPORTANT: This method only applies 'filter' behavior (items that don't
        match are removed entirely). For 'skip' behavior, items are handled in
        _process_single_item where they pass through with skip metadata.

        Args:
            data: List of data items to filter

        Returns:
            Filtered list of data items
        """
        where_clause_config = self._get_config_value("where_clause")
        if not where_clause_config:
            return data

        # Use unified WhereClauseHandler for online mode filtering
        where_clause_handler = get_where_clause_handler()

        # Convert where_clause_config to dict if it's a model object
        where_config_dict = (
            where_clause_config
            if isinstance(where_clause_config, dict)
            else (
                where_clause_config.__dict__
                if hasattr(where_clause_config, "__dict__")
                else where_clause_config
            )
        )

        filtered_data, filtering_context = (
            where_clause_handler.filter_items_online_mode(data, where_config_dict)
        )

        # Log filtering summary
        summary = filtering_context.get_summary()
        logger.info(
            "WHERE clause filtering complete: %s included, %s filtered "
            "(success rate: %.2f%%)",
            summary['included_items'],
            summary['filtered_items'],
            summary['success_rate'] * 100
        )

        return filtered_data

    # pylint: disable=too-many-locals
    def _process_single_item(
        self,
        item: Dict,
        source_data: List[Dict],
        file_path: Optional[str] = None,
        record_index: Optional[int] = None,
    ) -> List[Dict]:
        """
        Process a single data item synchronously.

        Kept for backward compatibility.

        Args:
            item: Data item to process
            source_data: Source data for reference
            file_path: Optional file path for historical node data loading
            record_index: Optional record index for loop correlation

        Returns:
            Processed data item

        Raises:
            ValueError: If item processing fails
        """
        try:
            contents, source_guid = (item["content"], item["source_guid"])
            source_content = DataTransformer.get_content_by_source_guid(
                source_data, source_guid
            )
            generated_data, executed, passthrough_fields = (
                self.data_generator.create_agent_with_data(
                    contents,
                    source_content,
                    current_item=item,
                    file_path=file_path,
                )
            )
            if executed:
                processed = self.data_processor.process_item(
                    contents,
                    generated_data,
                    source_guid,
                    passthrough_fields=passthrough_fields,
                )
                base_node_id = IDGenerator.generate_node_id(self.idx)
                for i, obj in enumerate(processed):
                    obj = FieldManager().ensure_required_fields(
                        obj, source_guid, self.idx
                    )
                    # For split records, append sub-index to node_id
                    node_id = (
                        f"{base_node_id}_{i}" if len(processed) > 1 else
                        base_node_id
                    )
                    obj = LineageBuilder.add_lineage_tracking(obj, item, node_id)
                    obj = LoopIdGenerator.add_loop_correlation_id(
                        obj, self.agent_config, record_index=record_index
                    )
                    processed[i] = obj
            else:
                # Agent was not executed (skipped by guard or filtered out)
                if generated_data is None:
                    # Filtered out entirely (behavior: 'filter')
                    return []
                # Skipped but passed through (behavior: 'skip')
                processed_item = PassthroughItemBuilder.build_item(
                    row={**item, "content": generated_data, "source_guid": source_guid},
                    reason="where_clause_not_matched",
                    idx=self.idx,
                    source_guid=source_guid,
                    mode="online",
                )

                # CRITICAL: Merge passthrough fields into skipped item
                # This ensures fields from context_scope.passthrough are
                # carried forward
                if passthrough_fields:
                    if (
                        "content" in processed_item
                        and isinstance(processed_item["content"], dict)
                    ):
                        processed_item["content"].update(passthrough_fields)
                    else:
                        processed_item.update(passthrough_fields)

                processed_item = LoopIdGenerator.add_loop_correlation_id(
                    processed_item, self.agent_config, record_index=record_index
                )
                processed = [processed_item]
            return processed
        except Exception as ex:
            raise ProcessingError(
                "Failed to process item",
                context={
                    "agent_name": self.agent_name,
                    "item_source_guid": item.get("source_guid", "unknown"),
                },
                cause=ex,
            ) from ex
