"""A $file: reference resolves per file: the workflow folder first, then the shared folders."""

import json
import os

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.static_loader import StaticDataLoadError
from agent_actions.prompt.service import PromptPreparationService


def _project(
    tmp_path, *, listed=("shared_seeds",), workflow_files=None, project_files=None, shared=None
):
    """A project with one workflow; every folder given gets the files named for it."""
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
    return project, str(workflow / "agent_config" / "wf.yml")


def _load(config_path, seed, source=None):
    config = {"workflow_config_path": config_path}
    return PromptPreparationService.load_seed_data(config, {"seed": seed}, "a", source=source)


class TestAFileIsFoundInTheFirstFolderThatHoldsIt:
    def test_a_file_only_in_a_shared_folder_loads_beside_a_workflow_folder(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"own.json": {"label": "OWN"}},
            shared={"shared_seeds": {"rules.json": {"label": "SHARED"}}},
        )

        loaded = _load(config_path, {"own": "$file:own.json", "rules": "$file:rules.json"})

        assert loaded == {"own": {"label": "OWN"}, "rules": {"label": "SHARED"}}

    def test_the_workflow_file_wins_over_the_project_file_of_the_same_name(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            listed=None,
            workflow_files={"rules.json": {"label": "WORKFLOW"}},
            project_files={"rules.json": {"label": "PROJECT"}},
        )

        assert _load(config_path, {"rules": "$file:rules.json"}) == {"rules": {"label": "WORKFLOW"}}

    def test_the_workflow_file_wins_over_a_listed_folder_too(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"rules.json": {"label": "WORKFLOW"}},
            shared={"shared_seeds": {"rules.json": {"label": "SHARED"}}},
        )

        assert _load(config_path, {"rules": "$file:rules.json"}) == {"rules": {"label": "WORKFLOW"}}

    def test_a_selected_seed_resolves_each_file_by_itself(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"dbt.json": {"label": "DBT"}},
            shared={"shared_seeds": {"snowflake.json": {"label": "SNOW"}}},
        )
        seed = {
            "syllabus": {
                "select_by": "source.exam",
                "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
            }
        }

        assert _load(config_path, seed, {"exam": "dbt"})["syllabus"]["label"] == "DBT"
        assert _load(config_path, seed, {"exam": "snowflake"})["syllabus"]["label"] == "SNOW"

    def test_a_project_without_the_new_key_behaves_as_before(self, tmp_path):
        _, config_path = _project(
            tmp_path, listed=None, project_files={"rules.json": {"label": "PROJECT"}}
        )

        assert _load(config_path, {"rules": "$file:rules.json"}) == {"rules": {"label": "PROJECT"}}


class TestANameInTwoSharedFoldersIsRefused:
    def test_a_referenced_duplicate_names_both_folders(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            listed=("shared_seeds", "more_seeds"),
            shared={
                "shared_seeds": {"rules.json": {"label": "A"}},
                "more_seeds": {"rules.json": {"label": "B"}},
            },
        )

        with pytest.raises(StaticDataLoadError) as excinfo:
            _load(config_path, {"rules": "$file:rules.json"})

        assert str(excinfo.value).endswith(
            "Seed file 'rules.json' is in more than one shared seed folder: "
            "shared_seeds, more_seeds. Keep it in one."
        )

    def test_the_project_folder_counts_as_a_shared_folder(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            project_files={"rules.json": {"label": "P"}},
            shared={"shared_seeds": {"rules.json": {"label": "S"}}},
        )

        with pytest.raises(StaticDataLoadError, match="more than one shared seed folder"):
            _load(config_path, {"rules": "$file:rules.json"})

    def test_an_unreferenced_duplicate_is_not_an_error(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            listed=("shared_seeds", "more_seeds"),
            shared={
                "shared_seeds": {"rules.json": {"label": "A"}, "only.json": {"label": "ONLY"}},
                "more_seeds": {"rules.json": {"label": "B"}},
            },
        )

        assert _load(config_path, {"only": "$file:only.json"}) == {"only": {"label": "ONLY"}}


class TestAMissingFileNamesEveryFolderSearched:
    def test_the_folders_are_listed_in_search_order(self, tmp_path):
        _, config_path = _project(
            tmp_path,
            workflow_files={"own.json": {}},
            project_files={"p.json": {}},
            shared={"shared_seeds": {"s.json": {}}},
        )

        with pytest.raises(StaticDataLoadError) as excinfo:
            _load(config_path, {"rules": "$file:rules.json"})

        assert "File not found" in str(excinfo.value)
        assert str(excinfo.value).endswith(
            "Searched: agent_workflow/wf/seed_data, seed_data, shared_seeds."
        )


class TestAListedFolderIsChecked:
    def test_a_missing_listed_folder_is_a_config_error(self, tmp_path):
        project, config_path = _project(
            tmp_path, listed=("shared_sedes",), workflow_files={"a.json": {}}
        )

        with pytest.raises(ConfigurationError) as excinfo:
            _load(config_path, {"a": "$file:a.json"})

        assert str(excinfo.value) == (
            f"seed_data_paths: folder 'shared_sedes' does not exist (project root: {project})."
        )

    @pytest.mark.parametrize("entry", ["/etc", "../outside"])
    def test_a_folder_outside_the_project_is_a_config_error(self, tmp_path, entry):
        (tmp_path / "outside").mkdir()
        _, config_path = _project(tmp_path, listed=(entry,), workflow_files={"a.json": {}})

        with pytest.raises(ConfigurationError) as excinfo:
            _load(config_path, {"a": "$file:a.json"})

        assert str(excinfo.value) == (
            f"seed_data_paths: '{entry}' is outside the project. Use a folder inside the project root."
        )

    def test_a_symlink_to_a_folder_outside_the_project_is_a_config_error(self, tmp_path):
        (tmp_path / "outside").mkdir()
        project, config_path = _project(tmp_path, listed=("linked",), workflow_files={"a.json": {}})
        os.symlink(tmp_path / "outside", project / "linked")

        with pytest.raises(ConfigurationError, match="'linked' is outside the project"):
            _load(config_path, {"a": "$file:a.json"})

    def test_a_missing_default_folder_is_still_not_an_error(self, tmp_path):
        _, config_path = _project(tmp_path, shared={"shared_seeds": {"s.json": {"label": "S"}}})

        assert _load(config_path, {"s": "$file:s.json"}) == {"s": {"label": "S"}}


class TestTheResolverReportsWhereAFileCameFrom:
    def test_a_workflow_file_reports_the_shared_file_it_hides(self, tmp_path):
        from agent_actions.config.path_config import resolve_seed_file, seed_search_folders

        project, config_path = _project(
            tmp_path,
            workflow_files={"rules.json": {}},
            shared={"shared_seeds": {"rules.json": {}}},
        )

        found = resolve_seed_file("$file:rules.json", seed_search_folders(config_path))

        assert found.path == project / "agent_workflow" / "wf" / "seed_data" / "rules.json"
        assert found.folder.kind == "workflow"
        assert [p.name for p in found.overrides] == ["rules.json"]
        assert found.overrides[0].parent == project / "shared_seeds"

    def test_the_search_order_is_workflow_then_project_then_listed(self, tmp_path):
        from agent_actions.config.path_config import seed_search_folders

        _, config_path = _project(
            tmp_path,
            listed=("more_seeds", "shared_seeds"),
            workflow_files={"w.json": {}},
            project_files={"p.json": {}},
            shared={"shared_seeds": {}, "more_seeds": {}},
        )

        folders = seed_search_folders(config_path)

        assert [(f.kind, f.label) for f in folders] == [
            ("workflow", "agent_workflow/wf/seed_data"),
            ("project", "seed_data"),
            ("listed", "more_seeds"),
            ("listed", "shared_seeds"),
        ]


class TestASharedLoaderIsOnePerFolderList:
    def test_two_workflows_with_different_folders_do_not_share_a_loader(self, tmp_path):
        from agent_actions.config.path_config import seed_search_folders
        from agent_actions.prompt.context.static_loader import shared_static_data_loader

        _, config_a = _project(
            tmp_path / "a", listed=None, workflow_files={"x.json": {"label": "A"}}
        )
        _, config_b = _project(
            tmp_path / "b", listed=None, workflow_files={"x.json": {"label": "B"}}
        )
        folders_a = seed_search_folders(config_a)
        folders_b = seed_search_folders(config_b)

        loader_a = shared_static_data_loader(folders_a)
        loader_b = shared_static_data_loader(folders_b)

        assert loader_a is not loader_b
        assert loader_a is shared_static_data_loader(seed_search_folders(config_a))
        assert loader_a.load_static_data({"x": "$file:x.json"}) == {"x": {"label": "A"}}
        assert loader_b.load_static_data({"x": "$file:x.json"}) == {"x": {"label": "B"}}

    def test_a_guard_shares_the_load_and_reads_the_record_s_file(self, tmp_path):
        from agent_actions.processing.guard_context import build_guard_context

        _, config_path = _project(
            tmp_path,
            workflow_files={"dbt.json": {"label": "DBT"}},
            shared={"shared_seeds": {"snowflake.json": {"label": "SNOW"}}},
        )
        config = {
            "workflow_config_path": config_path,
            "guard": {
                "clause": "seed.syllabus.label == 'SNOW'",
                "behavior": "filter",
                "scope": "item",
            },
            "context_scope": {
                "seed": {
                    "syllabus": {
                        "select_by": "source.exam",
                        "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
                    }
                },
                "observe": ["source.title"],
            },
        }
        record = {"content": {"source": {"exam": "snowflake", "title": "t"}}, "source_guid": "g"}

        context = build_guard_context(
            record, agent_name="a", agent_config=config, is_first_stage=True
        )

        assert context["seed"]["syllabus"]["label"] == "SNOW"
