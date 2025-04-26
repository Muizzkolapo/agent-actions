from typing import Any, Dict, List, Union


class ContentGenerator:
    """
    A class responsible for generating content using prompt processors and LLMs.
    """

    def __init__(self, prompt_processor: Any):
        self.prompt_processor = prompt_processor

    def generate_from_text(self, text: str) -> Union[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from a text input."""
        return self.prompt_processor.staging_dynamic_creator(text)

    def generate_from_json(self, json_data: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Union[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from JSON input."""
        if isinstance(json_data, dict):
            json_data = [json_data]  # Wrap dict into a list to ensure uniform processing
        return self.prompt_processor.staging_dynamic_creator(json_data)

    def generate_from_tabular(self, rows: List[Dict[str, Any]]) -> Union[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from tabular (CSV/TSV) input."""
        return self.prompt_processor.staging_dynamic_creator(rows)

    def generate_from_xml(self, xml_data: List[Dict[str, Any]]) -> Union[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Generate agent content from XML input."""
        return self.prompt_processor.staging_dynamic_creator(xml_data)
