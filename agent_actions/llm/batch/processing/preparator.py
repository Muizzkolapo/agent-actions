"""Batch task preparation from raw data using shared TaskPreparer logic."""

import logging
from pathlib import Path
from typing import Any

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import (
    BatchTaskPreparationStats,
    PreparedBatchTasks,
)
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer, get_task_preparer
from agent_actions.utils.constants import JSON_MODE_KEY
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.tools_resolver import resolve_tools_path

logger = logging.getLogger(__name__)


class BatchTaskPreparator:
    """Prepares batch tasks from raw data using TaskPreparer for unified preparation."""

    def __init__(
        self,
        action_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        storage_backend: Any | None = None,
        version_context: dict[str, Any] | None = None,
    ):
        self.action_indices = action_indices or {}
        self.dependency_configs = dependency_configs or {}
        self.storage_backend = storage_backend
        self.version_context = version_context

    def prepare_tasks(
        self,
        agent_config: dict[str, Any],
        data: list[dict[str, Any]],
        provider,
        output_directory: str | None = None,
        batch_name: str | None = None,
        source_data: list[Any] | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> PreparedBatchTasks:
        """Prepare batch tasks from raw data.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        # Validate agent_config is not None
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

        # Validate configuration
        self._validate_config(agent_config, provider)

        from agent_actions.prompt.formatter import PromptFormatter

        PromptFormatter.get_raw_prompt(agent_config)  # Validate prompt exists

        # Pre-flight validation
        self._run_preflight_validation(
            agent_config,
            data,
            output_directory,
            batch_name,
            source_data,
            workflow_metadata,
        )

        tools_path = resolve_tools_path(agent_config)
        self._add_tools_to_path(tools_path)

        schema = self._prepare_schema(agent_config, provider)

        context_map_builder: dict[str, Any] = {}
        tasks_builder: list[dict[str, Any]] = []
        stats = BatchTaskPreparationStats(total_items=len(data))

        # Build PreparationContext for TaskPreparer
        prep_context = self._build_preparation_context(
            agent_config=agent_config,
            output_directory=output_directory,
            batch_name=batch_name,
            source_data=source_data,
            workflow_metadata=workflow_metadata,
            tools_path=tools_path,
        )

        # Process each data item using TaskPreparer
        task_preparer = get_task_preparer()

        for row in data:
            try:
                result = self._process_single_item(
                    row=row,
                    prep_context=prep_context,
                    task_preparer=task_preparer,
                    context_map_builder=context_map_builder,
                    stats=stats,
                )

                if result:
                    tasks_builder.append(result)
                    stats.included_items += 1

            except Exception as e:
                logger.exception("Failed to prepare task for row: %s", e)
                stats.error_items += 1

        # Finalize tasks with provider
        provider_config = agent_config.copy()
        provider_config["compiled_schema"] = schema
        final_tasks = provider.prepare_tasks(tasks_builder, provider_config)

        # Return immutable result
        return PreparedBatchTasks(
            tasks=final_tasks,
            context_map=context_map_builder,
            stats=stats,
            config=agent_config,
        )

    def _process_single_item(
        self,
        row: dict[str, Any],
        prep_context: PreparationContext,
        task_preparer: TaskPreparer,
        context_map_builder: dict[str, Any],
        stats: BatchTaskPreparationStats,
    ) -> dict[str, Any] | None:
        """Process a single data item using TaskPreparer.

        Return prepared task if item should be included, None otherwise.
        Update context_map_builder and stats as side effects.
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

        # 3. Update prep_context with current item
        prep_context.current_item = row_with_meta

        # 4. Use TaskPreparer for unified preparation
        # ONE guard check with full context (normalize → source → prompt → guard)
        prepared = task_preparer.prepare(row, prep_context, existing_target_id=custom_id)

        # 5. Store passthrough_fields for later merging
        if prepared.passthrough_fields and custom_id in context_map_builder:
            BatchContextMetadata.set_passthrough_fields(
                context_map_builder[custom_id], prepared.passthrough_fields
            )

        # 6. Handle guard results
        if prepared.guard_status == GuardStatus.UPSTREAM_UNPROCESSED:
            BatchContextMetadata.set_filter_status(
                context_map_builder[custom_id], FilterStatus.SKIPPED
            )
            context_map_builder[custom_id][ContextMetaKeys.FILTER_PHASE] = "upstream_unprocessed"
            stats.skipped_items += 1
            logger.debug("Upstream unprocessed item %s", custom_id)
            return None

        if prepared.guard_status == GuardStatus.FILTERED:
            BatchContextMetadata.set_filter_status(
                context_map_builder[custom_id], FilterStatus.FILTERED
            )
            context_map_builder[custom_id][ContextMetaKeys.FILTER_PHASE] = "unified"
            stats.filtered_items += 1
            logger.debug("Guard filtered item %s (phase=unified)", custom_id)
            return None

        if prepared.guard_status == GuardStatus.SKIPPED:
            BatchContextMetadata.set_filter_status(
                context_map_builder[custom_id], FilterStatus.SKIPPED
            )
            context_map_builder[custom_id][ContextMetaKeys.FILTER_PHASE] = "unified"
            stats.skipped_items += 1
            logger.debug("Guard skipped item %s (phase=unified)", custom_id)
            return None

        # 7. Create and return task
        return {
            "target_id": custom_id,
            "content": prepared.llm_context,
            "prompt": prepared.formatted_prompt,
        }

    def _validate_config(self, agent_config: dict[str, Any], provider) -> None:
        """Validate agent configuration."""
        schema = self._prepare_schema(agent_config, provider)
        json_mode = agent_config.get(JSON_MODE_KEY, True)

        if not schema and json_mode:
            raise ConfigurationError(
                "Schema is required for batch processing when json_mode is enabled",
                context={
                    "agent_config": agent_config["agent_type"],
                    "json_mode": json_mode,
                    "hint": "Either provide a schema or set json_mode: false",
                },
            )

    def _prepare_schema(self, agent_config: dict[str, Any], provider) -> dict[str, Any] | None:
        """Prepare and compile schema for provider."""
        from pathlib import Path

        from agent_actions.output.response.schema import ResponseSchemaCompiler
        from agent_actions.utils.constants import MODEL_VENDOR_KEY

        vendor = agent_config.get(MODEL_VENDOR_KEY, "").lower()
        if not vendor:
            vendor = type(provider).__name__.replace("BatchProvider", "").lower()

        _pr = agent_config.get("_project_root")
        compiler = ResponseSchemaCompiler(project_root=Path(_pr) if _pr else None)
        schema, _captured_results = compiler.compile(agent_config, vendor)
        return schema  # type: ignore[return-value]

    def _add_tools_to_path(self, tools_path: str | None) -> None:
        """Do nothing (tools are loaded via spec_from_file_location, not sys.path)."""

    def _build_preparation_context(
        self,
        agent_config: dict[str, Any],
        output_directory: str | None,
        batch_name: str | None,
        source_data: list[Any] | None,
        workflow_metadata: dict[str, Any] | None,
        tools_path: str | None,
        current_item: dict[str, Any] | None = None,
    ) -> PreparationContext:
        """Build PreparationContext with common settings."""
        agent_name = agent_config.get("agent_type", agent_config.get("name", "unknown"))
        file_path = (
            str(Path(output_directory) / batch_name) if output_directory and batch_name else None
        )

        return PreparationContext(
            agent_config=agent_config,
            agent_name=agent_name,
            is_first_stage=False,  # Batch is always subsequent-stage
            mode=RunMode.BATCH,
            source_data=source_data,
            agent_indices=self.action_indices,
            dependency_configs=self.dependency_configs,
            workflow_metadata=workflow_metadata,
            version_context=self.version_context,
            file_path=file_path,
            output_directory=output_directory,
            tools_path=tools_path,
            storage_backend=self.storage_backend,
            current_item=current_item,
        )

    def _run_preflight_validation(
        self,
        agent_config: dict[str, Any],
        data: list[dict[str, Any]],
        output_directory: str | None = None,
        batch_name: str | None = None,
        source_data: list[Any] | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Run pre-flight validation on first data row to catch template errors early."""
        if not data:
            return

        first_row = data[0]
        tools_path = resolve_tools_path(agent_config)
        prep_context = self._build_preparation_context(
            agent_config=agent_config,
            output_directory=output_directory,
            batch_name=batch_name,
            source_data=source_data,
            workflow_metadata=workflow_metadata,
            tools_path=tools_path,
            current_item=first_row,
        )

        # Run preparation on first row to catch template errors early
        # Skip guard evaluation to ensure prompt is always rendered for validation
        # (guards might filter the first row, hiding template errors)
        task_preparer = get_task_preparer()
        task_preparer.prepare(first_row, prep_context, skip_guard=True)
