"""Tests for get_seed_data_path configuration helper."""

import pytest
import yaml

from agent_actions.config.path_config import get_seed_data_path


@pytest.mark.parametrize(
    ("config_text", "expected"),
    [
        pytest.param(None, "seed_data", id="no_file"),
        pytest.param(yaml.dump({"schema_path": "schema"}), "seed_data", id="key_absent"),
        pytest.param(
            yaml.dump({"seed_data_path": "reference_data"}), "reference_data", id="configured"
        ),
        pytest.param("", "seed_data", id="empty"),
        # non-string value is coerced via str()
        pytest.param(yaml.dump({"seed_data_path": 42}), "42", id="int_coerced"),
        # a value with '..', '/' or '\\' is rejected and the default comes back
        pytest.param(yaml.dump({"seed_data_path": "../../../etc"}), "seed_data", id="dotdot"),
        pytest.param(yaml.dump({"seed_data_path": "some/nested/dir"}), "seed_data", id="slash"),
        pytest.param(yaml.dump({"seed_data_path": "some\\dir"}), "seed_data", id="backslash"),
    ],
)
def test_get_seed_data_path(tmp_path, config_text, expected):
    if config_text is not None:
        (tmp_path / "agent_actions.yml").write_text(config_text)
    assert get_seed_data_path(tmp_path) == expected
