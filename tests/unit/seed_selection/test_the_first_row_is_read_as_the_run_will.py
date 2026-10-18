"""The first row is read the way the run will, whatever the file type, before anything renders it."""

import json

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging import initial_pipeline
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    _envelope_row,
    _validate_staged_data,
    process_initial_stage,
)
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer

SYLLABUS = {
    "select_by": "source.exam",
    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
}
FILES = {"dbt.json": {"label": "DBT-LABEL"}, "snowflake.json": {"label": "SNOW-LABEL"}}


def _workflow(tmp_path):
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    for name, content in FILES.items():
        (workflow / "seed_data" / name).write_text(json.dumps(content))
    return workflow


def _action(workflow, seed, prompt, observe, run_mode="online"):
    return {
        "run_mode": run_mode,
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "prompt": prompt,
        "context_scope": {"seed": seed, "observe": observe},
    }


def _stage(tmp_path, name, text, first, later):
    workflow = tmp_path / "workflow"
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    target = workflow / "agent_io" / "target" / "label"
    target.mkdir(parents=True)
    doc = staging / name
    doc.write_text(text)
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


class TestABadFirstRowIsRefusedWithItsLocation:
    @pytest.mark.parametrize("run_mode", ["online", "batch"])
    def test_the_first_row_is_record_zero(self, tmp_path, run_mode):
        workflow = _workflow(tmp_path)
        action = _action(
            workflow,
            {"syllabus": SYLLABUS},
            "{{ seed.syllabus.label }}",
            ["source.title"],
            run_mode,
        )
        rows = [{"exam": "snowflak", "title": "a"}, {"exam": "dbt", "title": "b"}]

        with pytest.raises(ConfigValidationError) as excinfo:
            _stage(tmp_path, "pages.json", json.dumps(rows), action, action)

        assert str(excinfo.value).endswith(
            "Known values: dbt, snowflake. (staging/pages.json, record 0)"
        )


class TestATextFileIsCheckedAsTheChunksTheRunPrepares:
    def test_a_later_actions_selector_refuses_a_markdown_file(self, tmp_path):
        workflow = _workflow(tmp_path)
        first = _action(workflow, {}, "{{ source.page_content }}", ["source.page_content"])
        later = _action(workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}", [])

        with pytest.raises(ConfigValidationError) as excinfo:
            _stage(tmp_path, "pages.md", "# A page of prose\n", first, later)

        assert str(excinfo.value).endswith(
            "record has no value for 'source.exam'. Known values: dbt, snowflake. "
            "(staging/pages.md, record 0)"
        )


class TestTheDryRunReadsTheFirstRowAsTheRunWill:
    def test_a_content_field_beside_the_selector_does_not_hide_it(self, tmp_path):
        workflow = _workflow(tmp_path)
        action = _action(
            workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}", ["source.title"]
        )

        _validate_staged_data(
            records=[_envelope_row({"exam": "dbt", "content": {"body": "x"}, "title": "a"})],
            agent_config=action,
            agent_name="label",
            mode="online",
            file_path=str(workflow / "agent_io" / "staging" / "pages.json"),
        )


class TestATabularFileIsRenderedAsTheRowsTheRunPrepares:
    @pytest.mark.parametrize("run_mode", ["online", "batch"])
    def test_a_csv_whose_rows_are_all_covered_passes_every_check(
        self, tmp_path, run_mode, monkeypatch
    ):
        workflow = _workflow(tmp_path)
        action = _action(
            workflow,
            {"syllabus": SYLLABUS},
            "{{ seed.syllabus.label }}",
            ["source.title"],
            run_mode,
        )

        def reached_the_save(*args, **kwargs):
            raise RuntimeError("every check passed")

        monkeypatch.setattr(initial_pipeline, "_save_source_data", reached_the_save)

        with pytest.raises(RuntimeError, match="every check passed"):
            _stage(tmp_path, "pages.csv", "exam,title\ndbt,a\nsnowflake,b\n", action, action)

    def test_a_csv_with_a_bad_row_is_refused_with_its_location(self, tmp_path):
        workflow = _workflow(tmp_path)
        action = _action(
            workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}", ["source.title"]
        )

        with pytest.raises(ConfigValidationError) as excinfo:
            _stage(tmp_path, "pages.csv", "exam,title\ndbt,a\nsnowflak,b\n", action, action)

        assert str(excinfo.value).endswith(
            "Known values: dbt, snowflake. (staging/pages.csv, record 1)"
        )


class TestAStoredRecordReadsItsSelectorFromTheSourcePool:
    def test_only_the_pool_row_holds_the_selector(self, tmp_path):
        workflow = _workflow(tmp_path)
        config = _action(
            workflow, {"syllabus": SYLLABUS}, "{{ seed.syllabus.label }}", ["source.title"]
        )
        pool = [{"source_guid": "g1", "content": {"source": {"exam": "snowflake", "title": "a"}}}]
        context = PreparationContext(
            agent_config=config, agent_name="translate", is_first_stage=False, source_data=pool
        )
        stored = {"source_guid": "g1", "content": {"label": {"summary": "s"}}}

        repaired = TaskPreparer().prepare(stored, context, attempt=1)

        assert repaired.formatted_prompt == "SNOW-LABEL"
