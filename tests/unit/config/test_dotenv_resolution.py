"""Tests for .env resolution from project root.

Verifies that .env files are found when running from subdirectories or
worktrees — i.e. when CWD != project root.
"""

from agent_actions.config.environment import EnvironmentConfig
from agent_actions.config.manager import ConfigManager
from agent_actions.config.path_config import find_project_root_dir

# -- find_project_root_dir ---------------------------------------------------


class TestFindProjectRootDir:
    def test_finds_marker_from_subdirectory(self, tmp_path):
        (tmp_path / "agent_actions.yml").write_text("name: test")
        child = tmp_path / "sub" / "deep"
        child.mkdir(parents=True)

        assert find_project_root_dir(start=child) == tmp_path

    def test_finds_yaml_variant(self, tmp_path):
        (tmp_path / "agent_actions.yaml").write_text("name: test")
        assert find_project_root_dir(start=tmp_path) == tmp_path

    def test_finds_hidden_variant(self, tmp_path):
        (tmp_path / ".agent_actions.yml").write_text("name: test")
        assert find_project_root_dir(start=tmp_path) == tmp_path

    def test_fallback_agent_actions_dir(self, tmp_path):
        (tmp_path / "agent_actions").mkdir()
        assert find_project_root_dir(start=tmp_path) == tmp_path

    def test_fallback_agent_config_dir(self, tmp_path):
        (tmp_path / "agent_config").mkdir()
        assert find_project_root_dir(start=tmp_path) == tmp_path

    def test_fallback_disabled(self, tmp_path):
        (tmp_path / "agent_actions").mkdir()
        assert find_project_root_dir(start=tmp_path, use_fallback_heuristics=False) is None

    def test_custom_marker_file(self, tmp_path):
        (tmp_path / "custom.yml").write_text("name: test")
        assert find_project_root_dir(start=tmp_path, marker_file="custom.yml") == tmp_path

    def test_returns_none_when_no_marker(self, tmp_path):
        assert find_project_root_dir(start=tmp_path) is None

    def test_uses_cwd_when_start_is_none(self, tmp_path, monkeypatch):
        (tmp_path / "agent_actions.yml").write_text("name: test")
        monkeypatch.chdir(tmp_path)
        assert find_project_root_dir() == tmp_path


# -- EnvironmentConfig .env loading ------------------------------------------


def _clean_env(monkeypatch):
    """Remove env vars that would interfere with EnvironmentConfig defaults."""
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "DATABASE_URL",
        "AGENT_ACTIONS_ENV",
    ):
        monkeypatch.delenv(key, raising=False)


class TestEnvironmentConfigDotenv:
    def test_loads_env_file_from_explicit_path(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        env_file = tmp_path / ".env"
        env_file.write_text("AGENT_ACTIONS_ENV=staging\n")

        config = EnvironmentConfig(_env_file=env_file)
        assert config.agent_actions_env.value == "staging"

    def test_falls_back_to_env_vars_when_no_env_file(self, monkeypatch):
        _clean_env(monkeypatch)
        monkeypatch.setenv("AGENT_ACTIONS_ENV", "production")
        config = EnvironmentConfig()
        assert config.agent_actions_env.value == "production"

    def test_env_file_none_is_safe(self, monkeypatch):
        """EnvironmentConfig(_env_file=None) should not error."""
        _clean_env(monkeypatch)
        config = EnvironmentConfig(_env_file=None)
        assert config.agent_actions_env.value == "development"  # default


# -- ConfigManager._resolve_dotenv -------------------------------------------


class TestConfigManagerResolveDotenv:
    def test_resolves_dotenv_from_explicit_project_root(self, tmp_path, monkeypatch):
        _clean_env(monkeypatch)
        (tmp_path / "agent_actions.yml").write_text("name: test")
        (tmp_path / ".env").write_text("AGENT_ACTIONS_ENV=staging\n")

        mgr = ConfigManager(
            constructor_path=str(tmp_path / "dummy.yml"),
            default_path=str(tmp_path / "default.yml"),
            project_root=tmp_path,
        )
        env_file = mgr._resolve_dotenv()
        assert env_file is not None
        assert env_file.is_file()
        assert str(tmp_path) in str(env_file)

    def test_resolves_dotenv_via_find_project_root_dir(self, tmp_path, monkeypatch):
        """When project_root is None, _resolve_dotenv walks up from CWD."""
        _clean_env(monkeypatch)
        (tmp_path / "agent_actions.yml").write_text("name: test")
        (tmp_path / ".env").write_text("AGENT_ACTIONS_ENV=staging\n")

        nested = tmp_path / "sub" / "deep"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        mgr = ConfigManager(
            constructor_path=str(tmp_path / "dummy.yml"),
            default_path=str(tmp_path / "default.yml"),
        )
        env_file = mgr._resolve_dotenv()
        assert env_file is not None
        assert str(tmp_path) in str(env_file)

    def test_returns_none_when_no_dotenv(self, tmp_path):
        (tmp_path / "agent_actions.yml").write_text("name: test")
        # No .env file

        mgr = ConfigManager(
            constructor_path=str(tmp_path / "dummy.yml"),
            default_path=str(tmp_path / "default.yml"),
            project_root=tmp_path,
        )
        assert mgr._resolve_dotenv() is None

    def test_returns_none_when_no_project_root(self, tmp_path, monkeypatch):
        """No project root and no marker — returns None."""
        monkeypatch.chdir(tmp_path)
        mgr = ConfigManager(
            constructor_path=str(tmp_path / "dummy.yml"),
            default_path=str(tmp_path / "default.yml"),
        )
        assert mgr._resolve_dotenv() is None


# -- Integration: subdirectory scenario --------------------------------------


def test_dotenv_found_from_subdirectory(tmp_path, monkeypatch):
    """Simulates the worktree/subdirectory scenario end-to-end."""
    _clean_env(monkeypatch)

    # Set up project root with marker and .env
    (tmp_path / "agent_actions.yml").write_text("name: test")
    (tmp_path / ".env").write_text("AGENT_ACTIONS_ENV=staging\n")

    # CWD is a nested subdirectory (like a worktree)
    nested = tmp_path / "sub" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    # find_project_root_dir discovers the root
    root = find_project_root_dir()
    assert root == tmp_path

    # .env at that root is loadable via the _env_file parameter
    env_file = root / ".env"
    config = EnvironmentConfig(_env_file=env_file)
    assert config.agent_actions_env.value == "staging"
