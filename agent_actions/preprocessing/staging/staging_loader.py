"""Module for staging data loading and processing.

REFACTORED: Unified source saving logic to prevent timing issues.
- Source data is ALWAYS saved before any processing (batch or realtime)
- Single source of truth for source saving eliminates duplication
- Helper functions separate concerns and improve maintainability
"""
from pathlib import Path
from agent_actions.preprocessing.transformation.string_transformer import Tokenizer
from .staging_content import StagingContentLoader
from agent_actions.input_loading.file_reader import FileReader
from agent_actions.io.file_writer import FileWriter
from agent_actions.utilities.constants import CHUNK_CONFIG_KEY
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.errors import AgentActionsException  # New modular pattern!
import json
import logging
import uuid

logger = logging.getLogger(__name__)


def generate_staging(agent_config, agent_name, file_path, base_directory, output_directory, idx):
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
    file_reader = FileReader(file_path)
    content = file_reader.read()
    file_type = file_reader.file_type
    content_processor = StagingContentLoader(agent_config, agent_name)
    run_mode = agent_config.get('run_mode')

    # DEBUG: Log what run_mode we're actually getting
    logger.info(
        "Staging loader run_mode check: mode=%s, agent=%s, file=%s",
        run_mode,
        agent_name,
        Path(file_path).name,
        extra={
            'run_mode': run_mode,
            'agent_name': agent_name,
            'has_run_mode_in_config': 'run_mode' in agent_config,
            'agent_config_keys': list(agent_config.keys())[:10]
        }
    )

    # ============================================================================
    # STEP 1: Prepare data based on run mode
    # ============================================================================
    if run_mode == 'batch':
        data_chunk, src_text = _prepare_batch_data(
            content, file_type, content_processor, agent_config,
            file_path, agent_name, idx
        )
    else:
        data_chunk, src_text = _prepare_realtime_data(
            content, file_type, content_processor, agent_config,
            file_path, agent_name
        )

    # ============================================================================
    # STEP 2: UNIFIED SOURCE SAVING (happens for BOTH modes)
    # ============================================================================
    # This is the KEY fix: save source BEFORE any processing
    # Prevents timing issues where processing tries to load source that doesn't exist yet
    _save_source_data(src_text, data_chunk, file_path, base_directory, output_directory)

    # ============================================================================
    # STEP 3: Process based on mode (source is now guaranteed to exist)
    # ============================================================================
    if run_mode == 'batch':
        return _process_batch_mode(
            agent_config, agent_name, data_chunk, file_path,
            base_directory, output_directory, idx
        )
    else:
        return _process_realtime_mode(
            data_chunk, file_path, base_directory, output_directory
        )


def _save_source_data(src_text, data_chunk, file_path, base_directory, output_directory):
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
        output_directory: Directory where the output file will be saved

    Implementation Note:
        - Batch mode: Extracts source from data_chunk (which has source_guid)
        - Realtime mode: Uses pre-prepared src_text
        - Both modes use the same BatchService._save_task_source() method
    """
    batch_service = BatchService()

    # Determine source items to save
    if src_text:
        # Realtime mode: src_text already prepared by content processor
        source_items = src_text if isinstance(src_text, list) else [src_text]
    else:
        # Batch mode: extract from data_chunk (each row has source_guid)
        source_items = [
            row.copy()
            for row in data_chunk
            if row.get('source_guid')
        ]

    # Save to source folder (single source of truth)
    if source_items:
        batch_service._save_task_source(source_items, file_path, base_directory, output_directory)


def _prepare_batch_data(content, file_type, content_processor, agent_config, file_path, agent_name, idx):
    """
    Prepare data for batch mode processing.

    Creates data_chunk with batch-specific metadata (batch_id, source_guid, etc).

    Args:
        content: File content
        file_type: File extension (.json, .csv, etc.)
        content_processor: StagingContentLoader instance
        agent_config: Agent configuration
        file_path: Path to input file
        agent_name: Name of the agent
        idx: Index of the config being processed

    Returns:
        Tuple of (data_chunk, src_text) where:
        - data_chunk: List of dicts with batch metadata
        - src_text: Empty list (not used in batch mode)
    """
    local_batch_id = f'batch_{uuid.uuid4().hex}'
    node_id = f'node_{idx}_{uuid.uuid4()}'

    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
        chunk_size = chunk_config.get('chunk_size', 1000)
        chunk_overlap = chunk_config.get('overlap', 200)
        tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
        split_method = chunk_config.get('split_method', 'tiktoken')
        chunks = Tokenizer.split_text_content(content, chunk_size, chunk_overlap, tokenizer_model=tokenizer_model, split_method=split_method)
        data_chunk = [
            {
                'content': chunk,
                'batch_id': local_batch_id,
                'batch_uuid': f'{local_batch_id}_{idx}',
                'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, str(chunk))),
                'target_id': str(uuid.uuid4()),
                'node_id': node_id
            }
            for idx, chunk in enumerate(chunks)
        ]
        src_text = []

    elif file_type == '.json':
        try:
            parsed = json.loads(content)
        except Exception as e:
            logger.warning(
                "Failed to parse JSON content from %s, using raw content: %s",
                file_path, e,
                extra={
                    'file_path': file_path,
                    'file_type': file_type,
                    'agent_name': agent_name,
                    'operation': 'json_parse',
                    'content_length': len(content) if content else 0
                }
            )
            parsed = content

        if isinstance(parsed, list):
            data_chunk = [
                {
                    **row,
                    'batch_id': local_batch_id,
                    'batch_uuid': f'{local_batch_id}_{idx}',
                    'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))),
                    'target_id': str(uuid.uuid4()),
                    'node_id': node_id
                }
                for idx, row in enumerate(parsed)
            ]
        else:
            data_chunk = [
                {
                    'content': parsed,
                    'batch_id': local_batch_id,
                    'batch_uuid': f'{local_batch_id}_0'
                }
            ]
        src_text = []

    elif file_type in ('.csv', '.xlsx'):
        rows = content_processor.tabular_loader.process(content)
        data_chunk = [
            {
                **row,
                'batch_id': local_batch_id,
                'batch_uuid': f'{local_batch_id}_{idx}',
                'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))),
                'target_id': str(uuid.uuid4()),
                'node_id': node_id
            }
            for idx, row in enumerate(rows)
        ]
        src_text = []

    elif file_type == '.xml':
        rows = content_processor.xml_loader.process(content)
        if isinstance(rows, list):
            data_chunk = [
                {
                    **row,
                    'batch_id': local_batch_id,
                    'batch_uuid': f'{local_batch_id}_{idx}',
                    'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))),
                    'target_id': str(uuid.uuid4()),
                    'node_id': node_id
                }
                for idx, row in enumerate(rows)
            ]
        else:
            data_chunk = [
                {
                    'content': rows,
                    'batch_id': local_batch_id,
                    'batch_uuid': f'{local_batch_id}_0'
                }
            ]
        src_text = []

    else:
        raise AgentActionsException(
            'Unsupported file type in staging loader',
            context={
                'file_type': file_type,
                'file_path': file_path,
                'agent_name': agent_name,
                'supported_types': ['.txt', '.md', '.pdf', '.docx', '.html', '.json', '.csv', '.xlsx', '.xml']
            }
        )

    # Ensure all rows have target_id
    for row in data_chunk:
        if 'target_id' not in row or not row['target_id']:
            row['target_id'] = str(uuid.uuid4())

    return data_chunk, src_text


def _prepare_realtime_data(content, file_type, content_processor, agent_config, file_path, agent_name):
    """
    Prepare data for realtime mode processing.

    Uses content processor methods to create both data_chunk and src_text.

    Args:
        content: File content
        file_type: File extension (.json, .csv, etc.)
        content_processor: StagingContentLoader instance
        agent_config: Agent configuration
        file_path: Path to input file
        agent_name: Name of the agent

    Returns:
        Tuple of (data_chunk, src_text) where:
        - data_chunk: List of dicts for staging
        - src_text: List of source items with source_guid
    """
    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
        chunk_size = chunk_config.get('chunk_size', 1000)
        chunk_overlap = chunk_config.get('overlap', 200)
        tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
        split_method = chunk_config.get('split_method', 'tiktoken')
        chunks = Tokenizer.split_text_content(content, chunk_size, chunk_overlap, tokenizer_model=tokenizer_model, split_method=split_method)
        data_chunk, src_text = content_processor._process_chunks(chunks)

    elif file_type == '.json':
        data_chunk, src_text = content_processor._process_json_content(content, file_path)

    elif file_type in ('.csv', '.xlsx'):
        data_chunk, src_text = content_processor._process_tabular_content(content, agent_config, agent_name)

    elif file_type == '.xml':
        data_chunk, src_text = content_processor._process_xml_content(content, agent_config, agent_name)

    else:
        raise AgentActionsException(
            'Unsupported file type in staging loader',
            context={
                'file_type': file_type,
                'file_path': file_path,
                'agent_name': agent_name,
                'supported_types': ['.txt', '.md', '.pdf', '.docx', '.html', '.json', '.csv', '.xlsx', '.xml']
            }
        )

    return data_chunk, src_text


def _process_batch_mode(agent_config, agent_name, data_chunk, file_path, base_directory, output_directory, idx):
    """
    Process data in batch mode by submitting to batch service.

    NOTE: Source data has already been saved by _save_source_data(), so it will be
    available during batch task preparation.

    Args:
        agent_config: Agent configuration
        agent_name: Name of the agent
        data_chunk: Prepared data chunk with batch metadata
        file_path: Path to input file
        base_directory: Base directory for the relative file path
        output_directory: Directory where the output file will be saved
        idx: Index of the config being processed

    Returns:
        None (writes output files as side effect)
    """
    batch_service = BatchService()
    local_batch_id = data_chunk[0].get('batch_id', f'batch_{uuid.uuid4().hex}') if data_chunk else f'batch_{uuid.uuid4().hex}'

    file_name = Path(file_path).name
    result = batch_service.submit_batch_job(agent_config, file_name, data_chunk, output_directory)

    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(result, dict) and result.get('type') == 'passthrough':
        file_writer = FileWriter(str(output_file_path))
        file_writer.write_target(result['data'])
        passthrough_marker = output_file_path.parent / '.passthrough_processed'
        passthrough_marker.touch()
    else:
        placeholder = {
            'batch_job_id': local_batch_id,
            'vendor_batch_id': result,
            'status': 'submitted',
            'agent': agent_name
        }
        with open(output_file_path, 'w') as f:
            json.dump(placeholder, f)


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
    output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    file_writer = FileWriter(str(output_file_path))
    file_writer.write_staging(data_chunk)
