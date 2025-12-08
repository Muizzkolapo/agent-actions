"""Module for reading data loading and processing."""
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from agent_actions.errors import AgentActionsException  # New modular pattern!
from agent_actions.utilities.processor.error_handling import ProcessorErrorHandlerMixin

class FileReader(ProcessorErrorHandlerMixin):

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()

    def read(self):
        file_type_handlers = {'.json': self._read_json, '.txt': self._read_text, '.md': self._read_text, '.csv': self._read_csv, '.pdf': self._read_pdf, '.xml': self._read_xml, '.docx': self._read_docx, '.xlsx': self._read_xlsx, '.html': self._read_html}
        if self.file_type in file_type_handlers:
            try:
                return file_type_handlers[self.file_type]()
            except FileNotFoundError as e:
                self.handle_file_error(e, 'read', self.file_path, file_type=self.file_type)
            except IOError as e:
                self.handle_file_error(e, 'read', self.file_path, file_type=self.file_type)
            except Exception as e:
                self.handle_processing_error(e, f'Read file {self.file_path} (type: {self.file_type})', file_path=self.file_path, file_type=self.file_type)
        else:
            raise AgentActionsException(f'Unsupported file type: {self.file_type}', context={'file_path': self.file_path, 'file_type': self.file_type, 'operation': 'read'})

    def _read_json(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            if isinstance(data, dict) and 'batch_job_id' in data and (data.get('status') == 'submitted'):
                raise AgentActionsException(f"Cannot process batch placeholder file. Batch job {data['batch_job_id']} is still pending.", context={'file_path': self.file_path, 'batch_job_id': data['batch_job_id'], 'status': data.get('status'), 'operation': 'read_json'})
            return data

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
            text = ''
            for page in reader.pages:
                text += page.extract_text()
            return text

    def _read_xml(self):
        tree = ET.parse(self.file_path)
        root = tree.getroot()
        return (tree, root)

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