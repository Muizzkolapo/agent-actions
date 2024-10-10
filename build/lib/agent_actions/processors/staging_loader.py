"""Module for staging data loading and processing."""
import os
from agent_actions.models import agent_builder
import logging
from agent_actions.core.agent_handlers import split_text_content
from agent_actions.processors.content_processor import StagingContentProcessor
from agent_actions.processors.file_processor import FileReader, FileWriter

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
    chunks = split_text_content(content, chunk_size, overlap)

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


