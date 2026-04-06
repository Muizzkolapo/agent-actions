"""Tests for agent_actions.tooling.docs.run_tracker module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import portalocker
import pytest

from agent_actions.tooling.docs.run_tracker import (
    ActionCompleteConfig,
    RunConfig,
    RunTracker,
    _empty_runs_data,
    retry,
    track_workflow_run,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_config(**overrides) -> RunConfig:
    defaults = {
        "workflow_id": "wf_test",
        "workflow_name": "Test Workflow",
        "status": "success",
        "started_at": "2026-01-01T00:00:00",
        "ended_at": "2026-01-01T00:01:00",
        "duration_seconds": 60.0,
        "actions_completed": 3,
        "actions_total": 5,
    }
    defaults.update(overrides)
    return RunConfig(**defaults)


def _seed_runs_file(runs_file: Path, data: dict | None = None) -> None:
    """Write runs data to the runs file, creating parent dirs."""
    runs_file.parent.mkdir(parents=True, exist_ok=True)
    with open(runs_file, "w", encoding="utf-8") as f:
        json.dump(data or _empty_runs_data(), f, indent=2)


# ---------------------------------------------------------------------------
# _empty_runs_data
# ---------------------------------------------------------------------------


class TestEmptyRunsData:
    def test_basic_structure(self):
        data = _empty_runs_data()
        assert "metadata" in data
        assert "executions" in data
        assert data["metadata"]["total_runs"] == 0
        assert data["executions"] == []
        assert "workflow_metrics" not in data

    def test_extended_structure(self):
        data = _empty_runs_data(extended=True)
        assert data["metadata"]["schema_version"] == "1.0"
        assert data["workflow_metrics"] == {}

    def test_generated_at_is_iso_string(self):
        data = _empty_runs_data()
        parsed = datetime.fromisoformat(data["metadata"]["generated_at"])
        assert isinstance(parsed, datetime)


# ---------------------------------------------------------------------------
# retry decorator
# ---------------------------------------------------------------------------


class TestRetryDecorator:
    def test_success_on_first_attempt(self):
        call_count = 0

        @retry(max_attempts=3, backoff=0.0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_retries_on_matching_exception(self):
        call_count = 0

        @retry(max_attempts=3, backoff=0.0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("boom")
            return "recovered"

        assert fn() == "recovered"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, backoff=0.0, exceptions=(RuntimeError,))
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            fn()

    def test_non_matching_exception_not_retried(self):
        call_count = 0

        @retry(max_attempts=3, backoff=0.0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            fn()
        assert call_count == 1

    def test_preserves_function_metadata(self):
        @retry(max_attempts=1, backoff=0.0)
        def documented():
            """My docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# RunTracker.__init__
# ---------------------------------------------------------------------------


class TestRunTrackerInit:
    def test_default_artefact_dir_from_project_root(self, tmp_path):
        tracker = RunTracker(project_root=tmp_path)
        assert tracker.artefact_dir == tmp_path / "artefact"
        assert tracker.runs_file == tmp_path / "artefact" / "runs.json"

    def test_explicit_artefact_dir(self, tmp_path):
        custom = tmp_path / "custom_artefacts"
        tracker = RunTracker(artefact_dir=custom)
        assert tracker.artefact_dir == custom

    def test_artefact_dir_takes_precedence(self, tmp_path):
        custom = tmp_path / "custom"
        tracker = RunTracker(artefact_dir=custom, project_root=tmp_path)
        assert tracker.artefact_dir == custom


# ---------------------------------------------------------------------------
# RunTracker.record_run
# ---------------------------------------------------------------------------


class TestRecordRun:
    def test_creates_runs_file_if_missing(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path / "artefact")
        config = _make_run_config()
        run_id = tracker.record_run(config=config)

        assert tracker.runs_file.exists()
        assert run_id.startswith("run_wf_test_")

    def test_creates_artefact_dir_if_missing(self, tmp_path):
        artefact = tmp_path / "deep" / "nested" / "artefact"
        tracker = RunTracker(artefact_dir=artefact)
        tracker.record_run(config=_make_run_config())
        assert artefact.exists()

    def test_run_record_fields(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        config = _make_run_config(
            error_message="some error",
            metadata={"key": "value"},
        )
        run_id = tracker.record_run(config=config)

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert len(data["executions"]) == 1
        rec = data["executions"][0]
        assert rec["id"] == run_id
        assert rec["workflow_id"] == "wf_test"
        assert rec["status"] == "success"
        assert rec["error_message"] == "some error"
        assert rec["metadata"] == {"key": "value"}
        assert rec["duration_seconds"] == 60.0

    def test_duration_calculated_from_timestamps_when_none(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        config = _make_run_config(
            duration_seconds=None,
            started_at="2026-01-01T00:00:00",
            ended_at="2026-01-01T00:02:30",
        )
        tracker.record_run(config=config)

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert data["executions"][0]["duration_seconds"] == 150.0

    def test_multiple_runs_prepended(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        id1 = tracker.record_run(config=_make_run_config(workflow_id="first"))
        id2 = tracker.record_run(config=_make_run_config(workflow_id="second"))

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert len(data["executions"]) == 2
        # Most recent first
        assert data["executions"][0]["id"] == id2
        assert data["executions"][1]["id"] == id1

    def test_max_100_executions(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        # Seed with 100 existing runs
        existing = _empty_runs_data()
        for i in range(100):
            existing["executions"].append({"id": f"old_{i}", "workflow_id": "old"})
        _seed_runs_file(tracker.runs_file, existing)

        tracker.record_run(config=_make_run_config())

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert len(data["executions"]) == 100
        # Newest is first
        assert data["executions"][0]["id"].startswith("run_wf_test_")

    def test_no_error_message_field_when_none(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        tracker.record_run(config=_make_run_config(error_message=None))

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert "error_message" not in data["executions"][0]

    def test_no_metadata_field_when_none(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        tracker.record_run(config=_make_run_config(metadata=None))

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert "metadata" not in data["executions"][0]


# ---------------------------------------------------------------------------
# RunTracker._calculate_duration
# ---------------------------------------------------------------------------


class TestCalculateDuration:
    def test_valid_timestamps(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        result = tracker._calculate_duration("2026-01-01T00:00:00", "2026-01-01T01:00:00")
        assert result == 3600.0

    def test_utc_z_suffix(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        result = tracker._calculate_duration("2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z")
        assert result == 300.0

    def test_invalid_timestamps_return_zero(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        assert tracker._calculate_duration("not-a-date", "also-bad") == 0

    def test_attribute_error_returns_zero(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        # Non-string input triggers AttributeError on .replace()
        assert tracker._calculate_duration(None, None) == 0


# ---------------------------------------------------------------------------
# RunTracker.update_run
# ---------------------------------------------------------------------------


class TestUpdateRun:
    def test_update_existing_run(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.record_run(config=_make_run_config(status="running"))

        result = tracker.update_run(run_id, {"status": "success", "actions_completed": 5})
        assert result is True

        with open(tracker.runs_file) as f:
            data = json.load(f)
        rec = data["executions"][0]
        assert rec["status"] == "success"
        assert rec["actions_completed"] == 5

    def test_update_with_ended_at_recalculates_duration(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.record_run(
            config=_make_run_config(
                started_at="2026-01-01T00:00:00",
                duration_seconds=0,
            )
        )

        tracker.update_run(run_id, {"ended_at": "2026-01-01T00:10:00"})

        with open(tracker.runs_file) as f:
            data = json.load(f)
        assert data["executions"][0]["duration_seconds"] == 600.0

    def test_update_error_message(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.record_run(config=_make_run_config())

        tracker.update_run(run_id, {"error_message": "something broke"})

        with open(tracker.runs_file) as f:
            data = json.load(f)
        assert data["executions"][0]["error_message"] == "something broke"

    def test_update_nonexistent_run_returns_false(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        tracker.record_run(config=_make_run_config())

        result = tracker.update_run("run_nonexistent_abc123", {"status": "failed"})
        assert result is False

    def test_update_when_no_file_returns_false(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        result = tracker.update_run("run_any_id", {"status": "failed"})
        assert result is False

    def test_update_with_none_updates_is_noop(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.record_run(config=_make_run_config(status="running"))
        result = tracker.update_run(run_id, None)
        # Should still return True (run found, empty updates applied)
        assert result is True

    def test_update_lock_failure_returns_false(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.record_run(config=_make_run_config())

        with patch("portalocker.Lock", side_effect=portalocker.exceptions.LockException("locked")):
            result = tracker.update_run(run_id, {"status": "failed"})
        assert result is False


# ---------------------------------------------------------------------------
# RunTracker.start_workflow_run
# ---------------------------------------------------------------------------


class TestStartWorkflowRun:
    def test_creates_extended_runs_file(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(
            workflow_id="wf1",
            workflow_name="My Workflow",
            actions_total=3,
        )

        assert run_id.startswith("run_wf1_")
        with open(tracker.runs_file) as f:
            data = json.load(f)

        rec = data["executions"][0]
        assert rec["status"] == "running"
        assert rec["total_actions"] == 3
        assert rec["successful_actions"] == 0
        assert rec["failed_actions"] == 0
        assert rec["skipped_actions"] == 0
        assert rec["total_tokens"] == 0
        assert rec["actions"] == {}

    def test_adds_workflow_metrics_key_if_missing(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        # Seed a file without workflow_metrics
        _seed_runs_file(tracker.runs_file, _empty_runs_data(extended=False))

        tracker.start_workflow_run(
            workflow_id="wf1",
            workflow_name="WF",
            actions_total=1,
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)
        assert "workflow_metrics" in data

    def test_corrupted_file_recovery(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        # Write garbage to the file
        tracker.artefact_dir.mkdir(parents=True, exist_ok=True)
        tracker.runs_file.write_text("not json")

        run_id = tracker.start_workflow_run(
            workflow_id="wf1",
            workflow_name="WF",
            actions_total=1,
        )

        assert run_id.startswith("run_wf1_")
        with open(tracker.runs_file) as f:
            data = json.load(f)
        assert len(data["executions"]) == 1


# ---------------------------------------------------------------------------
# RunTracker.record_action_start
# ---------------------------------------------------------------------------


class TestRecordActionStart:
    def test_records_llm_action_start(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=2)

        tracker.record_action_start(
            run_id=run_id,
            action_name="summarize",
            action_type="llm",
            action_config={"model_vendor": "openai", "model_name": "gpt-4"},
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        action = data["executions"][0]["actions"]["summarize"]
        assert action["status"] == "running"
        assert action["type"] == "llm"
        assert action["vendor"] == "openai"
        assert action["model"] == "gpt-4"

    def test_records_tool_action_start(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.record_action_start(
            run_id=run_id,
            action_name="format",
            action_type="tool",
            action_config={"model_name": "formatter_v2"},
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        action = data["executions"][0]["actions"]["format"]
        assert action["type"] == "tool"
        assert action["impl"] == "formatter_v2"

    def test_no_match_run_id_is_noop(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.record_action_start(
            run_id="run_nonexistent_abc",
            action_name="anything",
            action_type="llm",
            action_config={},
        )
        data = json.loads(tracker.runs_file.read_text())
        real_run = next(r for r in data.get("executions", []) if r["id"] == run_id)
        assert "anything" not in real_run.get("actions", {})

    def test_creates_actions_dict_if_missing(self, tmp_path):
        """If a run record somehow lacks the 'actions' key, it is created."""
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        # Remove the actions key manually
        with open(tracker.runs_file) as f:
            data = json.load(f)
        del data["executions"][0]["actions"]
        with open(tracker.runs_file, "w") as f:
            json.dump(data, f)

        tracker.record_action_start(
            run_id=run_id,
            action_name="test_action",
            action_type="llm",
            action_config={},
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)
        assert "test_action" in data["executions"][0]["actions"]


# ---------------------------------------------------------------------------
# RunTracker.record_action_complete
# ---------------------------------------------------------------------------


class TestRecordActionComplete:
    def test_records_successful_action(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)
        tracker.record_action_start(
            run_id=run_id,
            action_name="act1",
            action_type="llm",
            action_config={},
        )

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="act1",
                status="success",
                duration_seconds=2.5,
                tokens={"total_tokens": 100, "prompt_tokens": 60},
                files_processed=3,
            )
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        run = data["executions"][0]
        action = run["actions"]["act1"]
        assert action["status"] == "success"
        assert action["duration_seconds"] == 2.5
        assert action["tokens"]["total_tokens"] == 100
        assert action["files_processed"] == 3
        assert run["successful_actions"] == 1
        assert run["total_tokens"] == 100

    def test_records_failed_action(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)
        tracker.record_action_start(
            run_id=run_id, action_name="act1", action_type="llm", action_config={}
        )

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="act1",
                status="failed",
                duration_seconds=1.0,
                error="timeout",
            )
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        run = data["executions"][0]
        assert run["failed_actions"] == 1
        assert run["actions"]["act1"]["error"] == "timeout"

    def test_records_skipped_action(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)
        tracker.record_action_start(
            run_id=run_id, action_name="act1", action_type="llm", action_config={}
        )

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="act1",
                status="skipped",
                duration_seconds=0.0,
                skip_reason="guard condition false",
            )
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        run = data["executions"][0]
        assert run["skipped_actions"] == 1
        assert run["actions"]["act1"]["skip_reason"] == "guard condition false"

    def test_missing_action_name_is_noop(self, tmp_path):
        """Completing an action that was never started should not crash."""
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="never_started",
                status="success",
                duration_seconds=0.0,
            )
        )
        # No crash — the _update_action_entry short-circuits

    def test_nonexistent_run_id_is_noop(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id="run_ghost_abc",
                action_name="whatever",
                status="success",
                duration_seconds=0.0,
            )
        )
        data = json.loads(tracker.runs_file.read_text())
        real_run = next(r for r in data["executions"] if r["id"] == run_id)
        assert "whatever" not in real_run.get("actions", {})

    def test_no_tokens_field_when_none(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)
        tracker.record_action_start(
            run_id=run_id, action_name="act1", action_type="llm", action_config={}
        )

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="act1",
                status="success",
                duration_seconds=1.0,
                tokens=None,
            )
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert "tokens" not in data["executions"][0]["actions"]["act1"]

    def test_zero_files_processed_not_added(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)
        tracker.record_action_start(
            run_id=run_id, action_name="act1", action_type="llm", action_config={}
        )

        tracker.record_action_complete(
            config=ActionCompleteConfig(
                run_id=run_id,
                action_name="act1",
                status="success",
                duration_seconds=1.0,
                files_processed=0,
            )
        )

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert "files_processed" not in data["executions"][0]["actions"]["act1"]


# ---------------------------------------------------------------------------
# RunTracker.finalize_workflow_run
# ---------------------------------------------------------------------------


class TestFinalizeWorkflowRun:
    def test_finalize_success(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.finalize_workflow_run(run_id=run_id, status="success")

        with open(tracker.runs_file) as f:
            data = json.load(f)

        run = data["executions"][0]
        assert run["status"] == "success"
        assert run["ended_at"] is not None
        assert run["duration_seconds"] > 0 or run["duration_seconds"] == 0
        assert "workflow_metrics" in data

    def test_finalize_with_error(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.finalize_workflow_run(run_id=run_id, status="failed", error_message="crash")

        with open(tracker.runs_file) as f:
            data = json.load(f)

        assert data["executions"][0]["error_message"] == "crash"

    def test_finalize_nonexistent_run_is_noop(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        run_id = tracker.start_workflow_run(workflow_id="wf1", workflow_name="WF", actions_total=1)

        tracker.finalize_workflow_run(run_id="run_ghost_abc", status="success")
        data = json.loads(tracker.runs_file.read_text())
        real_run = next(r for r in data["executions"] if r["id"] == run_id)
        assert real_run.get("status") != "success"


# ---------------------------------------------------------------------------
# RunTracker._calculate_workflow_metrics
# ---------------------------------------------------------------------------


class TestCalculateWorkflowMetrics:
    def test_single_workflow_metrics(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        runs_data = {
            "metadata": {},
            "executions": [
                {
                    "workflow_id": "wf1",
                    "status": "success",
                    "duration_seconds": 10,
                    "total_tokens": 500,
                },
                {
                    "workflow_id": "wf1",
                    "status": "failed",
                    "duration_seconds": 5,
                    "total_tokens": 200,
                },
            ],
        }
        metrics = tracker._calculate_workflow_metrics(runs_data)

        assert metrics["wf1"]["total_runs"] == 2
        assert metrics["wf1"]["successful_runs"] == 1
        assert metrics["wf1"]["failed_runs"] == 1
        assert metrics["wf1"]["success_rate"] == 0.5
        assert metrics["wf1"]["avg_duration_seconds"] == 7.5
        assert metrics["wf1"]["total_tokens"] == 700
        # total_duration should be removed
        assert "total_duration" not in metrics["wf1"]

    def test_multiple_workflows(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        runs_data = {
            "metadata": {},
            "executions": [
                {
                    "workflow_id": "a",
                    "status": "success",
                    "duration_seconds": 10,
                    "total_tokens": 0,
                },
                {"workflow_id": "b", "status": "failed", "duration_seconds": 20, "total_tokens": 0},
            ],
        }
        metrics = tracker._calculate_workflow_metrics(runs_data)
        assert "a" in metrics
        assert "b" in metrics
        assert metrics["a"]["success_rate"] == 1.0
        assert metrics["b"]["success_rate"] == 0.0

    def test_empty_executions(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        metrics = tracker._calculate_workflow_metrics({"metadata": {}, "executions": []})
        assert metrics == {}

    def test_missing_duration_and_tokens_default_to_zero(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        runs_data = {
            "metadata": {},
            "executions": [
                {"workflow_id": "wf1", "status": "success"},
            ],
        }
        metrics = tracker._calculate_workflow_metrics(runs_data)
        assert metrics["wf1"]["avg_duration_seconds"] == 0
        assert metrics["wf1"]["total_tokens"] == 0

    def test_non_string_status_handled(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        runs_data = {
            "metadata": {},
            "executions": [
                {"workflow_id": "wf1", "status": 123, "duration_seconds": 0, "total_tokens": 0},
            ],
        }
        metrics = tracker._calculate_workflow_metrics(runs_data)
        # Should not crash; status is not "success" or "failed"
        assert metrics["wf1"]["successful_runs"] == 0
        assert metrics["wf1"]["failed_runs"] == 0


# ---------------------------------------------------------------------------
# RunTracker._load_runs_data_from_file (corrupted / empty)
# ---------------------------------------------------------------------------


class TestLoadRunsDataFromFile:
    def test_empty_file_returns_empty_structure(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)
        f = MagicMock()
        f.seek = MagicMock()
        f.read = MagicMock(return_value="")

        import io

        buf = io.StringIO("")
        result = tracker._load_runs_data_from_file(buf)
        assert result["executions"] == []
        assert result["metadata"]["total_runs"] == 0

    def test_corrupted_json_returns_empty_structure(self, tmp_path):
        tracker = RunTracker(artefact_dir=tmp_path)

        import io

        buf = io.StringIO("{invalid json")
        result = tracker._load_runs_data_from_file(buf)
        assert result["executions"] == []


# ---------------------------------------------------------------------------
# track_workflow_run (module-level convenience function)
# ---------------------------------------------------------------------------


class TestTrackWorkflowRun:
    def test_delegates_to_run_tracker(self):
        config = _make_run_config()
        with patch(
            "agent_actions.tooling.docs.run_tracker.RunTracker.record_run",
            return_value="run_mock_abc",
        ) as mock_record:
            result = track_workflow_run(config=config)

        assert result == "run_mock_abc"
        mock_record.assert_called_once_with(config=config)
