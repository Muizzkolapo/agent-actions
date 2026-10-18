"""Every staged file is checked before any record of any file is stored or sent."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)
from agent_actions.workflow.runner import ActionRunner
from agent_actions.workflow.runner_file_processing import process_directory_files
from agent_actions.workflow.strategies import InitialStrategy, StandardStrategy

SYLLABUS = {
    "select_by": "source.exam",
    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
}
GOOD = [{"exam": "dbt", "title": "a"}, {"exam": "snowflake", "title": "b"}]
BAD = [{"exam": "dbt", "title": "c"}, {"exam": "snowflak", "title": "d"}]
BAD_TEXT = (
    "Seed 'syllabus' in action 'label': record value 'snowflak' for 'source.exam' is not "
    "in the file map. Known values: dbt, snowflake. (staging/b.json, record 1)"
)


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


def _workflow(tmp_path, run_mode="online"):
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    (workflow / "seed_data" / "dbt.json").write_text(json.dumps({"label": "DBT"}))
    (workflow / "seed_data" / "snowflake.json").write_text(json.dumps({"label": "SNOW"}))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "target" / "label").mkdir(parents=True)
    config = {
        "run_mode": run_mode,
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
        "prompt": "{{ seed.syllabus.label }} {{ source.title }}",
        "context_scope": {"seed": {"syllabus": SYLLABUS}, "observe": ["source.title"]},
    }
    return workflow, config


def _stage(workflow, files):
    staging = workflow / "agent_io" / "staging"
    for name, rows in files.items():
        (staging / name).write_text(json.dumps(rows) if not isinstance(rows, str) else rows)
    return staging


def _runner(config, *, storage_backend=None, retried=frozenset()):
    runner = MagicMock()
    runner.retried_records = retried
    runner.storage_backend = storage_backend
    runner.action_configs = {"label": config}
    runner.workflow_metadata = None
    runner.input_left_unreached = set()
    runner.processed = []
    runner._process_single_file.side_effect = lambda fp: runner.processed.append(
        fp.locations.item.name
    )
    runner._strategy_params.side_effect = lambda fp, storage_backend=None: (
        ActionRunner._strategy_params(runner, fp, storage_backend=storage_backend)
    )
    runner._precheck_single_file.side_effect = lambda fp: ActionRunner._precheck_single_file(
        runner, fp
    )
    return runner


def _params(workflow, config, strategy=None, file_type_filter=frozenset({"json"})):
    params = MagicMock()
    params.action_config = config
    params.action_name = "label"
    params.strategy = strategy or InitialStrategy()
    params.idx = 0
    params.file_type_filter = set(file_type_filter) if file_type_filter else None
    params.output_directory = str(workflow / "agent_io" / "target" / "label")
    params.upstream_data_dirs = [str(workflow / "agent_io" / "staging")]
    return params


def _walk(workflow, config, runner, params=None, processed_paths=None):
    staging = workflow / "agent_io" / "staging"
    return process_directory_files(
        runner,
        staging,
        workflow / "agent_io" / "target" / "label",
        str(staging),
        params or _params(workflow, config),
        processed_paths if processed_paths is not None else set(),
    )


class TestABadRowInALaterFileStopsTheWalkBeforeAnyFile:
    @pytest.mark.parametrize("run_mode", ["online", "batch"])
    def test_nothing_is_processed_and_the_row_is_named(self, tmp_path, run_mode):
        workflow, config = _workflow(tmp_path, run_mode)
        _stage(workflow, {"a.json": GOOD, "b.json": BAD})
        runner = _runner(config)

        with pytest.raises(ConfigValidationError) as excinfo:
            _walk(workflow, config, runner)

        assert str(excinfo.value) == BAD_TEXT
        assert runner.processed == []

    def test_the_store_is_not_touched_before_the_refusal(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": BAD})
        backend = MagicMock()
        runner = _runner(config, storage_backend=backend)

        with pytest.raises(ConfigValidationError):
            _walk(workflow, config, runner)

        assert backend.method_calls == []

    def test_a_file_limit_does_not_hide_a_later_bad_file(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        config["file_limit"] = 1
        _stage(workflow, {"a.json": GOOD, "b.json": GOOD, "c.json": BAD})
        runner = _runner(config)

        with pytest.raises(ConfigValidationError, match=r"\(staging/c\.json, record 1\)"):
            _walk(workflow, config, runner)

        assert runner.processed == []


class TestAWalkWhoseFilesAreAllValidIsUnchanged:
    def test_every_file_is_processed_in_order(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": GOOD})
        runner = _runner(config)

        found, processed, errors = _walk(workflow, config, runner)

        assert (found, processed) == (2, 2)
        assert runner.processed == ["a.json", "b.json"]

    def test_each_file_is_checked_once_and_one_at_a_time(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": GOOD, "c.json": GOOD})
        runner = _runner(config)

        _walk(workflow, config, runner)

        checked = [
            c.args[0].locations.item.name for c in runner._precheck_single_file.call_args_list
        ]
        assert checked == ["a.json", "b.json", "c.json"]


class TestOnlyTheFilesTheRunWouldProcessAreChecked:
    def test_a_file_already_processed_is_not_checked(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": BAD})
        runner = _runner(config)

        found, processed, _ = _walk(workflow, config, runner, processed_paths={Path("b.json")})

        assert runner.processed == ["a.json"]

    def test_a_file_of_a_type_the_action_does_not_read_is_not_checked(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.txt": "snowflak"})
        runner = _runner(config)

        _walk(workflow, config, runner)

        assert runner.processed == ["a.json"]

    def test_a_repair_checks_only_the_files_holding_its_records(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": BAD})
        backend = MagicMock()
        backend.records_share_a_repeat_chain.return_value = False
        backend.source_files_for_records.return_value = {"a"}
        runner = _runner(config, storage_backend=backend, retried=frozenset({"r1"}))

        _walk(workflow, config, runner)

        assert runner.processed == ["a.json"]

    def test_a_later_stage_does_not_read_the_staging_folder(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        _stage(workflow, {"a.json": GOOD, "b.json": BAD})
        runner = _runner(config)

        _walk(workflow, config, runner, _params(workflow, config, strategy=StandardStrategy()))

        assert runner._precheck_single_file.call_count == 0
        assert runner.processed == ["a.json", "b.json"]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
    def test_an_unreadable_file_is_left_to_the_walk(self, tmp_path):
        workflow, config = _workflow(tmp_path)
        staging = _stage(workflow, {"a.json": GOOD, "b.json": GOOD})
        os.chmod(staging / "b.json", 0)
        runner = _runner(config)
        try:
            found, processed, errors = _walk(workflow, config, runner)
        finally:
            os.chmod(staging / "b.json", stat.S_IRUSR | stat.S_IWUSR)

        assert runner.processed == ["a.json", "b.json"]


class TestTheCheckIsTheOneTheFirstStageRuns:
    def test_the_same_bad_file_is_refused_the_same_way_by_both(self, tmp_path):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            precheck_staged_file,
        )

        workflow, config = _workflow(tmp_path)
        staging = _stage(workflow, {"b.json": BAD})
        ctx = InitialStageContext(
            agent_config=config,
            agent_name="label",
            file_path=str(staging / "b.json"),
            base_directory=str(staging),
            output_directory=str(workflow / "agent_io" / "target" / "label"),
            action_configs={"label": config},
        )

        with pytest.raises(ConfigValidationError) as first:
            precheck_staged_file(ctx)
        with pytest.raises(ConfigValidationError) as second:
            process_initial_stage(ctx)

        assert str(first.value) == str(second.value) == BAD_TEXT

    def test_the_check_prepares_with_no_backend(self, tmp_path):
        from agent_actions.input.preprocessing.staging.initial_pipeline import (
            precheck_staged_file,
        )

        workflow, config = _workflow(tmp_path)
        staging = _stage(workflow, {"a.json": GOOD})
        backend = MagicMock()
        ctx = InitialStageContext(
            agent_config=config,
            agent_name="label",
            file_path=str(staging / "a.json"),
            base_directory=str(staging),
            output_directory=str(workflow / "agent_io" / "target" / "label"),
            storage_backend=backend,
            action_configs={"label": config},
        )

        precheck_staged_file(ctx)

        assert backend.method_calls == []
