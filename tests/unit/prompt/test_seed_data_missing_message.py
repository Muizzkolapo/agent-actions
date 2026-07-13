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
    def test_message_names_folder_and_seed_path_namespace(self, tmp_path):
        """Missing folder: message names the resolved folder AND the seed_path namespace knob."""
        config_path = _make_workflow(tmp_path, seed_data_path="reference_data")

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "reference_data" in msg  # the resolved folder it looked for
        assert "seed_path" in msg  # the context namespace is always seed_path
        assert "seed_data_path" in msg  # the folder-name knob, separate from the namespace

    def test_seed_path_folder_footgun_points_at_default_seed_data(self, tmp_path):
        """seed_data_path=seed_path while seed_data/ exists: hint that they confused namespace with folder."""
        config_path = _make_workflow(tmp_path, seed_data_path="seed_path", folders=("seed_data",))

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "already exists" in msg  # points them at the seed_data/ that holds the files
        assert "namespace" in msg.lower()

    def test_footgun_hint_absent_when_no_default_seed_data(self, tmp_path):
        """seed_data_path=seed_path but no seed_data/: base namespace note only, no false footgun hint."""
        config_path = _make_workflow(tmp_path, seed_data_path="seed_path")

        with pytest.raises(StaticDataLoadError) as excinfo:
            PromptPreparationService._determine_static_data_dir(config_path)

        msg = str(excinfo.value)
        assert "context namespace" in msg  # base clarification still present
        assert "already exists" not in msg  # footgun hint gated on the folder existing


class TestSeedDataHappyPath:
    def test_default_seed_data_folder_resolves(self, tmp_path):
        """Default config + seed_data/ present + seed_path namespace resolves without error."""
        config_path = _make_workflow(tmp_path, folders=("seed_data",))

        resolved = PromptPreparationService._determine_static_data_dir(config_path)

        assert resolved.name == "seed_data"
        assert resolved.is_dir()
