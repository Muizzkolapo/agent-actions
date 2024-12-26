"""Module for file handling operations."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from agent_actions.exceptions import (
    raise_file_processing_error,
    raise_file_type_error
)

class FileHandler:
    @staticmethod
    def find_specific_folder(base_dir, folder_name, parent_folder):
        """Find a specific folder within the project structure."""
        for root, dirs, _ in os.walk(base_dir):
            if parent_folder in dirs and folder_name in os.listdir(os.path.join(root, parent_folder)):
                return os.path.join(root, parent_folder, folder_name)
        return None

    @staticmethod
    def get_agent_paths(agent_name):
        current_dir = os.getcwd()
        agent_folder = FileHandler.find_specific_folder(current_dir, agent_name, 'agent_io')
        
        if not agent_folder:
            raise_file_processing_error(agent_name, "Agent folder not found")
            
        staging_path = os.path.join(agent_folder, 'staging')
        source_path = os.path.join(agent_folder, 'source')
        few_shot_samples_path = os.path.join(agent_folder, 'few_shot_samples')
        
        return staging_path, source_path, few_shot_samples_path

class FileReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = os.path.splitext(file_path)[1].lower()

    def read(self):
        try:
            if self.file_type == '.json':
                return self._read_json()
            elif self.file_type == '.csv':
                return self._read_csv()
            elif self.file_type == '.xml':
                return self._read_xml()
            elif self.file_type == '.pdf':
                return self._read_pdf()
            elif self.file_type == '.docx':
                return self._read_docx()
            elif self.file_type in ['.txt', '.md']:
                return self._read_text()
            else:
                raise_file_type_error(self.file_type)
        except Exception as e:
            raise_file_processing_error(self.file_path, str(e))

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
        # Document() takes the file path directly
        doc = Document(self.file_path)
        return '\n'.join([para.text for para in doc.paragraphs])

    def _read_xlsx(self):
        # Pandas can read Excel files directly from the file path
        df = pd.read_excel(self.file_path)
        return df.to_dict(orient='records')

    def _read_html(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            return soup.get_text()