"""Module for staging content loading and processing."""
import logging
from agent_actions.input_loading.text_loader import TextLoader
from agent_actions.input_loading.json_loader import JsonLoader
from agent_actions.input_loading.tabular_loader import TabularLoader
from agent_actions.input_loading.xml_loader import XmlLoader
from agent_actions.prompt_generation.content_generator import ContentGenerator
logger = logging.getLogger(__name__)
from .staging_processor import StagingProcessor
import asyncio

class StagingContentLoader:
    """Loads and processes different types of content."""

    def __init__(self, agent_config, agent_name):
        """Initialize with agent configuration and name."""
        self.prompt_processor = StagingProcessor(agent_config, agent_name)
        self.content_generator = ContentGenerator(self.prompt_processor)
        self.text_loader = TextLoader(agent_config, agent_name)
        self.json_loader = JsonLoader(agent_config, agent_name)
        self.tabular_loader = TabularLoader(agent_config, agent_name)
        self.xml_loader = XmlLoader(agent_config, agent_name)

    async def _process_chunks_async(self, chunks):
        """Async: Process text chunks in parallel."""

        async def process_one(chunk):
            return await asyncio.to_thread(self.text_loader.process, chunk)
        results = await asyncio.gather(*(process_one(chunk) for chunk in chunks))
        return self.content_generator.generate_from_text(results)

    def _process_chunks(self, chunks):
        """Process text chunks."""
        content = self.text_loader.process(chunks)
        return self.content_generator.generate_from_text(content)

    async def _process_json_content_async(self, content, file_path=None):
        """Async: Process JSON content in parallel."""

        async def process_one(item):
            return await asyncio.to_thread(self.json_loader.process, item, file_path)
        results = await asyncio.gather(*(process_one(item) for item in content))
        return self.content_generator.generate_from_json(results)

    def _apply_field_chunking_if_enabled(self, processed_content, agent_config=None):
        """Apply field chunking if enabled and return processed content."""
        from agent_actions.preprocessing.field_chunking import FieldAnalyzer, FieldChunker
        from agent_actions.utilities.constants import CHUNK_CONFIG_KEY
        import json
        import uuid
        if agent_config is None:
            agent_config = getattr(self.prompt_processor, 'agent_config', {})
        chunk_config = agent_config.get(CHUNK_CONFIG_KEY, {})
        field_chunking_config = chunk_config.get('field_chunking', {})
        if field_chunking_config.get('enabled') and isinstance(processed_content, list):
            field_chunker = FieldChunker(chunk_config)
            field_analyzer = FieldAnalyzer(chunk_config)
            chunked_content = []
            for idx, record in enumerate(processed_content):
                analysis = field_analyzer.analyze_record(record)
                if analysis.requires_chunking:
                    chunked_records = field_chunker.chunk_record(record, analysis)
                    for chunk_idx, chunk_record in enumerate(chunked_records):
                        chunk_record.update({'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(chunk_record, sort_keys=True))), 'target_id': str(uuid.uuid4()), 'record_index': idx, 'chunk_index': chunk_idx})
                        chunked_content.append(chunk_record)
                else:
                    record.update({'source_guid': str(uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(record, sort_keys=True))), 'target_id': str(uuid.uuid4()), 'record_index': idx})
                    chunked_content.append(record)
            return chunked_content
        return processed_content

    def _process_json_content(self, content, file_path=None):
        """Process JSON content with field chunking support."""
        processed_content = self.json_loader.process(content, file_path)
        chunked_content = self._apply_field_chunking_if_enabled(processed_content)
        return self.content_generator.generate_from_json(chunked_content)

    async def _process_tabular_content_async(self, content, agent_config=None, agent_name=None):
        """Async: Process tabular content in parallel."""

        async def process_one(item):
            return await asyncio.to_thread(self.tabular_loader.process, item)
        results = await asyncio.gather(*(process_one(item) for item in content))
        return self.content_generator.generate_from_tabular(results)

    def _process_tabular_content(self, content, agent_config=None, agent_name=None):
        """Process tabular content with field chunking support."""
        processed_content = self.tabular_loader.process(content)
        chunked_content = self._apply_field_chunking_if_enabled(processed_content, agent_config)
        return self.content_generator.generate_from_tabular(chunked_content)

    async def _process_xml_content_async(self, content, agent_config=None, agent_name=None):
        """Async: Process XML content in parallel."""

        async def process_one(item):
            return await asyncio.to_thread(self.xml_loader.process, item)
        results = await asyncio.gather(*(process_one(item) for item in content))
        return self.content_generator.generate_from_xml(results)

    def _process_xml_content(self, content, agent_config=None, agent_name=None):
        """Process XML content with field chunking support."""
        processed_content = self.xml_loader.process(content)
        chunked_content = self._apply_field_chunking_if_enabled(processed_content, agent_config)
        return self.content_generator.generate_from_xml(chunked_content)