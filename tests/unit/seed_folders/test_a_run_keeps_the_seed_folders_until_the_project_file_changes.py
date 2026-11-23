"""A run's records read the project file again only when a stat of it changes."""

import json
import shutil
from unittest.mock import patch

import pytest

from agent_actions.config import path_config
from agent_actions.config.path_config import record_seed_search_folders, seed_search_folders
from agent_actions.errors import ConfigurationError
from agent_actions.prompt.service import PromptPreparationService


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(path_config, "_record_candidates", {})


@pytest.fixture
def settled(monkeypatch):
    """Treat every project file as settled, so the folders it names are kept."""
    monkeypatch.setattr(path_config, "_RACY_WINDOW_NS", 0)


def _project(tmp_path, config: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_actions.yml").write_text(config)
    workflow = tmp_path / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    return workflow, str(workflow / "agent_config" / "wf.yml")


def _names(folders) -> list[str]:
    return [f.path.name for f in folders]


def _counting_loads():
    return patch.object(path_config, "load_project_config", wraps=path_config.load_project_config)


def test_an_unchanged_project_file_is_read_once_for_many_records(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_data\n")
    (workflow / "seed_data").mkdir()
    with _counting_loads() as loads:
        first = record_seed_search_folders(config_path)
        reads = loads.call_count
        for _ in range(5):
            assert record_seed_search_folders(config_path) == first
    assert reads > 0
    assert loads.call_count == reads


def test_an_edit_to_the_project_file_is_seen_by_the_next_record(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_a\n")
    for name, value in (("seed_a", 1), ("seed_bbbb", 2)):
        (workflow / name).mkdir()
        (workflow / name / "refs.json").write_text(json.dumps({"v": value}))
    agent_config = {"workflow_config_path": config_path}
    scope = {"seed": {"refs": "$file:refs.json"}}

    assert PromptPreparationService.load_seed_data(agent_config, scope, "act") == {
        "refs": {"v": 1}
    }
    (tmp_path / "agent_actions.yml").write_text("seed_data_path: seed_bbbb\n")
    assert PromptPreparationService.load_seed_data(agent_config, scope, "act") == {
        "refs": {"v": 2}
    }


def test_a_new_seed_folder_named_by_an_edit_is_seen_by_the_next_record(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_data\n")
    (workflow / "seed_data").mkdir()
    assert _names(record_seed_search_folders(config_path)) == ["seed_data"]

    (tmp_path / "shared").mkdir()
    (tmp_path / "agent_actions.yml").write_text(
        "seed_data_path: seed_data\nseed_data_paths: [shared]\n"
    )
    assert _names(record_seed_search_folders(config_path)) == ["seed_data", "shared"]


def test_a_seed_folder_made_without_an_edit_is_seen_by_the_next_record(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_data\n")
    (workflow / "seed_data").mkdir()
    assert _names(record_seed_search_folders(config_path)) == ["seed_data"]

    (tmp_path / "seed_data").mkdir()
    with _counting_loads() as loads:
        folders = record_seed_search_folders(config_path)
    assert [f.kind for f in folders] == ["workflow", "project"]
    assert loads.call_count == 0


def test_a_listed_folder_removed_without_an_edit_stops_the_next_record(tmp_path, settled):
    _, config_path = _project(tmp_path, "seed_data_paths: [shared]\n")
    (tmp_path / "shared").mkdir()
    assert _names(record_seed_search_folders(config_path)) == ["shared"]

    shutil.rmtree(tmp_path / "shared")
    with pytest.raises(ConfigurationError, match="folder 'shared' does not exist"):
        record_seed_search_folders(config_path)


def test_a_project_file_written_just_now_is_not_kept(tmp_path):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_aaa\n")
    for name in ("seed_aaa", "seed_bbb"):
        (workflow / name).mkdir()
    assert _names(record_seed_search_folders(config_path)) == ["seed_aaa"]

    # Same size, and likely the same mtime tick: only the racy window catches it.
    (tmp_path / "agent_actions.yml").write_text("seed_data_path: seed_bbb\n")
    assert _names(record_seed_search_folders(config_path)) == ["seed_bbb"]
    assert path_config._record_candidates == {}


def test_a_root_without_a_marker_file_is_not_kept(tmp_path, settled):
    workflow = tmp_path / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    config_path = str(workflow / "agent_config" / "wf.yml")

    assert _names(record_seed_search_folders(config_path)) == ["seed_data"]
    assert path_config._record_candidates == {}


def test_the_uncached_search_reads_the_project_file_every_time(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_data\n")
    (workflow / "seed_data").mkdir()
    record_seed_search_folders(config_path)
    with _counting_loads() as loads:
        seed_search_folders(config_path)
        seed_search_folders(config_path)
    assert loads.call_count >= 2


def test_two_workflows_in_one_process_each_get_their_own_folders(tmp_path, settled):
    first, first_config = _project(tmp_path / "one", "seed_data_path: seed_one\n")
    second, second_config = _project(tmp_path / "two", "seed_data_path: seed_two\n")
    (first / "seed_one").mkdir()
    (second / "seed_two").mkdir()

    for _ in range(2):
        assert _names(record_seed_search_folders(first_config)) == ["seed_one"]
        assert _names(record_seed_search_folders(second_config)) == ["seed_two"]


def test_presence_is_checked_on_every_record_not_only_the_first_after_a_change(tmp_path, settled):
    workflow, config_path = _project(tmp_path, "seed_data_path: seed_data\n")
    record_seed_search_folders(config_path)
    for _ in range(2):
        (workflow / "seed_data").mkdir()
        assert _names(record_seed_search_folders(config_path)) == ["seed_data"]
        (workflow / "seed_data").rmdir()
        assert record_seed_search_folders(config_path) == []


def test_a_listed_folder_swapped_for_a_symlink_outside_the_project_is_refused(tmp_path, settled):
    project = tmp_path / "project"
    _workflow, config_path = _project(project, "seed_data_paths: [shared]\n")
    (project / "shared").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _names(record_seed_search_folders(config_path)) == ["shared"]

    (project / "shared").rmdir()
    (project / "shared").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="outside the project"):
        record_seed_search_folders(config_path)
