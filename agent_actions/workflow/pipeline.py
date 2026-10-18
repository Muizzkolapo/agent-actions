"""Module for orchestrating data processing pipelines through configured agents."""

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors import AgentActionsError, ConfigurationError
from agent_actions.input.loaders.file_reader import FileReader
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    batch_file_identity,
    batch_output_name,
    held_by_a_dependency,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.llm.realtime.output import OutputHandler
from agent_actions.output.writer import target_relative_path
from agent_actions.processing.disposition_gate import (
    note_answered_by_repair,
    note_replaced_above,
    positions_named_by_repair,
    replaced_above,
    stored_answers_stand,
)
from agent_actions.processing.repair_lineage import (
    drop_rows_built_on_rows_gone_above,
    note_rewritten_by_repair,
    written_above,
)
from agent_actions.processing.result_collector import write_dispositions
from agent_actions.processing.strategies import FileToolStrategy, HITLStrategy
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import ProcessingStrategy, UnifiedProcessor
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.storage.backend import (
    DISPOSITION_SKIPPED,
    DispositionRow,
)
from agent_actions.utils.constants import MODEL_VENDOR_KEY
from agent_actions.utils.limits import record_indices_to_process
from agent_actions.utils.safe_format import safe_format_error

if TYPE_CHECKING:
    from agent_actions.processing.disposition_gate import DispositionGate
    from agent_actions.storage.backend import StorageBackend

TOOL_VENDOR = "tool"
HITL_VENDOR = "hitl"
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
    # Records this run is repairing; a repair processes these and no others.
    retried_records: frozenset[str] = frozenset()


def scope_skip_disposition_rows(
    action_name: str, scope_skipped: list[dict[str, Any]]
) -> list[DispositionRow]:
    """The disposition rows for records the scope pass refused.

    `detail` is the seventh column and carries which field was missing, or how large the
    source pool was -- the reason alone says only that something was. A record with no
    source_guid has nothing to key a disposition on and is left out.
    """
    return [
        (
            action_name,
            str(skip["source_guid"]),
            DISPOSITION_SKIPPED,
            skip["reason"],
            None,
            None,
            skip.get("detail"),
        )
        for skip in scope_skipped
        if skip.get("source_guid")
    ]


def _stored_rows(
    storage_backend: Optional["StorageBackend"], action_name: str, relative_path: str
) -> list[dict[str, Any]]:
    """The rows *action_name* holds in *relative_path*, or none."""
    if storage_backend is None:
        return []
    try:
        return storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        return []


def _records_named_by(stored: list[dict[str, Any]], records: Any) -> frozenset[str]:
    """The records of *records* a FILE tool's *stored* rows of their file name.

    A row names the input it carries the identity of and those it names as parent or
    producer. One naming none, as a roll-up's does, says nothing of which records the
    limit admitted when it was written, so it adds none to what the limit admits.
    """
    inputs = {
        guid
        for record in (records if isinstance(records, list) else [])
        if isinstance(record, dict) and (guid := record.get("source_guid"))
    }
    return frozenset(_identities_named(stored) & inputs)


def _identities_named(rows: Any) -> set[str]:
    """Every identity *rows* carry or name as parent or producer."""
    named: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            named.update(
                guid
                for guid in (
                    row.get("source_guid"),
                    row.get("parent_source_guid"),
                    *(row.get("producer_source_guids") or ()),
                )
                if guid
            )
    return named


def _actions_below(storage_backend: "StorageBackend", action_name: str) -> list[str]:
    """Every action whose input derives from *action_name*'s output, per the stored graph."""
    raw = storage_backend.load_metadata("dependency_graph")
    try:
        graph = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        graph = None
    if not isinstance(graph, dict):
        logger.warning(
            "Action '%s': no dependency graph is stored, so the actions reading it keep "
            "what they hold for a file it replaced whole",
            action_name,
        )
        return []
    return [
        name
        for name, upstream in graph.items()
        if isinstance(upstream, list) and action_name in upstream
    ]


def _forget_answers_below(
    storage_backend: "StorageBackend",
    below: list[str],
    relative_path: str,
    replaced_rows: list[dict[str, Any]],
    inputs: Any,
) -> None:
    """Clear what each action in *below* holds a disposition for in *relative_path*.

    Each of their rows there was computed from the rows being replaced, so none may be
    carried by the gate. Cleared before the replacement is written: a run stopped in
    between finds them unanswered rather than answered over rows that are gone.
    """
    stale = _identities_named(replaced_rows) | _identities_named(inputs)
    for action in below:
        stale |= _identities_named(_stored_rows(storage_backend, action, relative_path))
    if not stale:
        return
    for action in below:
        storage_backend.clear_dispositions_batch(action, sorted(stale))


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
    disposition_gate: Optional["DispositionGate"] = field(default=None)
    # Only used when no gate is injected; a gate built without it never narrows.
    retried_records: frozenset[str] = frozenset()
    # This action's input above every narrowing, which carry-forward records so a
    # stored row of a record the run left out is not read as one that is gone.
    # None means unrecorded, and nothing is inferred from it.
    run_inputs: list[dict[str, Any]] | None = None


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
    action_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    storage_backend: Optional["StorageBackend"] = field(default=None)
    retried_records: frozenset[str] = frozenset()


class ProcessingPipeline:
    """Orchestrates data processing through configured agents in batch and online modes."""

    # Whether this run repairs records, kept when a file replaced above runs un-narrowed.
    _repairing: bool = False

    def __init__(self, config: PipelineConfig):
        """
        Initialize the processing pipeline.

        Args:
            config: PipelineConfig with agent configuration

        Raises:
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

        # A repair names, at every action below a split it re-runs, the rows the split
        # wrote: they are what this action is handed for the records it names.
        self._repairing = bool(config.retried_records)
        if self._repairing:
            above = written_above(config.storage_backend, config.action_name)
            if not above <= config.retried_records:
                config = replace(config, retried_records=config.retried_records | above)
        self.config = config
        self.model_vendor = str(config.action_config.get(MODEL_VENDOR_KEY) or "").lower()
        self.action_kind = str(config.action_config.get("kind") or "").lower()
        self.granularity = str(config.action_config.get("granularity") or "").lower()
        # Detect synchronous action types via kind OR model_vendor so that
        # batch-mode bypass works regardless of which field the user sets.
        self.is_tool_action = self.action_kind == "tool" or self.model_vendor == "tool"
        self.is_hitl_action = self.action_kind == "hitl" or self.model_vendor == "hitl"

        # HITL actions require FILE granularity
        if self.is_hitl_action and self.granularity != "file":
            from agent_actions.utils.constants import HITL_FILE_GRANULARITY_ERROR

            raise ConfigurationError(
                HITL_FILE_GRANULARITY_ERROR,
                context={
                    "action_name": config.action_name,
                    "granularity": self.granularity,
                    "kind": self.action_kind,
                },
            )

        # RECORD mode processor — created once, reused per file
        self._online_strategy = OnlineLLMStrategy(
            agent_config=cast(dict[str, Any], config.action_config),
            agent_name=config.action_name,
        )

        self._build_gate()

        # Initialize OutputHandler with optional storage backend
        self.output_handler = OutputHandler(
            storage_backend=config.storage_backend,
            action_name=config.action_name,
        )

    def _build_gate(self) -> None:
        """The disposition gate, and the processor it sits in, for what `config` repairs."""
        from agent_actions.processing.disposition_gate import DispositionGate

        self._disposition_gate = DispositionGate(
            storage_backend=self.config.storage_backend,
            repairing=self.config.retried_records,
        )
        self._unified_processor = UnifiedProcessor(
            disposition_gate=self._disposition_gate,
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
        context field is added to one path but missed in the other.

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
        disposition_gate = params.disposition_gate
        if disposition_gate is None and params.storage_backend is not None:
            from agent_actions.processing.disposition_gate import DispositionGate

            disposition_gate = DispositionGate(
                storage_backend=params.storage_backend,
                repairing=params.retried_records,
            )

        task_preparator = BatchTaskPreparator(
            action_indices=params.agent_indices,
            dependency_configs=params.dependency_configs,
            storage_backend=params.storage_backend,
            version_context=params.version_context,
        )
        client_resolver = BatchClientResolver(client_cache={}, default_client=None)
        context_manager = BatchContextManager()
        registry_manager_factory = create_registry_manager_factory(params.storage_backend)
        submission_service = BatchSubmissionService(
            task_preparator=task_preparator,
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
            storage_backend=params.storage_backend,
            disposition_gate=disposition_gate,
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
        # A file read is the whole input by construction — no narrowing sits above it —
        # so it is its own recording. Only a caller that narrowed before this has to say
        # what it narrowed from, and "it did not say" must not be read as "nothing".
        run_inputs = params.run_inputs if params.data is not None else data
        relative_path = Path(params.batch_file_path).relative_to(params.batch_base_directory)
        output_file_path = Path(params.batch_output_directory) / relative_path
        batch_name = batch_file_identity(
            relative_path.as_posix(),
            params.pipeline_action_name,
            params.storage_backend,
            base_owner=held_by_a_dependency(
                params.storage_backend,
                params.pipeline_action_config.get("dependencies") or [],
                params.dependency_configs,
            ),
            registry=registry_manager_factory,
        )
        if disposition_gate is not None and disposition_gate.repairing:
            drop_rows_built_on_rows_gone_above(
                params.storage_backend,
                params.pipeline_action_name,
                batch_output_name(batch_name),
                run_inputs,
                disposition_gate.repairing,
            )

        # A run with nothing to send writes its file there; one that sends is marked in
        # flight by the batch_jobs table, so no placeholder is needed on disk.
        submission_service.submit_batch_job(
            cast(dict[str, Any], params.pipeline_action_config),
            batch_name,
            data,
            params.batch_output_directory,
            source_data=params.source_data,
            workflow_metadata=params.workflow_metadata,
            run_inputs=run_inputs,
        )
        return str(output_file_path)

    @staticmethod
    def process_file(params: ProcessParams):
        """
        Static method for processing data through the pipeline.

        Args:
            params: ProcessParams containing all processing parameters

        Returns:
            Path to the generated output file
        """
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
                    retried_records=params.retried_records,
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
            action_configs=params.action_configs,
            workflow_metadata=params.workflow_metadata,
            storage_backend=params.storage_backend,
            retried_records=params.retried_records,
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
            self._answer_as_a_run_if_replaced_above(file_path, base_directory, output_directory)
            self._process_by_strategy(data, file_path, base_directory, output_directory)
            note_answered_by_repair(
                data,
                self.config.retried_records,
                storage_backend=self.config.storage_backend,
                action_name=self.config.action_name,
            )
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

    def _answer_as_a_run_if_replaced_above(
        self, file_path: str, base_directory: str, output_directory: str
    ) -> None:
        """Answer this file as a plain run would if an action above replaced it whole.

        Every row this action holds for it was computed from rows that are gone, and a
        row minted above is one no named record leads to. Its dispositions there were
        cleared when the file above was replaced, so the gate carries none of them.
        """
        if not self.config.retried_records:
            return
        relative_path = target_relative_path(
            OutputHandler.output_path(file_path, base_directory, output_directory),
            output_directory,
        )
        if not replaced_above(self.config.storage_backend, self.config.action_name, relative_path):
            return
        logger.info(
            "Action '%s': %s was replaced whole above, so every record of it is answered "
            "again, not only those the repair names",
            self.config.action_name,
            relative_path,
        )
        self.config = replace(self.config, retried_records=frozenset())
        self._build_gate()

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
        run_inputs: list[dict[str, Any]] | None = None,
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
            run_inputs: This action's input above every narrowing — see BatchPipelineParams
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
                disposition_gate=self._disposition_gate,
                run_inputs=run_inputs,
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
        configuration.
        """
        # Initialize source_data with the input data.
        # For cross-workflow records (source_relative_path is None), the input
        # data IS the source — there's no staging data in this workflow for them.
        source_data = data

        from agent_actions.utils.lineage import LineageBuilder

        parent_records = (
            [r for r in data if LineageBuilder.is_lineage_bearing(r)]
            if isinstance(data, list)
            else []
        )

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

            except (FileNotFoundError, ValueError) as e:
                # FileNotFoundError: no source data for this path (normal for
                # cross-workflow workflows that have no staging data).
                # ValueError: empty/invalid path from storage backend validation.
                # In both cases, input data is the correct source context.
                logger.debug(
                    "Source data not loaded for %s (using input data as source context): %s",
                    file_path,
                    e,
                )

        # Above every narrowing this function makes. A record the limit drops is still
        # one of this action's inputs: left out, its stored rows read as a repaired
        # record's and are deleted by a rewrite that never makes them again.
        offered_to_repair = data

        # A FILE tool's rows may each depend on every record of the file, so a file a
        # run reaches goes to it whole, and what the file held is replaced whole.
        whole_file = self.granularity == "file" and self.is_tool_action
        output_file_path = OutputHandler.output_path(file_path, base_directory, output_directory)
        run_mode = self.config.action_config.get("run_mode")
        in_batch = run_mode == RunMode.BATCH and not (self.is_tool_action or self.is_hitl_action)
        # The batch path drops them under the name its batch stores the file by.
        stored_before = (
            drop_rows_built_on_rows_gone_above(
                self.config.storage_backend,
                self.config.action_name,
                target_relative_path(output_file_path, output_directory),
                offered_to_repair,
                self.config.retried_records,
            )
            if self._repairing and not in_batch
            else []
        )
        stored_here = (
            _stored_rows(
                self.config.storage_backend,
                self.config.action_name,
                target_relative_path(output_file_path, output_directory),
            )
            if whole_file
            else []
        )

        # ── per-action record_limit ──────────────────────────────────────
        # A limit keeps what a repair rewrites the rows of, and a FILE tool's rows can
        # name their inputs as parent or producer. A roll-up names none, so the limit
        # admits for it what a run of the same config admits, and the named records.
        held = self.config.retried_records
        if whole_file and held:
            held = held | _records_named_by(stored_here, data)
        kept = record_indices_to_process(
            data,
            self.config.action_config,
            self.config.action_name,
            retried=held,
            storage_backend=self.config.storage_backend,
        )
        if kept is not None:
            data = [data[i] for i in kept]

        # Above the context scope, which writes `skipped` for every record it drops:
        # a repair must not disposition a record it never named. A FILE tool's file
        # a repair reaches is the exception: every record of it is decided again.
        repair_kept = positions_named_by_repair(
            data,
            self.config.retried_records,
            storage_backend=self.config.storage_backend,
            action_name=self.config.action_name,
        )
        if repair_kept is not None and not (whole_file and repair_kept):
            data = [data[i] for i in repair_kept]

        # Build shared pipeline context BEFORE the batch/online fork.
        # See _build_pipeline_context() docstring for the architecture invariant.
        agent_indices, dependency_configs, version_context = self._build_pipeline_context(
            self.config.action_config,
            self.config.action_configs,
        )

        # ── batch/online fork ──────────────────────────────────────────────
        # Everything above this point is shared. Below here, paths diverge.
        if in_batch:
            self._handle_batch_mode(
                data,
                file_path,
                base_directory,
                output_directory,
                source_data,
                agent_indices,
                dependency_configs,
                version_context,
                run_inputs=offered_to_repair,
            )
            return

        context = ProcessingContext(
            agent_config=self.config.action_config,
            agent_name=self.config.action_name,
            mode=RunMode.ONLINE,
            is_first_stage=False,
            source_data=source_data,  # Pass the loaded source data
            parent_records=parent_records,  # Previous-stage output (lineage source)
            file_path=file_path,
            output_directory=output_directory,
            target_relative_path=target_relative_path(output_file_path, output_directory),
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            version_context=version_context,
            workflow_metadata=self.config.workflow_metadata,
            storage_backend=self.config.storage_backend,
            defer_kept_dispositions=True,
        )

        # Select processing strategy based on granularity and action kind.
        strategy = self._select_strategy()

        replaced: set[str] = set()
        if self.granularity == "file" and (self.is_tool_action or self.is_hitl_action):
            # raw_records is what the guard is evaluated against, paired to the scoped
            # list by position; UnifiedProcessor then sets context.source_data from it.
            filtered, scope_skipped = apply_context_scope_for_records(
                records=data,
                context_scope=cast(dict[str, Any], self.config.action_config).get(
                    "context_scope", {}
                ),
                action_name=self.config.action_name,
                source_data=source_data,
            )
            if scope_skipped and self.config.storage_backend:
                batch = scope_skip_disposition_rows(self.config.action_name, scope_skipped)
                if batch:
                    try:
                        self.config.storage_backend.set_dispositions_batch(batch)
                    except Exception:
                        logger.exception(
                            "Failed to batch-write %d scope-skip dispositions for %s",
                            len(batch),
                            self.config.action_name,
                        )
            # Matched to `filtered`, not to `data`: the guard pairs the two lists by
            # position, so the pre-drop list failed the whole file over one drop.
            dropped = {skip["position"] for skip in scope_skipped}
            pre_observe = [record for at, record in enumerate(data) if at not in dropped]
            replaced = {guid for row in stored_here if (guid := row.get("source_guid"))}
            output, stats = self._unified_processor.process(
                filtered,
                context,
                strategy,
                raw_records=pre_observe,
                repair_inputs=offered_to_repair,
                whole_file=whole_file,
            )
            # A row the tool did not write again is gone with the file it was replaced
            # in, and so is what vouched for it. Not an input's own disposition, which
            # this run decides wherever it reaches the input.
            replaced -= {row.get("source_guid") for row in output}
            replaced -= {
                record.get("source_guid")
                for record in (offered_to_repair if isinstance(offered_to_repair, list) else [])
                if isinstance(record, dict)
            }
        else:
            # RECORD mode — UnifiedProcessor handles guard + invoke + enrich + collect
            output, stats = self._unified_processor.process(
                data, context, strategy, repair_inputs=offered_to_repair
            )

        failure = stats.terminal_failure(
            self.config.action_name, data, output, self.config.storage_backend
        )
        if failure is not None and (
            self.config.storage_backend is None
            or stored_answers_stand(
                self.config.storage_backend,
                self.config.action_name,
                target_relative_path(output_file_path, output_directory),
            )
        ):
            raise failure

        # What the actions below hold for a file replaced whole was computed from the rows
        # it held, so each of them answers it again, whatever records a repair names.
        below: list[str] = []
        if (
            context.replaces_file_whole
            and context.target_relative_path
            and self.config.storage_backend is not None
        ):
            below = _actions_below(self.config.storage_backend, self.config.action_name)
            if below:
                _forget_answers_below(
                    self.config.storage_backend,
                    below,
                    context.target_relative_path,
                    stored_here,
                    offered_to_repair,
                )

        self.output_handler.save_main_output(output, file_path, base_directory, output_directory)
        # Only now that the file holds the rows they vouch for.
        write_dispositions(
            self.config.storage_backend, context.kept_dispositions, self.config.action_name
        )
        if replaced and self.config.storage_backend:
            try:
                self.config.storage_backend.clear_dispositions_batch(
                    self.config.action_name, sorted(replaced)
                )
            except Exception:
                logger.warning(
                    "Action '%s': could not clear the dispositions of %d row(s) %s no "
                    "longer holds; they vouch for rows that are gone",
                    self.config.action_name,
                    len(replaced),
                    context.target_relative_path,
                    exc_info=True,
                )

        note_replaced_above(self.config.storage_backend, below, context.target_relative_path)
        if (
            self._repairing
            and self.config.storage_backend is not None
            and context.target_relative_path
        ):
            note_rewritten_by_repair(
                self.config.storage_backend,
                below or _actions_below(self.config.storage_backend, self.config.action_name),
                stored_before,
                _stored_rows(
                    self.config.storage_backend,
                    self.config.action_name,
                    context.target_relative_path,
                ),
            )

        # This file's only: another file's checkpoint rows are answers not stored yet.
        if self.config.storage_backend:
            self.config.storage_backend.clear_checkpoint_records(
                self.config.action_name, context.target_relative_path
            )
        if failure is not None:
            raise failure

    def _select_strategy(self) -> ProcessingStrategy:
        """Select the processing strategy based on granularity and action kind."""
        if self.granularity == "file":
            if self.is_tool_action:
                return FileToolStrategy()
            if self.is_hitl_action:
                return HITLStrategy()
        return self._online_strategy


def create_processing_pipeline_from_params(
    action_config: ActionConfigDict,
    action_name: str,
    idx: int,
    action_configs: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    storage_backend: Optional["StorageBackend"] = None,
    source_relative_path: str | None = None,
    retried_records: frozenset[str] = frozenset(),
) -> ProcessingPipeline:
    """
    Factory function for creating a ProcessingPipeline instance from individual parameters.

    Args:
        action_config: Configuration for the action
        action_name: Name of the action
        idx: Index of the action
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
        retried_records=retried_records,
    )
    return ProcessingPipeline(config)
