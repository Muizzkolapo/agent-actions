"""Loaders module initialization."""
from agent_actions.processors.staging_processor.loaders.base_loader import BaseLoader
from agent_actions.processors.staging_processor.loaders.text_loader import TextLoader
from agent_actions.processors.staging_processor.loaders.json_loader import JsonLoader
from agent_actions.processors.staging_processor.loaders.tabular_loader import TabularLoader
from agent_actions.processors.staging_processor.loaders.xml_loader import XmlLoader

__all__ = [
    'BaseLoader',
    'TextLoader',
    'JsonLoader',
    'TabularLoader',
    'XmlLoader'
]