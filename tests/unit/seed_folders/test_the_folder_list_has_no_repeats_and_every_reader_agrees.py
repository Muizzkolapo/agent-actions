"""A folder is searched once however it is listed, and every reader of a reference agrees."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.cli.inspect import ContextCommand
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.tooling.lsp.handlers import build_hover_content
from agent_actions.tooling.lsp.models import Location, Reference, ReferenceType
from agent_actions.tooling.lsp.resolver import resolve_reference
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


def _write(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(json.dumps(content))


def _nested_project(tmp_path, listed, *, workflow_files=None, project_files=None, shared=None):
    project = tmp_path / "project"
    workflow = project / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (project / "agent_actions.yml").write_text(
        "schema_path: schema\nseed_data_paths: [" + ", ".join(listed) + "]\n"
    )
    if workflow_files is not None:
        _write(workflow / "seed_data", workflow_files)
    if project_files is not None:
        _write(project / "seed_data", project_files)
    for name, files in (shared or {}).items():
        _write(project / name, files)
    config_path = workflow / "agent_config" / "wf.yml"
    config_path.write_text("name: wf\n")
    return project, config_path


def _flat_project(tmp_path, listed, *, own_files, shared):
    """agent_config/ sits at the project root, so the workflow's folder is the project's."""
    project = tmp_path / "project"
    (project / "agent_config").mkdir(parents=True)
    (project / "agent_actions.yml").write_text(
        "schema_path: schema\nseed_data_paths: [" + ", ".join(listed) + "]\n"
    )
    _write(project / "seed_data", own_files)
    for name, files in shared.items():
        _write(project / name, files)
    config_path = project / "agent_config" / "wf.yml"
    config_path.write_text("name: wf\n")
    return project, config_path


def _load(config_path, seed):
    config = {"workflow_config_path": str(config_path)}
    return PromptPreparationService.load_seed_data(config, {"seed": seed}, "a")


class TestAFolderIsSearchedOnce:
    def test_the_project_folder_listed_again_is_one_folder(self, tmp_path):
        from agent_actions.config.path_config import seed_search_folders

        _, config_path = _nested_project(
            tmp_path, ["seed_data"], project_files={"a.json": {"label": "A"}}
        )

        assert [f.kind for f in seed_search_folders(str(config_path))] == ["project"]
        assert _load(config_path, {"a": "$file:a.json"}) == {"a": {"label": "A"}}

    def test_one_folder_listed_twice_in_two_spellings_is_one_folder(self, tmp_path):
        from agent_actions.config.path_config import seed_search_folders

        _, config_path = _nested_project(
            tmp_path, ["shared", "./shared/"], shared={"shared": {"a.json": {"label": "A"}}}
        )

        assert [f.label for f in seed_search_folders(str(config_path))] == ["shared"]
        assert _load(config_path, {"a": "$file:a.json"}) == {"a": {"label": "A"}}

    def test_the_workflow_folder_listed_as_shared_does_not_override_itself(self, tmp_path):
        from agent_actions.config.path_config import resolve_seed_file, seed_search_folders

        _, config_path = _nested_project(
            tmp_path, ["agent_workflow/wf/seed_data"], workflow_files={"a.json": {"label": "A"}}
        )

        folders = seed_search_folders(str(config_path))
        found = resolve_seed_file("$file:a.json", folders)

        assert [f.kind for f in folders] == ["workflow"]
        assert found.overrides == ()


class TestAFlatProjectsOwnFolderStillWins:
    def test_the_own_file_wins_over_a_listed_one_and_reports_it(self, tmp_path):
        from agent_actions.config.path_config import resolve_seed_file, seed_search_folders

        project, config_path = _flat_project(
            tmp_path,
            ["shared"],
            own_files={"a.json": {"label": "OWN"}},
            shared={"shared": {"a.json": {"label": "SHARED"}}},
        )

        folders = seed_search_folders(str(config_path))
        found = resolve_seed_file("$file:a.json", folders)

        assert [(f.kind, f.label) for f in folders] == [
            ("workflow", "seed_data"),
            ("listed", "shared"),
        ]
        assert found.path == project / "seed_data" / "a.json"
        assert found.overrides == (project / "shared" / "a.json",)
        assert _load(config_path, {"a": "$file:a.json"}) == {"a": {"label": "OWN"}}


def _seed_ref(value):
    return Reference(
        type=ReferenceType.SEED_FILE,
        value=value,
        location=Location(file_path=Path(), line=0, column=0),
        raw_text=f"$file:{value}",
    )


class TestTheHoverReadsTheFileTheRunReads:
    def test_a_workflow_file_is_previewed(self, tmp_path):
        project, config_path = _nested_project(
            tmp_path, ["shared"], workflow_files={"a.json": {"label": "OWN"}}, shared={"shared": {}}
        )
        index = MagicMock()
        index.root = project

        hover = build_hover_content(_seed_ref("a.json"), index, current_file=config_path)

        assert hover is not None
        assert "File not found" not in hover
        assert "OWN" in hover

    def test_a_shared_file_is_previewed(self, tmp_path):
        project, config_path = _nested_project(
            tmp_path,
            ["shared"],
            workflow_files={},
            shared={"shared": {"a.json": {"label": "SHARED"}}},
        )
        index = MagicMock()
        index.root = project

        hover = build_hover_content(_seed_ref("a.json"), index, current_file=config_path)

        assert hover is not None
        assert "SHARED" in hover

    def test_a_file_nowhere_says_which_folders_were_searched(self, tmp_path):
        project, config_path = _nested_project(
            tmp_path, ["shared"], workflow_files={}, shared={"shared": {}}
        )
        index = MagicMock()
        index.root = project

        hover = build_hover_content(_seed_ref("a.json"), index, current_file=config_path)

        assert hover is not None
        assert "Searched: agent_workflow/wf/seed_data, shared" in hover


class TestEveryReaderGivesTheSameAnswer:
    def test_loader_preflight_editor_hover_and_inspect_agree_on_one_project(self, tmp_path):
        project, config_path = _nested_project(
            tmp_path,
            ["shared"],
            workflow_files={"rules.json": {"label": "OWN-RULES"}},
            project_files={"rules.json": {"label": "PROJECT-RULES"}, "p.json": {"label": "P"}},
            shared={"shared": {"s.json": {"label": "S"}}},
        )
        seed = {"rules": "$file:rules.json", "p": "$file:p.json", "s": "$file:s.json"}
        expected = {
            "rules": project / "agent_workflow" / "wf" / "seed_data" / "rules.json",
            "p": project / "seed_data" / "p.json",
            "s": project / "shared" / "s.json",
        }
        index = MagicMock()
        index.root = project

        loaded = _load(config_path, seed)
        preflight = WorkflowResolutionService(
            action_configs={"a": {"context_scope": {"seed": seed, "observe": ["seed.rules"]}}},
            workflow_config_path=str(config_path),
        ).resolve_all()
        editor = {
            key: resolve_reference(_seed_ref(spec[6:]), index, current_file=config_path).file_path
            for key, spec in seed.items()
        }
        hover = {
            key: build_hover_content(_seed_ref(spec[6:]), index, current_file=config_path)
            for key, spec in seed.items()
        }
        inspected = ContextCommand._seed_files({"seed": seed}, str(config_path))

        assert loaded == {k: json.loads(p.read_text()) for k, p in expected.items()}
        assert preflight.errors == []
        assert editor == expected
        for key, path in expected.items():
            assert json.loads(path.read_text())["label"] in hover[key]
            assert inspected[key][0]["file"] == path.relative_to(project).as_posix()
        assert inspected["rules"][0]["overrides"] == ["seed_data/rules.json"]
