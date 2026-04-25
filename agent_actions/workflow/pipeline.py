"""Module for orchestrating data processing pipelines through configured agents."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from agent_actions.config.di.container import ProcessorFactory
from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors import AgentActionsError, ConfigurationError, DependencyError
from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.llm.realtime.output import OutputHandler
from agent_actions.output.writer import FileWriter
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode
from agent_actions.storage.backend import (
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.utils.constants import MODEL_VENDOR_KEY
from agent_actions.utils.safe_format import safe_format_error
from agent_actions.workflow.pipeline_file_mode import (
    prefilter_by_guard,
    process_file_mode_hitl,
    process_file_mode_tool,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

TOOL_VENDOR = "tool"
HITL_VENDOR = "hitl"
SOURCE_FOLDER = "source"
logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for ProcessingPipeline."""

    action_config: ActionConfigDict
    action_name: str
    idx: int
    action_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    source_relative_path: str | None = None  # For storage backend source lookups


@dataclass
class BatchPipelineParams:
    """Parameters for batch pipeline processing."""

    pipeline_action_config: ActionConfigDict
    pipeline_action_name: str
    batch_file_path: str
    batch_base_directory: str
    batch_output_directory: str
    batch_action_configs: dict[str, Any] | None = None
    source_data: Any | None = None
    workflow_metadata: dict[str, Any] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    data: list[dict[str, Any]] | None = None  # Pre-loaded data (skips file read)
    # Pre-built pipeline context from _build_pipeline_context().
    # These fields MUST be populated by the caller — _handle_batch_generation
    # does not rebuild them.
    agent_indices: dict[str, int] | None = None
    dependency_configs: dict[str, Any] | None = None
    version_context: dict[str, Any] | None = None


@dataclass
class FilePathsConfig:
    """File paths configuration."""

    file_path: str
    base_directory: str
    output_directory: str


@dataclass
class ProcessParams:
    """Parameters for pipeline processing."""

    action_config: ActionConfigDict
    action_name: str
    paths: FilePathsConfig
    idx: int
    processor_factory: ProcessorFactory | None
    action_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)


class ProcessingPipeline:
    """Orchestrates data processing through configured agents in batch and online modes."""

    def __init__(self, config: PipelineConfig, processor_factory: ProcessorFactory):
        """
        Initialize the processing pipeline.

        Args:
            config: PipelineConfig with agent configuration
            processor_factory: Required factory for creating processors with DI

        Raises:
            DependencyError: If processor_factory is not provided
            ConfigurationError: If action_config is None or invalid
        """
        if config.action_config is None:
            raise ConfigurationError(
                f"action_config is None for action '{config.action_name}'. "
                f"This usually means the action is not defined in the "
                f"workflow configuration or the configuration failed to "
                f"load properly. Please check your workflow YAML file.",
                context={"action_name": config.action_name, "idx": config.idx},
            )

        self.config = config
        self.model_vendor = str(config.action_config.get(MODEL_VENDOR_KEY) or "").lower()
        self.action_kind = str(config.action_config.get("kind") or "").lower()
        self.granularity = str(config.action_config.get("granularity") or "").lower()
        # Detect synchronous action types via kind OR model_vendor so that
        # batch-mode bypass works regardless of which field the user sets.
        self.is_tool_action = self.action_kind == "tool" or self.model_vendor == "tool"
        self.is_hitl_action = self.action_kind == "hitl" or self.model_vendor == "hitl"
        if processor_factory is None:
            raise DependencyError(
                "ProcessingPipeline requires processor_factory",
                {
                    "component": "ProcessingPipeline",
                    "dependency": "processor_factory",
                    "action_name": config.action_name,
                },
            )

        self.record_processor = RecordProcessor.create(
            agent_config=cast(dict[str, Any], config.action_config),
            agent_name=config.action_name,
        )
        # Initialize OutputHandler with optional storage backend
        self.output_handler = OutputHandler(
            storage_backend=config.storage_backend,
            action_name=config.action_name,
        )

    @staticmethod
    def _build_pipeline_context(
        action_config: ActionConfigDict,
        action_configs: dict[str, Any] | None,
    ) -> tuple[dict[str, int] | None, dict[str, Any] | None, dict[str, Any] | None]:
        """Build shared pipeline context for both batch and online paths.

        ARCHITECTURE INVARIANT: Both batch and online pipelines MUST use this
        method to build pipeline-level context (agent indices, dependency configs,
        version context).  Do not add mode-specific context building outside
        this function.  This prevents the divergence class of bugs where a new
        context field is added to one path but missed in the other (see #87).

        Returns:
            (agent_indices, dependency_configs, version_context)
        """
        agent_indices = None
        dependency_configs = None
        if action_configs:
            agent_indices = {
                name: kconf.get("idx", 999)
                for name, kconf in action_configs.items()
                if kconf is not None and "idx" in kconf
            }
            dependency_configs = action_configs

        version_context = None
        if action_config.get("is_versioned_agent"):
            version_context = action_config.get("_version_context")
            if version_context:
                version_context = dict(version_context)  # Copy to avoid mutation

        return agent_indices, dependency_configs, version_context

    @staticmethod
    def _handle_batch_generation(params: BatchPipelineParams) -> str:
        """Handle batch mode processing.

        Expects agent_indices, dependency_configs, and version_context to be
        pre-populated on ``params`` via ``_build_pipeline_context()``.
        """
        task_preparator = BatchTaskPreparator(
            action_indices=params.agent_indices,
            dependency_configs=params.dependency_configs,
            storage_backend=params.storage_backend,
            version_context=params.version_context,
        )
        client_resolver = BatchClientResolver(client_cache={}, default_client=None)
        context_manager = BatchContextManager()
        registry_manager_factory = create_registry_manager_factory()
        submission_service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
        )
        # Use pre-loaded data if available (storage backend), otherwise read from file
        if params.data is not None:
            data = params.data
            logger.debug(
                "Using pre-loaded data for batch processing (skipping file read): %s",
                params.batch_file_path,
            )
        else:
            file_reader = FileReader(params.batch_file_path)
            data = file_reader.read()
        file_name = Path(params.batch_file_path).name

        result = submission_service.submit_batch_job(
            cast(dict[str, Any], params.pipeline_action_config),
            file_name,
            data,
            params.batch_output_directory,
            source_data=params.source_data,
            workflow_metadata=params.workflow_metadata,
        )

        relative_path = Path(params.batch_file_path).relative_to(params.batch_base_directory)
        output_file_path = Path(params.batch_output_directory) / relative_path
        if (
            result.is_passthrough
            and result.passthrough is not None
            and result.passthrough.get("type") == "tombstone"
        ):
            file_writer = FileWriter(
                str(output_file_path),
                storage_backend=params.storage_backend,
                action_name=params.pipeline_action_name,
                output_directory=params.batch_output_directory,
            )
            file_writer.write_target(result.passthrough["data"])
            if params.storage_backend:
                params.storage_backend.set_disposition(
                    params.pipeline_action_name,
                    NODE_LEVEL_RECORD_ID,
                    DISPOSITION_PASSTHROUGH,
                    reason="All records tombstoned",
                )
            return str(output_file_path)

        # Batch job placeholder - always JSON (tracking file, not data)
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        placeholder = {
            "batch_job_id": result.batch_id,
            "status": "submitted",
            "agent": params.pipeline_action_name,
        }
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(placeholder, f)
        return str(output_file_path)

    @staticmethod
    def process_file(params: ProcessParams):
        """
        Static method for processing data through the pipeline.

        Args:
            params: ProcessParams containing all processing parameters

        Returns:
            Path to the generated output file

        Raises:
            DependencyError: If processor_factory is not provided
        """
        if params.processor_factory is None:
            raise DependencyError(
                "ProcessingPipeline.process_file requires processor_factory",
                {
                    "method": "ProcessingPipeline.process_file",
                    "dependency": "processor_factory",
                    "agent_name": params.action_name,
                },
            )
        # Tool and HITL actions run synchronously regardless of run_mode
        # (tools are Python functions, HITL blocks for human input)
        is_synchronous = params.action_config.get("model_vendor") in [
            TOOL_VENDOR,
            HITL_VENDOR,
        ] or params.action_config.get("kind") in ["tool", "hitl"]

        run_mode = params.action_config.get("run_mode")
        if run_mode == RunMode.BATCH and not is_synchronous:
            agent_indices, dependency_configs, version_context = (
                ProcessingPipeline._build_pipeline_context(
                    params.action_config,
                    params.action_configs,
                )
            )
            return ProcessingPipeline._handle_batch_generation(
                BatchPipelineParams(
                    pipeline_action_config=params.action_config,
                    pipeline_action_name=params.action_name,
                    batch_file_path=params.paths.file_path,
                    batch_base_directory=params.paths.base_directory,
                    batch_output_directory=params.paths.output_directory,
                    batch_action_configs=params.action_configs,
                    workflow_metadata=params.workflow_metadata,
                    storage_backend=params.storage_backend,
                    agent_indices=agent_indices,
                    dependency_configs=dependency_configs,
                    version_context=version_context,
                )
            )
        if run_mode == RunMode.BATCH and is_synchronous:
            logger.warning(
                "Action '%s' has run_mode=batch but kind '%s' requires synchronous "
                "execution. Running in online mode.",
                params.action_name,
                params.action_config.get("kind", params.action_config.get("model_vendor")),
            )
        pipeline = create_processing_pipeline_from_params(
            action_config=params.action_config,
            action_name=params.action_name,
            idx=params.idx,
            processor_factory=params.processor_factory,
            action_configs=params.action_configs,
            storage_backend=params.storage_backend,
        )
        return pipeline.process(
            params.paths.file_path, params.paths.base_directory, params.paths.output_directory
        )

    def process(
        self,
        file_path: str,
        base_directory: str,
        output_directory: str,
        data: list[dict[str, Any]] | None = None,
    ) -> str:
        """
        Process input file and generate output.

        Args:
            file_path: Path to the input JSON file (also used for output path calculation)
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
            data: Optional pre-loaded data (skips file read when provided)

        Returns:
            Path to the generated output file
        """
        try:
            if data is None:
                data = self._read_input_data(file_path)
            else:
                logger.debug(
                    "Using pre-loaded data for %s (skipping file read)",
                    file_path,
                )
            self._process_by_strategy(data, file_path, base_directory, output_directory)
            relative_path = Path(file_path).relative_to(base_directory)
            return str(Path(output_directory) / relative_path)
        except (AgentActionsError, ValueError) as e:
            raise AgentActionsError(
                f"Error generating target: {safe_format_error(e)}",
                context={
                    "file_path": str(file_path),
                    "base_directory": str(base_directory),
                    "output_directory": str(output_directory),
                    "agent_name": self.config.action_name,
                },
                cause=e,
            ) from e
        except (OSError, TypeError, KeyError) as e:
            raise AgentActionsError(
                f"Unexpected error generating target: {safe_format_error(e)}",
                context={
                    "file_path": str(file_path),
                    "base_directory": str(base_directory),
                    "output_directory": str(output_directory),
                    "agent_name": self.config.action_name,
                },
                cause=e,
            ) from e

    def _read_input_data(self, file_path):
        """Read data from input file."""
        file_reader = FileReader(file_path)
        return file_reader.read()

    def _handle_batch_mode(
        self,
        data: Any,
        file_path: str,
        base_directory: str,
        output_directory: str,
        source_data: Any | None = None,
        agent_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, Any] | None = None,
        version_context: dict[str, Any] | None = None,
    ):
        """Handle batch mode processing.

        Args:
            data: Input data (pre-loaded from storage backend or None to read from file)
            file_path: Path to the input file
            base_directory: Base directory for processing
            output_directory: Directory for output files
            source_data: Optional source data for {{ source.* }} templates
            agent_indices: Pre-built agent indices from _build_pipeline_context()
            dependency_configs: Pre-built dependency configs from _build_pipeline_context()
            version_context: Pre-built version context from _build_pipeline_context()
        """
        result_path = self._handle_batch_generation(
            BatchPipelineParams(
                pipeline_action_config=self.config.action_config,
                pipeline_action_name=self.config.action_name,
                batch_file_path=file_path,
                batch_base_directory=base_directory,
                batch_output_directory=output_directory,
                batch_action_configs=self.config.action_configs,
                source_data=source_data,
                workflow_metadata=self.config.workflow_metadata,
                storage_backend=self.config.storage_backend,
                data=data,  # Pass pre-loaded data to avoid file read
                agent_indices=agent_indices,
                dependency_configs=dependency_configs,
                version_context=version_context,
            )
        )
        return result_path

    def _process_by_strategy(
        self,
        data: Any,
        file_path: str,
        base_directory: str,
        output_directory: str,
    ):
        """
        Select and apply the appropriate processing strategy based on
        configuration. Uses RecordProcessor for unified processing.
        """
        # Initialize source_data with the input data.
        # For cross-workflow records (source_relative_path is None), the input
        # data IS the source — there's no staging data in this workflow for them.
        source_data = data

        if self.config.source_relative_path and self.config.storage_backend is not None:
            try:
                from agent_actions.input.loaders.source_data import SourceDataLoader

                source_loader = SourceDataLoader(
                    agent_name=self.config.action_name,
                    storage_backend=self.config.storage_backend,  # type: ignore[arg-type]
                )

                loaded_source = source_loader.load_source_data(self.config.source_relative_path)

                if isinstance(loaded_source, list):
                    source_data = loaded_source
                else:
                    source_data = [loaded_source] if loaded_source else []  # type: ignore[unreachable]

                logger.debug("Loaded source data via SourceDataLoader for %s", file_path)

            except (FileNotFoundError, ValueError):
                # FileNotFoundError: no source data for this path (normal for
                # cross-workflow workflows that have no staging data).
                # ValueError: empty/invalid path from storage backend validation.
                # In both cases, input data is the correct source context.
                pass

        # ── per-action record_limit ──────────────────────────────────────
        record_limit = self.config.action_config.get("record_limit")
        if isinstance(record_limit, int) and isinstance(data, list) and len(data) > record_limit:
            total = len(data)
            data = data[:record_limit]
            logger.info(
                "record_limit=%d: processing %d of %d records for %s",
                record_limit,
                len(data),
                total,
                self.config.action_name,
            )

        # Build shared pipeline context BEFORE the batch/online fork.
        # See _build_pipeline_context() docstring for the architecture invariant.
        agent_indices, dependency_configs, version_context = self._build_pipeline_context(
            self.config.action_config,
            self.config.action_configs,
        )

        # ── batch/online fork ──────────────────────────────────────────────
        # Everything above this point is shared. Below here, paths diverge.
        run_mode = self.config.action_config.get("run_mode")
        if run_mode == RunMode.BATCH and not (self.is_tool_action or self.is_hitl_action):
            self._handle_batch_mode(
                data,
                file_path,
                base_directory,
                output_directory,
                source_data,
                agent_indices,
                dependency_configs,
                version_context,
            )
            return

        # Create processing context
        context = ProcessingContext(
            agent_config=self.config.action_config,
            agent_name=self.config.action_name,
            mode=RunMode.ONLINE,
            is_first_stage=False,
            source_data=source_data,  # Pass the loaded source data
            file_path=file_path,
            output_directory=output_directory,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            version_context=version_context,
            storage_backend=self.config.storage_backend,
        )

        # Process via RecordProcessor
        # NOTE: Do NOT filter _unprocessed records here. Guard-skipped records
        # (on_false: skip) produce _unprocessed tombstones that are valid pipeline
        # data. task_preparer._is_upstream_unprocessed() handles them per-record.
        if self.granularity == "file" and (self.is_tool_action or self.is_hitl_action):
            # For FILE mode, use the input data as source for parent lookup
            # (not source_data which points to original source folder)
            context.source_data = data
            filtered = apply_observe_for_file_mode(
                data=data,
                agent_config=cast(dict[str, Any], self.config.action_config),
                agent_name=self.config.action_name,
                agent_indices=agent_indices,
                file_path=file_path,
                source_data=source_data,
                storage_backend=self.config.storage_backend,
            )

            # Guards must run before FILE-mode processing because FILE mode
            # sends the entire array in one batch and cannot filter per-record.
            # Pass raw `data` so original_passing preserves pre-observe fields.
            passing, skipped, original_passing = prefilter_by_guard(
                filtered,
                cast(dict[str, Any], self.config.action_config),
                self.config.action_name,
                original_data=data,
            )

            # Align context.source_data with the guard-passing subset so the
            # enricher's source_mapping indices resolve to the correct parents.
            context.source_data = original_passing

            if not passing:
                results = _build_skipped_results(skipped)
            else:
                if self.is_tool_action:
                    results = self._process_file_mode_tool(passing, original_passing, context)
                else:
                    results = self._process_file_mode_hitl(passing, original_passing, context)

                results.extend(_build_skipped_results(skipped))
        else:
            results = self.record_processor.process_batch(data, context)

        # Collect success results
        output, stats = ResultCollector.collect_results(
            results,
            cast(dict[str, Any], self.config.action_config),
            self.config.action_name,
            is_first_stage=False,
            storage_backend=self.config.storage_backend,
        )

        # Signal node-level SKIP only when output is truly empty and the
        # only outcomes were guard-skip / guard-filter.  Guard-skipped
        # records with passthrough data ARE in `output`, so `not output`
        # prevents cascade-blocking when passthrough data exists.
        if data and stats.only_guard_outcomes and not output:
            storage_backend = self.config.storage_backend
            if storage_backend is not None:
                try:
                    storage_backend.set_disposition(
                        self.config.action_name,
                        NODE_LEVEL_RECORD_ID,
                        DISPOSITION_SKIPPED,
                        reason="All records filtered — no output produced",
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to write guard-skip disposition for %s: %s",
                        self.config.action_name,
                        e,
                    )

        # Zero-success failure: raise so executor marks FAILED and circuit
        # breaker skips downstream.  Uses stats.success (not `not output`)
        # because EXHAUSTED tombstones inflate the output list.
        if data and stats.success == 0 and (stats.failed + stats.exhausted) > 0:
            raise RuntimeError(
                f"Action '{self.config.action_name}' produced 0 successful records — "
                f"all {len(data)} input item(s) failed or exhausted "
                f"({stats.failed} failed, {stats.exhausted} exhausted)"
            )

        self.output_handler.save_main_output(output, file_path, base_directory, output_directory)

    def _process_file_mode_tool(
        self, data: list[dict], original_data: list[dict], context: ProcessingContext
    ) -> list:
        """Delegator stub — see :func:`pipeline_file_mode.process_file_mode_tool`."""
        return process_file_mode_tool(self, data, original_data, context)

    def _process_file_mode_hitl(
        self, data: list[dict], original_data: list[dict], context: ProcessingContext
    ) -> list:
        """Delegator stub — see :func:`pipeline_file_mode.process_file_mode_hitl`."""
        return process_file_mode_hitl(self, data, original_data, context)


def _build_skipped_results(skipped: list[dict]) -> list[ProcessingResult]:
    """Convert guard-skipped items into UNPROCESSED ProcessingResults."""
    return [
        ProcessingResult.unprocessed(
            data=[item],
            reason="guard_prefilter_skip",
            source_guid=item.get("source_guid"),
        )
        for item in skipped
    ]


def create_processing_pipeline(
    config: PipelineConfig, processor_factory: ProcessorFactory
) -> ProcessingPipeline:
    """
    Factory function for creating a ProcessingPipeline instance.

    Args:
        config: PipelineConfig with agent configuration
        processor_factory: Required factory for creating processors with DI

    Returns:
        ProcessingPipeline instance
    """
    return ProcessingPipeline(config, processor_factory)


def create_processing_pipeline_from_params(
    action_config: ActionConfigDict,
    action_name: str,
    idx: int,
    processor_factory: ProcessorFactory,
    action_configs: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    storage_backend: Optional["StorageBackend"] = None,
    source_relative_path: str | None = None,
) -> ProcessingPipeline:
    """
    Factory function for creating a ProcessingPipeline instance from individual parameters.

    Args:
        action_config: Configuration for the action
        action_name: Name of the action
        idx: Index of the action
        processor_factory: Required factory for creating processors with DI
        action_configs: Optional dictionary of all action configurations
        workflow_metadata: Optional workflow metadata for {{ workflow.* }} templates
        storage_backend: Optional storage backend for database persistence
        source_relative_path: Optional explicit path for storage backend source lookups

    Returns:
        ProcessingPipeline instance
    """
    config = PipelineConfig(
        action_config=action_config,
        action_name=action_name,
        idx=idx,
        action_configs=action_configs,
        workflow_metadata=workflow_metadata,
        storage_backend=storage_backend,
        source_relative_path=source_relative_path,
    )
    return ProcessingPipeline(config, processor_factory)
