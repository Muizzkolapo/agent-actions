"""Module for staging data loading and processing."""
from pathlib import Path
from agent_actions.models import agent_builder
from agent_actions.transformers.string_transformer import Tokenizer
from agent_actions.processors.staging_processor.staging_content import StagingContentLoader
from agent_actions.handlers.file_reader import FileReader
from agent_actions.handlers.file_writer import FileWriter
import json

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
    if agent_builder is None:
        print("Agent builder import error.")

    file_reader = FileReader(file_path)
    content = file_reader.read()
    file_type = file_reader.file_type  
    content_processor = StagingContentLoader(agent_config, agent_name)

    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        # Get chunk configuration with defaults if not specified
        chunk_config = agent_config.get("chunk_config", {})
        chunk_size = chunk_config.get("chunk_size", 1000)  # Default chunk size
        chunk_overlap = chunk_config.get("overlap", 200)   # Default overlap
        tokenizer_model = agent_config.get("tokenizer_model", "cl100k_base")
        split_method = agent_config.get("split_method", "tiktoken")
        
        chunks = Tokenizer.split_text_content(
            content, 
            chunk_size, 
            chunk_overlap,
            tokenizer_model=tokenizer_model,
            split_method=split_method
        )
        data_chunk, src_text = content_processor._process_chunks(chunks)

    elif file_type == '.json':
        data_chunk, src_text = content_processor._process_json_content(content, file_path)

    elif file_type in ('.csv', '.xlsx'):
        data_chunk, src_text = content_processor._process_tabular_content(content, agent_config, agent_name)

    elif file_type == '.xml':
        data_chunk, src_text = content_processor._process_xml_content(content, agent_config, agent_name)

    else:
        print(f"Unsupported file type: {file_type}")

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

