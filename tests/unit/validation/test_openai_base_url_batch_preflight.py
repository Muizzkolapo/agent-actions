"""Batch mode on an openai action with base_url is refused, not routed to OpenAI.

The OpenAI batch client speaks the OpenAI Batch API, which the
OpenAI-compatible local servers do not serve. Preflight must refuse the
combination by name, and the batch factory must never build a client that
drops the URL and submits the job to the default endpoint.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.batch_client_factory import _create_openai
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

LOCAL = "http://localhost:8080/v1"

REFUSAL = "Action 'classify_local': vendor 'openai' with base_url does not support run_mode: batch."


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _batch_errors(action_configs: dict) -> list:
    result = WorkflowResolutionService(action_configs=action_configs).resolve_all()
    return [e for e in result.errors if "batch" in e.message.lower()]


class TestPreflightRefusal:
    def test_batch_with_base_url_is_refused_by_name(self):
        errors = _batch_errors(
            {
                "classify_local": {
                    "model_vendor": "openai",
                    "model_name": "local",
                    "base_url": LOCAL,
                    "run_mode": "batch",
                }
            }
        )

        assert [e.message for e in errors] == [REFUSAL]
        assert errors[0].hint == "Set run_mode: online."
        assert errors[0].location.agent_name == "classify_local"
        assert errors[0].location.config_field == "run_mode"

    def test_batch_without_base_url_still_resolves(self):
        errors = _batch_errors(
            {
                "summarize_cloud": {
                    "model_vendor": "openai",
                    "model_name": "gpt-4o-mini",
                    "run_mode": "batch",
                }
            }
        )

        assert errors == []

    def test_online_with_base_url_is_allowed(self):
        errors = _batch_errors(
            {
                "classify_local": {
                    "model_vendor": "openai",
                    "model_name": "local",
                    "base_url": LOCAL,
                    "run_mode": "online",
                }
            }
        )

        assert errors == []

    def test_only_the_base_url_action_is_named_in_a_mixed_run(self):
        errors = _batch_errors(
            {
                "classify_local": {
                    "model_vendor": "openai",
                    "model_name": "local",
                    "base_url": LOCAL,
                    "run_mode": "batch",
                },
                "summarize_cloud": {
                    "model_vendor": "openai",
                    "model_name": "gpt-4o-mini",
                    "run_mode": "batch",
                },
            }
        )

        assert [e.location.agent_name for e in errors] == ["classify_local"]


class TestBatchFactoryRefusal:
    def test_factory_refuses_a_config_with_base_url(self):
        with pytest.raises(ConfigurationError) as excinfo:
            _create_openai({"api_key": "local-key", "base_url": LOCAL})

        assert LOCAL in str(excinfo.value)

    def test_factory_builds_the_batch_client_without_base_url(self):
        client = _create_openai({"api_key": "sk-cloud-key"})

        assert type(client).__name__ == "OpenAIBatchClient"
