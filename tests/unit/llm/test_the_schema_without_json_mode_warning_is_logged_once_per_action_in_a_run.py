"""The "json_mode=false but schema was compiled" warning: once per action in a run (#1932).

A text-mode action with a schema made one warning for each LLM call, so a run of 500
calls filled its log with it. Preflight warns of the same thing once per action.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.logging.core.manager import get_manager

WARNING = "json_mode=false but schema was compiled"
SCHEMA = {"type": "object", "properties": {"raw": {"type": "string"}}}


class TextClient(BaseClient):
    CAPABILITIES = {"json_mode": True}

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        return [{"content": "json"}]

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        return [{"content": "text"}]


@pytest.fixture(autouse=True)
def _a_run():
    """Each test is a new run: a run sets a new correlation id when it starts."""
    manager = get_manager()
    before = manager.get_context("correlation_id")
    manager.set_context(correlation_id=f"run-{uuid.uuid4().hex[:8]}")
    yield
    manager.set_context(correlation_id=before)


def _call(action: str, times: int = 1) -> None:
    config: dict[str, Any] = {"json_mode": False, "agent_type": action, "output_field": "raw"}
    with patch.object(BaseClient, "get_api_key", return_value="sk-test"):
        for _ in range(times):
            TextClient.invoke(config, "prompt", {}, SCHEMA)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if WARNING in r.getMessage()]


class TestTheWarningOncePerActionInARun:
    def test_ten_calls_of_one_action_warn_once(self, caplog):
        with caplog.at_level(logging.WARNING):
            _call("classify", times=10)

        assert len(_warnings(caplog)) == 1
        assert "'classify'" in _warnings(caplog)[0]

    def test_each_action_warns_once(self, caplog):
        with caplog.at_level(logging.WARNING):
            _call("classify", times=3)
            _call("summarize", times=3)

        assert len(_warnings(caplog)) == 2

    def test_a_new_run_warns_again(self, caplog):
        with caplog.at_level(logging.WARNING):
            _call("classify", times=2)
            get_manager().set_context(correlation_id=f"run-{uuid.uuid4().hex[:8]}")
            _call("classify", times=2)

        assert len(_warnings(caplog)) == 2
