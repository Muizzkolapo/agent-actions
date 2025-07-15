"""Module for staging content loading and processing."""
import logging

# Import from our new modular structure
from agent_actions.processors.data_loaders.text_loader import TextLoader
from agent_actions.processors.data_loaders.json_loader import JsonLoader
from agent_actions.processors.data_loaders.tabular_loader import TabularLoader
from agent_actions.processors.data_loaders.xml_loader import XmlLoader
from agent_actions.processors.content_generators.content_generator import ContentGenerator

# Configure logger
logger = logging.getLogger(__name__)
from agent_actions.processors.staging_processor.staging_processor import StagingProcessor  

# Create a compatible StagingContentLoader that uses our modular components
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
        
    # Keep the original method names and signatures for API compatibility
    async def _process_chunks_async(self, chunks):
        """Async: Process text chunks in parallel."""
        async def process_one(chunk):
            return await asyncio.to_thread(self.text_loader.process, chunk)
        results = await asyncio.gather(*(process_one(chunk) for chunk in chunks))
        # Flatten results if needed
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

    def _process_json_content(self, content, file_path=None):
        """Process JSON content."""
        content = self.json_loader.process(content, file_path)
        return self.content_generator.generate_from_json(content)
        
    async def _process_tabular_content_async(self, content, agent_config=None, agent_name=None):
        """Async: Process tabular content in parallel."""
        async def process_one(item):
            return await asyncio.to_thread(self.tabular_loader.process, item)
        results = await asyncio.gather(*(process_one(item) for item in content))
        return self.content_generator.generate_from_tabular(results)

    def _process_tabular_content(self, content, agent_config=None, agent_name=None):
        """Process tabular content."""
        content = self.tabular_loader.process(content)
        return self.content_generator.generate_from_tabular(content)
        
    async def _process_xml_content_async(self, content, agent_config=None, agent_name=None):
        """Async: Process XML content in parallel."""
        async def process_one(item):
            return await asyncio.to_thread(self.xml_loader.process, item)
        results = await asyncio.gather(*(process_one(item) for item in content))
        return self.content_generator.generate_from_xml(results)

    def _process_xml_content(self, content, agent_config=None, agent_name=None):
        """Process XML content."""
        content = self.xml_loader.process(content)
        return self.content_generator.generate_from_xml(content)