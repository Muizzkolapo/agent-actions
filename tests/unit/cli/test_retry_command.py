"""Tests for the retry CLI command logic."""

from unittest.mock import MagicMock

from agent_actions.cli.retry import RetryCommand
from agent_actions.validation.retry_validator import RetryCommandArgs


def _make_backend(dispositions: dict[str, list[dict]] | None = None):
    """Create a mock storage backend with disposition data."""
    dispositions = dispositions or {}
    backend = MagicMock()

    def get_disposition(action_name, record_id=None, disposition=None):
        rows = dispositions.get(action_name, [])
        if disposition:
            rows = [r for r in rows if r.get("disposition") == disposition]
        if record_id:
            rows = [r for r in rows if r.get("record_id") == record_id]
        return rows

    backend.get_disposition = MagicMock(side_effect=get_disposition)
    backend.clear_disposition = MagicMock(return_value=1)
    return backend


class TestFindFailures:
    """RetryCommand._find_failures queries disposition table correctly."""

    def test_finds_failed_records(self):
        backend = _make_backend(
            {
                "classify": [
                    {
                        "record_id": "r2",
                        "disposition": "failed",
                        "reason": "LLM error",
                    }
                ],
            }
        )
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        failures = cmd._find_failures(backend, ["extract", "classify", "enrich"])

        assert "classify" in failures
        assert len(failures["classify"]) == 1
        assert failures["classify"][0]["record_id"] == "r2"

    def test_finds_exhausted_records(self):
        backend = _make_backend(
            {
                "classify": [
                    {
                        "record_id": "r4",
                        "disposition": "exhausted",
                        "reason": "retry_exhausted",
                    }
                ],
            }
        )
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        failures = cmd._find_failures(backend, ["extract", "classify"])

        assert "classify" in failures
        assert failures["classify"][0]["record_id"] == "r4"

    def test_no_failures_returns_empty(self):
        backend = _make_backend({})
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        failures = cmd._find_failures(backend, ["extract", "classify"])
        assert failures == {}

    def test_ignores_success_dispositions(self):
        backend = _make_backend(
            {
                "classify": [
                    {
                        "record_id": "r1",
                        "disposition": "success",
                        "reason": "success",
                    }
                ],
            }
        )
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        failures = cmd._find_failures(backend, ["extract", "classify"])
        assert failures == {}

    def test_multiple_actions_with_failures(self):
        backend = _make_backend(
            {
                "classify": [
                    {"record_id": "r2", "disposition": "failed", "reason": "error"},
                ],
                "enrich": [
                    {"record_id": "r3", "disposition": "exhausted", "reason": "retry"},
                ],
            }
        )
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        failures = cmd._find_failures(backend, ["extract", "classify", "enrich"])
        assert len(failures) == 2
        assert "classify" in failures
        assert "enrich" in failures


class TestRetryPlan:
    """RetryCommand._display_retry_plan builds correct output."""

    def test_display_retry_plan_no_crash(self):
        """Ensure display doesn't crash with valid input."""
        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        cmd.console = MagicMock()

        # Should not raise
        cmd._display_retry_plan(
            "classify",
            [{"record_id": "r2", "disposition": "failed", "reason": "LLM error"}],
            ["extract", "classify", "enrich", "summarize"],
        )


class TestRetryCommandArgs:
    """Validation of retry command arguments."""

    def test_minimal_args(self):
        args = RetryCommandArgs(agent="my_workflow")
        assert args.agent == "my_workflow"
        assert args.from_action is None
        assert args.record is None
        assert args.dry_run is False

    def test_full_args(self):
        args = RetryCommandArgs(
            agent="my_workflow",
            from_action="classify",
            record="r2",
            dry_run=True,
        )
        assert args.from_action == "classify"
        assert args.record == "r2"
        assert args.dry_run is True
