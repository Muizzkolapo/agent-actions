"""File reader for various file formats."""

import csv
import json
from pathlib import Path

import defusedxml.ElementTree as DefusedET  # type: ignore[import-untyped]
import pandas as pd
import pypdf
from bs4 import BeautifulSoup
from docx import Document

from agent_actions.errors import AgentActionsError
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin


class FileReader(ProcessorErrorHandlerMixin):
    """File reader for various file formats."""

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()

    def read(self):
        """Read file based on file type."""
        file_type_handlers = {
            ".json": self._read_json,
            ".txt": self._read_text,
            ".md": self._read_text,
            ".csv": self._read_csv,
            ".pdf": self._read_pdf,
            ".xml": self._read_xml,
            ".docx": self._read_docx,
            ".xlsx": self._read_xlsx,
            ".html": self._read_html,
        }
        if self.file_type in file_type_handlers:
            try:
                return file_type_handlers[self.file_type]()
            except FileNotFoundError as e:
                self.handle_file_error(e, "read", self.file_path, file_type=self.file_type)
                raise
            except OSError as e:
                self.handle_file_error(e, "read", self.file_path, file_type=self.file_type)
                raise
            except Exception as e:
                operation = f"Read file {self.file_path} (type: {self.file_type})"
                self.handle_processing_error(
                    e, operation, file_path=self.file_path, file_type=self.file_type
                )
                raise
        else:
            error_context = {
                "file_path": self.file_path,
                "file_type": self.file_type,
                "operation": "read",
            }
            raise AgentActionsError(
                f"Unsupported file type: {self.file_type}", context=error_context
            )

    def _read_json(self):
        with open(self.file_path, encoding="utf-8") as file:
            data = json.load(file)
            is_batch_placeholder = (
                isinstance(data, dict)
                and "batch_job_id" in data
                and data.get("status") == "submitted"
            )
            if is_batch_placeholder:
                error_msg = (
                    f"Cannot process batch placeholder file. "
                    f"Batch job {data['batch_job_id']} is still pending."
                )
                error_context = {
                    "file_path": self.file_path,
                    "batch_job_id": data["batch_job_id"],
                    "status": data.get("status"),
                    "operation": "read_json",
                }
                raise AgentActionsError(error_msg, context=error_context)
            return data

    def _read_text(self):
        with open(self.file_path, encoding="utf-8") as file:
            return file.read()

    def _read_csv(self):
        with open(self.file_path, encoding="utf-8") as file:
            reader = csv.reader(file)
            return list(reader)

    def _read_pdf(self):
        with open(self.file_path, "rb") as file:
            reader = pypdf.PdfReader(file)
            # Use join() instead of += for O(n) instead of O(n²)
            return "".join(page.extract_text() or "" for page in reader.pages)

    def _read_xml(self):
        tree = DefusedET.parse(self.file_path)
        root = tree.getroot()
        return (tree, root)

    def _read_docx(self):
        doc = Document(self.file_path)
        return "\n".join([para.text for para in doc.paragraphs])

    def _read_xlsx(self):
        df = pd.read_excel(self.file_path)
        return df.to_dict(orient="records")

    def _read_html(self):
        with open(self.file_path, encoding="utf-8") as file:
            soup = BeautifulSoup(file, "html.parser")
            return soup.get_text()
