"""Seed-data resolution: happy path and the missing-folder error message."""

import pytest

from agent_actions.prompt.context.static_loader import StaticDataLoadError
from agent_actions.prompt.service import PromptPreparationService


def _make_workflow(tmp_path, *, seed_data_path=None, folders=()):
    """Build a workflow tree; return the config path passed to resolution."""
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    if seed_data_path is not None:
        (workflow / "agent_actions.yml").write_text(f"seed_data_path: {seed_data_path}\n")
    for folder in folders:
        (workflow / folder).mkdir()
    return str(workflow / "agent_config" / "wf.yml")


class TestMissingSeedDirMessage:
    def test_message_names_folder_and_seed_path_directive(self, tmp_path):
        """Missing folder: message names the resolved folder, the seed_data_path knob, and the seed_path directive."""
        config_path = _make_workflow(tmp_path, seed_data_path="reference_data")

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "reference_data" in msg  # the resolved folder it looked for
        assert "seed_path" in msg  # the context_scope directive, separate from the folder
        assert "seed_data_path" in msg  # the folder-name knob
        assert "context_scope" in msg  # frames seed_path as the directive, not a folder/namespace

    def test_message_does_not_imply_unset_seed_data_path(self, tmp_path):
        """Default folder (seed_data_path unset): message frames seed_data_path as an override, not a set key."""
        config_path = _make_workflow(tmp_path)  # no agent_actions.yml, no seed_data_path

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "seed_data_path" in msg  # the override knob is named
        assert "defaults to 'seed_data'" in msg  # framed as the default, not "currently set to"
        assert "currently" not in msg  # must not claim the user set a key they didn't

    def test_seed_path_folder_footgun_points_at_default_seed_data(self, tmp_path):
        """seed_data_path=seed_path while seed_data/ exists: hint they confused the directive with the folder."""
        config_path = _make_workflow(tmp_path, seed_data_path="seed_path", folders=("seed_data",))

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "already exists" in msg  # points them at the seed_data/ that holds the files
        assert "seed_data_path: seed_path" in msg  # the exact misconfig to remove
        assert "directive" in msg  # frames seed_path as a context_scope directive, not the folder

    def test_footgun_hint_absent_when_no_default_seed_data(self, tmp_path):
        """seed_data_path=seed_path but no seed_data/: base clarification only, no false footgun hint."""
        config_path = _make_workflow(tmp_path, seed_data_path="seed_path")

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "context_scope" in msg  # base clarification still present
        assert "already exists" not in msg  # footgun hint gated on the folder existing


class TestSeedDataHappyPath:
    def test_default_seed_data_folder_resolves_to_workflow_level_dir(self, tmp_path):
        """Default config + seed_data/ present resolves to the workflow-level seed_data folder."""
        config_path = _make_workflow(tmp_path, folders=("seed_data",))

        resolved = PromptPreparationService._determine_static_data_dir(config_path)

        assert resolved == (tmp_path / "workflow" / "seed_data").resolve()
        assert resolved.is_dir()
