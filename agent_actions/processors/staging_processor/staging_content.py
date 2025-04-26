"""Module for staging content loading and processing."""
import logging

# Import from our new modular structure
from agent_actions.processors.data_loaders.text_loader import TextLoader
from agent_actions.processors.data_loaders.json_loader import JsonLoader
from agent_actions.processors.data_loaders.tabular_loader import TabularLoader
from agent_actions.processors.data_loaders.xml_loader import XmlLoader

# Configure logger
logger = logging.getLogger(__name__)
from agent_actions.processors.staging_processor.staging_processor import StagingProcessor  

# Create a compatible StagingContentLoader that uses our modular components
class StagingContentLoader:
    """Loads and processes different types of content."""
    
    def __init__(self, agent_config, agent_name):
        """Initialize with agent configuration and name."""
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.prompt_processor = StagingProcessor(agent_config, agent_name)
        
        # Initialize loaders with proper dependencies
        self.text_loader = TextLoader(agent_config, agent_name, self.prompt_processor)
        self.json_loader = JsonLoader(agent_config, agent_name, self.prompt_processor)
        self.tabular_loader = TabularLoader(agent_config, agent_name, self.prompt_processor)
        self.xml_loader = XmlLoader(agent_config, agent_name, self.prompt_processor)
        
    # Keep the original method names and signatures for API compatibility
    def _process_chunks(self, chunks):
        """Process text chunks."""
        return self.text_loader.process(chunks)
        
    def _process_json_content(self, content, file_path=None):
        """Process JSON content."""
        return self.json_loader.process(content, file_path)
        
    def _process_tabular_content(self, content, agent_config=None, agent_name=None):
        """Process tabular content.
        
        Note: agent_config and agent_name are ignored since they're already 
        initialized in the constructor, but kept for API compatibility.
        """
        return self.tabular_loader.process(content)
        
    def _process_xml_content(self, content, agent_config=None, agent_name=None):
        """Process XML content.
        
        Note: agent_config and agent_name are ignored since they're already 
        initialized in the constructor, but kept for API compatibility.
        """
        return self.xml_loader.process(content)