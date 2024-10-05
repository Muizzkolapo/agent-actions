"""Module for staging data loading and processing."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from agent_actions.models import agent_builder
from agent_actions.core.utils import transform_structure
from agent_actions.core.utils import generate_id
from agent_actions.core.agent_handlers import load_few_shot_samples,get_file_info
import random
from agent_actions.core.utils import find_specific_folder,get_agent_paths
import logging
logger = logging.getLogger(__name__)













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


    # Load the sample output path using get_agent_paths
    _, _, few_shot_samples_path = get_agent_paths(agent_name)

    # Retrieve the sample count from the agent configuration
    sample_count = agent_config.get("use_few_shot_samples", 0)
    try:
        sample_count = int(sample_count)
    except ValueError:
        logger.warning("use_few_shot_samples is not an integer. Defaulting to 0.")
        sample_count = 0

    # Check if sample_count is a positive integer
    if sample_count > 0:
        logger.info(f"Loading {sample_count} few shot samples.")
        samples = load_few_shot_samples(
            few_shot_samples_path,
            agent_type=agent_config['agent_type'],
            sample_count=sample_count
        )
        # Since input_documentation is a string, append samples to it
        samples_str = "\n\n".join(json.dumps(sample, indent=2) for sample in samples)
        input_documentation += "\n\nfew shot samples:\n" + samples_str
    else:
        logger.info("Not using few shot samples.")



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



    



class FileReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = os.path.splitext(file_path)[1].lower()

    def read(self):
        file_type_handlers = {
            '.json': self._read_json,
            '.txt': self._read_text,
            '.md': self._read_text,
            '.csv': self._read_csv,
            '.pdf': self._read_pdf,
            '.xml': self._read_xml,
            '.docx': self._read_docx,
            '.xlsx': self._read_xlsx,
            '.html': self._read_html,
        }

        if self.file_type in file_type_handlers:
            with open(self.file_path, 'r', encoding='utf-8') as file:
                return file_type_handlers[self.file_type](file)
        else:
            raise ValueError(f"Unsupported file type: {self.file_type}")

    def _read_json(self, file):
        return json.load(file)

    def _read_text(self, file):
        return file.read()

    def _read_csv(self, file):
        reader = csv.reader(file)
        return list(reader)

    def _read_pdf(self, file):
        reader = PyPDF2.PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text

    def _read_xml(self, file):
        tree = ET.parse(file)
        root = tree.getroot()
        return tree, root

    def _read_docx(self, file_path):
        doc = Document(file_path)
        return '\n'.join([para.text for para in doc.paragraphs])

    def _read_xlsx(self, file):
        df = pd.read_excel(file)
        return df.to_dict(orient='records')

    def _read_html(self, file):
        soup = BeautifulSoup(file, 'html.parser')
        return soup.get_text()


class FileWriter:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = os.path.splitext(file_path)[1].lower()

    def write(self, data):
        with open(self.file_path, 'w', encoding='utf-8') as file:
            if self.file_type == '.json':
                json.dump(data, file, indent=4)
            elif self.file_type == '.txt':
                if isinstance(data, list):
                    file.write('\n'.join(data))
                else:
                    file.write(data)
            elif self.file_type == '.csv':
                writer = csv.writer(file)
                writer.writerows(data)
            else:
                raise ValueError(f"Unsupported output file type: {self.file_type}")


class ContentProcessor:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def process(self, content, file_type):
        if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
            return self._process_chunks(content)
        elif file_type == '.json':
            return self._process_json_content(content)
        elif file_type in ('.csv', '.xlsx'):
            return self._process_tabular_content(content)
        elif file_type == '.xml':
            return self._process_xml_content(content)

    def _process_chunks(self, chunks):
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
            dynamic_agent, src_collection = staging_dynamic_creator(
                self.agent_config, self.agent_name, input_documentation)
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)
        return data_chunk, src_text



    def _process_json_content(content, agent_config, agent_name,file_path):
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


    def _process_tabular_content(content, agent_config, agent_name):
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


    def _process_xml_content(content, agent_config, agent_name):
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

    content_processor = ContentProcessor(agent_config, agent_name)
    data_chunk, src_text = content_processor.process(content, file_reader.file_type)

    relative_path = os.path.relpath(file_path, base_directory)
    output_file_path = os.path.join(output_directory, relative_path.replace(file_reader.file_type, '.json'))
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    file_writer = FileWriter(output_file_path)
    file_writer.write(data_chunk)

    base_path = os.path.join(base_directory, "..")
    source_path = os.path.join(base_path, "source")
    output_src_path = os.path.join(source_path, relative_path.replace(file_reader.file_type, '.json'))
    os.makedirs(os.path.dirname(output_src_path), exist_ok=True)

    source_file_writer = FileWriter(output_src_path)
    source_file_writer.write(src_text)


