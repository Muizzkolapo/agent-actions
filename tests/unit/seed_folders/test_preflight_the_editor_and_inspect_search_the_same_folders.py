"""Preflight, the editor and `inspect context` find the same file the run will."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.cli.inspect import ContextCommand
from agent_actions.tooling.lsp.models import Location, Reference, ReferenceType
from agent_actions.tooling.lsp.resolver import resolve_reference
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


def _project(
    tmp_path, *, listed=("shared_seeds",), workflow_files=None, project_files=None, shared=None
):
    project = tmp_path / "project"
    workflow = project / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    lines = ["schema_path: schema"]
    if listed is not None:
        lines.append("seed_data_paths: [" + ", ".join(listed) + "]")
    (project / "agent_actions.yml").write_text("\n".join(lines) + "\n")
    for folder, files in (
        (workflow / "seed_data", workflow_files),
        (project / "seed_data", project_files),
        *((project / name, files) for name, files in (shared or {}).items()),
    ):
        if files is None:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (folder / name).write_text(json.dumps(content))
    config_path = workflow / "agent_config" / "wf.yml"
    config_path.write_text("name: wf\n")
    return project, config_path


def _preflight(config_path, seed, observe=("seed.rules",)):
    service = WorkflowResolutionService(
        action_configs={"a": {"context_scope": {"seed": seed, "observe": list(observe)}}},
        workflow_config_path=str(config_path),
    )
    return service.resolve_all()


class TestPreflightSearchesEveryFolder:
    def test_a_file_only_in_a_shared_folder_passes(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"own.json": {}},
            shared={"shared_seeds": {"rules.json": {"domains": []}}},
        )

        result = _preflight(config_path, {"rules": "$file:rules.json"}, ["seed.rules.domains"])

        assert result.errors == []
        assert [w for w in result.warnings if "rules" in w.message] == []

    def test_a_missing_file_lists_the_folders_searched(self, tmp_path):
        _, config_path = _project(
            tmp_path, workflow_files={"own.json": {}}, shared={"shared_seeds": {"s.json": {}}}
        )

        result = _preflight(config_path, {"rules": "$file:rules.json"})

        missing = [e for e in result.errors if e.message.startswith("Seed file not found")]
        assert len(missing) == 1
        assert missing[0].message.endswith("Searched: agent_workflow/wf/seed_data, shared_seeds.")
        assert "own.json" in missing[0].hint and "s.json" in missing[0].hint

    def test_a_name_in_two_shared_folders_is_an_error_naming_both(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            listed=("shared_seeds", "more_seeds"),
            shared={"shared_seeds": {"rules.json": {}}, "more_seeds": {"rules.json": {}}},
        )

        result = _preflight(config_path, {"rules": "$file:rules.json"})

        duplicate = [e for e in result.errors if "more than one shared seed folder" in e.message]
        assert len(duplicate) == 1
        assert "shared_seeds, more_seeds" in duplicate[0].message
        assert duplicate[0].location.config_field == "context_scope.seed.rules"

    def test_a_bad_listed_folder_is_one_config_error(self, tmp_path):
        _, config_path = _project(tmp_path, listed=("missing",), workflow_files={"a.json": {}})

        result = _preflight(config_path, {"a": "$file:a.json"}, ["seed.a"])

        bad = [e for e in result.errors if "seed_data_paths" in e.message]
        assert len(bad) == 1
        assert "folder 'missing' does not exist" in bad[0].message

    def test_a_template_path_is_checked_against_the_file_found(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"rules.json": {"domains": []}},
            shared={"shared_seeds": {"rules.json": {"topics": []}}},
        )

        result = _preflight(config_path, {"rules": "$file:rules.json"}, ["seed.rules.domains"])

        assert result.errors == []
        assert [w for w in result.warnings if "rules.domains" in w.message] == []


def _seed_ref(value):
    return Reference(
        type=ReferenceType.SEED_FILE,
        value=value,
        location=Location(file_path=Path(), line=0, column=0),
        raw_text=f"$file:{value}",
    )


class TestTheEditorOpensTheFileTheRunReads:
    def test_the_workflow_file_wins_over_the_project_file(self, tmp_path):
        project, config_path = _project(
            tmp_path,
            listed=None,
            workflow_files={"rules.json": {}},
            project_files={"rules.json": {}},
        )
        index = MagicMock()
        index.root = project

        found = resolve_reference(_seed_ref("rules.json"), index, current_file=config_path)

        assert found is not None
        assert found.file_path == project / "agent_workflow" / "wf" / "seed_data" / "rules.json"

    def test_a_file_in_a_listed_folder_is_found(self, tmp_path):
        project, config_path = _project(
            tmp_path, workflow_files={"own.json": {}}, shared={"shared_seeds": {"rules.json": {}}}
        )
        index = MagicMock()
        index.root = project

        found = resolve_reference(_seed_ref("rules.json"), index, current_file=config_path)

        assert found is not None
        assert found.file_path == project / "shared_seeds" / "rules.json"


class TestInspectShowsWhereEachSeedFileComesFrom:
    def test_each_key_names_its_file_and_an_override(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"rules.json": {}},
            shared={"shared_seeds": {"rules.json": {}, "style.json": {}}},
        )
        scope = {
            "seed": {
                "rules": "$file:rules.json",
                "style": "$file:style.json",
                "tone": {"select_by": "source.tone", "files": {"formal": "$file:style.json"}},
            }
        }

        files = ContextCommand._seed_files(scope, str(config_path))

        assert files == {
            "rules": [
                {
                    "file": "agent_workflow/wf/seed_data/rules.json",
                    "overrides": ["shared_seeds/rules.json"],
                }
            ],
            "style": [{"file": "shared_seeds/style.json", "overrides": []}],
            "tone": [{"file": "shared_seeds/style.json", "overrides": [], "value": "formal"}],
        }

    def test_a_file_nowhere_is_reported_not_raised(self, tmp_path):
        _, config_path = _project(tmp_path, listed=None, workflow_files={"own.json": {}})

        files = ContextCommand._seed_files(
            {"seed": {"rules": "$file:rules.json"}}, str(config_path)
        )

        assert files["rules"][0]["file"] is None
        assert files["rules"][0]["error"].startswith("Seed file not found")
