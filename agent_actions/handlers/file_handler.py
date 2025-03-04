"""Module for staging data loading and processing."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from agent_actions.handlers.exceptions import (
    raise_file_type_error,
    raise_file_read_error,
    raise_file_write_error,
    raise_agent_folder_error,
    raise_config_file_error
)

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
            try:
                return file_type_handlers[self.file_type]()
            except Exception as e:
                raise_file_read_error(self.file_path, str(e))
        else:
            raise_file_type_error(self.file_type)

    def _read_json(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def _read_text(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            return file.read()

    def _read_csv(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            return list(reader)

    def _read_pdf(self):
        with open(self.file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
            return text

    def _read_xml(self):
        tree = ET.parse(self.file_path)
        root = tree.getroot()
        return tree, root

    def _read_docx(self):
        doc = Document(self.file_path)
        return '\n'.join([para.text for para in doc.paragraphs])

    def _read_xlsx(self):
        df = pd.read_excel(self.file_path)
        return df.to_dict(orient='records')

    def _read_html(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            return soup.get_text()

class FileWriter:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = os.path.splitext(file_path)[1].lower()

    def write_staging(self, data):
        try:
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
                    raise_file_type_error(self.file_type)
        except Exception as e:
            raise_file_write_error(self.file_path, str(e))

    def write_target(self, data):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            raise_file_write_error(self.file_path, str(e))

    def write_source(self, data):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)
        except Exception as e:
            raise_file_write_error(self.file_path, str(e))

class FileHandler:
    """
    A class for handling file and directory operations.
    """

    @staticmethod
    def find_file_in_directory(directory, target_filename):
        """
        Recursively searches for a file in a directory.

        Parameters:
            directory (str): The base directory to start the search from.
            target_filename (str): The name of the file to find.

        Returns:
            str or None: The full path to the file or None if not found.
        """
        for root, _, files in os.walk(directory):
            if target_filename in files:
                return os.path.join(root, target_filename)
        return None

    @staticmethod
    def find_specific_folder(current_dir, parent_folder_name, folder_name):
        """
        Search for a specific folder within a directory specified by the parent folder name.

        Parameters:
            current_dir (str): The base directory to start searching from.
            parent_folder_name (str): The folder under which the specific folder is expected.
            folder_name (str): The name of the specific folder to search for.

        Returns:
            str or None: The full path to the folder if found, otherwise None.
        """
        for root, dirs, _ in os.walk(current_dir):
            if parent_folder_name in dirs:
                target_folder_path = os.path.join(root, parent_folder_name, folder_name)
                if os.path.isdir(target_folder_path):
                    return target_folder_path
        return None

    @staticmethod
    def find_agent_folder(working_directory, folder_name, base_dir):
        """
        Searches for a specific folder within the base directory.

        Parameters:
            working_directory (str): The base directory to start searching from.
            folder_name (str): The name of the folder to search for.
            base_dir (str): The base directory name.

        Returns:
            str or None: The full path to the folder if found, otherwise None.
        """
        base_path = os.path.join(working_directory, base_dir)
        for root, dirs, _ in os.walk(base_path):
            if folder_name in dirs:
                return os.path.join(root, folder_name)
        return None

    @staticmethod
    def get_agent_paths(agent_name):
        """
        Returns the agent configuration directory, IO directory, and sample output path.

        Parameters:
            agent_name (str): The name of the agent.

        Returns:
            tuple: (agent_config_dir, io_dir, few_shot_samples_path)
        """
        current_dir = os.getcwd()
        agent_config_dir = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_config')
        io_dir = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')

        if agent_config_dir is None:
            raise_agent_folder_error(f"Configuration directory for agent '{agent_name}'")
        if io_dir is None:
            raise_agent_folder_error(f"IO directory for agent '{agent_name}'")

        few_shot_samples_path = os.path.join(io_dir, 'few_shot_samples')
        if not os.path.exists(few_shot_samples_path):
            few_shot_samples_path = None

        return agent_config_dir, io_dir, few_shot_samples_path

    @staticmethod
    def find_config_file(base_dir, filename):
        """
        Recursively searches for a configuration file in the base directory and its parents.

        Parameters:
            base_dir (str): The directory to start searching from.
            filename (str): The name of the configuration file.

        Returns:
            str or None: The path to the configuration file if found.
        """
        for root, _, files in os.walk(base_dir):
            if filename in files:
                return os.path.join(root, filename)

        parent_dir = os.path.dirname(base_dir)
        if parent_dir != base_dir:  # Ensure we're not at the root
            return FileHandler.find_config_file(parent_dir, filename)

        raise_config_file_error(filename, f"Config file not found in {base_dir} or its parent directories")

    @staticmethod
    def get_folder_after_agent_config(path):
        """
        Extracts the folder name immediately following 'agent_config' in a path.

        Parameters:
            path (str): The file path to analyze.

        Returns:
            str or None: The folder name following 'agent_config' or None if not found.
        """
        path_components = path.split(os.sep)

        if 'agent_config' in path_components:
            agent_config_index = path_components.index('agent_config')

            if agent_config_index + 1 == len(path_components) - 1 and os.path.isfile(path):
                return '(isfile)'

            if agent_config_index + 1 < len(path_components):
                return path_components[agent_config_index + 1]

        return None

    @staticmethod
    def get_folder(agent_name):
        """
        Gets the folder name and full path for an agent's configuration.

        Parameters:
            agent_name (str): The name of the agent.

        Returns:
            tuple: (folder_name, full_path) or (None, None) if not found.
        """
        agent_config_dir = os.path.join(os.getcwd(), 'agent_config')
        filename = f"{agent_name}.yml" if not agent_name.endswith(".yml") else agent_name
        full_path = FileHandler.find_config_file(agent_config_dir, filename)
        return FileHandler.get_folder_after_agent_config(full_path), full_path

    @staticmethod
    def get_all_agent_paths(base_dir):
        """
        Gets all agent configuration file paths within the base directory.

        Parameters:
            base_dir (str): The base directory to search in.

        Returns:
            list: A list of paths to agent configuration files.
        """
        agent_paths = []
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".yml"):
                    agent_paths.append(os.path.join(root, file))
        return agent_paths

    @staticmethod
    def get_file_info(file_path):
        """
        Gets information about a file in the staging directory.

        Parameters:
            file_path (str): The file path in the staging directory.

        Returns:
            str: The source file path or an error message.
        """
        if not os.path.exists(file_path):
            return f"File '{file_path}' does not exist."

        dir_path, file_name = os.path.split(file_path)
        agent_dir = os.path.dirname(dir_path)
        source_path = os.path.join(agent_dir, 'source')
        source_file_path = os.path.join(source_path, file_name)

        if os.path.exists(source_path):
            return source_file_path
        else:
            return None