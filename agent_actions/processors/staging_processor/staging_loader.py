"""Module for staging data loading and processing."""
from pathlib import Path
from agent_actions.models import agent_builder
from agent_actions.transformers.string_transformer import Tokenizer
from agent_actions.processors.staging_processor.staging_content import StagingContentLoader
from agent_actions.handlers.file_reader import FileReader
from agent_actions.handlers.file_writer import FileWriter
from agent_actions.constants import CHUNK_CONFIG_KEY
from agent_actions.services.batch_service import BatchService
from agent_actions.cli.exceptions import AgentActionsError
import json
import uuid

def generate_staging(agent_config, agent_name, file_path, base_directory, output_directory):
    """
    Processes a file by splitting its content into chunks or looping through its objects/rows,
    and generating data using an agent.

    Parameters:
        agent_config: Configuration for the agent.
        agent_name (str): Name of the agent.
        file_path (str): Path to the input file.
        base_directory (str): Base directory for the relative file path.
        output_directory (str): Directory where the output file will be saved.
    """
    file_reader = FileReader(file_path)
    content = file_reader.read()
    file_type = file_reader.file_type
    content_processor = StagingContentLoader(agent_config, agent_name)
    # In batch mode, only perform local chunking/parsing, do NOT call any agent/LLM logic
    if agent_config.get('run_mode') == 'batch':
        # Generate a unique batch_id for this batch job
        local_batch_id = f"batch_{uuid.uuid4().hex}"
        if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
            chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
            chunk_size = chunk_config.get("chunk_size", 1000)
            chunk_overlap = chunk_config.get("overlap", 200)
            tokenizer_model = agent_config.get("tokenizer_model", "cl100k_base")
            split_method = agent_config.get("split_method", "tiktoken")
            chunks = Tokenizer.split_text_content(
                content, chunk_size, chunk_overlap, tokenizer_model=tokenizer_model, split_method=split_method
            )
            # Assign a unique batch_uuid to each chunk for custom_id
            data_chunk = [
                {"content": chunk, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_{idx}"}
                for idx, chunk in enumerate(chunks)
            ]
            src_text = []
        elif file_type == '.json':
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content  # fallback if already parsed
            # Add batch_id and batch_uuid to each row if it's a list
            if isinstance(parsed, list):
                data_chunk = [
                    {**row, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_{idx}"}
                    for idx, row in enumerate(parsed)
                ]
            else:
                data_chunk = [{"content": parsed, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_0"}]
            src_text = []
        elif file_type in ('.csv', '.xlsx'):
            rows = content_processor.tabular_loader.process(content)
            data_chunk = [
                {**row, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_{idx}"}
                for idx, row in enumerate(rows)
            ]
            src_text = []
        elif file_type == '.xml':
            rows = content_processor.xml_loader.process(content)
            if isinstance(rows, list):
                data_chunk = [
                    {**row, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_{idx}"}
                    for idx, row in enumerate(rows)
                ]
            else:
                data_chunk = [{"content": rows, "batch_id": local_batch_id, "batch_uuid": f"{local_batch_id}_0"}]
            src_text = []
        else:
            raise AgentActionsError(f"Unsupported file type: {file_type}")
        batch_service = BatchService()
        vendor_batch_id = batch_service.submit_batch_job_from_data(agent_config, agent_name, data_chunk, output_directory)
        relative_path = Path(file_path).relative_to(base_directory)
        output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        placeholder = {
            "batch_job_id": local_batch_id,
            "vendor_batch_id": vendor_batch_id,
            "status": "submitted",
            "agent": agent_name
        }
        with open(output_file_path, 'w') as f:
            json.dump(placeholder, f)
        return
    # Non-batch mode: original behavior (calls agent/LLM for each chunk/row)
    data_chunk, src_text = [], []
    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
        chunk_size = chunk_config.get("chunk_size", 1000)
        chunk_overlap = chunk_config.get("overlap", 200)
        tokenizer_model = agent_config.get("tokenizer_model", "cl100k_base")
        split_method = agent_config.get("split_method", "tiktoken")
        chunks = Tokenizer.split_text_content(
            content, chunk_size, chunk_overlap, tokenizer_model=tokenizer_model, split_method=split_method
        )
        data_chunk, src_text = content_processor._process_chunks(chunks)
    elif file_type == '.json':
        data_chunk, src_text = content_processor._process_json_content(content, file_path)
    elif file_type in ('.csv', '.xlsx'):
        data_chunk, src_text = content_processor._process_tabular_content(content, agent_config, agent_name)
    elif file_type == '.xml':
        data_chunk, src_text = content_processor._process_xml_content(content, agent_config, agent_name)
    else:
        raise AgentActionsError(f"Unsupported file type: {file_type}")
    # ... (rest of the original non-batch output logic follows)

    relative_path = Path(file_path).relative_to(base_directory)
    output_file_path = Path(output_directory) / relative_path.with_suffix('.json')
    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    file_writer = FileWriter(str(output_file_path))
    file_writer.write_staging(data_chunk)
    
    base_path = Path(base_directory).parent
    source_path = base_path / "source"
    output_src_path = source_path / relative_path.with_suffix('.json')
    output_src_path.parent.mkdir(parents=True, exist_ok=True)

    if output_src_path.exists():
        with open(output_src_path, 'r') as existing_file:
            existing_source = json.load(existing_file)
        
        new_guids = [list(item.keys())[0] for item in src_text if list(item.keys())[0] not in [list(existing_item.keys())[0] for existing_item in existing_source]]
        
        if new_guids:
            existing_source.extend([item for item in src_text if list(item.keys())[0] in new_guids])
            source_file_writer = FileWriter(str(output_src_path))
            source_file_writer.write_source(existing_source)
    else:
        source_file_writer = FileWriter(str(output_src_path))
        source_file_writer.write_source(src_text)

