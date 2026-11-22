"""Each read of the project file sees it as it is now, and gets a config of its own."""

import json
from unittest.mock import patch

import pytest

from agent_actions.config.path_config import load_project_config, seed_search_folders
from agent_actions.errors import ConfigValidationError
from agent_actions.logging.events import ConfigLoadEvent, ConfigLoadStartEvent
from agent_actions.prompt.service import PromptPreparationService


def test_an_edit_is_read_on_the_next_load(tmp_path):
    config_file = tmp_path / "agent_actions.yml"
    config_file.write_text("seed_data_path: seed_aaa\n")
    assert load_project_config(tmp_path) == {"seed_data_path": "seed_aaa"}

    config_file.write_text("seed_data_path: seed_bbb\n")
    assert load_project_config(tmp_path) == {"seed_data_path": "seed_bbb"}

    config_file.write_text("seed_data_path: seed_ccccc\nschema_path: schema\n")
    assert load_project_config(tmp_path) == {
        "seed_data_path": "seed_ccccc",
        "schema_path": "schema",
    }


def test_a_change_to_the_loaded_config_does_not_reach_the_next_load(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("nested:\n  keys: [1, 2]\n")
    first = load_project_config(tmp_path)
    first["nested"]["keys"].append(3)
    first["added"] = True

    assert load_project_config(tmp_path) == {"nested": {"keys": [1, 2]}}


def test_invalid_yaml_is_refused_with_the_file_named_on_every_load(tmp_path):
    config_file = tmp_path / "agent_actions.yml"
    config_file.write_text("a: [1\nb: 2\n")
    messages = []
    for _ in range(2):
        with pytest.raises(ConfigValidationError) as raised:
            load_project_config(tmp_path)
        messages.append(str(raised.value.__cause__))
    assert messages[0] == messages[1]
    assert str(config_file) in messages[0]


def test_every_load_reports_the_file_it_loads(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    events: list = []
    with patch("agent_actions.config.path_config.fire_event", side_effect=events.append):
        load_project_config(tmp_path)
        load_project_config(tmp_path)
    assert [type(e) for e in events] == [
        ConfigLoadStartEvent,
        ConfigLoadEvent,
        ConfigLoadStartEvent,
        ConfigLoadEvent,
    ]


def test_a_new_seed_folder_named_in_the_project_file_is_read_by_the_next_record(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("seed_data_path: seed_aaa\n")
    workflow = tmp_path / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    for name, value in (("seed_aaa", 1), ("seed_bbb", 2)):
        (workflow / name).mkdir()
        (workflow / name / "refs.json").write_text(json.dumps({"v": value}))
    agent_config = {"workflow_config_path": str(workflow / "agent_config" / "wf.yml")}
    scope = {"seed": {"refs": "$file:refs.json"}}

    def load() -> dict:
        return PromptPreparationService.load_seed_data(agent_config, scope, "act")

    assert load() == {"refs": {"v": 1}}
    (tmp_path / "agent_actions.yml").write_text("seed_data_path: seed_bbb\n")
    assert load() == {"refs": {"v": 2}}
    assert [f.path.name for f in seed_search_folders(agent_config["workflow_config_path"])] == [
        "seed_bbb"
    ]
