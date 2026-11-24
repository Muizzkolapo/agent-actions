"""`default_agent_config:` refuses a key that no `defaults:` block takes.

The project block is merged under each workflow's `defaults:`, so it takes the same
keys. A key outside that set used to load and reach every agent unread.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import (
    ConfigManager,
    project_action_defaults,
    project_agent_config,
)
from agent_actions.config.schema import DefaultsConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.config_schema import DefaultAgentConfig

REPO = Path(__file__).resolve().parents[3]

BASE = {"api_key": "OPENAI_API_KEY", "model_name": "gpt-4o-mini"}

# Each key the configuration pages show in `default_agent_config:`, or say it takes.
DOCUMENTED = {
    "api_key": "OPENAI_API_KEY",
    "model_name": "gpt-4o-mini",
    "model_vendor": "openai",
    "chunk_config": {"chunk_size": 4000, "chunk_overlap": 500, "split_method": "tiktoken"},
    "chunk_size": 4000,
    "chunk_overlap": 500,
    "split_method": "chars",
    "tokenizer_model": "cl100k_base",
    "record_concurrency": 4,
    "request_timeout": 120,
    "context_window": 200000,
    "vendor_params": {"seed": 7},
    "expect": {"repair": "auto"},
    "prompt_debug": False,
    "is_operational": True,
    "run_mode": "online",
    "json_mode": True,
    "granularity": "record",
    "temperature": 0.3,
    "enable_prompt_caching": True,
}


def _message(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return "; ".join(error["msg"] for error in caught.value.errors())


class TestAnUndeclaredKeyIsRefused:
    def test_the_model_refuses_it_and_lists_the_keys_it_takes(self):
        with pytest.raises(ValidationError) as caught:
            DefaultAgentConfig.model_validate({**BASE, "few_shot": 3})

        message = _message(caught)
        assert "unknown default_agent_config key 'few_shot'" in message
        assert (
            "valid default_agent_config keys are " + ", ".join(sorted(DefaultsConfig.model_fields))
            in message
        )

    def test_a_near_miss_names_the_key_it_resembles(self):
        with pytest.raises(ValidationError) as caught:
            DefaultAgentConfig.model_validate({**BASE, "model_nmae": "gpt-4"})

        assert "did you mean 'model_name'?" in _message(caught)

    def test_the_agent_merge_refuses_it(self):
        with pytest.raises(
            ConfigurationError, match="unknown default_agent_config key 'few_shot'"
        ):
            project_agent_config({"default_agent_config": {**BASE, "few_shot": 3}})

    def test_the_workflow_defaults_merge_refuses_it(self):
        """The first reader of the block, so the refusal lands before the expander runs."""
        with pytest.raises(
            ConfigurationError, match="unknown default_agent_config key 'few_shot'"
        ):
            project_action_defaults({"default_agent_config": {**BASE, "few_shot": 3}})

    def test_the_real_load_path_refuses_it(self, tmp_path):
        manager = _project(tmp_path, {**BASE, "model_vendor": "openai", "few_shot": 3})

        with pytest.raises(ConfigurationError, match="unknown default_agent_config key"):
            manager.merge_agent_configs(manager.get_user_agents())


class TestEveryDocumentedKeyStillLoads:
    @pytest.mark.parametrize("key", sorted(DOCUMENTED))
    def test_the_key_loads_on_both_readers(self, key):
        project = {"default_agent_config": {**BASE, key: DOCUMENTED[key]}}

        project_action_defaults(project)
        project_agent_config(project)

    def test_the_block_takes_what_a_defaults_block_takes(self):
        """The block sits under each workflow's `defaults:`, so the two sets match."""
        assert set(DOCUMENTED) <= set(DefaultsConfig.model_fields)

    def test_a_project_default_still_reaches_every_agent(self, tmp_path):
        """Asserted on a setting the workflow does not also carry."""
        manager = _project(tmp_path, {**BASE, "model_vendor": "openai", "temperature": 0.42})

        manager.merge_agent_configs(manager.get_user_agents())

        assert manager.agent_configs["a1"].model_dump()["temperature"] == 0.42


class TestEveryShippedProjectStillLoads:
    def _project_files(self) -> list[Path]:
        files = sorted(REPO.glob("examples/*/agent_actions.yml"))
        files += sorted(REPO.glob("tests/integration/fixtures/*/agent_actions.yml"))
        files += [REPO / "tests/fixtures/project_configs/basic_project.yml"]
        return files

    def test_each_block_loads_on_both_readers(self):
        files = self._project_files()
        assert len(files) > 3, files

        for path in files:
            project = yaml.safe_load(path.read_text()) or {}
            project_action_defaults(project)
            project_agent_config(project)

    def test_the_block_agac_init_writes_loads(self, tmp_path):
        from agent_actions.config.init import ProjectInitializer

        ProjectInitializer("p", tmp_path).init_project()
        project = yaml.safe_load((tmp_path / "p" / "agent_actions.yml").read_text())

        project_action_defaults(project)
        project_agent_config(project)


def _project(tmp_path: Path, agent_defaults: dict) -> ConfigManager:
    (tmp_path / "agent_actions.yml").write_text(
        yaml.safe_dump({"project_name": "p", "default_agent_config": agent_defaults})
    )
    config_dir = tmp_path / "agent_config"
    config_dir.mkdir()
    (config_dir / "wf.yml").write_text(
        yaml.safe_dump(
            {
                "name": "wf",
                "description": "d",
                "version": "1.0",
                "defaults": {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"},
                "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
            }
        )
    )
    manager = ConfigManager(
        str(config_dir / "wf.yml"), str(tmp_path / "agent_actions.yml"), project_root=tmp_path
    )
    manager.load_configs()
    manager.validate_agent_name()
    return manager
