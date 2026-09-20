"""Tests for the retry CLI command logic."""

from unittest.mock import MagicMock

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from tests.unit.cli.conftest import make_mock_backend


class TestFindFailures:
    """RetryCommand._find_failures queries disposition table correctly."""

    def test_finds_failed_records(self):
        backend = make_mock_backend(
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
        failures = RetryCommand._find_failures(backend, ["extract", "classify", "enrich"])

        assert "classify" in failures
        assert len(failures["classify"]) == 1
        assert failures["classify"][0]["record_id"] == "r2"

    def test_finds_exhausted_records(self):
        backend = make_mock_backend(
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
        failures = RetryCommand._find_failures(backend, ["extract", "classify"])

        assert "classify" in failures
        assert failures["classify"][0]["record_id"] == "r4"

    def test_no_failures_returns_empty(self):
        backend = make_mock_backend({})
        failures = RetryCommand._find_failures(backend, ["extract", "classify"])
        assert failures == {}

    def test_ignores_success_dispositions(self):
        backend = make_mock_backend(
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
        failures = RetryCommand._find_failures(backend, ["extract", "classify"])
        assert failures == {}

    def test_multiple_actions_with_failures(self):
        backend = make_mock_backend(
            {
                "classify": [
                    {"record_id": "r2", "disposition": "failed", "reason": "error"},
                ],
                "enrich": [
                    {"record_id": "r3", "disposition": "exhausted", "reason": "retry"},
                ],
            }
        )
        failures = RetryCommand._find_failures(backend, ["extract", "classify", "enrich"])
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

        cmd._display_retry_plan(
            "classify",
            [{"record_id": "r2", "disposition": "failed", "reason": "LLM error"}],
            ["extract", "classify", "enrich", "summarize"],
            all_failures={"classify": [{"record_id": "r2"}]},
        )

    def test_display_retry_plan_shows_other_failures(self):
        """When failures exist at later actions, the plan notes them."""
        from io import StringIO

        from rich.console import Console

        args = RetryCommandArgs(agent="test_workflow")
        cmd = RetryCommand(args)
        buf = StringIO()
        cmd.console = Console(file=buf, force_terminal=False, width=120)

        cmd._display_retry_plan(
            "classify",
            [{"record_id": "r2", "disposition": "failed", "reason": "error"}],
            ["extract", "classify", "enrich", "summarize"],
            all_failures={
                "classify": [{"record_id": "r2"}],
                "enrich": [{"record_id": "r5"}],
            },
        )
        output = buf.getvalue()
        assert "enrich" in output
        assert "Run 'retry' again" in output


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


class TestRecordsThisRepairMayProcess:
    """What a repair is allowed to re-run, which is not what it clears."""

    @staticmethod
    def _command(record=None):
        return RetryCommand(RetryCommandArgs(agent="wf", record=record))

    def test_a_failure_below_the_starting_action_joins_the_repair(self):
        repairing = self._command()._records_this_repair_may_process(
            {"r1"},
            ["extract", "classify"],
            {"extract": [{"record_id": "r1"}], "classify": [{"record_id": "r9"}]},
        )
        assert repairing == {"r1", "r9"}

    def test_naming_a_record_excludes_every_other_failure(self):
        repairing = self._command(record="r1")._records_this_repair_may_process(
            {"r1"},
            ["extract", "classify"],
            {"extract": [{"record_id": "r1"}], "classify": [{"record_id": "r9"}]},
        )
        assert repairing == {"r1"}

    def test_a_node_level_failure_alone_selects_nothing(self):
        """An empty selection means "narrow nothing" — the sentinel names an action,
        not a record, so keeping it would narrow every real record out of the run."""
        repairing = self._command()._records_this_repair_may_process(
            {"__node__"}, ["extract"], {"extract": [{"record_id": "__node__"}]}
        )
        assert repairing == set()
