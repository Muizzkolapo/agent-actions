"""Every name `chunk_config` accepts is written by the expander and read by the chunker.

Three lists have to agree — what the schema declares, what the expander copies,
what the reader looks up — and nothing else couples them. A name added to one of
them alone is accepted in YAML, shown by `agac inspect`, and silently replaced by
the hardcoded default at split time, which is the shape this surface already had.
"""

import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ChunkConfig, WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.input.preprocessing.staging.initial_pipeline import _chunk_settings
from agent_actions.output.response.expander_merge import CHUNK_SETTINGS

# A value distinct from every default, per declared type.
SENTINELS = {
    "chunk_size": 4242,
    "chunk_overlap": 77,
    "tokenizer_model": "p50k_base",
    "split_method": "chars",
}

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}


def _project_tree(project_agent_defaults, workflow_defaults=None):
    root = Path(tempfile.mkdtemp())
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump({"project_name": "p", "default_agent_config": project_agent_defaults})
    )
    config_dir = root / "agent_config"
    config_dir.mkdir()
    (config_dir / "w.yml").write_text(
        yaml.safe_dump(
            {
                "name": "w",
                "description": "d",
                "version": "1.0",
                "defaults": {"model_vendor": "openai", **(workflow_defaults or {})},
                "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
            }
        )
    )
    return root


def _manager(root):
    manager = ConfigManager(
        str(root / "agent_config" / "w.yml"), str(root / "agent_actions.yml"), project_root=root
    )
    manager.load_configs()
    manager.validate_agent_name()
    return manager


def test_the_schema_and_the_expander_name_the_same_settings():
    assert set(ChunkConfig.model_fields) == set(CHUNK_SETTINGS)


def test_every_name_the_schema_declares_has_a_sentinel_here():
    """Guard on the guard: a new field with no sentinel would skip the round-trip
    below rather than fail it."""
    assert set(SENTINELS) == set(ChunkConfig.model_fields)


@pytest.mark.parametrize("setting", sorted(ChunkConfig.model_fields))
def test_every_declared_name_changes_what_the_chunker_is_given(setting):
    """A declared name the reader never looks up leaves the split on its default."""
    baseline = _chunk_settings({"chunk_config": {}})

    configured = _chunk_settings({"chunk_config": {setting: SENTINELS[setting]}})

    assert configured != baseline, (
        f"chunk_config {setting}={SENTINELS[setting]!r} left the chunker on {baseline!r}"
    )
    assert SENTINELS[setting] in configured


@pytest.mark.parametrize("setting,value", [("chunk_size", 0), ("chunk_overlap", -5)])
@pytest.mark.parametrize("spelling", ["block", "loose"])
def test_defaults_level_settings_carry_the_same_range_as_an_action(setting, value, spelling):
    written = {"chunk_config": {setting: value}} if spelling == "block" else {setting: value}

    with pytest.raises(ValidationError):
        WorkflowConfig.model_validate(
            {
                "name": "wf",
                "description": "d",
                "version": "1.0",
                "defaults": {**BASE_DEFAULTS, **written},
                "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
            }
        )


def test_the_project_block_beats_a_loose_key_written_beside_it():
    """The same within-level rule the workflow and action blocks follow."""
    root = Path(tempfile.mkdtemp())
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump(
            {
                "project_name": "p",
                "default_agent_config": {
                    "api_key": "k",
                    "model_name": "gpt-4",
                    "chunk_config": {"chunk_size": 4000, "chunk_overlap": 500},
                    "chunk_overlap": 10,
                },
            }
        )
    )
    config_dir = root / "agent_config"
    config_dir.mkdir()
    (config_dir / "w.yml").write_text(
        yaml.safe_dump(
            {
                "name": "w",
                "description": "d",
                "version": "1.0",
                "defaults": {"model_vendor": "openai"},
                "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
            }
        )
    )
    manager = ConfigManager(
        str(config_dir / "w.yml"), str(root / "agent_actions.yml"), project_root=root
    )
    manager.load_configs()
    manager.validate_agent_name()
    manager.merge_agent_configs(manager.get_user_agents())

    agent = manager.agent_configs["a1"].model_dump()

    assert _chunk_settings(agent)[1] == 500


def test_a_project_block_key_the_schema_refuses_names_the_replacement():
    root = Path(tempfile.mkdtemp())
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump(
            {
                "project_name": "p",
                "default_agent_config": {
                    "api_key": "k",
                    "model_name": "gpt-4",
                    "chunk_config": {"overlap": 500},
                },
            }
        )
    )
    config_dir = root / "agent_config"
    config_dir.mkdir()
    (config_dir / "w.yml").write_text(
        yaml.safe_dump(
            {
                "name": "w",
                "description": "d",
                "version": "1.0",
                "defaults": {"model_vendor": "openai"},
                "actions": [{"name": "a1", "intent": "i", "prompt": "p"}],
            }
        )
    )
    manager = ConfigManager(
        str(config_dir / "w.yml"), str(root / "agent_actions.yml"), project_root=root
    )
    manager.load_configs()
    manager.validate_agent_name()

    with pytest.raises(ConfigurationError) as exc:
        manager.get_user_agents()

    assert "did you mean 'chunk_overlap'?" in str(exc.value)


def test_a_retired_spelling_beside_the_project_block_is_refused_too():
    """`default_agent_config` allows extras, so the one place `overlap:` is
    actually written in the wild is the one place it could still be swallowed."""
    root = _project_tree(
        {"api_key": "k", "model_name": "gpt-4", "chunk_size": 4000, "overlap": 500}
    )
    manager = _manager(root)

    with pytest.raises(ConfigurationError) as exc:
        manager.get_user_agents()

    assert "did you mean 'chunk_overlap'?" in str(exc.value)


def test_an_overlap_at_or_above_the_chunk_size_is_refused_at_load():
    """Merging by name lets a nearer chunk_size pair with an outer overlap, a
    combination the splitter rejects. Both values are known at load, so the run
    should not get partway in before finding out."""
    root = _project_tree(
        {
            "api_key": "k",
            "model_name": "gpt-4",
            "chunk_config": {"chunk_size": 4000, "chunk_overlap": 500},
        },
        workflow_defaults={"chunk_size": 300},
    )
    manager = _manager(root)

    with pytest.raises(ConfigurationError) as exc:
        manager.get_user_agents()

    message = str(exc.value)
    assert "chunk_overlap" in message and "chunk_size" in message
