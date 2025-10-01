"""Module for reading data loading and processing."""
import json
import csv
import xml.etree.ElementTree as ET
import PyPDF2
from docx import Document
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path

from agent_actions.core.exceptions import FileLoadError as AgentFileNotFoundError, AgentActionsException
from agent_actions.core.safe_format import safe_format_error
class FileReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()

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
            except FileNotFoundError:
                raise AgentFileNotFoundError(f"File not found: {self.file_path}")
            except IOError as e:
                raise AgentActionsException(
                    f"IOError reading file {self.file_path}: {safe_format_error(e)}",
                    context={'file_path': self.file_path, 'file_type': self.file_type, 'operation': 'read'},
                    cause=e
                ) from e
            except Exception as e:
                # Catch other specific parsing errors if possible, e.g., PyPDF2.errors.PdfReadError
                raise AgentActionsException(
                    f"Error reading file {self.file_path} (type: {self.file_type}): {safe_format_error(e)}",
                    context={'file_path': self.file_path, 'file_type': self.file_type, 'operation': 'read'},
                    cause=e
                ) from e
        else:
            raise AgentActionsException(f"Unsupported file type: {self.file_type} for file {self.file_path}")

    def _read_json(self):
        with open(self.file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
            # Check if this is a batch placeholder file
            if isinstance(data, dict) and 'batch_job_id' in data and data.get('status') == 'submitted':
                raise AgentActionsException(
                    f"Cannot process batch placeholder file: {self.file_path}. "
                    f"Batch job {data['batch_job_id']} is still pending. "
                    "Please wait for batch processing to complete."
                )
            
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