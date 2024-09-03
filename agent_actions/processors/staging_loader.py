"""Module for staging data loading and processing."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup

import itertools


from agent_actions.models import agent_builder
from agent_actions.core.utils import transform_structure
from agent_actions.core.utils import generate_id
from agent_actions.core.agent_handlers import split_text_content










def get_file_info(file_path):
    # Check if the file exists
    if not os.path.exists(file_path):
        return f"File '{file_path}' does not exist."

    # Extract the directory and file name from the file path
    dir_path, file_name = os.path.split(file_path)

    # Extract the path up to the 'summary_agent' directory
    summary_agent_dir = os.path.dirname(dir_path)

    # Define the source path as '/source' at the same level as 'staging'
    source_path = os.path.join(summary_agent_dir, 'source')

    # Join the file name with the source path
    source_file_path = os.path.join(source_path, file_name)

    # Check if the source path exists
    if os.path.exists(source_path):
        return source_file_path
    else:
        return None



def staging_dynamic_creator(agent_config, agent_name, input_documentation, source_path=None, formatted_prompt=None):
    """
    Create a dynamic agent for processing input documentation.

    Parameters:
        agent_config (dict): Configuration for the agent.
        agent_name (str): Name of the agent.
        input_documentation (str): Documentation or input data to be processed.
        source_path (str, optional): Path to the source data file.
        formatted_prompt (str, optional): Optional formatted prompt.

    Returns:
        tuple: Transformed response and source text.
    """
    # If source_path is provided, attempt to load the source data
    if source_path is not None and "guid" in input_documentation and "content" in input_documentation:
       with open(source_path, 'r') as file:
        source_data = json.load(file)
        for item in source_data:
            guid_key = list(item.keys())[0]
        # Check if the loaded data has the required structure
            if guid_key == input_documentation["guid"]:                
                input_documentation_new = input_documentation["content"]
                response = agent_builder.create_dynamic_agent(agent_config, agent_name, input_documentation_new)
                transformed_response_temp = [{guid_key: response}]
                transformed_response = transform_structure(transformed_response_temp)
                src_text = [item]
                return transformed_response,src_text

      
        
            elif guid_key != input_documentation["guid"] or guid_key not in input_documentation:
                input_documentation_new = input_documentation["content"]
                # This block handles the scenario where source_path is None or keys are missing
                response = agent_builder.create_dynamic_agent(agent_config, agent_name, input_documentation_new)
                guid = input_documentation["guid"]
                transformed_response_temp = [{guid: response}]
                transformed_response = transform_structure(transformed_response_temp)
                src_text = [{guid: input_documentation_new}]
                return transformed_response, src_text
                
    else:
        # This block handles the scenario where source_path is None or keys are missing
        response = agent_builder.create_dynamic_agent(agent_config, agent_name, input_documentation)
        guid = generate_id()
        transformed_response_temp = [{guid: response}]
        transformed_response = transform_structure(transformed_response_temp)
        src_text = [{guid: input_documentation}]

        return transformed_response, src_text



    



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

    file_type = os.path.splitext(file_path)[1].lower()

    if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
        chunks = split_text_content(content, agent_config["chunk_config"])
        data_chunk,src_text = process_chunks(chunks, agent_config, agent_name)
    elif file_type == '.json':
        data_chunk,src_text = process_json_content(content, agent_config, agent_name,file_path)
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
    write_source_file(src_text, output_src_path)


def write_source_file(content, file_path):
    """
    Writes content to a file, appending it if it doesn't already exist.

    Parameters:
        content: The content to be written to the file.
        file_path (str): The path to the file.
    """
    # If the file exists, load its current contents
    if os.path.exists(file_path):
        # Read the existing content
        with open(file_path, 'r') as file:
            try:
                existing_content = json.load(file)
            except json.JSONDecodeError:
                existing_content = []

        # Ensure existing content is a list
        if not isinstance(existing_content, list):
            existing_content = [existing_content]

        # Flatten the existing content to a set of unique IDs for quick lookup
        existing_ids = set()
        for item in existing_content:
            if isinstance(item, dict):
                existing_ids.update(item.keys())

        # Check if each content item already exists
        new_content = []
        for item in content:
            if isinstance(item, list):  # Handle list of items in content
                for sub_item in item:
                    if isinstance(sub_item, dict) and not set(sub_item.keys()).intersection(existing_ids):
                        new_content.append(sub_item)
            elif isinstance(item, dict) and not set(item.keys()).intersection(existing_ids):
                new_content.append(item)

        # Append new content if there are any new entries
        if new_content:
            existing_content.extend(new_content)

    else:
        # If file does not exist, start a new list with content
        existing_content = content if isinstance(content, list) else [content]

    # Write back to the file if there were any changes
    with open(file_path, 'w') as file:
        json.dump(existing_content, file, indent=4)




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
    src_text = []
    for input_documentation in chunks:
        dynamic_agent,src_collection = staging_dynamic_creator(
            agent_config, agent_name, input_documentation)
        data_chunk.extend(dynamic_agent)
        src_text.extend(src_collection)
    return data_chunk,src_text



def process_json_content(content, agent_config, agent_name,file_path):
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
    src_text = []
    src_legacy_path = get_file_info(file_path)
    
    # Check if content is a list
    if isinstance(content, list):
        for obj in content:
            # Create a dynamic agent for each object in the list
            dynamic_agent,src_collection = staging_dynamic_creator(agent_config, agent_name, obj,src_legacy_path)
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)
    
    # Check if content is a dictionary
    elif isinstance(content, dict):
        for value in content.values():
            if isinstance(value, list):
                for obj in value:
                    # Create a dynamic agent for each object in the list
                    dynamic_agent,src_collection = staging_dynamic_creator(agent_config, agent_name, obj)
                    data_chunk.extend(dynamic_agent)
                    src_text.extend(src_collection)
            else:
                # Create a dynamic agent for the entire dictionary content
                generated_content,src_collection  = staging_dynamic_creator(agent_config, agent_name, content)
                data_chunk.extend(generated_content)
                src_text.extend(src_collection)
    
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
    src_text = []
    
    # Iterate over each row in the content
    for row in content:
        # Create a dynamic agent for each row
        dynamic_agent,src_collection = staging_dynamic_creator(agent_config, agent_name, row)
        data_chunk.extend(dynamic_agent)
        src_text.extend(src_collection)
    
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
    src_text = []
    _, root = content
    for element in root.findall('.//*'):
        if list(element):
            chunk_output,src_collection = staging_dynamic_creator(agent_config, agent_name, process_xml_element(element))
            data_chunk.extend(chunk_output)
            src_text.extend(src_collection)
    return data_chunk,src_text


