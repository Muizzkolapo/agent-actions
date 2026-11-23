"""A workflow in the older format is held to the `batch_preparation_concurrency` rule too.

That format skips the workflow schema, and the coordinator reads the key as written. An
unchecked `"2"` reached `asyncio.Semaphore("2")` and failed there with a TypeError.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError

AGENT = {"agent_type": "label_page", "model_vendor": "openai", "model_name": "gpt-4o"}


def _load(value: Any) -> list[dict]:
    manager = ConfigManager("wf.yml", "")
    manager.user_config = {"wf": [dict(AGENT)], "batch_preparation_concurrency": value}
    manager.agent_name = "wf"
    return manager.get_user_agents()


@pytest.mark.parametrize("value", ["2", 0, 51, True, 1.5])
def test_a_value_the_schema_refuses_is_refused(value):
    with pytest.raises(ConfigurationError, match="Workflow configuration is invalid") as refused:
        _load(value)

    (error,) = refused.value.context["validation_errors"]
    assert error["field"] == "batch_preparation_concurrency"


@pytest.mark.parametrize("value", [1, 2, 50, None])
def test_a_value_the_schema_takes_loads(value):
    (agent,) = _load(value)

    assert agent["agent_type"] == "label_page"
