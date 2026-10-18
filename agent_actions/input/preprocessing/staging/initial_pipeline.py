"""Initial stage pipeline: file reading, data preparation, source saving, and processing."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import RunMode
from agent_actions.errors import AgentActionsError, ConfigValidationError
from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.output.response.config_fields import get_default
from agent_actions.output.saver import UnifiedSourceDataSaver
from agent_actions.output.writer import FileWriter, target_relative_path
from agent_actions.processing.disposition_gate import (
    note_answered_by_repair,
    positions_named_by_repair,
    stored_answers_stand,
)
from agent_actions.processing.result_collector import write_dispositions
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.utils.constants import CHUNK_CONFIG_KEY, MODEL_VENDOR_KEY
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.limits import record_indices_to_process

if TYPE_CHECKING:
    from agent_actions.config.types import ActionConfigDict

logger = logging.getLogger(__name__)

_DELIMITED_FILE_TYPES = frozenset({".csv", ".tsv"})
# Staged formats read as text and split into chunks, each staged as {"content": <chunk>}.
_TEXT_FILE_TYPES = frozenset({".txt", ".md", ".pdf", ".docx", ".html"})
_TEXT_CHUNK_FIELD = "content"


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
    # The start node's file types: the staged files the walk processes.
    file_type_filter: set[str] | None = None


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
    # The chunk above every narrowing, which carry-forward records so a stored row
    # of a record this run left out is not read as one that is gone. None means
    # unrecorded, and nothing is inferred from it.
    run_inputs: list[dict[str, Any]] | None = None
    file_type_filter: set[str] | None = None


def _save_source_items_helper(
    source_items: list[dict[str, Any]],
    file_path: str,
    base_directory: str,
    storage_backend: Any = None,
) -> None:
    """Save source items using UnifiedSourceDataSaver."""
    relative_path = Path(file_path).relative_to(base_directory)

    saver = UnifiedSourceDataSaver(enable_deduplication=True, storage_backend=storage_backend)

    saver.save_source_items(items=source_items, relative_path=str(relative_path.with_suffix("")))


def _first_stage_workflow_metadata(
    workflow_metadata: dict[str, Any] | None, file_path: str
) -> dict[str, Any]:
    """The run's `workflow` namespace as a first action's prompts and guards read it."""
    return {**(workflow_metadata or {}), "source_file": str(file_path)}


def _validate_staged_data(
    records: list[Any],
    file_type: str,
    agent_config: dict[str, Any],
    agent_name: str,
    mode: str,
    file_path: str,
    *,
    action_configs: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
) -> None:
    """Render a file's first prepared record against the prompt before any is stored or sent.

    The record is the one the run prepared, whatever the file type, so the render
    sees the fields a prompt will. Renders with the version and workflow metadata
    the records are prepared with, so a prompt that reads `version.*` or
    `workflow.*` is not refused here.
    """
    from agent_actions.prompt.service import (
        PromptPreparationService,
    )
    from agent_actions.workflow.pipeline import ProcessingPipeline

    if not records:
        return

    try:
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
    except (ValueError, KeyError, ConfigValidationError):
        return

    if not raw_prompt:
        return

    first_item = records[0]
    source_content = first_item

    agent_indices, dependency_configs, version_context = ProcessingPipeline._build_pipeline_context(
        cast("ActionConfigDict", agent_config), action_configs
    )
    try:
        PromptPreparationService.prepare_prompt_with_context(
            agent_config=agent_config,
            agent_name=agent_name,
            contents=source_content if isinstance(source_content, dict) else {},
            mode=RunMode.BATCH if mode == RunMode.BATCH else RunMode.ONLINE,
            agent_indices=agent_indices,
            dependency_configs=dependency_configs,
            source_content=source_content,
            version_context=version_context,
            workflow_metadata=_first_stage_workflow_metadata(workflow_metadata, file_path),
            current_item=first_item,
            file_path=file_path,
        )
    except AgentActionsError as e:
        if file_type not in _TEXT_FILE_TYPES or not _reads_a_source_field(e):
            raise
        raise ConfigValidationError(
            f"{str(e).rstrip('.')}. A staged {file_type} file is split into chunks, and "
            f"each record holds its chunk's text in one field, '{_TEXT_CHUNK_FIELD}': "
            f"read it as source.{_TEXT_CHUNK_FIELD}.",
            context=e.context,
            cause=e,
        ) from e


def _reads_a_source_field(error: AgentActionsError) -> bool:
    """Whether *error* is the check failing to find a field of the `source` namespace."""
    field_ref = str(error.context.get("field_ref", ""))
    missing = getattr(error, "missing_variables", None) or []
    return field_ref.startswith("source.") or any(
        str(name) == "source" or str(name).startswith("source.") for name in missing
    )


def _read_staged_file(ctx: InitialStageContext) -> tuple[Any, str]:
    """The staged file's content and type, a delimited file read as its rows.

    The template check renders the first of these rows, so it reads a column under the
    name the run's records carry it under; preparation reads the file with the same loader.
    """
    from agent_actions.input.loaders.file_reader import FileReader
    from agent_actions.input.loaders.tabular import TabularLoader

    file_type = Path(ctx.file_path).suffix.lower()
    if file_type in _DELIMITED_FILE_TYPES:
        loader = TabularLoader(ctx.agent_config, ctx.agent_name)
        return loader.process(content=None, file_path=ctx.file_path), file_type
    file_reader = FileReader(ctx.file_path)
    return file_reader.read(), file_reader.file_type


def process_initial_stage(ctx: InitialStageContext):
    """Process input files through the initial stage pipeline. Returns output file path."""
    content, file_type = _read_staged_file(ctx)
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
        validate_seed_selectors,
        validate_staging_field_names,
    )

    if file_type == ".json":
        # Before anything reads this as a record. Two validators below would
        # otherwise report a collision or a missing field for a document that is
        # not records at all, and the reader would fix those and still be here.
        _refuse_rows_that_are_not_records(content, ctx.file_path, ctx.agent_name)

    if file_type not in _DELIMITED_FILE_TYPES:
        # A delimited file reached this check as lists of cells, which it skips, so
        # a CSV column named like a namespace has always staged. Reading the file as
        # rows must not start refusing a workflow that runs.
        validate_staging_field_names(raw_content=content, file_path=ctx.file_path)

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

    # On the rows as prepared, whatever the file type, and before any is stored or sent.
    validate_seed_selectors(
        records=data_chunk,
        file_path=ctx.file_path,
        action_configs={**(ctx.action_configs or {}), ctx.agent_name: ctx.agent_config},
    )

    # After the row check, so a row no seed covers is refused with its location
    # rather than from this render of the first row.
    _validate_staged_data(
        records=data_chunk,
        file_type=file_type,
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=run_mode or RunMode.ONLINE,
        file_path=ctx.file_path,
        action_configs=ctx.action_configs,
        workflow_metadata=ctx.workflow_metadata,
    )

    # The records a repair leaves out are what let the disposition gate tell a
    # stored row of this action's own making from one minted upstream.
    offered_to_repair = data_chunk

    # A repair re-reads the staged file whole, so narrowing has to happen here,
    # above the source save: anything still in the chunk becomes a stored input
    # row, and a file edited since the run being repaired would otherwise enter
    # the store as new input on the strength of a repair that never named it.
    admitted = positions_named_by_repair(
        data_chunk,
        ctx.retried_records,
        storage_backend=ctx.storage_backend,
        action_name=ctx.agent_name,
    )
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
            run_inputs=offered_to_repair,
            file_type_filter=ctx.file_type_filter,
        )
        written = _process_batch_mode(batch_ctx)
    else:
        written = _process_online_mode_with_record_processor(
            data_chunk,
            ctx,
            ctx.file_path,
            ctx.base_directory,
            ctx.output_directory,
            offered_to_repair,
        )
    note_answered_by_repair(
        offered_to_repair,
        ctx.retried_records,
        storage_backend=ctx.storage_backend,
        action_name=ctx.agent_name,
    )
    return written


def _save_source_data(
    src_text: Any,
    data_chunk: Any,
    file_path: str,
    base_directory: str,
    storage_backend: Any = None,
) -> None:
    """UNIFIED source saving logic for both batch and online modes."""
    if src_text:
        source_items = src_text if isinstance(src_text, list) else [src_text]
    else:
        source_items = [row.copy() for row in data_chunk]

    if source_items:
        _save_source_items_helper(source_items, file_path, base_directory, storage_backend)


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


def _chunk_settings(agent_config: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """The four chunking settings, under the names `ChunkConfig` declares.

    One reader for both modes: the batch and online sites held the same four
    lines, and a key that drifted in one of them went unnoticed in the other.
    """
    chunk_config = agent_config.get(CHUNK_CONFIG_KEY) or {}

    def setting(key: str) -> Any:
        value = chunk_config.get(key)
        return get_default(key) if value is None else value

    return (
        setting("chunk_size"),
        setting("chunk_overlap"),
        setting("tokenizer_model"),
        setting("split_method"),
    )


def _text_chunk_payloads(content: str, agent_config: dict[str, Any]) -> list[dict[str, Any]]:
    """The payload of each record a staged text file becomes, before its envelope."""
    chunk_size, chunk_overlap, tokenizer_model, split_method = _chunk_settings(agent_config)
    chunks = Tokenizer.split_text_content(
        content,
        chunk_size,
        chunk_overlap,
        tokenizer_model=tokenizer_model,
        split_method=split_method,
    )
    return [{_TEXT_CHUNK_FIELD: chunk} for chunk in chunks]


def _prepare_text_chunks_batch(
    content: str,
    agent_config: dict[str, Any],
    batch_id: str,
    node_id: str,
    storage_backend: Any = None,
    relative_path: str = "",
) -> list[dict[str, Any]]:
    """Prepare text chunks for batch mode."""
    return _add_batch_metadata(
        _text_chunk_payloads(content, agent_config),
        batch_id,
        node_id,
        storage_backend,
        relative_path,
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

    if ctx.file_type in _TEXT_FILE_TYPES:
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

    if ctx.file_type in _TEXT_FILE_TYPES:
        data_chunk = src_text = _wrap_online_rows(
            _text_chunk_payloads(ctx.content, ctx.agent_config),
            ctx.storage_backend,
            ctx.relative_path,
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


def _staged_at_the_top(
    base_directory: str, file_type_filter: set[str] | None
) -> Callable[[str], bool]:
    """Whether a file the walk processes directly under *base_directory* stores as *legacy*.

    The walk's own skip rule decides, so a file it leaves out, or one it cannot read this
    run, owns no name.
    """
    from agent_actions.llm.batch.infrastructure.context import batch_output_name
    from agent_actions.workflow.runner_file_processing import should_skip_item

    root = Path(base_directory)

    def walked(entry: Path) -> bool:
        try:
            return not should_skip_item(entry, root, set(), file_type_filter)
        except OSError as e:
            logger.debug("Could not read %s while naming a batch file: %s", entry, e)
            return False

    def owns(legacy: str) -> bool:
        stored = batch_output_name(legacy)
        try:
            entries = list(root.iterdir())
        except OSError as e:
            logger.debug("Could not list %s for top-level inputs: %s", base_directory, e)
            return False
        return any(batch_output_name(entry.name) == stored and walked(entry) for entry in entries)

    return owns


def _process_batch_mode(ctx: BatchProcessingContext):
    """Process data in batch mode by submitting to batch service."""
    from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
    from agent_actions.llm.batch.infrastructure.context import (
        BatchContextManager,
        batch_file_identity,
    )
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.llm.batch.service import create_registry_manager_factory
    from agent_actions.llm.batch.services.submission import BatchSubmissionService
    from agent_actions.processing.disposition_gate import DispositionGate
    from agent_actions.workflow.pipeline import ProcessingPipeline

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
    relative_path = Path(ctx.file_path).relative_to(ctx.base_directory)
    output_file_path = Path(ctx.output_directory) / relative_path.with_suffix(".json")
    batch_name = batch_file_identity(
        relative_path.as_posix(),
        ctx.agent_name,
        ctx.storage_backend,
        base_owner=_staged_at_the_top(ctx.base_directory, ctx.file_type_filter),
        registry=registry_manager_factory,
    )
    submission_service.submit_batch_job(
        ctx.agent_config,
        batch_name,
        ctx.data_chunk,
        ctx.output_directory,
        source_data=ctx.data_chunk,
        workflow_metadata=_first_stage_workflow_metadata(ctx.workflow_metadata, ctx.file_path),
        run_inputs=ctx.run_inputs,
    )

    output_file_path.parent.mkdir(parents=True, exist_ok=True)
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
    from agent_actions.workflow.pipeline import ProcessingPipeline, _stored_rows

    agent_indices, dependency_configs, version_context = ProcessingPipeline._build_pipeline_context(
        cast("ActionConfigDict", ctx.agent_config),
        ctx.action_configs,
    )
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
        target_relative_path=target_relative_path(output_file_path, str(output_directory)),
        agent_indices=agent_indices,
        dependency_configs=dependency_configs,
        version_context=version_context,
        workflow_metadata=_first_stage_workflow_metadata(ctx.workflow_metadata, file_path),
        storage_backend=ctx.storage_backend,
        defer_kept_dispositions=True,
    )

    # What a repair leaves this file holding is compared with this, for the actions below.
    stored_before = (
        _stored_rows(ctx.storage_backend, ctx.agent_name, processing_context.target_relative_path)
        if ctx.retried_records and processing_context.target_relative_path
        else []
    )
    processed_items, stats = processor.process(
        data_chunk, processing_context, strategy, repair_inputs=offered_to_repair
    )

    failure = stats.terminal_failure(
        ctx.agent_name, data_chunk, processed_items, ctx.storage_backend
    )
    if failure is not None and (
        ctx.storage_backend is None
        or stored_answers_stand(
            ctx.storage_backend,
            ctx.agent_name,
            target_relative_path(output_file_path, str(output_directory)),
        )
    ):
        raise failure

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
    # Only now that the file holds the rows they vouch for.
    write_dispositions(ctx.storage_backend, processing_context.kept_dispositions, ctx.agent_name)
    # Kept past the write, they would read as answers given after it.
    ctx.storage_backend.clear_checkpoint_records(
        ctx.agent_name, processing_context.target_relative_path
    )
    if ctx.retried_records and processing_context.target_relative_path:
        from agent_actions.processing.repair_lineage import note_rewritten_by_repair
        from agent_actions.workflow.pipeline import _actions_below

        note_rewritten_by_repair(
            ctx.storage_backend,
            _actions_below(ctx.storage_backend, ctx.agent_name),
            stored_before,
            _stored_rows(
                ctx.storage_backend, ctx.agent_name, processing_context.target_relative_path
            ),
        )
    if failure is not None:
        raise failure

    return str(output_file_path)
