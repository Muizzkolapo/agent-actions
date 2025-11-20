"""
Batch Task Preparator.

Handles preparation of batch tasks from raw data without state mutation.
Extracted from BatchService.prepare_batch_tasks_from_data() as part of Phase 4 refactoring.
"""

import logging
import sys
from typing import Dict, List, Any, Optional
from pathlib import Path

from agent_actions.preprocessing.prompt_formatter import PromptFormatter
from agent_actions.utilities.constants import JSON_MODE_KEY
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.utilities.correlation import LoopCorrelator
from agent_actions.shared.exceptions import ConfigurationError
from agent_actions.llm_invocation.batch.batch_models import (
    PreparedBatchTasks,
    BatchTaskPreparationStats,
    BatchFilterResult
)

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
        dependency_configs: Optional[Dict[str, Dict]] = None
    ):
        """
        Initialize task preparator.

        Args:
            filter_service: Optional filter service (defaults to global)
            agent_indices: Dict mapping agent names to node indices
            dependency_configs: Dict mapping dependency names to configs
        """
        self.filter_service = filter_service
        self.agent_indices = agent_indices or {}
        self.dependency_configs = dependency_configs or {}

    def prepare_tasks(
        self,
        agent_config: Dict[str, Any],
        data: List[Dict[str, Any]],
        provider,
        output_directory: Optional[str] = None,
        batch_name: Optional[str] = None
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
                "This usually means the agent is not defined in the workflow configuration or "
                "the configuration failed to load properly. Please check your workflow YAML file.",
                context={'batch_name': batch_name, 'output_directory': output_directory}
            )

        # 1. Validate configuration
        self._validate_config(agent_config, provider)

        # 2. Setup context
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
        tools_path = self._resolve_tools_path(agent_config)
        self._add_tools_to_path(tools_path)

        # 3. Get filter service
        filter_service = self._get_filter_service()

        # 4. Extract filter configuration
        conditional_clause = agent_config.get('conditional_clause', '')
        where_clause_config = agent_config.get('where_clause')

        # 5. Prepare schema
        schema = self._prepare_schema(agent_config, provider)

        # 6. Initialize builders
        context_map_builder = {}
        tasks_builder = []
        stats = BatchTaskPreparationStats(total_items=len(data))

        # 7. Process each data item
        for row in data:
            try:
                result = self._process_single_item(
                    row=row,
                    agent_config=agent_config,
                    filter_service=filter_service,
                    conditional_clause=conditional_clause,
                    where_clause_config=where_clause_config,
                    output_directory=output_directory,
                    batch_name=batch_name,
                    tools_path=tools_path,
                    context_map_builder=context_map_builder,
                    stats=stats
                )

                if result:
                    tasks_builder.append(result)
                    stats.included_items += 1

            except Exception as e:
                logger.error("Failed to prepare task for row: %s", e, exc_info=True)
                stats.error_items += 1

        # 8. Finalize tasks with provider
        provider_config = agent_config.copy()
        provider_config['compiled_schema'] = schema
        final_tasks = provider.prepare_tasks(tasks_builder, provider_config)

        # 9. Return immutable result
        return PreparedBatchTasks(
            tasks=final_tasks,
            context_map=context_map_builder,
            stats=stats,
            config=agent_config
        )

    def _process_single_item(
        self,
        row: Dict[str, Any],
        agent_config: Dict[str, Any],
        filter_service,
        conditional_clause: str,
        where_clause_config: Optional[Dict[str, Any]],
        output_directory: Optional[str],
        batch_name: Optional[str],
        tools_path: Optional[str],
        context_map_builder: Dict[str, Any],
        stats: BatchTaskPreparationStats
    ) -> Optional[Dict[str, Any]]:
        """
        Process a single data item.

        Returns prepared task if item should be included, None otherwise.
        Updates context_map_builder and stats as side effects.
        """
        # 1. Generate target_id if missing
        custom_id = row.get('target_id')
        if not custom_id:
            custom_id = IDGenerator.generate_target_id()
            row['target_id'] = custom_id

        # 2. Store row in context map with initial status
        row_with_meta = row.copy()
        row_with_meta['_batch_filter_status'] = 'included'
        context_map_builder[custom_id] = row_with_meta

        # 3. Extract row content for filtering
        if 'source_guid' in row and 'content' in row:
            row_content = row['content']
        else:
            row_content = row

        # 4. Apply filtering
        filter_result = self._apply_filters(
            row_content=row_content,
            where_clause_config=where_clause_config,
            conditional_clause=conditional_clause,
            filter_service=filter_service
        )

        # 5. Update context map with filter status
        context_map_builder[custom_id]['_batch_filter_status'] = filter_result.status

        # 6. Update stats based on filter result
        if filter_result.status == 'filtered':
            stats.filtered_items += 1
        elif filter_result.status == 'skipped':
            stats.skipped_items += 1

        # 7. Skip if not included
        if not filter_result.should_include:
            return None

        # 8. Prepare prompt for this item
        return self._prepare_single_task(
            row=row,
            row_content=row_content,
            custom_id=custom_id,
            agent_config=agent_config,
            output_directory=output_directory,
            batch_name=batch_name,
            tools_path=tools_path,
            context_map_builder=context_map_builder
        )

    def _prepare_single_task(
        self,
        row: Dict[str, Any],
        row_content: Any,
        custom_id: str,
        agent_config: Dict[str, Any],
        output_directory: Optional[str],
        batch_name: Optional[str],
        tools_path: Optional[str],
        context_map_builder: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare a single batch task using PromptPreparationService."""
        from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService

        agent_name = agent_config.get('agent_type', agent_config.get('name', 'unknown'))

        # Construct file path for history
        file_path_for_history = None
        if output_directory and batch_name:
            file_path_for_history = str(Path(output_directory) / batch_name)

        # Call PromptPreparationService
        prep_result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name=agent_name,
            contents=row_content if isinstance(row_content, dict) else {},
            mode='batch',
            agent_indices=self.agent_indices,
            dependency_configs=self.dependency_configs,
            current_item=context_map_builder.get(custom_id),
            file_path=file_path_for_history,
            tools_path=tools_path
        )

        # Store passthrough_fields for later merging
        if prep_result.passthrough_fields and custom_id in context_map_builder:
            context_map_builder[custom_id]['_passthrough_fields'] = prep_result.passthrough_fields

        # Create and return task
        cleaned_row = prep_result.llm_context
        return {
            'target_id': custom_id,
            'content': cleaned_row,
            'prompt': prep_result.formatted_prompt
        }

    def _apply_filters(
        self,
        row_content: Any,
        where_clause_config: Optional[Dict[str, Any]],
        conditional_clause: str,
        filter_service
    ) -> BatchFilterResult:
        """
        Apply WHERE clause and conditional filtering to a single item.

        Returns BatchFilterResult with status and should_include flag.
        """
        filter_status_result = filter_service.filter_single_item(
            row_content,
            where_clause_config if where_clause_config and where_clause_config.get('scope') == 'item' else None,
            conditional_clause if conditional_clause else None
        )

        return BatchFilterResult(
            status=filter_status_result.status,
            should_include=filter_status_result.should_include,
            reason=getattr(filter_status_result, 'reason', None),
            metadata=getattr(filter_status_result, 'metadata', {})
        )

    def _validate_config(self, agent_config: Dict[str, Any], provider) -> None:
        """Validate agent configuration."""
        schema = self._prepare_schema(agent_config, provider)
        json_mode = agent_config.get(JSON_MODE_KEY, True)

        if not schema and json_mode:
            raise ConfigurationError(
                'Schema is required for batch processing when json_mode is enabled',
                context={
                    'agent_config': agent_config.get('agent_type', 'unknown'),
                    'json_mode': json_mode,
                    'hint': 'Either provide a schema or set json_mode: false'
                }
            )

    def _prepare_schema(self, agent_config: Dict[str, Any], provider) -> Optional[Dict[str, Any]]:
        """Prepare and compile schema for provider (resolves schema references from registry)."""
        from agent_actions.response_processing.schema_change import prepare_schema_unified
        from agent_actions.utilities.constants import MODEL_VENDOR_KEY

        vendor = agent_config.get(MODEL_VENDOR_KEY, '').lower()
        if not vendor:
            vendor = type(provider).__name__.replace('BatchProvider', '').lower()

        return prepare_schema_unified(agent_config, vendor)

    def _resolve_tools_path(self, agent_config: Dict[str, Any]) -> Optional[str]:
        """Resolve tools path from agent config."""
        tools = agent_config.get('tools', [])
        for tool in tools:
            if isinstance(tool, dict) and tool.get('type') == 'function':
                function_def = tool.get('function', {})
                if 'file' in function_def:
                    import yaml
                    try:
                        tool_file_path = function_def['file']
                        with open(tool_file_path, 'r', encoding='utf-8') as f:
                            tool_config = yaml.safe_load(f)
                            if tool_config and 'module_path' in tool_config:
                                return tool_config['module_path']
                    except (yaml.YAMLError, FileNotFoundError, PermissionError) as e:
                        logger.warning("Failed to load tool config from %s: %s", tool_file_path, e)
        return None

    def _add_tools_to_path(self, tools_path: Optional[str]) -> None:
        """Add tools path to sys.path if not already present."""
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)

    def _get_filter_service(self):
        """Get filter service instance."""
        if self.filter_service:
            return self.filter_service
        # Fall back to global filter service
        from agent_actions.preprocessing.filter_service import get_filter_service
        return get_filter_service()
