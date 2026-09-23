"""Initial stage pipeline: file reading, data preparation, source saving, and processing."""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import RunMode
from agent_actions.errors import AgentActionsError, ConfigValidationError
from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.output.response.config_fields import get_default
from agent_actions.output.saver import UnifiedSourceDataSaver
from agent_actions.output.writer import FileWriter
from agent_actions.processing.disposition_gate import positions_named_by_repair
from agent_actions.processing.result_collector import write_node_level_disposition
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.storage.backend import DISPOSITION_PASSTHROUGH
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.constants import CHUNK_CONFIG_KEY, MODEL_VENDOR_KEY
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.limits import record_indices_to_process

if TYPE_CHECKING:
    from agent_actions.config.types import ActionConfigDict

logger = logging.getLogger(__name__)


@dataclass
class InitialStageContext:
    """Context for initial stage pipeline processing."""

    agent_config: dict[str, Any]
    agent_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int = 0
    storage_backend: Any = None  # Optional StorageBackend for database persistence
    action_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    # Records this run is repairing; a repair processes these and no others.
    retried_records: frozenset[str] = frozenset()


@dataclass
class DataPreparationContext:
    """Context for data preparation."""

    content: Any  # str for text formats; list[dict] for .xlsx/.csv at runtime
    file_type: str
    agent_config: dict[str, Any]
    file_path: str
    agent_name: str
    idx: int = 0
    storage_backend: Any = None  # Optional StorageBackend for cross-file identity checks
    relative_path: str = ""  # Same value source_data will store this file's rows under


@dataclass
class BatchProcessingContext:
    """Context for batch mode processing."""

    agent_config: dict[str, Any]
    agent_name: str
    data_chunk: list[dict[str, Any]]
    file_path: str
    base_directory: str
    output_directory: str
    idx: int = 0
    storage_backend: Any = None  # Optional StorageBackend for database persistence
    action_configs: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    # Records this run is repairing; carried from the initial stage so the batch
    # path's own disposition gate narrows the same way the online path's does.
    retried_records: frozenset[str] = frozenset()


def _derive_workflow_root(primary_path: str | None, fallback_path: str) -> Path:
    """Derive workflow root by finding 'agent_io' in path parts."""
    from agent_actions.utils.path_utils import derive_workflow_root

    target_path = Path(primary_path) if primary_path else Path(fallback_path)
    return derive_workflow_root(target_path)


def _save_source_items_helper(
    source_items: list[dict[str, Any]],
    file_path: str,
    base_directory: str,
    output_directory: str | None = None,
    storage_backend: Any = None,
) -> None:
    """Save source items using UnifiedSourceDataSaver."""
    relative_path = Path(file_path).relative_to(base_directory)
    workflow_root = _derive_workflow_root(output_directory, base_directory)

    saver = UnifiedSourceDataSaver(
        base_directory=str(workflow_root),
        enable_deduplication=True,
        storage_backend=storage_backend,
    )

    saver.save_source_items(items=source_items, relative_path=str(relative_path.with_suffix("")))


def _validate_staged_data(
    raw_content: Any,
    file_type: str,
    agent_config: dict[str, Any],
    agent_name: str,
    mode: str,
    file_path: str,
) -> None:
    """Validate input context against prompt template requirements before LLM execution."""
    from agent_actions.prompt.service import (
        PromptPreparationService,
    )

    if not raw_content:
        return

    try:
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
    except (ValueError, KeyError, ConfigValidationError):
        return

    if not raw_prompt:
        return

    if file_type == ".json":
        # A JSON document is rows of records by the time it reaches here; the
        # document rule runs before this and refuses anything else.
        first_item = raw_content[0]
        source_content = first_item
    else:
        source_content = {"page_content": str(raw_content)[:1000]}
        first_item = {"page_content": source_content["page_content"]}

    PromptPreparationService.prepare_prompt_with_context(
        agent_config=agent_config,
        agent_name=agent_name,
        contents=source_content if isinstance(source_content, dict) else {},
        mode=RunMode.BATCH if mode == RunMode.BATCH else RunMode.ONLINE,
        source_content=source_content,
        current_item=first_item,
        file_path=file_path,
    )


def process_initial_stage(ctx: InitialStageContext):
    """Process input files through the initial stage pipeline. Returns output file path."""
    from agent_actions.input.loaders.file_reader import FileReader

    file_reader = FileReader(ctx.file_path)
    content = file_reader.read()
    file_type = file_reader.file_type
    run_mode = ctx.agent_config.get("run_mode")

    logger.info(
        "Staging loader run_mode check: mode=%s, agent=%s, file=%s",
        run_mode,
        ctx.agent_name,
        Path(ctx.file_path).name,
        extra={
            "run_mode": run_mode,
            "agent_name": ctx.agent_name,
            "has_run_mode_in_config": "run_mode" in ctx.agent_config,
            "agent_config_keys": list(ctx.agent_config.keys())[:10],
        },
    )

    from agent_actions.input.preprocessing.staging.field_validation import (
        validate_staging_field_names,
    )

    if file_type == ".json":
        # Before anything reads this as a record. Two validators below would
        # otherwise report a collision or a missing field for a document that is
        # not records at all, and the reader would fix those and still be here.
        _refuse_rows_that_are_not_records(content, ctx.file_path, ctx.agent_name)

    validate_staging_field_names(raw_content=content, file_path=ctx.file_path)

    _validate_staged_data(
        raw_content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=run_mode or RunMode.ONLINE,
        file_path=ctx.file_path,
    )

    # Same formula _save_source_items_helper uses, so the identity claim below
    # is keyed by the relative_path this file's rows will actually be stored under.
    relative_path = str(Path(ctx.file_path).relative_to(ctx.base_directory).with_suffix(""))

    prep_ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        file_path=ctx.file_path,
        agent_name=ctx.agent_name,
        idx=ctx.idx,
        storage_backend=ctx.storage_backend,
        relative_path=relative_path,
    )

    if run_mode == RunMode.BATCH:
        data_chunk, src_text = _prepare_batch_data(prep_ctx)
    else:
        data_chunk, src_text = _prepare_online_data(prep_ctx)

    # The records a repair leaves out are what let the disposition gate tell a
    # stored row of this action's own making from one minted upstream.
    offered_to_repair = data_chunk

    # A repair re-reads the staged file whole, so narrowing has to happen here,
    # above the source save: anything still in the chunk becomes a stored input
    # row, and a file edited since the run being repaired would otherwise enter
    # the store as new input on the strength of a repair that never named it.
    admitted = positions_named_by_repair(data_chunk, ctx.retried_records)
    if admitted is not None:
        data_chunk = [data_chunk[i] for i in admitted]
        if isinstance(src_text, list):
            src_text = [src_text[i] for i in admitted if i < len(src_text)]

    # Slice BEFORE source save to prevent dedup poisoning
    kept = record_indices_to_process(
        data_chunk,
        ctx.agent_config,
        ctx.agent_name,
        retried=ctx.retried_records,
        storage_backend=ctx.storage_backend,
    )
    if kept is not None:
        data_chunk = [data_chunk[i] for i in kept]
        if isinstance(src_text, list):
            src_text = [src_text[i] for i in kept if i < len(src_text)]

    _save_source_data(
        src_text,
        data_chunk,
        ctx.file_path,
        ctx.base_directory,
        ctx.output_directory,
        storage_backend=ctx.storage_backend,
    )

    if run_mode == RunMode.BATCH:
        batch_ctx = BatchProcessingContext(
            agent_config=ctx.agent_config,
            agent_name=ctx.agent_name,
            data_chunk=data_chunk,
            file_path=ctx.file_path,
            base_directory=ctx.base_directory,
            output_directory=ctx.output_directory,
            idx=ctx.idx,
            storage_backend=ctx.storage_backend,
            action_configs=ctx.action_configs,
            workflow_metadata=ctx.workflow_metadata,
            retried_records=ctx.retried_records,
        )
        return _process_batch_mode(batch_ctx)

    return _process_online_mode_with_record_processor(
        data_chunk,
        ctx,
        ctx.file_path,
        ctx.base_directory,
        ctx.output_directory,
        offered_to_repair,
    )


def _save_source_data(
    src_text: Any,
    data_chunk: Any,
    file_path: str,
    base_directory: str,
    output_directory: str | None = None,
    storage_backend: Any = None,
) -> None:
    """UNIFIED source saving logic for both batch and online modes."""
    if src_text:
        source_items = src_text if isinstance(src_text, list) else [src_text]
    else:
        source_items = [row.copy() for row in data_chunk]

    if source_items:
        _save_source_items_helper(
            source_items, file_path, base_directory, output_directory, storage_backend
        )


def _envelope_row(payload: dict[str, Any]) -> dict[str, Any]:
    """The single authority for a first-stage record's envelope and identity.

    The payload lands under content.source; source_guid is derived over the RAW payload,
    never lifted from a payload field of the same name — doing so would collapse identity
    across rows that share that value. Batch decorates the result with ancestry; online uses
    it as-is.
    """
    return {
        "content": {"source": {**payload}},
        "source_guid": IDGenerator.derive_source_guid(payload),
    }


def _give_repeats_their_own_identity(
    rows: list[Any], storage_backend: Any = None, relative_path: str = ""
) -> list[Any]:
    """Re-stamp a record whose identity another row already took.

    Two rows in THIS call sharing a guid always collide — same file, back to
    back — and bump regardless of relative_path. A guid claimed by an EARLIER
    call collides only if that claim was under a DIFFERENT relative_path:
    independent actions can share one staging file, and re-reading it must
    keep one identity, not diverge per reader. The cross-call claim is
    in-memory, scoped to this run only, never persisted — a re-staged or
    renamed file doesn't collide with its own past self.
    """
    claimed_this_file: set[str] = set()

    def already_claimed(guid: str) -> bool:
        if guid in claimed_this_file:
            return True
        claimed_this_file.add(guid)
        if storage_backend is not None:
            return bool(storage_backend.claim_source_guid_for_run(guid, relative_path))
        return False

    repeats = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        base = row.get("source_guid")
        if not base:
            continue
        occurrence = 0
        candidate = base
        while already_claimed(candidate):
            occurrence += 1
            candidate = IDGenerator.derive_repeat_source_guid(base, occurrence)
        if occurrence:
            row["repeat_of_source_guid"] = base
            row["source_guid"] = candidate
            repeats += 1
    if repeats:
        logger.info("%d staged record(s) repeat content and were given their own identity", repeats)
    return rows


def _wrap_online_rows(
    payloads: list[Any], storage_backend: Any = None, relative_path: str = ""
) -> list[Any]:
    """Envelope and stamp online first-stage rows through the single authority."""
    wrapped: list[Any] = [_envelope_row(payload) for payload in payloads]
    return _give_repeats_their_own_identity(wrapped, storage_backend, relative_path)


def _prepare_text_chunks_batch(
    content: str,
    agent_config: dict[str, Any],
    batch_id: str,
    node_id: str,
    storage_backend: Any = None,
    relative_path: str = "",
) -> list[dict[str, Any]]:
    """Prepare text chunks for batch mode."""
    chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
    chunk_size = chunk_config.get("chunk_size", get_default("chunk_size"))
    chunk_overlap = chunk_config.get("overlap", get_default("chunk_overlap"))
    tokenizer_model = chunk_config.get("tokenizer_model", get_default("tokenizer_model"))
    split_method = chunk_config.get("split_method", get_default("split_method"))
    chunks = Tokenizer.split_text_content(
        content,
        chunk_size,
        chunk_overlap,
        tokenizer_model=tokenizer_model,
        split_method=split_method,
    )
    return _add_batch_metadata(
        [{"content": chunk} for chunk in chunks], batch_id, node_id, storage_backend, relative_path
    )


def _prepare_json_batch(
    content: Any,
    batch_id: str,
    node_id: str,
    file_path: str,
    agent_name: str,
    storage_backend: Any = None,
    relative_path: str = "",
) -> list[dict[str, Any]]:
    """Prepare pre-parsed JSON content for batch mode."""
    _refuse_rows_that_are_not_records(content, file_path, agent_name)
    return _add_batch_metadata(content, batch_id, node_id, storage_backend, relative_path)


def _refuse_rows_that_are_not_records(rows: Any, file_path: str, agent_name: str) -> None:
    """Stop an input whose rows cannot carry a payload, before identity is derived."""
    if not isinstance(rows, list):
        remedy = (
            "Wrap it in an array: [ ... ]."
            if isinstance(rows, dict)
            else "Give each record its own object, and hold them in an array."
        )
        raise AgentActionsError(
            f"A staged input must be rows; found {type(rows).__name__}. {remedy}",
            context={
                "file_path": file_path,
                "agent_name": agent_name,
                "content_type": type(rows).__name__,
            },
        )
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            continue
        raise AgentActionsError(
            f"A staged row must be an object; found {type(row).__name__}. "
            "Give each record its own object naming its fields.",
            context={
                "file_path": file_path,
                "agent_name": agent_name,
                "row_index": index,
                "row_type": type(row).__name__,
            },
        )


def _add_batch_metadata(
    rows: list[dict[str, Any]],
    batch_id: str,
    node_id: str,
    storage_backend: Any = None,
    relative_path: str = "",
) -> list[dict[str, Any]]:
    """Add batch metadata to rows of data."""
    result = []
    for idx, row in enumerate(rows):
        target_id = str(uuid.uuid4())
        record = {
            **_envelope_row(row),
            "batch_id": batch_id,
            "batch_uuid": f"{batch_id}_{idx}",
            "target_id": target_id,
            # Ancestry Chain: first-stage records are their own root
            "parent_target_id": None,
            "root_target_id": target_id,
            "node_id": node_id,
        }
        result.append(record)
    return _give_repeats_their_own_identity(result, storage_backend, relative_path)


def _prepare_batch_data(ctx: DataPreparationContext):
    """Prepare data for batch mode processing."""
    local_batch_id = f"batch_{uuid.uuid4().hex}"
    node_id = f"node_{ctx.idx}_{uuid.uuid4()}"
    from agent_actions.input.loaders.tabular import TabularLoader

    tabular_loader = TabularLoader(ctx.agent_config, ctx.agent_name)

    data_chunk: list[dict[str, Any]]
    src_text: list[dict[str, Any]]

    if ctx.file_type in [".txt", ".md", ".pdf", ".docx", ".html"]:
        data_chunk = _prepare_text_chunks_batch(
            ctx.content,
            ctx.agent_config,
            local_batch_id,
            node_id,
            ctx.storage_backend,
            ctx.relative_path,
        )
        src_text = []

    elif ctx.file_type == ".json":
        data_chunk = _prepare_json_batch(
            ctx.content,
            local_batch_id,
            node_id,
            ctx.file_path,
            ctx.agent_name,
            ctx.storage_backend,
            ctx.relative_path,
        )
        src_text = []

    elif ctx.file_type in (".csv", ".tsv"):
        # Tabular: let TabularLoader read the file itself (FileReader returns list[list], not str).
        # TabularLoader handles both comma- and tab-separated by routing on extension.
        rows = tabular_loader.process(content=None, file_path=ctx.file_path)
        data_chunk = _add_batch_metadata(
            rows, local_batch_id, node_id, ctx.storage_backend, ctx.relative_path
        )
        src_text = []

    elif ctx.file_type == ".xlsx":
        _refuse_rows_that_are_not_records(ctx.content, ctx.file_path, ctx.agent_name)
        data_chunk = _add_batch_metadata(
            ctx.content, local_batch_id, node_id, ctx.storage_backend, ctx.relative_path
        )
        src_text = []

    elif ctx.file_type == ".xml":
        raise AgentActionsError(
            "XML first-stage input is not supported; convert to CSV or JSON.",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
            },
        )

    else:
        supported = [
            ".txt",
            ".md",
            ".pdf",
            ".docx",
            ".html",
            ".json",
            ".csv",
            ".tsv",
            ".xlsx",
        ]
        raise AgentActionsError(
            "Unsupported file type in staging loader",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
                "supported_types": supported,
            },
        )

    for row in data_chunk:
        if "target_id" not in row or not row["target_id"]:
            row["target_id"] = str(uuid.uuid4())
        # First-stage records are their own root
        if "parent_target_id" not in row:
            row["parent_target_id"] = None
        if "root_target_id" not in row:
            row["root_target_id"] = row["target_id"]

    return data_chunk, src_text


def _prepare_online_data(ctx: DataPreparationContext):
    """Prepare data for online mode processing using direct loaders."""
    from agent_actions.input.loaders.json import JsonLoader
    from agent_actions.input.loaders.tabular import TabularLoader

    json_loader = JsonLoader(ctx.agent_config, ctx.agent_name)
    tabular_loader = TabularLoader(ctx.agent_config, ctx.agent_name)

    data_chunk: Any
    src_text: Any

    if ctx.file_type in [".txt", ".md", ".pdf", ".docx", ".html"]:
        chunk_config = ctx.agent_config.get(CHUNK_CONFIG_KEY, {})
        chunk_size = chunk_config.get("chunk_size", get_default("chunk_size"))
        chunk_overlap = chunk_config.get("overlap", get_default("chunk_overlap"))
        tokenizer_model = chunk_config.get("tokenizer_model", get_default("tokenizer_model"))
        split_method = chunk_config.get("split_method", get_default("split_method"))
        chunks = Tokenizer.split_text_content(
            ctx.content,
            chunk_size,
            chunk_overlap,
            tokenizer_model=tokenizer_model,
            split_method=split_method,
        )
        data_chunk = src_text = _wrap_online_rows(
            [{"content": text} for text in chunks], ctx.storage_backend, ctx.relative_path
        )

    elif ctx.file_type == ".json":
        raw_items: Any = json_loader.process(ctx.content, ctx.file_path)
        _refuse_rows_that_are_not_records(raw_items, ctx.file_path, ctx.agent_name)
        data_chunk = src_text = _wrap_online_rows(raw_items, ctx.storage_backend, ctx.relative_path)

    elif ctx.file_type in (".csv", ".tsv"):
        rows = tabular_loader.process(content=None, file_path=ctx.file_path)
        data_chunk = src_text = _wrap_online_rows(rows, ctx.storage_backend, ctx.relative_path)

    elif ctx.file_type == ".xlsx":
        _refuse_rows_that_are_not_records(ctx.content, ctx.file_path, ctx.agent_name)
        data_chunk = src_text = _wrap_online_rows(
            ctx.content, ctx.storage_backend, ctx.relative_path
        )

    elif ctx.file_type == ".xml":
        raise AgentActionsError(
            "XML first-stage input is not supported; convert to CSV or JSON.",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
            },
        )

    else:
        supported = [
            ".txt",
            ".md",
            ".pdf",
            ".docx",
            ".html",
            ".json",
            ".csv",
            ".tsv",
            ".xlsx",
        ]
        raise AgentActionsError(
            "Unsupported file type in staging loader",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
                "supported_types": supported,
            },
        )

    return data_chunk, src_text


def _get_batch_id_from_chunk(data_chunk: list[dict[str, Any]]) -> str:
    """Get batch ID from data chunk or generate new one."""
    if data_chunk:
        default_batch_id = f"batch_{uuid.uuid4().hex}"
        try:
            batch_id: str = data_chunk[0].get("batch_id", default_batch_id)
            return batch_id
        except (AttributeError, TypeError):
            return default_batch_id
    return f"batch_{uuid.uuid4().hex}"


def _write_passthrough_result(
    output_file_path, result_data, storage_backend=None, action_name=None, output_directory=None
):
    """Write passthrough result and record disposition."""
    if storage_backend is None or action_name is None:
        raise AgentActionsError(
            "Storage backend is required for passthrough writes.",
            context={
                "file_path": str(output_file_path),
                "action_name": action_name,
            },
        )
    file_writer = FileWriter(
        str(output_file_path),
        storage_backend=storage_backend,
        action_name=action_name,
        output_directory=output_directory,
    )
    file_writer.write_target(result_data)
    write_node_level_disposition(
        storage_backend,
        action_name,
        DISPOSITION_PASSTHROUGH,
        "All records tombstoned (initial stage)",
    )


def _write_batch_placeholder(output_file_path, local_batch_id, result, agent_name):
    """Write batch job placeholder file."""
    placeholder = {
        "batch_job_id": local_batch_id,
        "vendor_batch_id": result,
        "status": "submitted",
        "agent": agent_name,
    }
    atomic_json_write(output_file_path, placeholder)


def _process_batch_mode(ctx: BatchProcessingContext):
    """Process data in batch mode by submitting to batch service."""
    from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
    from agent_actions.llm.batch.infrastructure.context import BatchContextManager
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.llm.batch.service import create_registry_manager_factory
    from agent_actions.llm.batch.services.submission import BatchSubmissionService
    from agent_actions.processing.disposition_gate import DispositionGate
    from agent_actions.workflow.pipeline import ProcessingPipeline

    local_batch_id = _get_batch_id_from_chunk(ctx.data_chunk)

    agent_indices, dependency_configs, version_context = ProcessingPipeline._build_pipeline_context(
        cast("ActionConfigDict", ctx.agent_config),
        ctx.action_configs,
    )

    task_preparator = BatchTaskPreparator(
        action_indices=agent_indices,
        dependency_configs=dependency_configs,
        storage_backend=ctx.storage_backend,
        version_context=version_context,
    )
    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory(ctx.storage_backend)

    disposition_gate = DispositionGate(
        storage_backend=ctx.storage_backend, repairing=ctx.retried_records
    )
    submission_service = BatchSubmissionService(
        task_preparator=task_preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=ctx.storage_backend,
        disposition_gate=disposition_gate,
    )
    file_name = Path(ctx.file_path).name
    result = submission_service.submit_batch_job(
        ctx.agent_config,
        file_name,
        ctx.data_chunk,
        ctx.output_directory,
        source_data=ctx.data_chunk,
        workflow_metadata={**(ctx.workflow_metadata or {}), "source_file": ctx.file_path},
    )

    relative_path = Path(ctx.file_path).relative_to(ctx.base_directory)
    output_file_path = Path(ctx.output_directory) / relative_path.with_suffix(".json")
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    passthrough = result.passthrough
    if passthrough is not None and passthrough.get("type") == "tombstone":
        _write_passthrough_result(
            output_file_path,
            passthrough["data"],
            storage_backend=ctx.storage_backend,
            action_name=ctx.agent_name,
            output_directory=ctx.output_directory,
        )
    elif not result.is_passthrough:
        _write_batch_placeholder(output_file_path, local_batch_id, result.batch_id, ctx.agent_name)

    return str(output_file_path)


def _process_online_mode_with_record_processor(
    data_chunk,
    ctx: InitialStageContext,
    file_path,
    base_directory,
    output_directory,
    offered_to_repair,
):
    """Process data in online mode using UnifiedProcessor."""
    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix(".json")

    from agent_actions.processing.disposition_gate import DispositionGate

    strategy = OnlineLLMStrategy(agent_config=ctx.agent_config, agent_name=ctx.agent_name)
    disposition_gate = DispositionGate(
        storage_backend=ctx.storage_backend, repairing=ctx.retried_records
    )
    processor = UnifiedProcessor(disposition_gate=disposition_gate)

    processing_context = ProcessingContext(
        agent_config=cast("ActionConfigDict", ctx.agent_config),
        agent_name=ctx.agent_name,
        mode=RunMode.ONLINE,
        is_first_stage=True,
        file_path=str(file_path),
        output_directory=str(output_directory),
        workflow_metadata={**(ctx.workflow_metadata or {}), "source_file": str(file_path)},
        storage_backend=ctx.storage_backend,
    )

    processed_items, stats = processor.process(
        data_chunk, processing_context, strategy, repair_inputs=offered_to_repair
    )

    stats.raise_if_terminal_failure(
        ctx.agent_name, data_chunk, processed_items, ctx.storage_backend
    )

    # Tool actions that return empty output should be treated as failures
    # rather than silently succeeding (mirrors pipeline.py check).
    if data_chunk and not processed_items and stats.success > 0:
        kind = str(ctx.agent_config.get("kind") or "").lower()
        vendor = str(ctx.agent_config.get(MODEL_VENDOR_KEY) or "").lower()
        if kind == "tool" or vendor == "tool":
            raise RuntimeError(
                f"Tool action '{ctx.agent_name}' produced 0 output records "
                f"from {len(data_chunk)} input item(s) — tool returned empty result"
            )

    if ctx.storage_backend is None:
        raise AgentActionsError(
            "Storage backend is required for online initial-stage writes.",
            context={
                "file_path": str(output_file_path),
                "agent_name": ctx.agent_name,
            },
        )

    file_writer = FileWriter(
        str(output_file_path),
        storage_backend=ctx.storage_backend,
        action_name=ctx.agent_name,
        output_directory=str(output_directory),
    )
    file_writer.write_target(processed_items)

    return str(output_file_path)
