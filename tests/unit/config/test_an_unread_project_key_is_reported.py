"""A project-file key with no reader is reported, and nothing ships declaring one."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.storage import get_storage_backend

_REPO = Path(__file__).resolve().parents[3]
_DOCS = _REPO / "docs.agent-actions" / "docs"

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


def _reported_keys(caplog) -> set[str]:
    """The keys the load named, read off the record rather than out of its wording.

    Asserting on the message text would make the report's prose load-bearing: reword it
    and every negative assertion here passes on any behaviour at all.
    """
    return {
        record.args[0]
        for record in caplog.records
        if record.funcName == "warn_unread_project_keys" and record.args
    }


class TestLoadingReportsTheUnreadKey:
    def test_the_key_is_named(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_UNREAD))

        assert _reported_keys(caplog) == {"output_storage"}

    def test_the_report_gives_the_path_a_run_writes_instead(self, tmp_path, caplog):
        """The documented db_path is not the convention, so naming the key is not enough."""
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_UNREAD))

        assert "agent_io/store" in caplog.text

    def test_only_the_unread_key_is_named_beside_keys_that_are_read(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, {**_READ_KEYS, **_UNREAD})

        assert _reported_keys(caplog) == {"output_storage"}


class TestAKeyWithAReaderIsNotReported:
    def test_every_read_key_together_names_nothing(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, dict(_READ_KEYS))

        assert _reported_keys(caplog) == set()

    def test_an_absent_project_file_names_nothing(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, {})

        assert _reported_keys(caplog) == set()

    def test_a_misspelled_key_names_nothing(self, tmp_path, caplog):
        """The report is a fixed list of keys known to be unread, not an undeclared-key check.

        The project file has no model, so a typo here is still dropped in silence; pinning
        that keeps the two apart, since reporting anything undeclared would need the model.
        """
        with caplog.at_level(logging.WARNING):
            _load_against(tmp_path, {"schmea_path": "schema", "outpt_storage": {}})

        assert _reported_keys(caplog) == set()


class TestTheAdvertisedPathTracksTheStorageLayer:
    def test_the_report_names_the_workflow_directory_the_store_actually_sits_in(
        self, tmp_path, caplog
    ):
        """Guidance pointing somewhere nothing writes is the defect being fixed here.

        The project root and the workflow directory must stay distinguishable for this to
        assert anything: a store built with the two collapsed onto one path agrees with
        either description, which is how a wrong location survives its own test.
        """
        project = tmp_path / "proj"
        workflow_dir = project / "agent_workflow" / "wf"
        workflow_dir.mkdir(parents=True)
        backend = get_storage_backend(workflow_path=str(workflow_dir), workflow_name="wf")
        database = Path(backend.db_path)

        assert database == workflow_dir / "agent_io" / "store" / "wf.db"
        assert not (project / "agent_io").exists()

        with caplog.at_level(logging.WARNING):
            _load_against(project, dict(_UNREAD))

        template = str(database.relative_to(workflow_dir)).replace("wf.db", "<workflow>.db")
        assert template in caplog.text
        assert "project root" not in caplog.text


class TestNoExampleOrDocsPageDeclaresIt:
    """Named for the two surfaces actually globbed, which is not every shipped file."""

    def test_no_example_project_declares_the_unread_key(self):
        configs = sorted(_REPO.glob("examples/*/agent_actions.yml"))
        assert configs, f"no example project configs found under {_REPO}/examples"

        declared = {
            str(path.relative_to(_REPO))
            for path in configs
            if "output_storage" in (yaml.safe_load(path.read_text()) or {})
        }

        assert declared == set()

    def test_no_documentation_page_documents_it(self):
        pages = sorted(_DOCS.rglob("*.md"))
        assert pages, f"no documentation pages found under {_DOCS}"

        assert [
            str(page.relative_to(_REPO)) for page in pages if "output_storage" in page.read_text()
        ] == []
