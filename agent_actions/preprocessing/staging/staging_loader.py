"""
Module for staging data loading and processing.
"""

from dataclasses import dataclass
from pathlib import Path
import json
import logging
import uuid

from agent_actions.errors import AgentActionsException
from agent_actions.input_loading.file_reader import FileReader
from agent_actions.file_io.file_writer import FileWriter
from agent_actions.file_io.unified_source_data_saver import UnifiedSourceDataSaver
from agent_actions.preprocessing.transformation.string_transformer import Tokenizer
from agent_actions.utilities.constants import CHUNK_CONFIG_KEY
from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.validation.preflight.preflight_validator import PreFlightValidator
from agent_actions.prompt_generation.prompt_formatter import PromptFormatter

from .staging_content import StagingContentLoader

logger = logging.getLogger(__name__)


@dataclass
class StagingContext:
    """Context for staging data processing."""

    agent_config: dict
    agent_name: str
    file_path: str
    base_directory: str
    output_directory: str
    idx: int = 0


@dataclass
class DataPreparationContext:
    """Context for data preparation."""

    content: str
    file_type: str
    content_processor: "StagingContentLoader"
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


def _save_source_items_helper(source_items, file_path, base_directory, output_directory=None):
    """
    Helper to save source items using UnifiedSourceDataSaver.

    Args:
        source_items: List of source items to save
        file_path: Path to the input file
        base_directory: Base directory for input files
        output_directory: Optional output directory - used to determine target workflow root
                         when processing inter-workflow dependencies (manifest-based input)

    Note:
        This is extracted to avoid calling protected methods from BatchService.
        When output_directory is provided, we derive the workflow root from it
        to ensure source data is saved to the TARGET workflow, not the source workflow.
    """
    relative_path = Path(file_path).relative_to(base_directory)

    # Determine workflow root - prefer output_directory if provided (for inter-workflow deps)
    # This ensures source is saved to the TARGET workflow when reading from upstream manifest
    if output_directory:
        output_path = Path(output_directory)
        parts = output_path.parts
        if "agent_io" in parts:
            agent_io_idx = parts.index("agent_io")
            workflow_root = Path(*parts[:agent_io_idx])
        else:
            # Fallback to going up from output directory
            workflow_root = output_path.parent.parent.parent
    else:
        # Legacy behavior - derive from base_directory
        base_path = Path(base_directory)
        parts = base_path.parts
        if "agent_io" in parts:
            agent_io_idx = parts.index("agent_io")
            workflow_root = Path(*parts[:agent_io_idx])
        else:
            # Fallback to going up 3 levels
            workflow_root = base_path.parent.parent.parent

    # Use unified saver with batch mode settings
    saver = UnifiedSourceDataSaver(
        base_directory=str(workflow_root), enable_deduplication=True, enable_locking=True
    )

    # Save source items
    saver.save_source_items(items=source_items, relative_path=str(relative_path.with_suffix("")))


def _extract_staged_fields(data_chunk: list) -> list:
    """
    Extract all available field names from staged data.

    Args:
        data_chunk: List of data items (dicts)

    Returns:
        Sorted list of unique field names available in the staged data
    """
    if not data_chunk:
        return []

    all_fields = set()
    for item in data_chunk[:5]:  # Sample first 5 items for efficiency
        if isinstance(item, dict):
            # Add top-level keys
            all_fields.update(item.keys())
            # Add nested keys from 'content' if it's a dict
            content = item.get("content")
            if isinstance(content, dict):
                for key in content.keys():
                    all_fields.add(f"content.{key}")
                    all_fields.add(key)  # Also available without prefix

    # Filter out internal metadata fields (not user-facing)
    internal_fields = {
        "batch_id",
        "batch_uuid",
        "source_guid",
        "target_id",
        "node_id",
        "lineage",
        "content",  # System wrapper fields
    }
    user_fields = sorted(f for f in all_fields if f not in internal_fields)

    return user_fields


def _validate_staged_data(
    raw_content: any,
    file_type: str,
    agent_config: dict,
    agent_name: str,
    mode: str,
    file_path: str,
):
    """
    Validate INPUT context against template requirements BEFORE LLM execution.

    This runs BEFORE _prepare_realtime_data() to catch template errors early,
    avoiding wasted LLM calls. Validates against INPUT context (source + seed),
    NOT against LLM OUTPUT.

    Args:
        raw_content: Raw content from staging file (JSON array, text, etc.)
        file_type: File extension (.json, .txt, .md, etc.)
        agent_config: Agent configuration with prompt template
        agent_name: Name of agent (for error context)
        mode: Execution mode ('batch' or 'online')
        file_path: Path to input file (for context building)

    Raises:
        PreFlightValidationError: If template references fields not in context
    """
    from agent_actions.prompt_generation.prompt_preparation_service import (
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

    # Validate against INPUT context (source + seed + previous actions)
    validator = PreFlightValidator()
    result = validator.validate(
        template=raw_prompt,
        context=prep_result.prompt_context,
        agent_name=agent_name,
        mode=mode,
        agent_config=agent_config,
    )

    result.raise_if_invalid()


def generate_staging(ctx: StagingContext):
    """
    Processes a file by splitting its content into chunks or looping through its objects/rows,
    and generating data using an agent.

    REFACTORED ARCHITECTURE:
    1. Read and prepare data (batch or realtime specific)
    2. UNIFIED source saving (happens for BOTH modes before processing)
    3. Process based on mode (source is guaranteed to exist)

    This ensures source data is ALWAYS available during processing, preventing
    chicken-and-egg timing issues in batch mode.

    Parameters:
        agent_config: Configuration for the agent.
        agent_name (str): Name of the agent.
        file_path (str): Path to the input file.
        base_directory (str): Base directory for the relative file path.
        output_directory (str): Directory where the output file will be saved.
        idx (int): Index of the config being processed.
    """
    file_reader = FileReader(ctx.file_path)
    content = file_reader.read()
    file_type = file_reader.file_type
    content_processor = StagingContentLoader(ctx.agent_config, ctx.agent_name)
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
    # Validate template against INPUT context (staging data + seed)
    # This MUST run BEFORE _prepare_realtime_data() which executes the LLM
    _validate_staged_data(
        raw_content=content,
        file_type=file_type,
        agent_config=ctx.agent_config,
        agent_name=ctx.agent_name,
        mode=run_mode or "online",
        file_path=ctx.file_path,
    )

    # ============================================================================
    # STEP 2: Prepare data based on run mode (LLM runs here for realtime)
    # ============================================================================
    prep_ctx = DataPreparationContext(
        content=content,
        file_type=file_type,
        content_processor=content_processor,
        agent_config=ctx.agent_config,
        file_path=ctx.file_path,
        agent_name=ctx.agent_name,
        idx=ctx.idx,
    )

    if run_mode == "batch":
        data_chunk, src_text = _prepare_batch_data(prep_ctx)
    else:
        data_chunk, src_text = _prepare_realtime_data(prep_ctx)

    # ============================================================================
    # STEP 3: UNIFIED SOURCE SAVING (happens for BOTH modes)
    # ============================================================================
    # This is the KEY fix: save source BEFORE any processing
    # Prevents timing issues where processing tries to load source that doesn't exist yet
    _save_source_data(src_text, data_chunk, ctx.file_path, ctx.base_directory, ctx.output_directory)

    # ============================================================================
    # STEP 4: Process based on mode (source is now guaranteed to exist)
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
        )
        return _process_batch_mode(batch_ctx)
    return _process_realtime_mode(
        data_chunk, ctx.file_path, ctx.base_directory, ctx.output_directory
    )


def _save_source_data(src_text, data_chunk, file_path, base_directory, output_directory=None):
    """
    UNIFIED source saving logic for both batch and realtime modes.

    This function ensures source data is saved BEFORE any processing happens,
    preventing the chicken-and-egg timing issue where batch task preparation
    tries to load source data that hasn't been saved yet.

    Args:
        src_text: Source text data (from realtime mode) or empty list
        data_chunk: Data chunk with source_guid fields
        file_path: Path to the input file
        base_directory: Base directory for the relative file path
        output_directory: Optional output directory - used to determine target workflow root
                         for inter-workflow dependencies (manifest-based input)

    Implementation Note:
        - Batch mode: Extracts source from data_chunk (which has source_guid)
        - Realtime mode: Uses pre-prepared src_text
        - Both modes use UnifiedSourceDataSaver directly
        - When output_directory differs from base_directory (inter-workflow case),
          source is saved to the TARGET workflow to ensure downstream agents can load it
    """

    # Determine source items to save
    if src_text:
        # Realtime mode: src_text already prepared by content processor
        source_items = src_text if isinstance(src_text, list) else [src_text]
    else:
        # Batch mode: extract from data_chunk (each row has source_guid)
        source_items = [row.copy() for row in data_chunk if row.get("source_guid")]

    # Save to source folder (single source of truth)
    if source_items:
        _save_source_items_helper(source_items, file_path, base_directory, output_directory)


def _prepare_text_chunks_batch(content, agent_config, batch_id, node_id):
    """
    Prepare text chunks for batch mode.

    Args:
        content: Text content to chunk
        agent_config: Agent configuration with chunk settings
        batch_id: Batch ID for this processing run
        node_id: Node ID for this chunk

    Returns:
        List of dicts with chunked content and batch metadata
    """
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
    """
    Prepare JSON content for batch mode.

    Args:
        content: JSON content string
        batch_id: Batch ID for this processing run
        node_id: Node ID for this chunk
        file_path: Path to file (for logging)
        agent_name: Agent name (for logging)

    Returns:
        List of dicts with JSON data and batch metadata
    """
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
    """
    Add batch metadata to rows of data.

    Args:
        rows: List of data rows
        batch_id: Batch ID for this processing run
        node_id: Node ID for this chunk

    Returns:
        List of dicts with batch metadata added
    """
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
    """
    Prepare data for batch mode processing.

    Creates data_chunk with batch-specific metadata (batch_id, source_guid, etc).

    Args:
        ctx: DataPreparationContext with all necessary data

    Returns:
        Tuple of (data_chunk, src_text) where:
        - data_chunk: List of dicts with batch metadata
        - src_text: Empty list (not used in batch mode)
    """
    local_batch_id = f"batch_{uuid.uuid4().hex}"
    node_id = f"node_{ctx.idx}_{uuid.uuid4()}"

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

    elif ctx.file_type in (".csv", ".xlsx"):
        rows = ctx.content_processor.tabular_loader.process(ctx.content)
        data_chunk = _add_batch_metadata(rows, local_batch_id, node_id)
        src_text = []

    elif ctx.file_type == ".xml":
        rows = ctx.content_processor.xml_loader.process(ctx.content)
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
    """
    Prepare data for realtime mode processing.

    Uses content processor methods to create both data_chunk and src_text.

    Args:
        ctx: DataPreparationContext with all necessary data

    Returns:
        Tuple of (data_chunk, src_text) where:
        - data_chunk: List of dicts for staging
        - src_text: List of source items with source_guid
    """
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
        data_chunk, src_text = ctx.content_processor.process_chunks(chunks)

    elif ctx.file_type == ".json":
        data_chunk, src_text = ctx.content_processor.process_json_content(
            ctx.content, ctx.file_path
        )

    elif ctx.file_type in (".csv", ".xlsx"):
        data_chunk, src_text = ctx.content_processor.process_tabular_content(
            ctx.content, ctx.agent_config, ctx.agent_name
        )

    elif ctx.file_type == ".xml":
        data_chunk, src_text = ctx.content_processor.process_xml_content(
            ctx.content, ctx.agent_config, ctx.agent_name
        )

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
        return data_chunk[0].get("batch_id", default_batch_id)
    return f"batch_{uuid.uuid4().hex}"


def _write_passthrough_result(output_file_path, result_data):
    """Write passthrough result and create marker file."""
    file_writer = FileWriter(str(output_file_path))
    file_writer.write_target(result_data)
    passthrough_marker = output_file_path.parent / ".passthrough_processed"
    passthrough_marker.touch()


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
    """
    Process data in batch mode by submitting to batch service.

    NOTE: Source data has already been saved by _save_source_data(), so it will be
    available during batch task preparation.

    Args:
        ctx: BatchProcessingContext with all necessary data

    Returns:
        None (writes output files as side effect)
    """
    # Import here to avoid circular dependency
    from agent_actions.llm_invocation.batch.batch_service import BatchService

    local_batch_id = _get_batch_id_from_chunk(ctx.data_chunk)
    batch_service = BatchService()
    file_name = Path(ctx.file_path).name
    result = batch_service.submit_batch_job(
        ctx.agent_config, file_name, ctx.data_chunk, ctx.output_directory
    )

    relative_path = Path(ctx.file_path).relative_to(ctx.base_directory)
    output_file_path = Path(ctx.output_directory) / relative_path.with_suffix(".json")
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(result, dict) and result.get("type") == "passthrough":
        _write_passthrough_result(output_file_path, result["data"])
    else:
        _write_batch_placeholder(output_file_path, local_batch_id, result, ctx.agent_name)


def _process_realtime_mode(data_chunk, file_path, base_directory, output_directory):
    """
    Process data in realtime mode by writing staging file.

    NOTE: Source data has already been saved by _save_source_data().

    Args:
        data_chunk: Prepared data chunk
        file_path: Path to input file
        base_directory: Base directory for the relative file path
        output_directory: Directory where the output file will be saved

    Returns:
        None (writes output files as side effect)
    """
    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix(".json")
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    file_writer = FileWriter(str(output_file_path))
    file_writer.write_staging(data_chunk)
