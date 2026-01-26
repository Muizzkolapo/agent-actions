"""
Batch Task Preparator.

Handles preparation of batch tasks from raw data without state mutation.
Extracted from BatchService.prepare_batch_tasks_from_data() as part of Phase 4 refactoring.
"""

import logging
import sys
from typing import Dict, List, Any, Optional
from pathlib import Path

from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.input.preprocessing.filtering.guard_handler import GuardHandler
from agent_actions.utils.constants import JSON_MODE_KEY
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.module_loader import ensure_path_importable
from agent_actions.errors import ConfigurationError  # New modular pattern!
from agent_actions.llm.batch.core.batch_models import (
    PreparedBatchTasks,
    BatchTaskPreparationStats,
)
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus

logger = logging.getLogger(__name__)


class BatchTaskPreparator:
    """
    Prepares batch tasks from raw data.

    Pure function approach - builds context map and tasks without mutating state.
    All dependencies are injected for testability.

    Example:
        preparator = BatchTaskPreparator()

        result = preparator.prepare_tasks(
            agent_config=config,
            data=[{'content': 'test'}],
            output_directory='/tmp/node_1_Agent',
            batch_name='test.json'
        )

        # result is PreparedBatchTasks with tasks, context_map, and stats
        provider.submit_batch(result.tasks)
    """

    def __init__(
        self,
        filter_service=None,
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        guard_handler: Optional[GuardHandler] = None,
    ):
        """
        Initialize task preparator.

        Args:
            filter_service: Optional filter service (defaults to global) - DEPRECATED,
                use guard_handler
            agent_indices: Dict mapping agent names to node indices
            dependency_configs: Dict mapping dependency names to configs
            guard_handler: Optional guard handler (defaults to global)
        """
        self.filter_service = filter_service
        self.guard_handler = guard_handler
        self.agent_indices = agent_indices or {}
        self.dependency_configs = dependency_configs or {}

    def prepare_tasks(
        self,
        agent_config: Dict[str, Any],
        data: List[Dict[str, Any]],
        provider,
        output_directory: Optional[str] = None,
        batch_name: Optional[str] = None,
        source_data: Optional[List[Any]] = None,
    ) -> PreparedBatchTasks:
        """
        Prepare batch tasks from raw data.

        This is the main entry point. Returns immutable PreparedBatchTasks
        instead of mutating instance state.

        Args:
            agent_config: Agent configuration
            data: List of raw data items
            provider: Batch provider instance
            output_directory: Output directory path
            batch_name: Batch file name

        Returns:
            PreparedBatchTasks with tasks, context_map, and stats

        Raises:
            ConfigurationError: If configuration is invalid
        """
        # 0. Validate agent_config is not None
        if agent_config is None:
            raise ConfigurationError(
                "agent_config is None in batch task preparation. "
                "Check that the agent is defined in the workflow configuration "
                "and the configuration loaded properly.",
                context={
                    "batch_name": batch_name,
                    "output_directory": output_directory,
                },
            )

        # 1. Validate configuration
        self._validate_config(agent_config, provider)

        # 2. Setup context
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)  # Validate prompt exists

        # 2.1 Pre-flight validation: check template variables against first data row
        # 2.1 Pre-flight validation: check template variables against first data row
        self._run_preflight_validation(
            agent_config, raw_prompt, data, output_directory, batch_name, source_data
        )
        from agent_actions.utils.tools_resolver import resolve_tools_path

        tools_path = resolve_tools_path(agent_config)
        self._add_tools_to_path(tools_path)

        # 3. Get guard handler
        guard_handler = self._get_guard_handler()

        # 4. Extract filter configuration
        conditional_clause = agent_config.get("conditional_clause", "")
        guard_config = agent_config.get("guard")

        # 5. Prepare schema
        schema = self._prepare_schema(agent_config, provider)

        # 6. Initialize builders
        context_map_builder = {}
        tasks_builder = []
        stats = BatchTaskPreparationStats(total_items=len(data))

        # 7. Process each data item
        for idx, row in enumerate(data):
            try:
                # Resolve source item for this row by source_guid (same as online mode)
                # This allows many processed records to correctly find their shared source document
                source_item = None
                if source_data:
                    source_guid = row.get("source_guid")
                    if source_guid:
                        from agent_actions.input.preprocessing.transformation.transformer import (
                            DataTransformer,
                        )

                        source_item = DataTransformer.get_content_by_source_guid(
                            source_data, source_guid
                        )

                result = self._process_single_item(
                    row=row,
                    agent_config=agent_config,
                    guard_handler=guard_handler,
                    conditional_clause=conditional_clause,
                    guard_config=guard_config,
                    output_directory=output_directory,
                    batch_name=batch_name,
                    tools_path=tools_path,
                    context_map_builder=context_map_builder,
                    stats=stats,
                    source_item=source_item,
                )

                if result:
                    tasks_builder.append(result)
                    stats.included_items += 1

            except Exception as e:
                # Catch all exceptions to avoid one bad row stopping entire batch
                logger.debug("Failed to prepare task for row: %s", e, exc_info=True)
                stats.error_items += 1

        # 8. Finalize tasks with provider
        provider_config = agent_config.copy()
        provider_config["compiled_schema"] = schema
        final_tasks = provider.prepare_tasks(tasks_builder, provider_config)

        # 9. Return immutable result
        return PreparedBatchTasks(
            tasks=final_tasks, context_map=context_map_builder, stats=stats, config=agent_config
        )

    def _process_single_item(
        self,
        row: Dict[str, Any],
        agent_config: Dict[str, Any],
        guard_handler: GuardHandler,
        conditional_clause: str,
        guard_config: Optional[Dict[str, Any]],
        output_directory: Optional[str],
        batch_name: Optional[str],
        tools_path: Optional[str],
        context_map_builder: Dict[str, Any],
        stats: BatchTaskPreparationStats,
        source_item: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Process a single data item.

        Returns prepared task if item should be included, None otherwise.
        Updates context_map_builder and stats as side effects.
        """
        # 1. Generate target_id if missing
        custom_id = row.get("target_id")
        if not custom_id:
            custom_id = IDGenerator.generate_target_id()
            row["target_id"] = custom_id

        # 2. Store row in context map with initial status
        row_with_meta = row.copy()
        BatchContextMetadata.set_filter_status(row_with_meta, FilterStatus.INCLUDED)
        context_map_builder[custom_id] = row_with_meta

        # 3. Extract row content for filtering
        if "source_guid" in row and "content" in row:
            row_content = row["content"]
        else:
            row_content = row

        # 4. Apply filtering using unified GuardHandler
        should_include, status = guard_handler.filter_single_item(
            {"content": row_content} if "content" in row else row,
            guard_config,
            conditional_clause if conditional_clause else None,
        )

        # 5. Update context map with filter status
        context_map_builder[custom_id][ContextMetaKeys.FILTER_STATUS] = status

        # 6. Update stats based on filter result
        if status == "filtered":
            stats.filtered_items += 1
        elif status == "skipped":
            stats.skipped_items += 1

        # 7. Skip if not included
        if not should_include:
            return None

        # 8. Prepare prompt for this item
        return self._prepare_single_task(
            _row=row,
            row_content=row_content,
            custom_id=custom_id,
            agent_config=agent_config,
            output_directory=output_directory,
            batch_name=batch_name,
            tools_path=tools_path,
            context_map_builder=context_map_builder,
            source_item=source_item,
        )

    def _prepare_single_task(
        self,
        _row: Dict[str, Any],
        row_content: Any,
        custom_id: str,
        agent_config: Dict[str, Any],
        output_directory: Optional[str],
        batch_name: Optional[str],
        tools_path: Optional[str],
        context_map_builder: Dict[str, Any],
        source_item: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Prepare a single batch task using PromptPreparationService."""
        from agent_actions.prompt.service import (
            PromptPreparationService,
        )

        agent_name = agent_config.get("agent_type", agent_config.get("name", "unknown"))

        # Construct file path for history
        file_path_for_history = None
        if output_directory and batch_name:
            file_path_for_history = str(Path(output_directory) / batch_name)

        # Call PromptPreparationService
        prep_result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name=agent_name,
            contents=row_content if isinstance(row_content, dict) else {},
            mode="batch",
            agent_indices=self.agent_indices,
            dependency_configs=self.dependency_configs,
            source_content=source_item
            if source_item is not None
            else row_content,  # Prioritize explicit source_item
            current_item=context_map_builder.get(custom_id),
            file_path=file_path_for_history,
            tools_path=tools_path,
        )

        # Store passthrough_fields for later merging
        if prep_result.passthrough_fields and custom_id in context_map_builder:
            BatchContextMetadata.set_passthrough_fields(
                context_map_builder[custom_id], prep_result.passthrough_fields
            )

        # Create and return task
        cleaned_row = prep_result.llm_context
        return {
            "target_id": custom_id,
            "content": cleaned_row,
            "prompt": prep_result.formatted_prompt,
        }

    def _get_guard_handler(self) -> GuardHandler:
        """
        Get guard handler instance.

        Returns:
            GuardHandler instance for filtering coordination
        """
        if self.guard_handler is not None:
            return self.guard_handler

        # Create handler with filter service
        from agent_actions.input.preprocessing.filtering.guard_handler import (
            get_guard_handler,
        )

        return get_guard_handler()

    def _validate_config(self, agent_config: Dict[str, Any], provider) -> None:
        """Validate agent configuration."""
        schema = self._prepare_schema(agent_config, provider)
        json_mode = agent_config.get(JSON_MODE_KEY, True)

        if not schema and json_mode:
            raise ConfigurationError(
                "Schema is required for batch processing when json_mode is enabled",
                context={
                    "agent_config": agent_config.get("agent_type", "unknown"),
                    "json_mode": json_mode,
                    "hint": "Either provide a schema or set json_mode: false",
                },
            )

    def _prepare_schema(self, agent_config: Dict[str, Any], provider) -> Optional[Dict[str, Any]]:
        """Prepare and compile schema for provider (resolves schema references from registry)."""
        from agent_actions.output.response.schema import prepare_schema_unified
        from agent_actions.utils.constants import MODEL_VENDOR_KEY

        vendor = agent_config.get(MODEL_VENDOR_KEY, "").lower()
        if not vendor:
            vendor = type(provider).__name__.replace("BatchProvider", "").lower()

        # prepare_schema_unified returns (schema, captured_results) tuple - extract just the schema
        schema, _captured_results = prepare_schema_unified(agent_config, vendor)
        return schema

    def _add_tools_to_path(self, tools_path: Optional[str]) -> None:
        """Add tools path to sys.path if not already present."""
        if tools_path:
            ensure_path_importable(tools_path)

    def _get_filter_service(self):
        """Get filter service instance."""
        if self.filter_service:
            return self.filter_service
        # Fall back to global filter service
        from agent_actions.input.preprocessing.filtering.service import get_filter_service

        return get_filter_service()

    def _run_preflight_validation(
        self,
        agent_config: Dict[str, Any],
        raw_prompt: Optional[str],
        data: List[Dict[str, Any]],
        output_directory: Optional[str] = None,
        batch_name: Optional[str] = None,
        source_data: Optional[List[Any]] = None,
    ) -> None:
        """Run pre-flight validation on template and first data row.

        Uses the SAME PromptPreparationService as actual task preparation to ensure
        context is built identically. This guarantees preflight validation catches
        exactly the errors that would occur during actual processing.

        Args:
            agent_config: Agent configuration
            raw_prompt: The raw prompt template
            data: List of data items (uses first row for validation)
            output_directory: Output directory for constructing file paths
            batch_name: Batch file name for constructing file paths

        Raises:
            PreFlightValidationError: If validation fails
        """
        from agent_actions.prompt.service import (
            PromptPreparationService,
        )

        if not raw_prompt or not data:
            return  # Nothing to validate

        # Use first row as sample context for validation
        first_row = data[0]

        # Extract content from row (same logic as _process_single_item)
        if "source_guid" in first_row and "content" in first_row:
            row_content = first_row["content"]
        else:
            row_content = first_row

        agent_name = agent_config.get("agent_type", agent_config.get("name", "unknown"))

        # Construct file path for history (same as _prepare_single_task)
        file_path_for_history = None
        if output_directory and batch_name:
            file_path_for_history = str(Path(output_directory) / batch_name)

        # Determine source content for validation by source_guid (same as main loop)
        source_content_for_validation = None
        if source_data:
            source_guid = first_row.get("source_guid")
            if source_guid:
                from agent_actions.input.preprocessing.transformation.transformer import (
                    DataTransformer,
                )

                source_content_for_validation = DataTransformer.get_content_by_source_guid(
                    source_data, source_guid
                )
        if source_content_for_validation is None:
            source_content_for_validation = row_content

        # Use the SAME service as actual task preparation - single source of truth
        prep_result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name=agent_name,
            contents=row_content if isinstance(row_content, dict) else {},
            mode="batch",
            agent_indices=self.agent_indices,
            dependency_configs=self.dependency_configs,
            source_content=source_content_for_validation,  # Use prioritized source
            current_item=first_row,
            file_path=file_path_for_history,
        )
