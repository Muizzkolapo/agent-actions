"""The staging check reads a row as the prompt will, and the record pipeline selects in every mode."""

import json
import math

import pytest

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging import field_validation
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.prompt.context.static_loader import StaticDataLoader, StaticDataLoadError

SYLLABUS = {
    "select_by": "source.exam",
    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
}
FILES = {
    "dbt.json": {"label": "DBT-LABEL"},
    "snowflake.json": {"label": "SNOW-LABEL"},
    "rules.json": {"label": "RULES-LABEL"},
}


def _workflow(tmp_path):
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    for name, content in FILES.items():
        (workflow / "seed_data" / name).write_text(json.dumps(content))
    return workflow


def _action(workflow, seed, prompt, run_mode="online"):
    return {
        "run_mode": run_mode,
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "prompt": prompt,
        "context_scope": {"seed": seed, "observe": ["source.title"]},
    }


def _stage(tmp_path, rows, first, later, run_mode="online"):
    workflow = tmp_path / "workflow"
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    target = workflow / "agent_io" / "target" / "label"
    target.mkdir(parents=True)
    doc = staging / "pages.json"
    doc.write_text(json.dumps(rows))
    return process_initial_stage(
        InitialStageContext(
            agent_config=first,
            agent_name="label",
            file_path=str(doc),
            base_directory=str(staging),
            output_directory=str(target),
            action_configs={"label": first, "translate": later},
        )
    )


class TestTheRunStopsBeforeAnyRecordIsPrepared:
    @pytest.mark.parametrize("run_mode", ["online", "batch"])
    def test_a_later_actions_selector_stops_the_first_stage_on_the_bad_row(
        self, tmp_path, run_mode
    ):
        workflow = _workflow(tmp_path)
        first = _action(workflow, {"rules": "$file:rules.json"}, "{{ source.title }}", run_mode)
        later = _action(workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}", run_mode)
        rows = [{"exam": "dbt", "title": "a"}, {"exam": "snowflak", "title": "b"}]

        with pytest.raises(ConfigValidationError) as excinfo:
            _stage(tmp_path, rows, first, later, run_mode)

        assert str(excinfo.value) == (
            "Seed 'syllabus' in action 'translate': record value 'snowflak' for "
            "'source.exam' is not in the file map. Known values: dbt, snowflake. "
            "(staging/pages.json, record 1)"
        )


class TestARowIsReadAsThePromptReadsIt:
    def _check(self, rows):
        actions = {"a": {"context_scope": {"seed": {"syllabus": SYLLABUS}}}}
        field_validation.validate_seed_selectors(rows, "/p/agent_io/staging/pages.json", actions)

    def test_a_record_envelope_is_read_through_its_source(self):
        self._check([{"content": {"source": {"exam": "dbt"}}, "source_guid": "g1"}])

    def test_a_content_dict_without_a_source_namespace_is_the_record(self):
        self._check([{"content": {"exam": "snowflake", "title": "a"}}])

    def test_a_framework_field_beside_a_content_dict_is_not_the_record(self):
        with pytest.raises(ConfigValidationError, match=r"record has no value for 'source\.exam'"):
            self._check([{"exam": "dbt", "content": {"body": "x"}}])

    def test_a_framework_field_is_never_a_selector_value(self):
        actions = {
            "a": {
                "context_scope": {
                    "seed": {
                        "by_node": {"select_by": "source.node_id", "files": {"n1": "$file:a.json"}}
                    }
                }
            }
        }
        with pytest.raises(
            ConfigValidationError, match=r"record has no value for 'source\.node_id'"
        ):
            field_validation.validate_seed_selectors(
                [{"node_id": "n1", "title": "a"}], "/p/agent_io/staging/pages.json", actions
            )


class TestASpreadsheetCellIsReadAsItsValue:
    def _load(self, tmp_path, value):
        _workflow(tmp_path)
        loader = StaticDataLoader(tmp_path / "workflow" / "seed_data")
        seed = {"tier": {"select_by": "source.tier", "files": {1: "$file:dbt.json"}}}
        return loader.load_static_data(seed, source={"tier": value}, action_name="a")

    def test_a_whole_number_read_as_a_float_matches_its_integer_key(self, tmp_path):
        assert self._load(tmp_path, 1.0)["tier"]["label"] == "DBT-LABEL"

    def test_a_blank_cell_has_no_value(self, tmp_path):
        with pytest.raises(StaticDataLoadError, match=r"record has no value for 'source\.tier'"):
            self._load(tmp_path, math.nan)

    def test_a_fraction_is_still_the_wrong_type(self, tmp_path):
        with pytest.raises(StaticDataLoadError, match=r"must be a string or an integer, got float"):
            self._load(tmp_path, 1.5)


class TestTheRecordPipelineSelectsInEveryMode:
    @pytest.mark.parametrize("mode", [RunMode.ONLINE, RunMode.BATCH])
    def test_a_first_stage_record_selects_its_file(self, tmp_path, mode):
        workflow = _workflow(tmp_path)
        config = _action(workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}")
        context = PreparationContext(
            agent_config=config, agent_name="a", is_first_stage=True, mode=mode
        )

        prepared = [
            TaskPreparer().prepare({"exam": exam, "title": exam}, context)
            for exam in ("dbt", "snowflake")
        ]

        assert [task.formatted_prompt for task in prepared] == ["DBT-LABEL", "SNOW-LABEL"]

    def test_a_stored_record_resolved_from_the_source_pool_selects_its_file(self, tmp_path):
        workflow = _workflow(tmp_path)
        config = _action(workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}")
        pool = [
            {"source_guid": "g1", "content": {"source": {"exam": "snowflake", "title": "a"}}},
            {"source_guid": "g2", "content": {"source": {"exam": "dbt", "title": "b"}}},
        ]
        context = PreparationContext(
            agent_config=config, agent_name="a", is_first_stage=False, source_data=pool
        )
        stored = {"source_guid": "g1", "content": {"source": {"exam": "snowflake", "title": "a"}}}

        repaired = TaskPreparer().prepare(stored, context, attempt=1)

        assert repaired.formatted_prompt == "SNOW-LABEL"
