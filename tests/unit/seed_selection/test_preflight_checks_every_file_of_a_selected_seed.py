"""Preflight checks each file of a selected seed and the shape of the entry."""

import json

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


def _project(tmp_path, files):
    project = tmp_path / "project"
    (project / "agent_config").mkdir(parents=True)
    (project / "seed_data").mkdir()
    for name, content in files.items():
        (project / "seed_data" / name).write_text(json.dumps(content))
    return str(project / "agent_config" / "workflow.yml")


def _resolve(tmp_path, files, seed, observe=("seed.syllabus",)):
    service = WorkflowResolutionService(
        action_configs={"a": {"context_scope": {"seed": seed, "observe": list(observe)}}},
        workflow_config_path=_project(tmp_path, files),
    )
    return service.resolve_all()


SELECTED = {
    "syllabus": {
        "select_by": "source.exam",
        "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
    }
}


class TestEveryFileOfTheMapIsChecked:
    def test_a_missing_file_in_the_map_is_an_error(self, tmp_path):
        result = _resolve(tmp_path, {"dbt.json": {"domains": []}}, SELECTED)

        missing = [e for e in result.errors if "Seed file not found" in e.message]
        assert len(missing) == 1
        assert "snowflake.json" in missing[0].message
        assert missing[0].location.config_field == "context_scope.seed.syllabus"

    def test_a_field_missing_from_one_file_names_that_file(self, tmp_path):
        files = {"dbt.json": {"domains": []}, "snowflake.json": {"topics": []}}
        result = _resolve(tmp_path, files, SELECTED, observe=["seed.syllabus.domains"])

        assert result.errors == []
        lacking = [w for w in result.warnings if "syllabus.domains" in w.message]
        assert len(lacking) == 1
        assert "snowflake.json" in lacking[0].message
        assert "dbt.json" not in lacking[0].message

    def test_a_field_present_in_every_file_passes(self, tmp_path):
        files = {"dbt.json": {"domains": []}, "snowflake.json": {"domains": []}}
        result = _resolve(tmp_path, files, SELECTED, observe=["seed.syllabus.domains"])

        assert result.errors == []
        assert [w for w in result.warnings if "syllabus" in w.message] == []

    def test_a_plain_seed_keeps_its_warning_text(self, tmp_path):
        seed = {"syllabus": "$file:dbt.json"}
        result = _resolve(tmp_path, {"dbt.json": {"topics": []}}, seed, ["seed.syllabus.domains"])

        lacking = [w for w in result.warnings if "syllabus.domains" in w.message]
        assert len(lacking) == 1
        assert lacking[0].message.endswith("does not exist in seed data")


class TestTheShapeOfAnEntryIsChecked:
    @pytest.mark.parametrize(
        ("entry", "fragment"),
        [
            (42, "expected a file path or a mapping"),
            ({"files": {"dbt": "$file:dbt.json"}}, "needs both 'select_by' and 'files'"),
            (
                {"select_by": "source.exam", "files": {"dbt": "$file:dbt.json"}, "default": "dbt"},
                "unknown key 'default'",
            ),
            (
                {"select_by": "upstream.kind", "files": {"dbt": "$file:dbt.json"}},
                "'select_by' must be 'source.<field>'",
            ),
            (
                {"select_by": "exam", "files": {"dbt": "$file:dbt.json"}},
                "'select_by' must be 'source.<field>'",
            ),
            ({"select_by": "source.exam", "files": {}}, "'files' must be a non-empty map"),
            (
                {"select_by": "source.exam", "files": "$file:dbt.json"},
                "'files' must be a non-empty map",
            ),
            (
                {"select_by": "source.exam", "files": {"dbt": 7}},
                "file for value 'dbt' must be a file path",
            ),
            (
                {"select_by": "source.exam", "files": {True: "$file:dbt.json"}},
                "must be a string or an integer",
            ),
        ],
    )
    def test_a_malformed_entry_is_an_error(self, tmp_path, entry, fragment):
        result = _resolve(tmp_path, {"dbt.json": {}}, {"syllabus": entry})

        shape = [
            e for e in result.errors if e.location.config_field == "context_scope.seed.syllabus"
        ]
        assert len(shape) == 1
        assert shape[0].message.startswith("Seed 'syllabus' in action 'a': ")
        assert fragment in shape[0].message

    def test_a_well_formed_entry_is_not_an_error(self, tmp_path):
        files = {"dbt.json": {}, "snowflake.json": {}}
        result = _resolve(tmp_path, files, SELECTED)

        assert result.errors == []
