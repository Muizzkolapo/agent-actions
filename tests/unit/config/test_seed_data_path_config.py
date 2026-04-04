"""Tests for get_seed_data_path configuration helper."""

import yaml

from agent_actions.config.path_config import get_seed_data_path


class TestGetSeedDataPath:
    """Tests for get_seed_data_path() — optional project config key."""

    def test_returns_default_when_no_config(self, tmp_path):
        """No agent_actions.yml → returns 'seed_data' default."""
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_returns_default_when_key_absent(self, tmp_path):
        """Config exists but has no seed_data_path key → returns default."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"schema_path": "schema"}))
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_returns_configured_value(self, tmp_path):
        """Config has seed_data_path → returns that value."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"seed_data_path": "reference_data"}))
        assert get_seed_data_path(tmp_path) == "reference_data"

    def test_returns_default_on_empty_config(self, tmp_path):
        """Empty YAML file → returns default."""
        (tmp_path / "agent_actions.yml").write_text("")
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_coerces_non_string_to_str(self, tmp_path):
        """Non-string value is coerced via str()."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"seed_data_path": 42}))
        assert get_seed_data_path(tmp_path) == "42"

    def test_rejects_path_traversal_dotdot(self, tmp_path):
        """Value containing '..' is rejected, returns default."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"seed_data_path": "../../../etc"}))
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_rejects_forward_slash(self, tmp_path):
        """Value containing '/' is rejected, returns default."""
        (tmp_path / "agent_actions.yml").write_text(
            yaml.dump({"seed_data_path": "some/nested/dir"})
        )
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_rejects_backslash(self, tmp_path):
        r"""Value containing '\\' is rejected, returns default."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"seed_data_path": "some\\dir"}))
        assert get_seed_data_path(tmp_path) == "seed_data"

    def test_standard_seed_data_value(self, tmp_path):
        """Standard seed_data_path: seed_data works."""
        (tmp_path / "agent_actions.yml").write_text(yaml.dump({"seed_data_path": "seed_data"}))
        assert get_seed_data_path(tmp_path) == "seed_data"
