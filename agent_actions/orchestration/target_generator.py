"""Module for target data generation based on configuration."""

from dataclasses import dataclass
from pathlib import Path
import json
import logging
from typing import Optional, Dict, Any, List

from agent_actions.input_loading.file_reader import FileReader
from agent_actions.file_io.file_writer import FileWriter
from agent_actions.llm_invocation.realtime.output_handler import OutputHandler
from agent_actions.errors import AgentActionsException, ConfigurationError, DependencyError
from agent_actions.utilities.constants import MODEL_VENDOR_KEY
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.dependency_injection import ProcessorFactory
from agent_actions.utilities.safe_format import safe_format_error
from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.utilities.processor.processor_helpers import run_dynamic_agent

TOOL_VENDOR = "tool"
SOURCE_FOLDER = "source"
logger = logging.getLogger(__name__)


@dataclass
class GeneratorConfig:
    """Configuration for TargetGenerator."""

    agent_config: Dict[str, Any]
    agent_name: str
    idx: int
    agent_configs: Optional[Dict[str, Any]] = None


@dataclass
class BatchGenerationParams:
    """Parameters for batch generation."""

    generator_agent_config: Dict[str, Any]
    generator_agent_name: str
    batch_file_path: str
    batch_base_directory: str
    batch_output_directory: str
    batch_agent_configs: Optional[Dict[str, Any]] = None
    source_data: Optional[Any] = None


@dataclass
class FilePathsConfig:
    """File paths configuration."""

    file_path: str
    base_directory: str
    output_directory: str


@dataclass
class GenerateParams:
    """Parameters for target generation."""

    agent_config: Dict[str, Any]
    agent_name: str
    paths: FilePathsConfig
    idx: int
    processor_factory: Optional[ProcessorFactory]
    agent_configs: Optional[Dict[str, Any]] = None


class TargetGenerator:
    """
    Responsible for generating target data from input files based on
    configuration.
    """

    def __init__(self, config: GeneratorConfig, processor_factory: ProcessorFactory):
        """
        Initialize the target generator.

        Args:
            config: GeneratorConfig with agent configuration
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
        self.side_output_enabled = config.agent_config.get("side_output", False)
        # kind: "tool" = tool action, "llm" = LLM action
        self.is_tool_action = self.action_kind == "tool"
        if processor_factory is None:
            raise DependencyError(
                "TargetGenerator requires processor_factory",
                {
                    "component": "TargetGenerator",
                    "dependency": "processor_factory",
                    "agent_name": config.agent_name,
                },
            )

        # Initialize RecordProcessor directly
        self.record_processor = RecordProcessor(
            agent_config=config.agent_config,
            agent_name=config.agent_name,
        )
        self.output_handler = OutputHandler()

    @staticmethod
    def _handle_batch_generation(params: BatchGenerationParams) -> str:
        """Handle batch mode generation."""
        agent_indices = None
        if params.batch_agent_configs:
            agent_indices = {
                name: config.get("idx", 999)
                for name, config in params.batch_agent_configs.items()
                if config is not None and "idx" in config
            }

        batch_service = BatchService(
            agent_indices=agent_indices, dependency_configs=params.batch_agent_configs
        )
        file_reader = FileReader(params.batch_file_path)
        data = file_reader.read()
        file_name = Path(params.batch_file_path).name

        result = batch_service.submit_batch_job(
            params.generator_agent_config,
            file_name,
            data,
            params.batch_output_directory,
            source_data=params.source_data,
        )

        relative_path = Path(params.batch_file_path).relative_to(params.batch_base_directory)
        output_file_path = Path(params.batch_output_directory) / relative_path
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(result, dict) and result.get("type") == "passthrough":
            file_writer = FileWriter(str(output_file_path))
            file_writer.write_target(result["data"])
            marker = output_file_path.parent / ".passthrough_processed"
            marker.touch()
            return str(output_file_path)

        placeholder = {
            "batch_job_id": result,
            "status": "submitted",
            "agent": params.generator_agent_name,
        }
        with open(output_file_path, "w", encoding="utf-8") as f:
            json.dump(placeholder, f)
        return str(output_file_path)

    @staticmethod
    def generate(params: GenerateParams):
        """
        Static method for generating target data.

        Args:
            params: GenerateParams containing all generation parameters

        Returns:
            Path to the generated output file

        Raises:
            DependencyError: If processor_factory is not provided
        """
        if params.processor_factory is None:
            raise DependencyError(
                "TargetGenerator.generate requires processor_factory",
                {
                    "method": "TargetGenerator.generate",
                    "dependency": "processor_factory",
                    "agent_name": params.agent_name,
                },
            )
        # Tool actions run synchronously regardless of run_mode (they're Python functions, not LLM calls)
        is_tool_action = params.agent_config.get("model_vendor") == TOOL_VENDOR

        if params.agent_config.get("run_mode") == "batch" and not is_tool_action:
            return TargetGenerator._handle_batch_generation(
                BatchGenerationParams(
                    generator_agent_config=params.agent_config,
                    generator_agent_name=params.agent_name,
                    batch_file_path=params.paths.file_path,
                    batch_base_directory=params.paths.base_directory,
                    batch_output_directory=params.paths.output_directory,
                    batch_agent_configs=params.agent_configs,
                )
            )
        generator = create_target_generator_from_params(
            agent_config=params.agent_config,
            agent_name=params.agent_name,
            idx=params.idx,
            processor_factory=params.processor_factory,
            agent_configs=params.agent_configs,
        )
        return generator.process(
            params.paths.file_path, params.paths.base_directory, params.paths.output_directory
        )

    def process(self, file_path: str, base_directory: str, output_directory: str) -> str:
        """
        Process input file and generate output.

        Args:
            file_path: Path to the input JSON file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be
                saved

        Returns:
            Path to the generated output file
        """
        try:
            data = self._read_input_data(file_path)
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
        _data: Any,
        file_path: str,
        base_directory: str,
        output_directory: str,
        source_data: Optional[Any] = None,
    ):
        """Handle batch mode processing.

        Args:
            _data: Input data (unused, kept for interface consistency)
            file_path: Path to the input file
            base_directory: Base directory for processing
            output_directory: Directory for output files
        """
        result_path = self._handle_batch_generation(
            BatchGenerationParams(
                generator_agent_config=self.config.agent_config,
                generator_agent_name=self.config.agent_name,
                batch_file_path=file_path,
                batch_base_directory=base_directory,
                batch_output_directory=output_directory,
                batch_agent_configs=self.config.agent_configs,
                source_data=source_data,
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
            # Architectural Fix: Delegate source loading to SourceDataLoader
            # which encapsulates standard path knowledge and validation logic.
            # This is more robust than ad-hoc path traversal.
            from agent_actions.state_management.path_manager import PathManager
            from agent_actions.input_loading.extractors_source_data_loader import SourceDataLoader

            # Initialize PathManager. We allow it to auto-discover project root if needed.
            path_manager = PathManager()

            # Using SourceDataLoader ensures we follow the rigorous path logic
            # (e.g. handling 'agent_io/target/NODE/file' -> 'agent_io/source/file')
            source_loader = SourceDataLoader(self.config.agent_name, path_manager)

            # Load the source data for the given input file
            loaded_source = source_loader.load_source_data(file_path)

            if isinstance(loaded_source, list):
                source_data = loaded_source
            else:
                # Should be a list, but handle single dict if returned
                source_data = [loaded_source] if loaded_source else []

            logger.info(f"Loaded source data via SourceDataLoader for {file_path}")

        except Exception as e:
            logger.error(
                f"SourceDataLoader failed to resolve source for '{file_path}': {e}. "
                f"Agent: {self.config.agent_name}. "
                "Falling back to using input data as source context. "
                "This will likely cause 'undefined variable' errors if templates expect source fields."
            )
            # source_data remains 'data' (the fallback)

        # Batch mode check (tools run synchronously, not in batch)
        if self.config.agent_config.get("run_mode") == "batch" and not self.is_tool_action:
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
        )

        # Process via RecordProcessor
        # Check if FILE mode for tools - bypass record loop
        if self.granularity == "file" and self.is_tool_action:
            # For FILE mode, use the input data as source for parent lookup
            # (not source_data which points to original source folder)
            context.source_data = data
            results = self._process_file_mode_tool(data, context)
        else:
            # process_batch handles looping and calls process() which handles retries
            results = self.record_processor.process_batch(data, context)

        # ===== UNIFIED AGGREGATION: Check on_exhausted config =====
        from agent_actions.core.exhausted_record_builder import ExhaustedRecordBuilder

        exhausted_results = [r for r in results if r.status == ProcessingStatus.EXHAUSTED]

        if exhausted_results:
            retry_config = self.config.agent_config.get("retry", {})
            on_exhausted = retry_config.get("on_exhausted", "return_last")

            logger.warning(
                f"[{self.config.agent_name}] {len(exhausted_results)} records have exhausted retries "
                f"(on_exhausted={on_exhausted})"
            )

            if on_exhausted == "raise":
                # Fail action immediately (matches batch mode)
                exhausted_record = exhausted_results[0]
                attempts = (
                    exhausted_record.recovery_metadata.retry.attempts
                    if exhausted_record.recovery_metadata
                    and exhausted_record.recovery_metadata.retry
                    else "unknown"
                )
                raise AgentActionsException(
                    f"Retry exhausted for record {exhausted_record.source_guid} after "
                    f"{attempts} attempts (on_exhausted=raise)",
                    context={
                        "agent_name": self.config.agent_name,
                        "exhausted_records": len(exhausted_results),
                        "on_exhausted": "raise",
                    },
                )

        # Collect results into output
        output = []
        for result in results:
            if result.status == ProcessingStatus.SUCCESS:
                logger.debug(
                    f"[{self.config.agent_name}] Processing SUCCESS result: "
                    f"source_guid={result.source_guid}, records={len(result.data)}"
                )
                output.extend(result.data)
            elif result.status == ProcessingStatus.SKIPPED:
                logger.debug(
                    f"[{self.config.agent_name}] Processing SKIPPED result: "
                    f"source_guid={result.source_guid}, records={len(result.data)}"
                )
                output.extend(result.data)
            elif result.status == ProcessingStatus.EXHAUSTED:
                # Use shared utility for exhausted records
                logger.debug(
                    f"[{self.config.agent_name}] Processing EXHAUSTED result: "
                    f"source_guid={result.source_guid}, "
                    f"has_recovery_metadata={result.recovery_metadata is not None}, "
                    f"has_retry={result.recovery_metadata.retry is not None if result.recovery_metadata else False}"
                )
                if result.recovery_metadata and result.recovery_metadata.retry:
                    # Use input_record (has full lineage) for downstream, source_snapshot for first-stage
                    original_row = result.input_record or result.source_snapshot
                    exhausted_item = ExhaustedRecordBuilder.build_exhausted_item(
                        source_guid=result.source_guid,
                        original_row=original_row,
                        recovery_metadata=result.recovery_metadata,
                        agent_config=self.config.agent_config,
                        action_name=self.config.agent_name,
                    )
                    output.append(exhausted_item)
                    logger.info(
                        f"[{self.config.agent_name}] ✓ EXHAUSTED RECORD WRITTEN: "
                        f"source_guid={result.source_guid}, "
                        f"content={exhausted_item.get('content')}, "
                        f"retry_attempts={result.recovery_metadata.retry.attempts}, "
                        f"lineage_length={len(exhausted_item.get('lineage', []))}"
                    )
            elif result.status == ProcessingStatus.FAILED:
                logger.error(
                    f"[{self.config.agent_name}] Processing FAILED result: "
                    f"source_guid={result.source_guid}, error={result.error} "
                    f"(FAILED records are NOT written to output file)"
                )

        logger.info(f"[{self.config.agent_name}] ===== WRITING {len(output)} RECORDS TO FILE =====")
        for i, item in enumerate(output):
            is_exhausted = item.get("metadata", {}).get("retry_exhausted", False)
            status_label = "EXHAUSTED" if is_exhausted else "NORMAL"
            logger.debug(
                f"[{self.config.agent_name}]   Record {i + 1}/{len(output)}: {status_label} - "
                f"source_guid={item.get('source_guid')}, "
                f"content_keys={list(item.get('content', {}).keys()) if 'content' in item else 'N/A'}"
            )

        self.output_handler.save_main_output(output, file_path, base_directory, output_directory)
        logger.info(f"[{self.config.agent_name}] ===== FILE WRITE COMPLETE =====")

    def _process_file_mode_tool(self, data: List[Dict], context: ProcessingContext) -> List:
        """
        Process tool in FILE granularity mode.

        Invokes tool once with full array instead of looping per-record.
        Tool receives array WITH existing IDs/lineage.
        Tool returns array of outputs (N→M transformation allowed).
        Enrichment assigns new IDs/lineage to each output.

        Args:
            data: Full array of input records
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

            # Tool should return array
            if not isinstance(raw_response, list):
                raise ValueError(
                    f"FILE mode tool must return array, got {type(raw_response).__name__}"
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
            # Error handling
            logger.error(f"Error in FILE mode tool processing: {e}")
            error_result = ProcessingResult(
                status=ProcessingStatus.FAILED,
                data=[],
                source_guid=None,
                error=str(e),
                executed=False,
            )
            return [error_result]


def create_target_generator(
    config: GeneratorConfig, processor_factory: ProcessorFactory
) -> TargetGenerator:
    """
    Factory function for creating a TargetGenerator instance.

    Args:
        config: GeneratorConfig with agent configuration
        processor_factory: Required factory for creating processors with DI

    Returns:
        TargetGenerator instance
    """
    return TargetGenerator(config, processor_factory)


def create_target_generator_from_params(
    agent_config: Dict[str, Any],
    agent_name: str,
    idx: int,
    processor_factory: ProcessorFactory,
    agent_configs: Optional[Dict[str, Any]] = None,
) -> TargetGenerator:
    """
    Factory function for creating a TargetGenerator instance from individual parameters.

    Args:
        agent_config: Configuration for the agent
        agent_name: Name of the agent
        idx: Index of the agent
        processor_factory: Required factory for creating processors with DI
        agent_configs: Optional dictionary of all agent configurations

    Returns:
        TargetGenerator instance
    """
    config = GeneratorConfig(
        agent_config=agent_config, agent_name=agent_name, idx=idx, agent_configs=agent_configs
    )
    return TargetGenerator(config, processor_factory)
