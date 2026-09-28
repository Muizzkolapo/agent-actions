"""A project-file key with no reader is reported, and nothing ships declaring one."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import yaml

from agent_actions.config.manager import ConfigManager

_REPO = Path(__file__).resolve().parents[3]
_REFERENCE = _REPO / "docs.agent-actions" / "docs" / "reference" / "configuration" / "index.md"

_WORKFLOW = (
    "name: workflow\ndescription: d\nversion: '1.0'\n"
    "actions:\n  - name: extract\n    intent: extract data\n    kind: llm\n"
)

# Every top-level key of agent_actions.yml that a reader takes today.
_READ_KEYS = {
    "schema_path": "schema",
    "tool_path": ["tools"],
    "seed_data_path": "seed_data",
    "required_by_default": False,
    "project_name": "p",
    "default_agent_config": {"model_name": "gpt-4o-mini"},
}

_UNREAD = {"output_storage": {"backend": "sqlite", "db_path": "./agent_io/outputs.db"}}


def _manager(tmp_path: Path) -> ConfigManager:
    cfg = tmp_path / "workflow.yml"
    cfg.write_text(_WORKFLOW)
    default = tmp_path / "default.yml"
    default.write_text("{}")
    (tmp_path / "templates").mkdir()
    manager = ConfigManager(str(cfg), str(default), project_root=tmp_path)
    manager.load_configs()
    return manager


def _load_against(tmp_path: Path, project_config: dict) -> None:
    """Load a workflow whose project file is *project_config*, the way a run does."""
    manager = _manager(tmp_path)
    with (
        patch("agent_actions.config.manager.PathManager") as path_manager,
        patch(
            "agent_actions.config.manager.load_project_config",
            return_value=project_config,
        ),
        patch(
            "agent_actions.output.response.expander.ActionExpander.expand_actions_to_agents",
            return_value={"workflow": [{"agent_type": "extract"}]},
        ),
    ):
        path_manager.return_value.get_project_root.return_value = tmp_path
        manager.get_user_agents()


class TestLoadingReportsTheUnreadKey:
    def test_the_key_is_named(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_UNREAD))

        assert "output_storage" in caplog.text

    def test_the_report_gives_the_path_a_run_writes_instead(self, tmp_path, caplog):
        """The documented db_path is not the convention, so naming the key is not enough."""
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_UNREAD))

        assert "agent_io/store" in caplog.text

    def test_the_key_is_reported_beside_keys_that_are_read(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, {**_READ_KEYS, **_UNREAD})

        assert "output_storage" in caplog.text


class TestAKeyWithAReaderIsNotReported:
    def test_every_read_key_together_reports_no_unread_key(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_READ_KEYS))

        assert "is not read" not in caplog.text

    def test_an_absent_project_file_reports_no_unread_key(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, {})

        assert "is not read" not in caplog.text


class TestNothingShipsDeclaringIt:
    def test_no_example_project_declares_the_unread_key(self):
        declared = {
            str(path.relative_to(_REPO))
            for path in sorted(_REPO.glob("examples/*/agent_actions.yml"))
            if "output_storage" in (yaml.safe_load(path.read_text()) or {})
        }

        assert declared == set()

    def test_the_configuration_reference_does_not_document_it(self):
        assert "output_storage" not in _REFERENCE.read_text()
