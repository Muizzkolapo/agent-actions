"""
Agac Provider - Mock LLM for Testing.

A deterministic mock LLM provider that generates fake responses based on
JSON schemas. Useful for testing without real API calls.

Usage:
    from agent_actions.llm.providers.agac import (
        AgacClient,
        AgacBatchClient,
        FakeDataGenerator,
    )
"""

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator

__all__ = [
    "AgacClient",
    "AgacBatchClient",
    "FakeDataGenerator",
]
