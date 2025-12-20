"""Module for generating content using prompt processors and LLMs."""
from typing import Any, Dict, List, Union, Optional, Tuple


class ContentGenerator:
    """
    A class responsible for generating content using prompt processors and LLMs.
    """

    def __init__(self, prompt_processor: Any):
        self.prompt_processor = prompt_processor

    def _generate_multiple(
        self, items: List[Any], source_path: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Helper to generate content and source text for each item individually."""
        data_chunk = []
        src_text = []
        for item in items:
            dynamic_agent, src_collection = (
                self.prompt_processor.staging_dynamic_creator(
                    item, source_path=source_path
                )
            )
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)
        return data_chunk, src_text

    def generate_from_text(
        self, text: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from a text input."""
        return self._generate_multiple([text])

    def generate_from_json(
        self, json_data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content for each JSON object individually."""
        if isinstance(json_data, dict):
            json_data = [json_data]
        return self._generate_multiple(json_data)

    def generate_from_tabular(
        self, rows: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from tabular (CSV/TSV) input."""
        return self._generate_multiple(rows)

    def generate_from_xml(
        self, xml_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from XML input."""
        return self._generate_multiple(xml_data)
