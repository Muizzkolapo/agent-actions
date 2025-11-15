"""Module for staging data loading and processing."""
from pathlib import Path
from agent_actions.preprocessing.string_transformer import Tokenizer
from .staging_content import StagingContentLoader
from agent_actions.input_loading.file_reader import FileReader
from agent_actions.utilities.file_writer import FileWriter
from agent_actions.utilities.constants import CHUNK_CONFIG_KEY
from agent_actions.utilities.source_data_utils import deduplicate_by_source_guid
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.shared.exceptions import AgentActionsException
import json
import uuid

def generate_staging(agent_config, agent_name, file_path, base_directory, output_directory, idx):
    """
    Processes a file by splitting its content into chunks or looping through its objects/rows,
    and generating data using an agent.

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
    if agent_config.get('run_mode') == 'batch':
        local_batch_id = f'batch_{uuid.uuid4().hex}'
        node_id = f'node_{idx}_{uuid.uuid4()}'
        if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
            chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
            chunk_size = chunk_config.get('chunk_size', 1000)
            chunk_overlap = chunk_config.get('overlap', 200)
            tokenizer_model = chunk_config.get('tokenizer_model', 'cl100k_base')
            split_method = chunk_config.get('split_method', 'tiktoken')
            chunks = Tokenizer.split_text_content(content, chunk_size, chunk_overlap, tokenizer_model=tokenizer_model, split_method=split_method)
            data_chunk = [{'content': chunk, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_{idx}', 'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, str(chunk))), 'target_id': str(uuid.uuid4()), 'node_id': node_id} for idx, chunk in enumerate(chunks)]
            src_text = []
        elif file_type == '.json':
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            if isinstance(parsed, list):
                data_chunk = [{**row, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_{idx}', 'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))), 'target_id': str(uuid.uuid4()), 'node_id': node_id} for idx, row in enumerate(parsed)]
            else:
                data_chunk = [{'content': parsed, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_0'}]
            src_text = []
        elif file_type in ('.csv', '.xlsx'):
            rows = content_processor.tabular_loader.process(content)
            data_chunk = [{**row, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_{idx}', 'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))), 'target_id': str(uuid.uuid4()), 'node_id': node_id} for idx, row in enumerate(rows)]
            src_text = []
        elif file_type == '.xml':
            rows = content_processor.xml_loader.process(content)
            if isinstance(rows, list):
                data_chunk = [{**row, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_{idx}', 'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(row, sort_keys=True))), 'target_id': str(uuid.uuid4()), 'node_id': node_id} for idx, row in enumerate(rows)]
            else:
                data_chunk = [{'content': rows, 'batch_id': local_batch_id, 'batch_uuid': f'{local_batch_id}_0'}]
            src_text = []
        else:
            raise AgentActionsException('Unsupported file type in staging loader', context={'file_type': file_type, 'file_path': file_path, 'agent_name': agent_name, 'supported_types': ['.txt', '.md', '.pdf', '.docx', '.html', '.json', '.csv', '.xlsx', '.xml']})
        for row in data_chunk:
            if 'target_id' not in row or not row['target_id']:
                row['target_id'] = str(uuid.uuid4())
        batch_service = BatchService()
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
            return
        else:
            for row in data_chunk:
                source_guid = row.get('source_guid')
                if source_guid:
                    # Use flat format instead of nested format
                    src_text = row.copy()
                    # source_guid already in row, therefore in copy - no need to check
                    batch_service._save_task_source([src_text], file_path, base_directory, output_directory)
            placeholder = {'batch_job_id': local_batch_id, 'vendor_batch_id': result, 'status': 'submitted', 'agent': agent_name}
            with open(output_file_path, 'w') as f:
                json.dump(placeholder, f)
            return
    data_chunk, src_text = ([], [])
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
        raise AgentActionsException('Unsupported file type in staging loader', context={'file_type': file_type, 'file_path': file_path, 'agent_name': agent_name, 'supported_types': ['.txt', '.md', '.pdf', '.docx', '.html', '.json', '.csv', '.xlsx', '.xml']})
    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    file_writer = FileWriter(str(output_file_path))
    file_writer.write_staging(data_chunk)
    base_path = Path(base_directory).parent
    source_path = base_path / 'source'
    output_src_path = source_path / relative_path.with_suffix('.json')
    output_src_path.parent.mkdir(parents=True, exist_ok=True)

    # Use file locking for atomic read-modify-write (prevents race conditions)
    import portalocker

    file_exists = output_src_path.exists()
    mode = 'r+' if file_exists else 'w'

    with open(output_src_path, mode) as f:
        # Acquire exclusive lock - blocks until available (cross-platform)
        portalocker.lock(f, portalocker.LOCK_EX)

        try:
            # Read existing data if file exists
            if file_exists:
                f.seek(0)
                existing_source = json.load(f)
            else:
                existing_source = []

            # Deduplicate by source_guid using flat format
            new_items = deduplicate_by_source_guid(existing_source, src_text)

            # Write back if we have new items or creating new file
            if new_items or not file_exists:
                if new_items:
                    existing_source.extend(new_items)

                # Clear file and write from beginning
                f.seek(0)
                f.truncate()
                json.dump(existing_source, f, indent=2)
        finally:
            # Unlock automatically when exiting context manager
            pass