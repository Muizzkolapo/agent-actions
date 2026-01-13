"""Module for generating content using prompt processors and LLMs.

This module uses RecordProcessor for unified processing with retry support.
"""

from typing import Any, Dict, List, Union, Optional, Tuple

from agent_actions.core.record_processor import RecordProcessor
from agent_actions.core.result_adapters import ProcessingResultAdapter
from agent_actions.core.types import ProcessingContext, ProcessingMode


class ContentGenerator:
    """
    A class responsible for generating content using prompt processors and LLMs.

    Uses RecordProcessor internally for unified processing with retry support.
    """

    def __init__(
        self,
        agent_config: Dict[str, Any],
        agent_name: str,
    ):
        """
        Initialize ContentGenerator.

        Args:
            agent_config: Agent configuration dictionary
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

        # Create RecordProcessor for unified processing with retry
        self._record_processor = RecordProcessor(
            agent_config=self.agent_config,
            agent_name=self.agent_name,
        )

    def _generate_multiple(
        self, items: List[Any], source_path: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Generate content and source text for each item via RecordProcessor.

        Args:
            items: List of items to process (text, dict, etc.)
            source_path: Optional source path for context

        Returns:
            Tuple of (data_chunk, src_text) for compatibility with staging pipeline
        """
        # Build context for first-stage processing
        context = ProcessingContext(
            agent_config=self.agent_config,
            agent_name=self.agent_name,
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
            file_path=source_path,
        )

        # Process all items via RecordProcessor (has retry support)
        results = self._record_processor.process_batch(items, context)

        # Convert to legacy tuple format for backward compatibility
        return ProcessingResultAdapter.to_staging_tuple(results)

    def generate_from_text(self, text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
