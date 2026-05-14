"""Tests for batch_max_workers plumbing: schema → inheritance → resolver → factory.

Validates the full config path from YAML action-level batch_max_workers
through to OllamaBatchClient construction.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.output.response.config_fields import inherit_simple_fields


class TestSchemaAcceptsBatchMaxWorkers:
    """ActionConfig and DefaultsConfig accept batch_max_workers."""

    def test_action_config_accepts_batch_max_workers(self):
        config = ActionConfig.model_validate({"name": "a", "intent": "i", "batch_max_workers": 12})
        assert config.batch_max_workers == 12

    def test_action_config_batch_max_workers_survives_round_trip(self):
        config = ActionConfig.model_validate({"name": "a", "intent": "i", "batch_max_workers": 8})
        dumped = config.model_dump()
        assert dumped["batch_max_workers"] == 8

    def test_action_config_rejects_zero(self):
        with pytest.raises(ValidationError, match="batch_max_workers"):
            ActionConfig.model_validate({"name": "a", "intent": "i", "batch_max_workers": 0})

    def test_action_config_rejects_negative(self):
        with pytest.raises(ValidationError, match="batch_max_workers"):
            ActionConfig.model_validate({"name": "a", "intent": "i", "batch_max_workers": -1})

    def test_action_config_none_by_default(self):
        config = ActionConfig.model_validate({"name": "a", "intent": "i"})
        assert config.batch_max_workers is None

    def test_defaults_config_accepts_batch_max_workers(self):
        config = DefaultsConfig.model_validate({"batch_max_workers": 6})
        assert config.batch_max_workers == 6

    def test_defaults_config_rejects_zero(self):
        with pytest.raises(ValidationError, match="batch_max_workers"):
            DefaultsConfig.model_validate({"batch_max_workers": 0})


class TestInheritanceBatchMaxWorkers:
    """batch_max_workers inherits through SIMPLE_CONFIG_FIELDS."""

    def test_action_level_value_used(self):
        agent: dict = {}
        action = {"batch_max_workers": 12}
        defaults = {"batch_max_workers": 4}
        inherit_simple_fields(agent, action, defaults)
        assert agent["batch_max_workers"] == 12

    def test_inherits_from_defaults_when_action_omits(self):
        agent: dict = {}
        action = {}
        defaults = {"batch_max_workers": 4}
        inherit_simple_fields(agent, action, defaults)
        assert agent["batch_max_workers"] == 4

    def test_none_when_neither_set(self):
        agent: dict = {}
        inherit_simple_fields(agent, {}, {})
        assert agent["batch_max_workers"] is None


class TestResolverForwardsBatchMaxWorkers:
    """BatchClientResolver passes batch_max_workers to client_config."""

    def test_batch_max_workers_reaches_factory(self):
        agent_config = {
            "model_vendor": "ollama_local",
            "model_name": "llama2",
            "batch_max_workers": 12,
        }

        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.validate_config.return_value = (True, None)
            mock_factory.create_client.return_value = mock_client

            resolver = BatchClientResolver()
            resolver.get_for_config(agent_config)

            call_args = mock_factory.create_client.call_args
            client_config = call_args[0][1]
            assert client_config["batch_max_workers"] == 12

    def test_batch_max_workers_absent_when_none(self):
        agent_config = {
            "model_vendor": "ollama_local",
            "model_name": "llama2",
        }

        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.validate_config.return_value = (True, None)
            mock_factory.create_client.return_value = mock_client

            resolver = BatchClientResolver()
            resolver.get_for_config(agent_config)

            call_args = mock_factory.create_client.call_args
            client_config = call_args[0][1]
            assert "batch_max_workers" not in client_config
