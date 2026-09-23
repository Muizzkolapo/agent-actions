"""A configured chunk setting reaches the chunker, or the load refuses the key.

Asserted on the arguments the tokenizer is called with, because every layer above
it — the YAML, the agent dict, `agac inspect` — shows the value that was asked
for whether or not the chunker ever saw it.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_online_data,
    _prepare_text_chunks_batch,
)
from agent_actions.output.response.expander import ActionExpander

SETTINGS = {
    "chunk_size": 999,
    "chunk_overlap": 200,
    "tokenizer_model": "spacy",
    "split_method": "spacy",
}

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}


def _tokenizer_call(agent_config, mode):
    """Return the kwargs-and-positionals the tokenizer was called with."""
    target = (
        "agent_actions.input.preprocessing.staging.initial_pipeline.Tokenizer.split_text_content"
    )
    with patch(target, return_value=["chunk"]) as split:
        if mode == "batch":
            _prepare_text_chunks_batch("some text", agent_config, "b1", "n1")
        else:
            _prepare_online_data(
                DataPreparationContext(
                    content="some text",
                    file_type=".txt",
                    agent_config=agent_config,
                    file_path="f.txt",
                    agent_name="a1",
                )
            )
    assert split.call_count == 1
    args, kwargs = split.call_args
    return {
        "chunk_size": args[1],
        "chunk_overlap": args[2],
        "tokenizer_model": kwargs["tokenizer_model"],
        "split_method": kwargs["split_method"],
    }


@pytest.mark.parametrize("setting", sorted(SETTINGS))
@pytest.mark.parametrize("mode", ["batch", "online"])
def test_a_setting_written_in_chunk_config_reaches_the_chunker(setting, mode):
    value = SETTINGS[setting]

    seen = _tokenizer_call({"chunk_config": {setting: value}}, mode)

    assert seen[setting] == value, (
        f"{mode}: chunk_config {setting}={value!r} never reached the chunker, "
        f"which was called with {seen[setting]!r}"
    )


@pytest.mark.parametrize("mode", ["batch", "online"])
def test_every_setting_together_reaches_the_chunker(mode):
    """One key landing correctly is what hides the rest: a workflow that sets
    several sees the first take effect and assumes the others did."""
    written = dict(SETTINGS)

    seen = _tokenizer_call({"chunk_config": written}, mode)

    assert seen == written


@pytest.mark.parametrize("level", ["defaults", "action"])
def test_a_top_level_chunk_overlap_reaches_the_chunker(level):
    """The documented top-level spelling, carried through the real expansion."""
    written = {"chunk_size": 999, "chunk_overlap": 25}
    action = {"name": "a1", "intent": "i", "prompt": "p"}
    defaults = dict(BASE_DEFAULTS)
    (defaults if level == "defaults" else action).update(written)

    workflow = WorkflowConfig.model_validate(
        {
            "name": "wf",
            "description": "d",
            "version": "1.0",
            "defaults": defaults,
            "actions": [action],
        }
    )
    agent = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [
                a.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for a in workflow.actions
            ],
            "defaults": workflow.defaults.model_dump(
                mode="python", exclude_unset=True, by_alias=True
            ),
        }
    )["wf"][0]

    assert _tokenizer_call(agent, "batch")["chunk_overlap"] == 25


def _expand(defaults_extra, action_extra=None):
    """Validate and expand, the way ConfigManager.get_user_agents does."""
    action = {"name": "a1", "intent": "i", "prompt": "p", **(action_extra or {})}
    workflow = WorkflowConfig.model_validate(
        {
            "name": "wf",
            "description": "d",
            "version": "1.0",
            "defaults": {**BASE_DEFAULTS, **defaults_extra},
            "actions": [action],
        }
    )
    return ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [
                a.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for a in workflow.actions
            ],
            "defaults": workflow.defaults.model_dump(
                mode="python", exclude_unset=True, by_alias=True
            ),
        }
    )["wf"][0]


@pytest.mark.parametrize("setting", ["tokenizer_model", "split_method"])
def test_a_defaults_level_tokenizer_setting_reaches_the_chunker(setting):
    """`defaults:` declares both, and inheritance puts them on the agent — but the
    chunker reads them out of chunk_config, which they never enter."""
    value = SETTINGS[setting]

    agent = _expand({setting: value})

    assert _tokenizer_call(agent, "batch")[setting] == value, (
        f"defaults {setting}={value!r} is on the agent as "
        f"{agent.get(setting)!r} and still never reached the chunker"
    )


@pytest.mark.parametrize("level", ["defaults", "action"])
def test_the_retired_overlap_spelling_is_refused_not_ignored(level):
    """`overlap` is what the chunker's own parameter is called, so it is the
    spelling a reader reaches for. Accepting it and reading `chunk_overlap`
    is how a configured value goes missing."""
    written = {"chunk_config": {"chunk_size": 999, "overlap": 500}}
    action = {"name": "a1", "intent": "i", "prompt": "p"}
    defaults = dict(BASE_DEFAULTS)
    (defaults if level == "defaults" else action).update(written)

    with pytest.raises(ValidationError) as exc:
        WorkflowConfig.model_validate(
            {
                "name": "wf",
                "description": "d",
                "version": "1.0",
                "defaults": defaults,
                "actions": [action],
            }
        )

    message = str(exc.value)
    assert "overlap" in message
    assert "chunk_overlap" in message


@pytest.mark.parametrize("setting", sorted(SETTINGS))
def test_the_project_files_chunk_config_reaches_the_chunker(setting):
    """`default_agent_config:` in agent_actions.yml is merged into every agent and
    validated by a model that allows extras. It is where the retired spelling is
    actually written, so a rename that skips this surface trades one silence for
    another."""
    root = Path(tempfile.mkdtemp())
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump(
            {
                "project_name": "p",
                "default_agent_config": {
                    "api_key": "k",
                    "model_name": "gpt-4",
                    "chunk_config": {setting: SETTINGS[setting]},
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

    assert _tokenizer_call(agent, "batch")[setting] == SETTINGS[setting]


def test_the_project_files_retired_spelling_is_refused_not_ignored():
    """The one spelling found in a real project. Refusing it is what keeps the
    rename from silently halving somebody's overlap."""
    root = Path(tempfile.mkdtemp())
    (root / "agent_actions.yml").write_text(
        yaml.safe_dump(
            {
                "project_name": "p",
                "default_agent_config": {
                    "api_key": "k",
                    "model_name": "gpt-4",
                    "chunk_config": {"chunk_size": 4000, "overlap": 500},
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

    with pytest.raises((ConfigurationError, ValidationError)) as exc:
        manager.merge_agent_configs(manager.get_user_agents())

    message = str(exc.value)
    assert "overlap" in message
    assert "chunk_overlap" in message
