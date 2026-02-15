"""Module for orchestrating data processing pipelines through configured agents."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.output.writer import FileWriter
from agent_actions.llm.realtime.output import OutputHandler
from agent_actions.errors import AgentActionsException, ConfigurationError, DependencyError
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID, DISPOSITION_PASSTHROUGH
from agent_actions.utils.constants import MODEL_VENDOR_KEY
from agent_actions.llm.batch.service import BatchService
from agent_actions.config.di.container import ProcessorFactory
from agent_actions.utils.safe_format import safe_format_error
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.prompt.context.scope import ContextScopeProcessor

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

TOOL_VENDOR = "tool"
HITL_VENDOR = "hitl"
SOURCE_FOLDER = "source"
logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for ProcessingPipeline."""

    agent_config: Dict[str, Any]
    agent_name: str
    idx: int
    agent_configs: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    source_relative_path: Optional[str] = None  # For storage backend source lookups


@dataclass
class BatchPipelineParams:
    """Parameters for batch pipeline processing."""

    pipeline_agent_config: Dict[str, Any]
    pipeline_agent_name: str
    batch_file_path: str
    batch_base_directory: str
    batch_output_directory: str
    batch_agent_configs: Optional[Dict[str, Any]] = None
    source_data: Optional[Any] = None
    workflow_metadata: Optional[Dict[str, Any]] = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    data: Optional[List[Dict[str, Any]]] = None  # Pre-loaded data (skips file read)


@dataclass
class FilePathsConfig:
    """File paths configuration."""

    file_path: str
    base_directory: str
    output_directory: str


@dataclass
class ProcessParams:
    """Parameters for pipeline processing."""

    agent_config: Dict[str, Any]
    agent_name: str
    paths: FilePathsConfig
    idx: int
    processor_factory: Optional[ProcessorFactory]
    agent_configs: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None
    storage_backend: Optional["StorageBackend"] = field(default=None)


class ProcessingPipeline:
    """
    Orchestrates data processing workflows through configured agents.

    Handles both batch and online processing modes, routing input files
    through agent pipelines and generating enriched output files.
    """

    def __init__(self, config: PipelineConfig, processor_factory: ProcessorFactory):
        """
        Initialize the processing pipeline.

        Args:
            config: PipelineConfig with agent configuration
            processor_factory: Required factory for creating processors with DI

        Raises:
            DependencyError: If processor_factory is not provided
            ConfigurationError: If agent_config is None or invalid
        """
        if config.agent_config is None:
            raise ConfigurationError(
                f"agent_config is None for agent '{config.agent_name}'. "
                f"This usually means the agent is not defined in the "
                f"workflow configuration or the configuration failed to "
                f"load properly. Please check your workflow YAML file.",
                context={"agent_name": config.agent_name, "idx": config.idx},
            )

        self.config = config
        self.model_vendor = (config.agent_config.get(MODEL_VENDOR_KEY) or "").lower()
        self.action_kind = (config.agent_config.get("kind") or "").lower()
        self.granularity = (config.agent_config.get("granularity") or "").lower()
        # kind: "tool" = tool action, "hitl" = HITL action, "llm" = LLM action
        self.is_tool_action = self.action_kind == "tool"
        self.is_hitl_action = self.action_kind == "hitl"
        if processor_factory is None:
            raise DependencyError(
                "ProcessingPipeline requires processor_factory",
                {
                    "component": "ProcessingPipeline",
                    "dependency": "processor_factory",
                    "agent_name": config.agent_name,
                },
            )

        # Initialize RecordProcessor directly
        self.record_processor = RecordProcessor(
            agent_config=config.agent_config,
            agent_name=config.agent_name,
        )
        # Initialize OutputHandler with optional storage backend
        self.output_handler = OutputHandler(
            storage_backend=config.storage_backend,
            action_name=config.agent_name,
        )

    @staticmethod
    def _handle_batch_generation(params: BatchPipelineParams) -> str:
        """Handle batch mode processing."""
        agent_indices = None
        if params.batch_agent_configs:
            agent_indices = {
                name: config.get("idx", 999)
                for name, config in params.batch_agent_configs.items()
                if config is not None and "idx" in config
            }

        batch_service = BatchService(
            agent_indices=agent_indices,
            dependency_configs=params.batch_agent_configs,
            storage_backend=params.storage_backend,
            action_name=params.pipeline_agent_name,
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

        result = batch_service.submit_batch_job(
            params.pipeline_agent_config,
            file_name,
            data,
            params.batch_output_directory,
            source_data=params.source_data,
            workflow_metadata=params.workflow_metadata,
        )

        relative_path = Path(params.batch_file_path).relative_to(params.batch_base_directory)
        output_file_path = Path(params.batch_output_directory) / relative_path
        if isinstance(result, dict) and result.get("type") == "tombstone":
            file_writer = FileWriter(
                str(output_file_path),
                storage_backend=params.storage_backend,
                action_name=params.pipeline_agent_name,
                output_directory=params.batch_output_directory,
            )
            file_writer.write_target(result["data"])
            if params.storage_backend:
                params.storage_backend.set_disposition(
                    params.pipeline_agent_name,
                    NODE_LEVEL_RECORD_ID,
                    DISPOSITION_PASSTHROUGH,
                    reason="All records tombstoned",
                )
            return str(output_file_path)

        # Batch job placeholder - always JSON (tracking file, not data)
        # Directory is needed for the placeholder file
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        placeholder = {
            "batch_job_id": result,
            "status": "submitted",
            "agent": params.pipeline_agent_name,
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
                    "agent_name": params.agent_name,
                },
            )
        # Tool and HITL actions run synchronously regardless of run_mode
        # (tools are Python functions, HITL blocks for human input)
        is_synchronous = params.agent_config.get("model_vendor") in [
            TOOL_VENDOR,
            HITL_VENDOR,
        ] or params.agent_config.get("kind") in ["tool", "hitl"]

        if params.agent_config.get("run_mode") == "batch" and not is_synchronous:
            return ProcessingPipeline._handle_batch_generation(
                BatchPipelineParams(
                    pipeline_agent_config=params.agent_config,
                    pipeline_agent_name=params.agent_name,
                    batch_file_path=params.paths.file_path,
                    batch_base_directory=params.paths.base_directory,
                    batch_output_directory=params.paths.output_directory,
                    batch_agent_configs=params.agent_configs,
                    workflow_metadata=params.workflow_metadata,
                    storage_backend=params.storage_backend,
                )
            )
        pipeline = create_processing_pipeline_from_params(
            agent_config=params.agent_config,
            agent_name=params.agent_name,
            idx=params.idx,
            processor_factory=params.processor_factory,
            agent_configs=params.agent_configs,
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
        data: Optional[List[Dict[str, Any]]] = None,
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
        except (AgentActionsException, ConfigurationError, ValueError) as e:
            raise AgentActionsException(
                f"Error generating target: {safe_format_error(e)}",
                context={
                    "file_path": str(file_path),
                    "base_directory": str(base_directory),
                    "output_directory": str(output_directory),
                    "agent_name": self.config.agent_name,
                },
                cause=e,
            ) from e
        except (OSError, IOError, TypeError, KeyError) as e:
            raise AgentActionsException(
                f"Unexpected error generating target: {safe_format_error(e)}",
                context={
                    "file_path": str(file_path),
                    "base_directory": str(base_directory),
                    "output_directory": str(output_directory),
                    "agent_name": self.config.agent_name,
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
        source_data: Optional[Any] = None,
    ):
        """Handle batch mode processing.

        Args:
            data: Input data (pre-loaded from storage backend or None to read from file)
            file_path: Path to the input file
            base_directory: Base directory for processing
            output_directory: Directory for output files
            source_data: Optional source data for {{ source.* }} templates
        """
        result_path = self._handle_batch_generation(
            BatchPipelineParams(
                pipeline_agent_config=self.config.agent_config,
                pipeline_agent_name=self.config.agent_name,
                batch_file_path=file_path,
                batch_base_directory=base_directory,
                batch_output_directory=output_directory,
                batch_agent_configs=self.config.agent_configs,
                source_data=source_data,
                workflow_metadata=self.config.workflow_metadata,
                storage_backend=self.config.storage_backend,
                data=data,  # Pass pre-loaded data to avoid file read
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
        # Initialize source_data with the input data as a fallback
        source_data = data

        try:
            from agent_actions.input.loaders.source_data import SourceDataLoader

            source_loader = SourceDataLoader(
                agent_name=self.config.agent_name,
                storage_backend=self.config.storage_backend,
            )

            # Load the source data using the explicit source_relative_path
            loaded_source = source_loader.load_source_data(self.config.source_relative_path)

            if isinstance(loaded_source, list):
                source_data = loaded_source
            else:
                # Should be a list, but handle single dict if returned
                source_data = [loaded_source] if loaded_source else []

            logger.info("Loaded source data via SourceDataLoader for %s", file_path)

        except Exception as e:
            logger.error(
                "SourceDataLoader failed to resolve source for '%s': %s. "
                "Agent: %s. "
                "Falling back to using input data as source context. "
                "This will likely cause 'undefined variable' errors if templates expect source fields.",
                file_path,
                e,
                self.config.agent_name,
            )
            # source_data remains 'data' (the fallback)

        # Batch mode check (tools and HITL run synchronously, not in batch)
        run_mode = self.config.agent_config.get("run_mode")
        if run_mode == "batch" and not (self.is_tool_action or self.is_hitl_action):
            self._handle_batch_mode(data, file_path, base_directory, output_directory, source_data)
            return

        # Prepare agent indices and dependency configs for context
        # (These might be needed if RecordProcessor does historical lookups)
        agent_indices = None
        dependency_configs = None
        if self.config.agent_configs:
            agent_indices = {
                name: kconf.get("idx", 999)
                for name, kconf in self.config.agent_configs.items()
                if kconf is not None and "idx" in kconf
            }
            dependency_configs = self.config.agent_configs

        agent_ids = agent_indices

        # Extract version context for versioned agents
        # This enables {{ i }}, {{ version.length }}, etc. in Jinja2 templates
        version_context = None
        agent_config = self.config.agent_config
        if agent_config.get("is_versioned_agent"):
            version_context = agent_config.get("_version_context")
            if version_context:
                version_context = dict(version_context)  # Copy to avoid mutation

        # Create processing context
        context = ProcessingContext(
            agent_config=self.config.agent_config,
            agent_name=self.config.agent_name,
            mode=ProcessingMode.ONLINE,
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
        if self.granularity == "file" and self.is_tool_action:
            # For FILE mode, use the input data as source for parent lookup
            # (not source_data which points to original source folder)
            context.source_data = data
            filtered = self._apply_observe_filter(data, self.config.agent_config)
            results = self._process_file_mode_tool(filtered, data, context)
        elif self.granularity == "file" and self.is_hitl_action:
            # For FILE mode HITL, present the entire dataset for one decision
            context.source_data = data
            filtered = self._apply_observe_filter(data, self.config.agent_config)
            results = self._process_file_mode_hitl(filtered, data, context)
        else:
            # process_batch handles looping and calls process() which handles retries
            results = self.record_processor.process_batch(data, context)

        # Collect success results
        output = ResultCollector.collect_results(
            results,
            self.config.agent_config,
            self.config.agent_name,
            is_first_stage=False,
            storage_backend=self.config.storage_backend,
        )

        self.output_handler.save_main_output(output, file_path, base_directory, output_directory)

    @staticmethod
    def _apply_observe_filter(data: List[Dict], agent_config: Dict[str, Any]) -> List[Dict]:
        """Filter records to context_scope.observe fields in defined order.

        Returns filtered copy; original data is unchanged.
        If no observe is configured, returns data as-is.
        """
        context_scope = agent_config.get("context_scope") or {}
        observe_refs = context_scope.get("observe")
        if not observe_refs:
            return data

        field_names = ContextScopeProcessor.extract_field_names_from_references(observe_refs)
        if not field_names:
            return data

        # Wildcard or prefix pattern → no filtering needed
        if "*" in field_names or "_" in field_names:
            return data

        filtered = []
        for item in data:
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            content = item.get("content", item) if isinstance(item.get("content"), dict) else item
            ordered = {k: content[k] for k in field_names if k in content}
            missing = [k for k in field_names if k not in content]
            if missing:
                logger.warning(
                    "[OBSERVE FILTER] Fields %s not found in record. "
                    "Available: %s. Check that observe field names match the actual data.",
                    missing,
                    list(content.keys()),
                )
            filtered.append(ordered)
        return filtered

    def _process_file_mode_tool(
        self, data: List[Dict], original_data: List[Dict], context: ProcessingContext
    ) -> List:
        """
        Process tool in FILE granularity mode.

        Invokes tool once with full array instead of looping per-record.
        Tool receives array WITH existing IDs/lineage.
        Tool returns array of outputs (N→M transformation allowed).
        Enrichment assigns new IDs/lineage to each output.

        Args:
            data: Observe-filtered records (passed to tool)
            original_data: Unfiltered records (available for enrichment)
            context: Processing context

        Returns:
            List with single ProcessingResult containing all outputs
        """
        try:
            # Get tools_path from agent config
            tools_path = context.agent_config.get("tools_path")

            # Invoke tool once with full array
            # For tools, formatted_prompt is not used, so we pass empty string
            raw_response, executed = run_dynamic_agent(
                agent_config=context.agent_config,
                agent_name=context.agent_name,
                context=data,  # Full array of records
                formatted_prompt="",  # Not used for tools
                tools_path=tools_path,
            )

            # Safety net: unwrap FileUDFResult if it wasn't already unwrapped
            # during validation in _validate_udf_output. Handles the case where
            # validation is skipped (validate_output=False or no json_output_schema).
            from agent_actions.utils.udf_management.registry import FileUDFResult

            if isinstance(raw_response, FileUDFResult):
                raw_response = raw_response.outputs

            # Tool should return array
            if not isinstance(raw_response, list):
                raise ValueError(
                    f"FILE mode tool must return a list (or FileUDFResult), "
                    f"got {type(raw_response).__name__}"
                )

            # Reserved framework fields that go at top level, not in content
            RESERVED_FIELDS = {
                "source_guid",
                "target_id",
                "node_id",
                "lineage",
                "metadata",
                "content",
            }

            # Wrap each tool output in {content: {...}} structure
            # Preserve source_guid at top level for lineage chaining
            structured_data = []
            for item in raw_response:
                if isinstance(item, dict):
                    # Separate data fields from reserved framework fields
                    data_fields = {k: v for k, v in item.items() if k not in RESERVED_FIELDS}

                    # Build structured item with content
                    structured_item = {"content": data_fields}

                    # Preserve source_guid at top level (needed for lineage chaining)
                    if "source_guid" in item:
                        structured_item["source_guid"] = item["source_guid"]

                    structured_data.append(structured_item)
                else:
                    # Handle non-dict outputs
                    structured_data.append({"content": {"value": item}})

            result = ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=structured_data,
                source_guid=None,  # FILE mode has no single source
                raw_response=raw_response,
                executed=executed,
            )

            # Run enrichment on ALL items in result
            result = self.record_processor.enrichment_pipeline.enrich(result, context)

            return [result]

        except Exception as e:
            # NOTE: Intentional behavioral change — FILE mode tool errors now raise
            # instead of returning FAILED silently. Workflows relying on partial-failure
            # tolerance should use try/except or error handling at the caller level.
            logger.error("FILE mode tool '%s' failed: %s", context.agent_name, e)
            raise AgentActionsException(
                f"FILE mode tool '{context.agent_name}' failed: {e}",
                context={
                    "agent_name": context.agent_name,
                    "record_count": len(data),
                    "operation": "file_mode_tool",
                },
                cause=e,
            ) from e

    def _process_file_mode_hitl(
        self, data: List[Dict], original_data: List[Dict], context: ProcessingContext
    ) -> List:
        """
        Process HITL action in FILE granularity mode.

        Invokes HITL once with the full array and applies the single file-level
        decision payload to every record so downstream stages retain full dataset
        cardinality.

        Args:
            data: Observe-filtered records (shown to HITL UI)
            original_data: Unfiltered records (used for merge to preserve all fields)
            context: Processing context
        """
        try:
            raw_response, executed = run_dynamic_agent(
                agent_config=context.agent_config,
                agent_name=context.agent_name,
                context=data,
                formatted_prompt="",
                tools_path=context.agent_config.get("tools_path"),
            )

            # Unwrap single-item list from invocation service
            if isinstance(raw_response, list) and len(raw_response) == 1:
                decision_payload = raw_response[0]
            elif isinstance(raw_response, list):
                raise ValueError(
                    "FILE mode HITL must return a single decision payload, "
                    f"got {len(raw_response)} items"
                )
            else:
                decision_payload = raw_response

            if not isinstance(decision_payload, dict):
                raise ValueError(
                    "FILE mode HITL must return an object payload, "
                    f"got {type(decision_payload).__name__}"
                )

            record_reviews = (
                decision_payload.get("record_reviews")
                if isinstance(decision_payload.get("record_reviews"), list)
                else None
            )
            # Only propagate HITL decision metadata. Keep source business fields
            # (for example `status`) intact.
            decision_common = {
                key: value
                for key, value in decision_payload.items()
                if key in {"hitl_status", "user_comment", "timestamp"}
            }

            # Propagate one file-level decision across all input records so
            # downstream processing keeps record cardinality intact.
            # Use original_data for the merge to preserve all upstream fields.
            structured_data = []
            if original_data:
                reserved_fields = {
                    "source_guid",
                    "target_id",
                    "node_id",
                    "lineage",
                    "metadata",
                    "content",
                    "_unprocessed",
                    "_recovery",
                }
                for idx, item in enumerate(original_data):
                    if isinstance(item, dict):
                        if isinstance(item.get("content"), dict):
                            base_content = dict(item["content"])
                        else:
                            base_content = {
                                key: value
                                for key, value in item.items()
                                if key not in reserved_fields
                            }
                            raw_content = item.get("content")
                            if not base_content and raw_content is not None:
                                base_content = {"value": raw_content}
                    else:
                        base_content = {"value": item}

                    merged_content = dict(base_content)
                    merged_content.update(decision_common)
                    if record_reviews and idx < len(record_reviews):
                        review_payload = record_reviews[idx]
                        if isinstance(review_payload, dict):
                            normalized_review_payload = {
                                key: value
                                for key, value in review_payload.items()
                                if key in {"hitl_status", "user_comment"}
                            }
                            merged_content.update(normalized_review_payload)
                    structured_item = {"content": merged_content}
                    if isinstance(item, dict):
                        for field in (
                            "source_guid",
                            "target_id",
                            "_unprocessed",
                            "_recovery",
                            "metadata",
                        ):
                            if field in item:
                                structured_item[field] = item[field]
                    structured_data.append(structured_item)

            result = ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=structured_data,
                source_guid=None,
                raw_response=raw_response,
                executed=executed,
            )

            result = self.record_processor.enrichment_pipeline.enrich(result, context)
            return [result]
        except Exception as e:
            logger.error("Error in FILE mode HITL processing: %s", e)
            error_result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                data=[],
                source_guid=None,
                error=str(e),
                executed=False,
            )
            return [error_result]


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
    agent_config: Dict[str, Any],
    agent_name: str,
    idx: int,
    processor_factory: ProcessorFactory,
    agent_configs: Optional[Dict[str, Any]] = None,
    workflow_metadata: Optional[Dict[str, Any]] = None,
    storage_backend: Optional["StorageBackend"] = None,
    source_relative_path: Optional[str] = None,
) -> ProcessingPipeline:
    """
    Factory function for creating a ProcessingPipeline instance from individual parameters.

    Args:
        agent_config: Configuration for the agent
        agent_name: Name of the agent
        idx: Index of the agent
        processor_factory: Required factory for creating processors with DI
        agent_configs: Optional dictionary of all agent configurations
        workflow_metadata: Optional workflow metadata for {{ workflow.* }} templates
        storage_backend: Optional storage backend for database persistence
        source_relative_path: Optional explicit path for storage backend source lookups

    Returns:
        ProcessingPipeline instance
    """
    config = PipelineConfig(
        agent_config=agent_config,
        agent_name=agent_name,
        idx=idx,
        agent_configs=agent_configs,
        workflow_metadata=workflow_metadata,
        storage_backend=storage_backend,
        source_relative_path=source_relative_path,
    )
    return ProcessingPipeline(config, processor_factory)
