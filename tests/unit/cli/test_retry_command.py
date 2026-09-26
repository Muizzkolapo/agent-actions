"""Tests for the retry CLI command logic."""

from unittest.mock import MagicMock

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
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


class TestDeferredRecordsAreScopedToTheBatchesBeingAbandoned:
    """Abandoning strands the records waiting on the batches it gives up.

    Scoped by action, which the integration fixture cannot check: its workflow
    has one action, so stranding every downstream action and stranding only the
    ones holding an in-flight batch are indistinguishable there.
    """

    @staticmethod
    def _backend(deferred_by_action):
        backend = MagicMock()

        def get_disposition(action_name, record_id=None, disposition=None):
            rows = [
                {"action_name": action_name, "record_id": r, "disposition": "deferred"}
                for r in deferred_by_action.get(action_name, [])
            ]
            return [r for r in rows if disposition in (None, "deferred")]

        backend.get_disposition = MagicMock(side_effect=get_disposition)
        return backend

    def test_only_actions_holding_a_batch_are_read(self):
        backend = self._backend({"summarize": ["r1", "r2"], "score": ["r3"]})

        waiting = RetryCommand._deferred_record_ids(backend, {"summarize"})

        assert waiting == [("summarize", "r1"), ("summarize", "r2")], (
            "records of an action with no batch in flight were swept in"
        )

    def test_the_node_level_sentinel_is_not_a_record(self):
        backend = self._backend({"summarize": ["r1", NODE_LEVEL_RECORD_ID]})

        waiting = RetryCommand._deferred_record_ids(backend, {"summarize"})

        assert waiting == [("summarize", "r1")]

    def test_stranding_writes_one_failure_per_waiting_record(self):
        backend = MagicMock()

        count = RetryCommand._strand_deferred_records(
            backend, [("summarize", "r1"), ("summarize", "r2")]
        )

        assert count == 2
        written = [
            (c.args[0], c.args[1], c.args[2]) for c in backend.set_disposition.call_args_list
        ]
        assert written == [("summarize", "r1", "failed"), ("summarize", "r2", "failed")]


class TestAbandoningStrandsOnlyTheActionsHoldingABatch:
    """Scope decided where it is used, not only in the helper.

    Two downstream actions, one holding an in-flight batch. Abandoning gives up
    that batch, so its waiting records must be moved — and the other action's,
    which no batch of this repair abandons, must be left alone.
    """

    @staticmethod
    def _backend(in_flight_action):
        import json

        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        registry = json.dumps(
            {
                "pages.json": {
                    "batch_id": "b_live",
                    "status": "submitted",
                    "timestamp": "t",
                    "provider": "p",
                }
            }
        )
        backend = MagicMock()
        backend.load_metadata = MagicMock(
            side_effect=lambda key: registry
            if key == f"{BatchRegistryManager.METADATA_KEY_PREFIX}{in_flight_action}"
            else None
        )
        backend.get_disposition = MagicMock(
            side_effect=lambda action, record_id=None, disposition=None: [
                {"record_id": f"{action}_r1", "disposition": "deferred"}
            ]
        )
        return backend

    def test_a_dry_run_counts_only_what_it_would_actually_strand(self):
        """The count is the whole point of the dry-run report, so counting records
        of an action this repair abandons no batch of overstates the cost."""
        backend = self._backend("summarize")
        command = RetryCommand(RetryCommandArgs(agent="wf", abandon_in_flight=True, dry_run=True))
        command.console = MagicMock()

        command._settle_batches_in_flight(backend, ["summarize", "score"])

        backend.set_disposition.assert_not_called()
        reported = " ".join(str(c.args[0]) for c in command.console.print.call_args_list)
        assert "would mark 1 record(s)" in reported, reported

    def test_the_other_action_keeps_its_deferred_records(self):
        backend = self._backend("summarize")
        command = RetryCommand(RetryCommandArgs(agent="wf", abandon_in_flight=True))
        command.console = MagicMock()

        command._settle_batches_in_flight(backend, ["summarize", "score"])

        moved = [c.args[1] for c in backend.set_disposition.call_args_list]
        assert moved == ["summarize_r1"], (
            f"abandoning one action's batch moved another action's records: {moved}"
        )
