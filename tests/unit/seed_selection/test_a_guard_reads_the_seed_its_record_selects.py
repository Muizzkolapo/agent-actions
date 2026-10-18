"""A guard reads the seed file its own record selects, and the prompt renders from that same load."""

import json

import pytest

from agent_actions.processing.guard_context import build_guard_context
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer

SYLLABUS = {
    "select_by": "source.exam",
    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
}


def _config(tmp_path, guard=None):
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    (workflow / "seed_data" / "dbt.json").write_text(json.dumps({"label": "DBT-LABEL"}))
    (workflow / "seed_data" / "snowflake.json").write_text(json.dumps({"label": "SNOW-LABEL"}))
    config = {
        "run_mode": "online",
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "prompt": "{{ seed.syllabus.label }}",
        "context_scope": {"seed": {"syllabus": SYLLABUS}, "observe": ["source.title"]},
    }
    if guard:
        config["guard"] = {"clause": guard, "behavior": "filter", "scope": "item"}
    return config


def _record(exam):
    return {"content": {"source": {"exam": exam, "title": exam}}, "source_guid": f"g-{exam}"}


class TestTheGuardContextLoadsTheRecordsSeed:
    @pytest.mark.parametrize(("exam", "label"), [("dbt", "DBT-LABEL"), ("snowflake", "SNOW-LABEL")])
    def test_each_record_gets_its_own_file_in_the_guard_context(self, tmp_path, exam, label):
        config = _config(tmp_path, guard='seed.syllabus.label != ""')
        context = build_guard_context(
            _record(exam), agent_name="a", agent_config=config, is_first_stage=True
        )

        assert context["seed"]["syllabus"]["label"] == label


class TestAGuardReadingTheSelectedSeed:
    def test_it_passes_the_record_whose_file_matches_and_filters_the_other(self, tmp_path):
        config = _config(tmp_path, guard='seed.syllabus.label == "SNOW-LABEL"')
        context = PreparationContext(agent_config=config, agent_name="a", is_first_stage=True)

        kept = TaskPreparer().prepare(_record("snowflake"), context)
        filtered = TaskPreparer().prepare(_record("dbt"), context)

        assert kept.guard_status == GuardStatus.PASSED
        assert kept.formatted_prompt == "SNOW-LABEL"
        assert filtered.guard_status != GuardStatus.PASSED
