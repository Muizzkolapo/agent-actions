
"""Module for staging data loading and processing."""
import os
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
import logging
logger = logging.getLogger(__name__)
    



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

    def write_staging(self, data):
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


    def write_target(self, data):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)

    def write_source(self, data):
        with open(self.file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)