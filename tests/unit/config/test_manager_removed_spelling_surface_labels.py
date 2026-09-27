"""The refusal names the surface the key was written on (1065).

Both surfaces raise the same sentence, so the substring the other tests match on
passes even if the two labels are swapped — which would send a reader to the
wrong file, the thing naming the surface exists to prevent.
"""

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError


def _manager(project_block: dict | None = None) -> ConfigManager:
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config = {"default_agent_config": project_block or {}}
    cm.tool_path = None
    cm.agent_configs = {}
    return cm


def test_project_block_refusal_names_the_project_block():
    cm = _manager({"depends_on": ["ghost"]})

    with pytest.raises(ConfigurationError) as excinfo:
        cm.merge_agent_configs([{"agent_type": "consumer", "chunk_config": {}}])

    assert str(excinfo.value).startswith("default_agent_config")
    # No agent to name: the block belongs to the project file, not to one agent.
    assert "agent_type" not in excinfo.value.context


def test_agent_refusal_names_the_agent_and_carries_its_type():
    cm = _manager()

    with pytest.raises(ConfigurationError) as excinfo:
        cm.merge_agent_configs(
            [{"agent_type": "consumer", "depends_on": ["ghost"], "chunk_config": {}}]
        )

    assert str(excinfo.value).startswith("Agent configuration")
    assert excinfo.value.context["agent_type"] == "consumer"
