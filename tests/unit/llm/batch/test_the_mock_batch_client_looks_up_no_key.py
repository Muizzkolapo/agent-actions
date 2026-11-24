"""The mock batch client is built with no key, even when the action names one.

A workflow sent to the mock, as a sandbox run sends it, keeps the `api_key` its
defaults name. The mock reads no key, so a variable that is not set is not an error.
A real vendor still needs its key.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient


def _config(vendor: str) -> dict:
    return {
        "agent_type": "summarize",
        "model_vendor": vendor,
        "model_name": "gpt-4o-mini",
        "api_key": "OPENAI_API_KEY",
    }


def test_the_mock_is_built_with_the_key_variable_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = BatchClientResolver(client_cache={}).get_for_config(_config("agac-provider"))

    assert isinstance(client, AgacBatchClient)


def test_a_real_vendor_still_needs_its_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        BatchClientResolver(client_cache={}).get_for_config(_config("openai"))
