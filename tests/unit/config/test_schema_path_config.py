"""Tests for get_schema_path configuration helper."""

import pytest
import yaml

from agent_actions.config.path_config import get_schema_path
from agent_actions.errors import ConfigValidationError


@pytest.mark.parametrize(
    ("config_text", "match"),
    [
        pytest.param(None, "schema_path", id="no_file"),
        pytest.param(yaml.dump({"tool_path": ["tools"]}), "schema_path", id="key_absent"),
        pytest.param("", "No agent_actions.yml", id="empty"),
    ],
)
def test_raises_without_schema_path(tmp_path, config_text, match):
    if config_text is not None:
        (tmp_path / "agent_actions.yml").write_text(config_text)
    with pytest.raises(ConfigValidationError, match=match):
        get_schema_path(tmp_path)


def test_returns_configured_value(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.dump({"schema_path": "custom_schemas"}))
    assert get_schema_path(tmp_path) == "custom_schemas"
