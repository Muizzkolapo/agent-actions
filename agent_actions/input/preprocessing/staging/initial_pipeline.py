"""
Module for initial stage pipeline processing.

Handles the first stage of data processing workflows including:
- Reading and validating input files
- Preparing data (chunking, parsing, transforming)
- Saving source data
- Processing through RecordProcessor (batch or online mode)
- Collecting and writing results
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Any
import json
import logging
import uuid
import asyncio

from agent_actions.errors import AgentActionsException
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID, DISPOSITION_PASSTHROUGH

from agent_actions.output.writer import FileWriter
from agent_actions.output.saver import UnifiedSourceDataSaver
from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.utils.constants import CHUNK_CONFIG_KEY
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingContext, ProcessingMode


logger = logging.getLogger(__name__)


@dataclass
class InitialStageContext:
    """Context for initial stage pipeline processing."""

    agent_config: dict
    agent_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int = 0
    storage_backend: Any = None  # Optional StorageBackend for database persistence


@dataclass
class DataPreparationContext:
    """Context for data preparation."""

    content: str
    file_type: str
    agent_config: dict
    file_path: str
    agent_name: str
    idx: int = 0


@dataclass
class BatchProcessingContext:
    """Context for batch mode processing."""

    agent_config: dict
    agent_name: str
    data_chunk: list
    file_path: str
    base_directory: str
    output_directory: str
    idx: int = 0
    storage_backend: Any = None  # Optional StorageBackend for database persistence


def _derive_workflow_root(primary_path: Optional[str], fallback_path: str) -> Path:
    """Derive workflow root by finding 'agent_io' in path parts."""
    target_path = Path(primary_path) if primary_path else Path(fallback_path)
    parts = target_path.parts
    if "agent_io" in parts:
        agent_io_idx = parts.index("agent_io")
        return Path(*parts[:agent_io_idx])
    return target_path.parent.parent.parent


def _save_source_items_helper(
    source_items, file_path, base_directory, output_directory=None, storage_backend=None
):
    """Save source items using UnifiedSourceDataSaver."""
    relative_path = Path(file_path).relative_to(base_directory)
    workflow_root = _derive_workflow_root(output_directory, base_directory)

    # Use unified saver with batch mode settings and optional storage backend
    saver = UnifiedSourceDataSaver(
        base_directory=str(workflow_root),
        enable_deduplication=True,
        enable_locking=True,
        storage_backend=storage_backend,
    )

    # Save source items
    saver.save_source_items(items=source_items, relative_path=str(relative_path.with_suffix("")))


def _validate_staged_data(
    raw_content: any,
    file_type: str,
    agent_config: dict,
    agent_name: str,
    mode: str,
    file_path: str,
):
    """Validate INPUT context against template requirements before LLM execution."""
    from agent_actions.prompt.service import (
        PromptPreparationService,
    )

    if not raw_content:
        return  # Nothing to validate

    # Get raw prompt template
    try:
        raw_prompt = PromptFormatter.get_raw_prompt(agent_config)
    except (ValueError, KeyError):
        return  # No template to validate

    if not raw_prompt:
        return

    # Build INPUT context from raw staging data
    # For JSON: first item becomes source content
    # For text: raw text becomes source content
    if file_type == ".json" and isinstance(raw_content, list) and raw_content:
        # JSON array: use first item as sample source content
        first_item = raw_content[0]
        source_content = first_item
    elif file_type == ".json" and isinstance(raw_content, dict):
        # Single JSON object
        source_content = raw_content
        first_item = raw_content
    else:
        # Text/other: wrap in dict with page_content
        source_content = {"page_content": str(raw_content)[:1000]}  # Truncate for validation
        first_item = {"page_content": source_content["page_content"]}

    # Use PromptPreparationService to build INPUT context
    # This builds: {source: {...}, seed: {...}, previous_actions: {...}}
    prep_result = PromptPreparationService.prepare_prompt_with_context(
        agent_config=agent_config,
        agent_name=agent_name,
        contents=source_content if isinstance(source_content, dict) else {},
        mode="batch" if mode == "batch" else "realtime",
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

    # DEBUG: Log what run_mode we're actually getting
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

    # ============================================================================
    # STEP 1: PREFLIGHT VALIDATION ON INPUT (before any LLM execution!)
    # ============================================================================
    _validate_staged_data(
        raw_content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=run_mode or "online",
        file_path=ctx.file_path,
    )

    # ============================================================================
    # STEP 2: Prepare data based on run mode
    # ============================================================================
    prep_ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        file_path=ctx.file_path,
        agent_name=ctx.agent_name,
        idx=ctx.idx,
    )

    if run_mode == "batch":
        # Legacy batch preparation logic
        data_chunk, src_text = _prepare_batch_data(prep_ctx)
    else:
        # Realtime preparation using loaders directly (no StagingContentLoader)
        data_chunk, src_text = _prepare_realtime_data(prep_ctx)

    # ============================================================================
    # STEP 3: UNIFIED SOURCE SAVING (happens for BOTH modes)
    # ============================================================================
    _save_source_data(
        src_text,
        data_chunk,
        ctx.file_path,
        ctx.base_directory,
        ctx.output_directory,
        storage_backend=ctx.storage_backend,
    )

    # ============================================================================
    # STEP 4: Process based on mode
    # ============================================================================
    if run_mode == "batch":
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

    return _process_realtime_mode_with_record_processor(
        data_chunk, ctx, ctx.file_path, ctx.base_directory, ctx.output_directory
    )


def _should_save_source_items(
    new_items: List[Dict],
    file_path: str,
    base_directory: str,
    output_directory: Optional[str] = None,
) -> bool:
    """Return True if new_items are richer (more fields) than existing source data."""
    if not new_items:
        return False

    # Build path to existing source file
    relative_path = Path(file_path).relative_to(base_directory)
    workflow_root = _derive_workflow_root(output_directory, base_directory)

    source_file = workflow_root / "agent_io" / "source" / f"{relative_path.with_suffix('')}.json"

    # If source file doesn't exist, always save
    if not source_file.exists():
        logger.debug("Source file doesn't exist, proceeding with save: %s", source_file)
        return True

    # Load existing source data
    try:
        with open(source_file, "r", encoding="utf-8") as f:
            existing_items = json.load(f)
            if not existing_items:
                logger.debug("Existing source file is empty, proceeding with save")
                return True

            # Compare field counts: use first item as representative
            existing_fields = set(existing_items[0].keys()) if existing_items else set()
            new_fields = set(new_items[0].keys()) if new_items else set()

            # Only save if new data has MORE fields than existing (is richer)
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

    except (IOError, json.JSONDecodeError) as e:
        logger.warning(
            "Error reading existing source file %s: %s, proceeding with save", source_file, e
        )
        return True


def _save_source_data(
    src_text, data_chunk, file_path, base_directory, output_directory=None, storage_backend=None
):
    """UNIFIED source saving logic for both batch and realtime modes."""
    # Determine source items to save
    if src_text:
        # Realtime mode: src_text already prepared by loaders
        source_items = src_text if isinstance(src_text, list) else [src_text]
    else:
        # Batch mode: extract from data_chunk (each row has source_guid)
        source_items = [row.copy() for row in data_chunk if row.get("source_guid")]

    # Save to source folder (single source of truth)
    if source_items:
        # Check if we're about to save sparse data when rich data might exist
        if not _should_save_source_items(source_items, file_path, base_directory, output_directory):
            logger.debug(
                "Skipping source save - existing source data is richer than new data for %s",
                file_path,
            )
            return

        _save_source_items_helper(
            source_items, file_path, base_directory, output_directory, storage_backend
        )


def _prepare_text_chunks_batch(content, agent_config, batch_id, node_id):
    """Prepare text chunks for batch mode."""
    chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
    chunk_size = chunk_config.get("chunk_size", 1000)
    chunk_overlap = chunk_config.get("overlap", 200)
    tokenizer_model = chunk_config.get("tokenizer_model", "cl100k_base")
    split_method = chunk_config.get("split_method", "tiktoken")
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


def _prepare_json_batch(content, batch_id, node_id, file_path, agent_name):
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


def _add_batch_metadata(rows, batch_id, node_id):
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

    # CSV/XML bypass ctx.content and re-read via file_path (see staging/_MANIFEST.md).
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
        # XLSX: FileReader already returns list[dict] from pandas, use directly
        if not isinstance(ctx.content, list):
            logger.debug("XLSX content is %s, expected list[dict]; wrapping", type(ctx.content))
        rows = ctx.content if isinstance(ctx.content, list) else [ctx.content]
        data_chunk = _add_batch_metadata(rows, local_batch_id, node_id)
        src_text = []

    elif ctx.file_type == ".xml":
        # XML: let XmlLoader read the file itself (FileReader returns (tree, root) tuple, not str)
        rows = xml_loader.process(content=None, file_path=ctx.file_path)
        if isinstance(rows, list):
            data_chunk = _add_batch_metadata(rows, local_batch_id, node_id)
        else:
            data_chunk = [
                {"content": rows, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_0"}
            ]
        src_text = []

    else:
        supported = [".txt", ".md", ".pdf", ".docx", ".html", ".json", ".csv", ".xlsx", ".xml"]
        raise AgentActionsException(
            "Unsupported file type in staging loader",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
                "supported_types": supported,
            },
        )

    # Ensure all rows have ancestry chain fields
    for row in data_chunk:
        if "target_id" not in row or not row["target_id"]:
            row["target_id"] = str(uuid.uuid4())
        # First-stage records are their own root
        if "parent_target_id" not in row:
            row["parent_target_id"] = None
        if "root_target_id" not in row:
            row["root_target_id"] = row["target_id"]

    return data_chunk, src_text


def _prepare_realtime_data(ctx: DataPreparationContext):
    """Prepare data for realtime mode processing using direct loaders."""
    from agent_actions.input.loaders.json import JsonLoader
    from agent_actions.input.loaders.tabular import TabularLoader
    from agent_actions.input.loaders.xml import XmlLoader

    json_loader = JsonLoader(ctx.agent_config, ctx.agent_name)
    tabular_loader = TabularLoader(ctx.agent_config, ctx.agent_name)
    xml_loader = XmlLoader(ctx.agent_config, ctx.agent_name)

    # CSV/XML bypass ctx.content and re-read via file_path (see staging/_MANIFEST.md).
    if ctx.file_type in [".txt", ".md", ".pdf", ".docx", ".html"]:
        chunk_config = ctx.agent_config.get(CHUNK_CONFIG_KEY, {})
        chunk_size = chunk_config.get("chunk_size", 1000)
        chunk_overlap = chunk_config.get("overlap", 200)
        tokenizer_model = chunk_config.get("tokenizer_model", "cl100k_base")
        split_method = chunk_config.get("split_method", "tiktoken")
        chunks = Tokenizer.split_text_content(
            ctx.content,
            chunk_size,
            chunk_overlap,
            tokenizer_model=tokenizer_model,
            split_method=split_method,
        )
        # Keep chunks as a list; avoid passing through TextLoader.process (stringifies lists).
        data_chunk = chunks

        # For text, we need to wrap strings in dicts for UnifiedSourceDataSaver
        # Use IDGenerator to ensure GUIDs match what RecordProcessor will generate
        from agent_actions.utils.id_generation import IDGenerator

        src_text = []
        for text in data_chunk:
            guid = IDGenerator.generate_deterministic_source_guid(text)
            # Store flat structure for consistency using 'content' as main text field
            # This avoids nesting and matches the user's expected flat-ish structure
            src_text.append({"source_guid": guid, "content": text})

    elif ctx.file_type == ".json":
        # JsonLoader returns parsed JSON
        data_chunk = json_loader.process(ctx.content, ctx.file_path)

        # Ensure list format for processing
        if not isinstance(data_chunk, list):
            data_chunk = [data_chunk]

        # Prepare source text for saving (add source_guid)
        # CRITICAL: Do NOT mutate data_chunk items in place, as RecordProcessor
        # calculates source_guid based on the raw item content. If we add
        # source_guid to data_chunk, RecordProcessor will include it in the hash,
        # causing a mismatch with the saved source file.
        from agent_actions.utils.id_generation import IDGenerator

        src_text = []
        for item in data_chunk:
            if isinstance(item, dict):
                # Create a copy for source saving to avoid modifying the input for processing
                source_item = item.copy()
                if "source_guid" not in source_item:
                    source_item["source_guid"] = IDGenerator.generate_deterministic_source_guid(
                        item
                    )
                src_text.append(source_item)
            else:
                src_text.append(item)

    elif ctx.file_type == ".csv":
        # CSV: let TabularLoader read the file itself (FileReader returns list[list], not str)
        data_chunk = tabular_loader.process(content=None, file_path=ctx.file_path)
        src_text = data_chunk

    elif ctx.file_type == ".xlsx":
        # XLSX: FileReader already returns list[dict] from pandas, use directly
        data_chunk = ctx.content if isinstance(ctx.content, list) else [ctx.content]
        src_text = data_chunk

    elif ctx.file_type == ".xml":
        # XML: let XmlLoader read the file itself (FileReader returns (tree, root) tuple, not str)
        data_chunk = xml_loader.process(content=None, file_path=ctx.file_path)
        src_text = data_chunk

    else:
        supported = [".txt", ".md", ".pdf", ".docx", ".html", ".json", ".csv", ".xlsx", ".xml"]
        raise AgentActionsException(
            "Unsupported file type in staging loader",
            context={
                "file_type": ctx.file_type,
                "file_path": ctx.file_path,
                "agent_name": ctx.agent_name,
                "supported_types": supported,
            },
        )

    return data_chunk, src_text


def _get_batch_id_from_chunk(data_chunk):
    """Get batch ID from data chunk or generate new one."""
    if data_chunk:
        default_batch_id = f"batch_{uuid.uuid4().hex}"
        try:
            return data_chunk[0].get("batch_id", default_batch_id)
        except (AttributeError, TypeError):
            return default_batch_id
    return f"batch_{uuid.uuid4().hex}"


def _write_passthrough_result(
    output_file_path, result_data, storage_backend=None, action_name=None, output_directory=None
):
    """Write passthrough result and record disposition."""
    if storage_backend is None or action_name is None:
        raise AgentActionsException(
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
    # Import here to avoid circular dependency
    from agent_actions.llm.batch.service import BatchService

    local_batch_id = _get_batch_id_from_chunk(ctx.data_chunk)
    batch_service = BatchService()
    file_name = Path(ctx.file_path).name
    result = batch_service.submit_batch_job(
        ctx.agent_config, file_name, ctx.data_chunk, ctx.output_directory
    )

    relative_path = Path(ctx.file_path).relative_to(ctx.base_directory)
    output_file_path = Path(ctx.output_directory) / relative_path.with_suffix(".json")
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    if result.is_passthrough and result.passthrough.get("type") == "tombstone":
        _write_passthrough_result(
            output_file_path,
            result.passthrough["data"],
            storage_backend=ctx.storage_backend,
            action_name=ctx.agent_name,
            output_directory=ctx.output_directory,
        )
    elif not result.is_passthrough:
        _write_batch_placeholder(output_file_path, local_batch_id, result.batch_id, ctx.agent_name)

    return str(output_file_path)


def _process_realtime_mode_with_record_processor(
    data_chunk, ctx: InitialStageContext, file_path, base_directory, output_directory
):
    """Process data in realtime mode using RecordProcessor."""
    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix(".json")
    # No directory creation - storage backend is required

    # Initialize RecordProcessor
    processor = RecordProcessor(ctx.agent_config, ctx.agent_name)

    # Create processing context
    # Use is_first_stage=True to trigger ID generation and enrichment logic for raw input
    processing_context = ProcessingContext(
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=ProcessingMode.ONLINE,
        is_first_stage=True,
        file_path=str(file_path),
        output_directory=str(output_directory),
        workflow_metadata={"source_file": str(file_path)},
        storage_backend=ctx.storage_backend,
    )

    # Execute batch processing (RecordProcessor.process_batch iterates and calls process() -> LLM)
    # The data_chunk here contains raw items (strings, dicts) or pre-chunked items
    results = processor.process_batch(data_chunk, processing_context)

    # Extract data from results
    processed_items = ResultCollector.collect_results(
        results,
        ctx.agent_config,
        ctx.agent_name,
        is_first_stage=True,
        storage_backend=ctx.storage_backend,
    )

    if ctx.storage_backend is None:
        raise AgentActionsException(
            "Storage backend is required for realtime initial-stage writes.",
            context={
                "file_path": str(output_file_path),
                "agent_name": ctx.agent_name,
            },
        )

    # Write output using storage backend (required)
    file_writer = FileWriter(
        str(output_file_path),
        storage_backend=ctx.storage_backend,
        action_name=ctx.agent_name,
        output_directory=str(output_directory),
    )
    file_writer.write_target(processed_items)

    return str(output_file_path)
