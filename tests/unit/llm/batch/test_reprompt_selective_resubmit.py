"""Regression tests: reprompt resubmits only failed records, not the full batch.

Bug: batch reprompt used to resubmit every record instead of just the ones that
failed validation.  The fix ensures all three code paths — sync
(validate_and_reprompt), async (submit_reprompt_batch), and recovery
(handle_reprompt_recovery) — build reprompt batches containing only the records
that actually failed validation.
"""

import contextlib
from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAIL_IDS = {"rec_003", "rec_007", "rec_009"}


def _make_results(n: int, fail_ids: set[str] | None = None) -> list[BatchResult]:
    """Create *n* successful BatchResults; IDs in *fail_ids* will fail validation."""
    fail_ids = fail_ids or set()
    return [
        BatchResult(
            custom_id=f"rec_{i:03d}",
            content='{"answer": "bad"}'
            if f"rec_{i:03d}" in fail_ids
            else f'{{"answer": "ok_{i}"}}',
            success=True,
        )
        for i in range(n)
    ]


def _make_context_map(n: int) -> dict[str, dict]:
    """Create a context_map with entries for *n* records."""
    return {
        f"rec_{i:03d}": {
            "content": {"question": f"q_{i}"},
            "user_content": f"original prompt {i}",
            "target_id": f"rec_{i:03d}",
        }
        for i in range(n)
    }


def _validation_func_for_bad_content(content):
    """Reject records whose content contains ``"bad"``."""
    return "bad" not in str(content)


def _extract_call_arg(call_obj, keyword, positional_index=0):
    """Extract a named-or-positional arg from a mock call."""
    return call_obj.kwargs.get(
        keyword,
        call_obj.args[positional_index] if len(call_obj.args) > positional_index else None,
    )


@contextlib.contextmanager
def _reprompt_patches():
    """Combined context manager for common reprompt dependency patches."""
    mock_parse = MagicMock()
    mock_parse.return_value = MagicMock(
        validation_name="check_it",
        max_attempts=3,
        on_exhausted="return_last",
    )

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "agent_actions.processing.recovery.reprompt.parse_reprompt_config",
                mock_parse,
            )
        )
        stack.enter_context(
            patch(
                "agent_actions.processing.recovery.response_validator.build_validation_feedback",
                return_value="Please fix",
            )
        )
        stack.enter_context(
            patch(
                "agent_actions.processing.recovery.response_validator.resolve_feedback_strategies",
                return_value=[],
            )
        )
        stack.enter_context(
            patch(
                "agent_actions.llm.batch.services.reprompt_ops._load_source_data_for_reprompt",
                return_value=None,
            )
        )
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSelectiveRepromptResubmission:
    """Prove that only failed records are resubmitted, not the full batch."""

    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_sync_reprompt_submits_only_failures(self, MockPreparator):
        """10 records, 3 fail validation -> retry batch has exactly 3 records."""
        from agent_actions.llm.batch.services.reprompt_ops import validate_and_reprompt

        results = _make_results(10, fail_ids=FAIL_IDS)
        context_map = _make_context_map(10)

        mock_prep = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [MagicMock() for _ in range(3)]
        mock_prep.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_reprompt_1", "submitted")
        provider.retrieve_results.return_value = [
            BatchResult(custom_id=cid, content='{"answer": "fixed"}', success=True)
            for cid in FAIL_IDS
        ]

        with (
            _reprompt_patches(),
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(_validation_func_for_bad_content, "fix it"),
            ),
            patch(
                "agent_actions.llm.batch.services.retry_polling.wait_for_batch_completion",
                return_value="completed",
            ),
        ):
            validate_and_reprompt(
                action_indices={},
                dependency_configs={},
                storage_backend=None,
                results=results,
                provider=provider,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
            )

        assert mock_prep.prepare_tasks.called, "prepare_tasks was never called"
        data_arg = _extract_call_arg(mock_prep.prepare_tasks.call_args, "data")
        assert len(data_arg) == 3
        assert {r["target_id"] for r in data_arg} == FAIL_IDS

    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_async_reprompt_submits_only_failures(self, MockPreparator):
        """submit_reprompt_batch receives only 3 failed results and submits only those."""
        from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch

        failed_results = [
            BatchResult(custom_id=cid, content='{"answer": "bad"}', success=True)
            for cid in FAIL_IDS
        ]
        context_map = _make_context_map(10)

        mock_prep = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [MagicMock() for _ in range(3)]
        mock_prep.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_reprompt_async", "submitted")

        with (
            _reprompt_patches(),
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(lambda x: False, "fix it"),
            ),
        ):
            result = submit_reprompt_batch(
                action_indices={},
                dependency_configs={},
                storage_backend=None,
                provider=provider,
                failed_results=failed_results,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
                attempt=1,
            )

        assert result is not None
        _, count = result
        assert count == 3

        data_arg = _extract_call_arg(mock_prep.prepare_tasks.call_args, "data")
        assert len(data_arg) == 3
        assert {r["target_id"] for r in data_arg} == FAIL_IDS

    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_graduated_records_never_resubmitted(self, MockPreparator):
        """Records that pass validation on attempt 1 do not appear in attempt 2 batch."""
        from agent_actions.llm.batch.services.reprompt_ops import validate_and_reprompt

        persistent_fail = {"rec_001", "rec_002"}
        results = _make_results(5, fail_ids=persistent_fail)
        context_map = _make_context_map(5)

        mock_prep = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [MagicMock(), MagicMock()]
        mock_prep.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_rp", "submitted")
        provider.retrieve_results.return_value = [
            BatchResult(custom_id=cid, content='{"answer": "bad"}', success=True)
            for cid in persistent_fail
        ]

        with (
            _reprompt_patches(),
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(_validation_func_for_bad_content, "fix it"),
            ),
            patch(
                "agent_actions.llm.batch.services.retry_polling.wait_for_batch_completion",
                return_value="completed",
            ),
        ):
            validate_and_reprompt(
                action_indices={},
                dependency_configs={},
                storage_backend=None,
                results=results,
                provider=provider,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
            )

        for call_obj in mock_prep.prepare_tasks.call_args_list:
            data_arg = _extract_call_arg(call_obj, "data")
            assert len(data_arg) == 2, f"Expected 2 records per reprompt batch, got {len(data_arg)}"
            assert {r["target_id"] for r in data_arg} == persistent_fail

    @patch("agent_actions.llm.batch.infrastructure.recovery_state.RecoveryStateManager.save")
    @patch("agent_actions.llm.batch.infrastructure.recovery_state.RecoveryStateManager.delete")
    def test_recovery_cycle_only_evaluates_reprompt_results(self, _mock_delete, _mock_save):
        """handle_reprompt_recovery validates merged results, not the full original batch.

        The recovery path merges reprompt results into accumulated, then validates
        the merged set. Only records that still fail are submitted for another round.
        """
        from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
        from agent_actions.llm.batch.services.processing_recovery import (
            handle_reprompt_recovery,
        )
        from agent_actions.llm.batch.services.retry import BatchRetryService

        accumulated = _make_results(10, fail_ids=set())
        recovery_results = [
            BatchResult(custom_id="rec_003", content='{"answer": "now_ok"}', success=True),
            BatchResult(custom_id="rec_007", content='{"answer": "still_bad"}', success=True),
        ]

        state = RecoveryState(
            phase="reprompt",
            reprompt_attempt=1,
            reprompt_max_attempts=3,
            validation_name="check_it",
            on_exhausted="return_last",
            accumulated_results=BatchRetryService.serialize_results(accumulated),
            reprompt_attempts_per_record={"rec_003": 1, "rec_007": 1},
        )

        service = MagicMock()
        service._retry_service.process_reprompt_results.return_value = accumulated
        service._retry_service.validate_results.return_value = (
            [BatchResult(custom_id="rec_007", content='{"answer": "still_bad"}', success=True)],
            "check_it",
        )
        service._retry_service.submit_reprompt_batch.return_value = ("batch_rp_2", 1)

        entry = MagicMock()
        entry.provider = "openai"
        entry.batch_id = "batch_rp_1"
        manager = MagicMock()

        result = handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=recovery_results,
            accumulated=accumulated,
            context_map=_make_context_map(10),
            output_directory="/tmp/out",
            parent_file_name="batch_1",
            entry=entry,
            agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
            manager=manager,
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        assert result is None

        # Validated the full merged set (10 records), not just recovery batch (2)
        validated_results = _extract_call_arg(
            service._retry_service.validate_results.call_args, "results"
        )
        assert len(validated_results) == 10

        submitted_failures = _extract_call_arg(
            service._retry_service.submit_reprompt_batch.call_args,
            "failed_results",
            positional_index=1,
        )
        assert len(submitted_failures) == 1
        assert submitted_failures[0].custom_id == "rec_007"

    @patch("agent_actions.llm.batch.processing.preparator.BatchTaskPreparator")
    def test_context_map_scoped_to_failing_records(self, MockPreparator):
        """Reprompt only accesses context_map entries for failing records."""
        from agent_actions.llm.batch.services.reprompt_ops import submit_reprompt_batch

        failed_results = [
            BatchResult(custom_id=cid, content='{"answer": "bad"}', success=True)
            for cid in FAIL_IDS
        ]

        # 6 entries: 3 that match FAIL_IDS + 3 that don't
        context_map = {}
        for i in range(10):
            cid = f"rec_{i:03d}"
            entry = MagicMock()
            entry.copy.return_value = {
                "user_content": f"prompt {i}",
                "target_id": cid,
            }
            entry.get = entry.copy.return_value.get
            context_map[cid] = entry

        mock_prep = MockPreparator.return_value
        mock_prepared = MagicMock()
        mock_prepared.tasks = [MagicMock() for _ in range(3)]
        mock_prep.prepare_tasks.return_value = mock_prepared

        provider = MagicMock()
        provider.submit_batch.return_value = ("batch_rp", "submitted")

        with (
            _reprompt_patches(),
            patch(
                "agent_actions.processing.recovery.validation.get_validation_function",
                return_value=(lambda x: False, "fix it"),
            ),
        ):
            submit_reprompt_batch(
                action_indices={},
                dependency_configs={},
                storage_backend=None,
                provider=provider,
                failed_results=failed_results,
                context_map=context_map,
                output_directory="/tmp/out",
                file_name="batch_1",
                agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
                attempt=1,
            )

        accessed_ids = {cid for cid, entry in context_map.items() if entry.copy.called}
        assert accessed_ids == FAIL_IDS


class TestCheckAndSubmitRepromptSelectivity:
    """check_and_submit_reprompt only submits failed records."""

    @patch("agent_actions.llm.batch.infrastructure.recovery_state.RecoveryStateManager.save")
    def test_submits_only_validation_failures(self, _mock_save):
        """check_and_submit_reprompt validates all results but submits only failures."""
        from agent_actions.llm.batch.services.processing_recovery import (
            check_and_submit_reprompt,
        )

        all_results = _make_results(10, fail_ids=set())
        fail_ids = {"rec_003", "rec_007"}
        failed_batch_results = [
            BatchResult(custom_id=cid, content='{"answer": "bad"}', success=True)
            for cid in fail_ids
        ]

        service = MagicMock()
        service._retry_service.validate_results.return_value = (
            failed_batch_results,
            "check_it",
        )
        service._retry_service.submit_reprompt_batch.return_value = ("batch_rp", 2)

        entry = MagicMock()
        entry.provider = "openai"
        manager = MagicMock()

        with patch(
            "agent_actions.processing.recovery.reprompt.parse_reprompt_config",
        ) as mock_parse:
            mock_parse.return_value = MagicMock(
                validation_name="check_it",
                max_attempts=3,
                on_exhausted="return_last",
            )

            result = check_and_submit_reprompt(
                service,
                batch_results=all_results,
                context_map=_make_context_map(10),
                output_directory="/tmp/out",
                file_name="batch_1",
                entry=entry,
                agent_config={"reprompt": {"validation": "check_it", "max_attempts": 3}},
                manager=manager,
                provider=MagicMock(),
            )

        assert result is False

        submitted = _extract_call_arg(
            service._retry_service.submit_reprompt_batch.call_args,
            "failed_results",
            positional_index=1,
        )
        assert len(submitted) == 2
        assert {r.custom_id for r in submitted} == fail_ids
