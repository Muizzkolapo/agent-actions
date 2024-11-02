"""Module for staging data loading and processing."""
import os
from agent_actions.models import agent_builder
import logging
from agent_actions.transformers.string_transformer import Tokenizer
from agent_actions.processors.staging_content import StagingContentProcessor
from agent_actions.handlers.file_handler import FileReader, FileWriter
import json
from agent_actions.logging_setup import setup_logging
logger = setup_logging()
logger = logging.getLogger(__name__)





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

    Raises:
        ValueError: If the file type is not supported.
    """
    if agent_builder is None:
        raise ImportError("Unable to import 'agent_actions.agent_utils.agent_builder'")

    # Use FileReader to read the file content
    file_reader = FileReader(file_path)
    content = file_reader.read()

    file_type = file_reader.file_type  # Get the file type

    # Create an instance of StagingContentProcessor
    content_processor = StagingContentProcessor(agent_config, agent_name)

    # Process the content based on the file type
    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        # Text-based content: Split into chunks and process
        chunks = Tokenizer.split_text_content(content, agent_config["chunk_config"]["chunk_size"], agent_config["chunk_config"]["overlap"])
        data_chunk, src_text = content_processor._process_chunks(chunks)

    elif file_type == '.json':
        # Process JSON content
        data_chunk, src_text = content_processor._process_json_content(content, file_path)

    elif file_type in ('.csv', '.xlsx'):
        # Process tabular content (CSV or Excel)
        data_chunk, src_text = content_processor._process_tabular_content(content, agent_config, agent_name)

    elif file_type == '.xml':
        # Process XML content
        data_chunk, src_text = content_processor._process_xml_content(content, agent_config, agent_name)

    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    #--sorting out output target
    relative_path = os.path.relpath(file_path, base_directory)
    output_file_path = os.path.join(output_directory, relative_path.replace(file_type, '.json'))
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    # Write the processed data to the output file
    file_writer = FileWriter(output_file_path)
    file_writer.write_staging(data_chunk)

    #--sorting out output source_text folder
    base_path = os.path.join(base_directory, "..")
    source_path = os.path.join(base_path, "source")
    output_src_path = os.path.join(source_path, relative_path.replace(file_type, '.json'))
    os.makedirs(os.path.dirname(output_src_path), exist_ok=True)

    # Check if the source file already exists
    if os.path.exists(output_src_path):
        with open(output_src_path, 'r') as existing_file:
            existing_source = json.load(existing_file)
        
        # Check if any new GUIDs need to be added
        new_guids = [list(item.keys())[0] for item in src_text if list(item.keys())[0] not in [list(existing_item.keys())[0] for existing_item in existing_source]]
        
        if new_guids:
            # Append only the new items to the existing source
            existing_source.extend([item for item in src_text if list(item.keys())[0] in new_guids])
            
            # Write the updated source content to the source output file
            source_file_writer = FileWriter(output_src_path)
            source_file_writer.write_source(existing_source)
    else:
        # If the file doesn't exist, write the entire src_text
        source_file_writer = FileWriter(output_src_path)
        source_file_writer.write_source(src_text)



def generate_stagingold(agent_config, agent_name, file_path, base_directory, output_directory):
    """
    Processes a file by splitting its content into chunks or looping through its objects/rows,
    and generating data using an agent.

    Parameters:
        agent_config: Configuration for the agent.
        agent_name (str): Name of the agent.
        file_path (str): Path to the input file.
        base_directory (str): Base directory for the relative file path.
        output_directory (str): Directory where the output file will be saved.
        chunk_config (dict, optional): Configuration for chunking the content.

    Raises:
        ValueError: If the file type is not supported.
    """
    if agent_builder is None:
        raise ImportError("Unable to import 'agent_actions.agent_utils.agent_builder'")

    file_reader = FileReader(file_path)
    content = file_reader.read()

    # Extract chunk_size and overlap from agent_config["chunk_config"]
    chunk_size = agent_config["chunk_config"]["chunk_size"]
    overlap = agent_config["chunk_config"]["overlap"]


    # Call the split_text_into_chunks function with the required arguments
    chunks = Tokenizer.split_text_content(content, chunk_size, overlap)

    content_processor = StagingContentProcessor(agent_config, agent_name)
    data_chunk, src_text = content_processor.process(chunks, os.path.splitext(file_path)[1].lower())



    relative_path = os.path.relpath(file_path, base_directory)
    output_file_path = os.path.join(output_directory, relative_path.replace(file_reader.file_type, '.json'))
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    file_writer = FileWriter(output_file_path)
    file_writer.write_staging(data_chunk)

    base_path = os.path.join(base_directory, "..")
    source_path = os.path.join(base_path, "source")
    output_src_path = os.path.join(source_path, relative_path.replace(file_reader.file_type, '.json'))
    os.makedirs(os.path.dirname(output_src_path), exist_ok=True)

    source_file_writer = FileWriter(output_src_path)
    source_file_writer.write_source(src_text)


