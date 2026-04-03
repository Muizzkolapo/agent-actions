"""Initial stage pipeline: file reading, data preparation, source saving, and processing."""

import json
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
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingContext
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.storage.backend import (
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.utils.constants import CHUNK_CONFIG_KEY

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


@dataclass
class DataPreparationContext:
    """Context for data preparation."""

    content: Any  # str for text formats; list[dict] for .xlsx/.csv at runtime
    file_type: str
    agent_config: dict[str, Any]
    file_path: str
    agent_name: str
    idx: int = 0


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

    if file_type == ".json" and isinstance(raw_content, list) and raw_content:
        first_item = raw_content[0]
        source_content = first_item
    elif file_type == ".json" and isinstance(raw_content, dict):
        source_content = raw_content
        first_item = raw_content
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

    _validate_staged_data(
        raw_content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=run_mode or RunMode.ONLINE,
        file_path=ctx.file_path,
    )

    prep_ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        file_path=ctx.file_path,
        agent_name=ctx.agent_name,
        idx=ctx.idx,
    )

    if run_mode == RunMode.BATCH:
        data_chunk, src_text = _prepare_batch_data(prep_ctx)
    else:
        data_chunk, src_text = _prepare_online_data(prep_ctx)

    # Slice BEFORE source save to prevent dedup poisoning
    record_limit = ctx.agent_config.get("record_limit")
    if record_limit is not None and isinstance(data_chunk, list) and len(data_chunk) > 0:
        total = len(data_chunk)
        data_chunk = data_chunk[:record_limit]
        if isinstance(src_text, list):
            src_text = src_text[:record_limit]
        logger.info(
            "record_limit=%d: processing %d of %d records for %s",
            record_limit,
            len(data_chunk),
            total,
            ctx.agent_name,
        )

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
        )
        return _process_batch_mode(batch_ctx)

    return _process_online_mode_with_record_processor(
        data_chunk, ctx, ctx.file_path, ctx.base_directory, ctx.output_directory
    )


def _should_save_source_items(
    new_items: list[dict],
    file_path: str,
    base_directory: str,
    output_directory: str | None = None,
) -> bool:
    """Return True if new_items are richer (more fields) than existing source data."""
    if not new_items:
        return False

    relative_path = Path(file_path).relative_to(base_directory)
    workflow_root = _derive_workflow_root(output_directory, base_directory)

    source_file = workflow_root / "agent_io" / "source" / f"{relative_path.with_suffix('')}.json"

    if not source_file.exists():
        logger.debug("Source file doesn't exist, proceeding with save: %s", source_file)
        return True

    try:
        with open(source_file, encoding="utf-8") as f:
            existing_items = json.load(f)
            if not isinstance(existing_items, list):
                logger.debug(
                    "Existing source file is not a list (type=%s), proceeding with save",
                    type(existing_items).__name__,
                )
                return True
            if not existing_items:
                logger.debug("Existing source file is empty, proceeding with save")
                return True
            if not isinstance(existing_items[0], dict):
                logger.debug(
                    "Existing source items are not dicts (type=%s), proceeding with save",
                    type(existing_items[0]).__name__,
                )
                return True

            existing_fields = set(existing_items[0].keys())
            new_fields = set(new_items[0].keys()) if new_items else set()

            if len(new_fields) > len(existing_fields):
                logger.info(
                    "New source data is richer (%d fields) than existing (%d fields), proceeding with save",
                    len(new_fields),
                    len(existing_fields),
                )
                return True
            else:
                logger.debug(
                    "Existing source data is richer (%d fields) than new data (%d fields), skipping save",
                    len(existing_fields),
                    len(new_fields),
                )
                return False

    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Error reading existing source file %s: %s, proceeding with save", source_file, e
        )
        return True


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
        source_items = [row.copy() for row in data_chunk if row.get("source_guid")]

    if source_items:
        if not _should_save_source_items(source_items, file_path, base_directory, output_directory):
            logger.debug(
                "Skipping source save - existing source data is richer than new data for %s",
                file_path,
            )
            return

        _save_source_items_helper(
            source_items, file_path, base_directory, output_directory, storage_backend
        )


def _prepare_text_chunks_batch(
    content: str, agent_config: dict[str, Any], batch_id: str, node_id: str
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
    result = []
    for idx, chunk in enumerate(chunks):
        target_id = str(uuid.uuid4())
        result.append(
            {
                "content": chunk,
                "batch_id": batch_id,
                "batch_uuid": f"{batch_id}_{idx}",
                "source_guid": str(uuid.uuid5(uuid.NAMESPACE_OID, str(chunk))),
                "target_id": target_id,
                # Ancestry Chain: first-stage records are their own root
                "parent_target_id": None,
                "root_target_id": target_id,
                "node_id": node_id,
            }
        )
    return result


def _prepare_json_batch(
    content: str, batch_id: str, node_id: str, file_path: str, agent_name: str
) -> list[dict[str, Any]]:
    """Prepare JSON content for batch mode."""
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to parse JSON from %s: %s",
            file_path,
            str(e),
            extra={
                "file_path": file_path,
                "agent_name": agent_name,
                "operation": "json_parse",
                "content_length": len(content) if content else 0,
            },
        )
        parsed = content

    if isinstance(parsed, list):
        result = []
        for idx, row in enumerate(parsed):
            target_id = str(uuid.uuid4())
            result.append(
                {
                    **row,
                    "batch_id": batch_id,
                    "batch_uuid": f"{batch_id}_{idx}",
                    "source_guid": str(
                        uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))
                    ),
                    "target_id": target_id,
                    # Ancestry Chain: first-stage records are their own root
                    "parent_target_id": None,
                    "root_target_id": target_id,
                    "node_id": node_id,
                }
            )
        return result
    return [{"content": parsed, "batch_id": batch_id, "batch_uuid": f"{batch_id}_0"}]


def _add_batch_metadata(
    rows: list[dict[str, Any]], batch_id: str, node_id: str
) -> list[dict[str, Any]]:
    """Add batch metadata to rows of data."""
    result = []
    for idx, row in enumerate(rows):
        target_id = str(uuid.uuid4())
        result.append(
            {
                **row,
                "batch_id": batch_id,
                "batch_uuid": f"{batch_id}_{idx}",
                "source_guid": str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))),
                "target_id": target_id,
                # Ancestry Chain: first-stage records are their own root
                "parent_target_id": None,
                "root_target_id": target_id,
                "node_id": node_id,
            }
        )
    return result


def _prepare_batch_data(ctx: DataPreparationContext):
    """Prepare data for batch mode processing."""
    local_batch_id = f"batch_{uuid.uuid4().hex}"
    node_id = f"node_{ctx.idx}_{uuid.uuid4()}"
    from agent_actions.input.loaders.tabular import TabularLoader
    from agent_actions.input.loaders.xml import XmlLoader

    tabular_loader = TabularLoader(ctx.agent_config, ctx.agent_name)
    xml_loader = XmlLoader(ctx.agent_config, ctx.agent_name)

    data_chunk: list[dict[str, Any]]
    src_text: list[dict[str, Any]]

    if ctx.file_type in [".txt", ".md", ".pdf", ".docx", ".html"]:
        data_chunk = _prepare_text_chunks_batch(
            ctx.content, ctx.agent_config, local_batch_id, node_id
        )
        src_text = []

    elif ctx.file_type == ".json":
        data_chunk = _prepare_json_batch(
            ctx.content, local_batch_id, node_id, ctx.file_path, ctx.agent_name
        )
        src_text = []

    elif ctx.file_type == ".csv":
        # CSV: let TabularLoader read the file itself (FileReader returns list[list], not str)
        rows = tabular_loader.process(content=None, file_path=ctx.file_path)
        data_chunk = _add_batch_metadata(rows, local_batch_id, node_id)
        src_text = []

    elif ctx.file_type == ".xlsx":
        if not isinstance(ctx.content, list):
            logger.debug("XLSX content is %s, expected list[dict]; wrapping", type(ctx.content))
        rows = ctx.content if isinstance(ctx.content, list) else [ctx.content]
        data_chunk = _add_batch_metadata(rows, local_batch_id, node_id)
        src_text = []

    elif ctx.file_type == ".xml":
        # XML: let XmlLoader read the file itself (FileReader returns (tree, root) tuple, not str)
        xml_result: Any = xml_loader.process(content=None, file_path=ctx.file_path)
        if isinstance(xml_result, list):
            data_chunk = _add_batch_metadata(xml_result, local_batch_id, node_id)
        else:
            data_chunk = [
                {
                    "content": xml_result,
                    "batch_id": local_batch_id,
                    "batch_uuid": f"{local_batch_id}_0",
                }
            ]
        src_text = []

    else:
        supported = [".txt", ".md", ".pdf", ".docx", ".html", ".json", ".csv", ".xlsx", ".xml"]
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
    from agent_actions.input.loaders.xml import XmlLoader

    json_loader = JsonLoader(ctx.agent_config, ctx.agent_name)
    tabular_loader = TabularLoader(ctx.agent_config, ctx.agent_name)
    xml_loader = XmlLoader(ctx.agent_config, ctx.agent_name)

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
        data_chunk = chunks

        # GUIDs must match what RecordProcessor will generate
        from agent_actions.utils.id_generation import IDGenerator

        src_text = []
        for text in data_chunk:
            guid = IDGenerator.generate_deterministic_source_guid(text)
            src_text.append({"source_guid": guid, "content": text})

    elif ctx.file_type == ".json":
        data_chunk = json_loader.process(ctx.content, ctx.file_path)

        if not isinstance(data_chunk, list):
            data_chunk = [data_chunk]

        # Do NOT mutate data_chunk: RecordProcessor hashes raw items for source_guid
        from agent_actions.utils.id_generation import IDGenerator

        src_text = []
        for item in data_chunk:
            if isinstance(item, dict):
                source_item = item.copy()
                if "source_guid" not in source_item:
                    source_item["source_guid"] = IDGenerator.generate_deterministic_source_guid(
                        item
                    )
                src_text.append(source_item)
            else:
                src_text.append(item)

    elif ctx.file_type == ".csv":
        data_chunk = tabular_loader.process(content=None, file_path=ctx.file_path)
        src_text = data_chunk

    elif ctx.file_type == ".xlsx":
        data_chunk = ctx.content if isinstance(ctx.content, list) else [ctx.content]
        src_text = data_chunk

    elif ctx.file_type == ".xml":
        data_chunk = xml_loader.process(content=None, file_path=ctx.file_path)
        src_text = data_chunk

    else:
        supported = [".txt", ".md", ".pdf", ".docx", ".html", ".json", ".csv", ".xlsx", ".xml"]
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
    storage_backend.set_disposition(
        action_name,
        NODE_LEVEL_RECORD_ID,
        DISPOSITION_PASSTHROUGH,
        reason="All records tombstoned (initial stage)",
    )


def _write_batch_placeholder(output_file_path, local_batch_id, result, agent_name):
    """Write batch job placeholder file."""
    placeholder = {
        "batch_job_id": local_batch_id,
        "vendor_batch_id": result,
        "status": "submitted",
        "agent": agent_name,
    }
    with open(output_file_path, "w", encoding="utf-8") as f:
        json.dump(placeholder, f)


def _process_batch_mode(ctx: BatchProcessingContext):
    """Process data in batch mode by submitting to batch service."""
    from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
    from agent_actions.llm.batch.infrastructure.context import BatchContextManager
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.llm.batch.service import create_registry_manager_factory
    from agent_actions.llm.batch.services.submission import BatchSubmissionService

    local_batch_id = _get_batch_id_from_chunk(ctx.data_chunk)
    task_preparator = BatchTaskPreparator()
    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory()
    submission_service = BatchSubmissionService(
        task_preparator=task_preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
    )
    file_name = Path(ctx.file_path).name
    result = submission_service.submit_batch_job(
        ctx.agent_config, file_name, ctx.data_chunk, ctx.output_directory
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
    data_chunk, ctx: InitialStageContext, file_path, base_directory, output_directory
):
    """Process data in online mode using RecordProcessor."""
    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix(".json")

    processor = RecordProcessor(ctx.agent_config, ctx.agent_name)

    processing_context = ProcessingContext(
        agent_config=cast("ActionConfigDict", ctx.agent_config),
        agent_name=ctx.agent_name,
        mode=RunMode.ONLINE,
        is_first_stage=True,
        file_path=str(file_path),
        output_directory=str(output_directory),
        workflow_metadata={"source_file": str(file_path)},
        storage_backend=ctx.storage_backend,
    )

    results = processor.process_batch(data_chunk, processing_context)

    processed_items, stats = ResultCollector.collect_results(
        results,
        ctx.agent_config,
        ctx.agent_name,
        is_first_stage=True,
        storage_backend=ctx.storage_backend,
    )

    # If input had records but no actual work was done (all guard-skipped/
    # filtered/unprocessed), signal this to the executor via a node-level
    # disposition so the tally shows SKIP instead of OK.
    if (
        data_chunk
        and stats.success == 0
        and stats.failed == 0
        and stats.exhausted == 0
        and stats.deferred == 0
    ):
        if ctx.storage_backend is not None:
            try:
                ctx.storage_backend.set_disposition(
                    ctx.agent_name,
                    NODE_LEVEL_RECORD_ID,
                    DISPOSITION_SKIPPED,
                    reason="All records guard-skipped or filtered",
                )
            except Exception as e:
                logger.warning(
                    "Failed to write guard-skip disposition for %s: %s",
                    ctx.agent_name,
                    e,
                )

    # If input had records but none succeeded AND there are actual failures
    # (failed or exhausted — not just guard-filtered/skipped), raise so the
    # executor marks the action as failed and the circuit breaker skips
    # downstream dependents.  We check stats.success rather than
    # `not processed_items` because EXHAUSTED records produce tombstone data
    # that inflates the output list despite representing zero real successes.
    if data_chunk and stats.success == 0 and (stats.failed + stats.exhausted) > 0:
        raise RuntimeError(
            f"Action '{ctx.agent_name}' produced 0 successful records — "
            f"all {len(data_chunk)} input item(s) failed "
            f"({stats.failed} failed, {stats.exhausted} exhausted)"
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
