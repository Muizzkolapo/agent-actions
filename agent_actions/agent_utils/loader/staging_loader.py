"""Module for staging data loading and processing."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from langchain.text_splitter import CharacterTextSplitter
import itertools
import uuid

try:
    from agent_actions.agent_utils.agent_builder import agent_builder
    from agent_actions.agent_utils.processor.clean_target import clean_agent_output
    from agent_actions.agent_utils.transformers.aggregators import transform_structure
except ImportError:
    transform_structure = None



try:
    from agent_actions.agent_utils.agent_builder import agent_builder
except ImportError:
    # Handle import error gracefully
    agent_builder = None




def generate_id():
    """Generate a unique identifier."""
    return str(uuid.uuid4())








def staging_dynamic_creator(agent_config, agent_name, input_documentation, formatted_prompt=None):
    if 'guid' in input_documentation and input_documentation['guid'] and input_documentation['content']:
        input_data = input_documentation['content']
        guid = input_documentation['guid']
        response = agent_builder.create_dynamic_agent(
                    agent_config, agent_name, input_data)   
        transformed_response_temp = [{guid: response}]
        transformed_response = transform_structure(transformed_response_temp) 
        src_text = input_documentation
    else:
        response = agent_builder.create_dynamic_agent(
                    agent_config, agent_name, input_documentation)
        guid = generate_id()
        transformed_response_temp = [{guid: response}]
        transformed_response = transform_structure(transformed_response_temp) 
        src_text = [{guid: input_documentation}]
    
    return transformed_response,src_text


def read_json(file):
    """
    Read JSON content from a file.

    Parameters:
        file (file): The file object.

    Returns:
        dict: The parsed JSON content.
    """
    return json.load(file)

def read_text(file):
    """
    Read text content from a file.

    Parameters:
        file (file): The file object.

    Returns:
        str: The text content.
    """
    return file.read()

def read_csv(file):
    """
    Read CSV content from a file.

    Parameters:
        file (file): The file object.

    Returns:
        list: List of rows, each row being a list of values.
    """
    reader = csv.reader(file)
    return list(reader)

def read_pdf(file):
    """
    Read text content from a PDF file.

    Parameters:
        file (file): The file object.

    Returns:
        str: The text content extracted from the PDF.
    """
    reader = PyPDF2.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text

def read_xml(file):
    """
    Read XML content from a file.

    Parameters:
        file (file): The file object.

    Returns:
        tuple: A tuple containing the XML tree and root element.
    """
    tree = ET.parse(file)
    root = tree.getroot()
    return tree, root

def read_docx(file_path):
    """
    Read text content from a DOCX file.

    Parameters:
        file_path (str): The path to the DOCX file.

    Returns:
        str: The text content.
    """
    doc = Document(file_path)
    return '\n'.join([para.text for para in doc.paragraphs])

def read_xlsx(file):
    """
    Read Excel content from a file.

    Parameters:
        file (file): The file object.

    Returns:
        list: List of dictionaries representing rows from the Excel file.
    """
    df = pd.read_excel(file)
    return df.to_dict(orient='records')

def read_html(file):
    """
    Read text content from an HTML file.

    Parameters:
        file (file): The file object.

    Returns:
        str: The text content.
    """
    soup = BeautifulSoup(file, 'html.parser')
    return soup.get_text()

def read_file(file_path):
    """
    Reads the content of a file based on its type.

    Parameters:
        file_path (str): The path to the file.

    Returns:
        The content of the file.

    Raises:
        ValueError: If the file type is not supported.
    """
    file_type_handlers = {
        '.json': read_json,
        '.txt': read_text,
        '.md': read_text,
        '.csv': read_csv,
        '.pdf': read_pdf,
        '.xml': read_xml,
        '.docx': read_docx,
        '.xlsx': read_xlsx,
        '.html': read_html,
    }

    file_type = os.path.splitext(file_path)[1].lower()
    if file_type in file_type_handlers:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file_type_handlers[file_type](file)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def process_xml_element(element):
    """
    Convert an XML element and its children to a dictionary.

    Parameters:
        element: An XML element.

    Returns:
        dict: A dictionary representation of the XML element.
    """
    data = {}
    if list(element):  # If the element has children
        for child in element:
            data[child.tag] = process_xml_element(child)
    else:
        data = element.text
    return data


def write_file(data, output_file_path):
    """
    Writes data to a file based on the specified file type.

    Parameters:
        data: The data to be written to the file.
        output_file_path (str): The path to the output file.

    Raises:
        ValueError: If the output file type is not supported.
    """
    output_file_type = os.path.splitext(output_file_path)[1].lower()
    with open(output_file_path, 'w', encoding='utf-8') as file:
        if output_file_type == '.json':
            json.dump(data, file, indent=4)
        elif output_file_type == '.txt':
            if isinstance(data, list):
                file.write('\n'.join(data))
            else:
                file.write(data)
        elif output_file_type == '.csv':
            writer = csv.writer(file)
            writer.writerows(data)
        else:
            raise ValueError(f"Unsupported output file type: {output_file_type}")


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

    content = read_file(file_path)

    data_chunk = []
    file_type = os.path.splitext(file_path)[1].lower()

    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        chunks = split_text_content(content, agent_config["chunk_config"])
        data_chunk,src_text = process_chunks(chunks, agent_config, agent_name)
    elif file_type == '.json':
        data_chunk,src_text = process_json_content(content, agent_config, agent_name)
    elif file_type in ('.csv', '.xlsx'):
        data_chunk,src_text = process_tabular_content(content, agent_config, agent_name)
    elif file_type == '.xml':
        data_chunk,src_text = process_xml_content(content, agent_config, agent_name)


    
    #--sorting out output target
    relative_path = os.path.relpath(file_path, base_directory)
    output_file_path = os.path.join(output_directory,
                                    relative_path.replace(os.path.splitext(file_path)[1], '.json'))
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    #--sorting out output source_text folder
    base_path = os.path.join(base_directory, "..")
    source_path = os.path.join(base_path, "source")
    output_src_path = os.path.join(source_path,
                                    relative_path.replace(os.path.splitext(file_path)[1], '.json'))
    
    os.makedirs(os.path.dirname(output_src_path), exist_ok=True)



    write_file(data_chunk, output_file_path)
    write_file(src_text, output_src_path)


def split_text_content(content, chunk_config=None):
    """
    Split the given text content into chunks based on the provided chunk configuration.

    Args:
        content (str): The text content.
        chunk_config (dict): The configuration for chunk size and overlap. Defaults to None.

    Returns:
        list: A list of text chunks.
    """
    if chunk_config is None:
        chunk_config = {}
    chunk_size = chunk_config.get('chunk_size', 300)
    chunk_overlap = chunk_config.get('chunk_overlap', 10)
    text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return text_splitter.split_text(content)

def process_chunks(chunks, agent_config, agent_name):
    """
    Process the given chunks and create dynamic agents for each chunk.

    Args:
        chunks (list): A list of text chunks.
        agent_config (dict): The configuration for the dynamic agents.
        agent_name (str): The name of the dynamic agents.

    Returns:
        list: A list of dynamic agents created from the chunks.
    """
    data_chunk = []
    for input_documentation in chunks:
        dynamic_agent,src_text = staging_dynamic_creator(
            agent_config, agent_name, input_documentation)
        data_chunk.extend(dynamic_agent)
    return data_chunk,src_text



def process_json_content(content, agent_config, agent_name):
    """
    Process JSON content and create dynamic agents for each value in the content.

    Args:
        content (list or dict): The JSON content to be processed.
        agent_config (dict): The configuration for the dynamic agents.
        agent_name (str): The name of the dynamic agents.

    Returns:
        list: A list of dynamic agents created from the JSON content.
    """
    data_chunk = []
    
    # Check if content is a list
    if isinstance(content, list):
        for obj in content:
            # Create a dynamic agent for each object in the list
            dynamic_agent,src_text = staging_dynamic_creator(agent_config, agent_name, obj)
            data_chunk.extend(dynamic_agent)
    
    # Check if content is a dictionary
    elif isinstance(content, dict):
        for value in content.values():
            if isinstance(value, list):
                for obj in value:
                    # Create a dynamic agent for each object in the list
                    dynamic_agent,src_text = staging_dynamic_creator(agent_config, agent_name, obj)
                    data_chunk.extend(dynamic_agent)
            else:
                # Create a dynamic agent for the entire dictionary content
                generated_content = staging_dynamic_creator(agent_config, agent_name, content)
                data_chunk.extend(generated_content)
    
    return data_chunk,src_text


def process_tabular_content(content, agent_config, agent_name):
    """
    Process tabular content and create dynamic agents for each row in the content.

    Args:
        content (list): The tabular content to be processed.
        agent_config (dict): The configuration for the dynamic agents.
        agent_name (str): The name of the dynamic agents.

    Returns:
        list: A list of dynamic agents created from the tabular content.
    """
    data_chunk = []
    
    # Iterate over each row in the content
    for row in content:
        # Create a dynamic agent for each row
        dynamic_agent,src_text = staging_dynamic_creator(agent_config, agent_name, row)
        data_chunk.extend(dynamic_agent)
    
    return data_chunk,src_text


def process_xml_content(content, agent_config, agent_name):
    """
    Process XML content and create dynamic agents for each element in the content.

    Args:
        content (tuple): The XML content to be processed.
        agent_config (dict): The configuration for the dynamic agents.
        agent_name (str): The name of the dynamic agents.

    Returns:
        list: A list of dynamic agents created from the XML content.
    """
    data_chunk = []
    _, root = content
    for element in root.findall('.//*'):
        if list(element):
            chunk_output,src_text = staging_dynamic_creator(agent_config, agent_name, process_xml_element(element))
            data_chunk.extend(chunk_output)
    return data_chunk,src_text


