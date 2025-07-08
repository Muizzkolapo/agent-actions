"""Loaders module initialization."""

from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.processors.data_loaders.batch_data_loader import BatchDataLoader
from agent_actions.processors.data_loaders.text_loader import TextLoader
from agent_actions.processors.data_loaders.json_loader import JsonLoader
from agent_actions.processors.data_loaders.tabular_loader import TabularLoader
from agent_actions.processors.data_loaders.xml_loader import XmlLoader

__all__ = [
    "BaseLoader",
    "BatchDataLoader",
    "TextLoader",
    "JsonLoader",
    "TabularLoader",
    "XmlLoader",
]
