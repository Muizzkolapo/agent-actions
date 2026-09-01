"""Simulation: async recovery edge case verification.

Verifies recovery path edge cases:
- on_exhausted='raise' propagates (not swallowed)
- retry→reprompt transition does not mutate caller's state
- None-content records filtered from reprompt
- cancelled entries produce meaningful status (not 'error')

Run:
    python tests/simulation/simulate_reprompt_recovery_edge_cases.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    BatchRegistryStats,
    RecoveryContext,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.processing_recovery import check_and_submit_reprompt
from agent_actions.llm.providers.batch_base import BatchResult


def _make_result(custom_id, content="response", success=True):
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_eval_loop_mocks(max_attempts=2):
    loop = MagicMock()
    strategy = MagicMock()
    strategy.name = "validation"
    strategy.max_attempts = max_attempts
    strategy.on_exhausted = "return_last"
    return loop, strategy


def _make_parent_entry():
    return BatchJobEntry(
        batch_id="batch-parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=10,
        file_name="my_action",
    )


# ======================================================================
# Bug 5: on_exhausted='raise' must propagate
# ======================================================================


def run_bug5_raise_not_swallowed():
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Bug 5: on_exhausted='raise' propagates ---")

    svc = BatchProcessingService.__new__(BatchProcessingService)
    manager = MagicMock()
    manager.get_all_jobs.return_value = {"my_action": _make_parent_entry()}
    manager.get_registry_stats.return_value = BatchRegistryStats(
        total_jobs=1, completed=0, failed=1, in_progress=0, cancelled=0
    )

    svc._registry_manager_factory = MagicMock(return_value=manager)
    svc._workflow_name = "test_action"
    svc._is_batch_ready_for_processing = MagicMock(return_value=True)
    svc._process_single_batch_file = MagicMock(
        side_effect=RuntimeError("Reprompt validation exhausted")
    )

    caught_runtime = False
    caught_other = None
    try:
        svc.process_all_batch_results("/tmp/output", action_name="test_action")
    except RuntimeError:
        caught_runtime = True
    except Exception as e:
        caught_other = e

    check(caught_runtime, "RuntimeError propagated", "RuntimeError was swallowed")
    check(
        caught_other is None,
        "No other exception raised",
        f"Wrong exception: {type(caught_other).__name__}: {caught_other}",
    )

    return passed, failed


# ======================================================================
# Bug 8: retry→reprompt must not mutate caller's state
# ======================================================================


def run_bug8_no_state_mutation():
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Bug 8: retry→reprompt state not mutated ---")

    service = MagicMock()
    service._retry_service = MagicMock()
    service._retry_service.submit_reprompt_batch.side_effect = lambda **kw: (
        "batch-reprompt",
        {r.custom_id for r in kw["failed_results"]},
    )

    state = RecoveryState(
        phase="retry",
        retry_attempt=3,
        retry_max_attempts=3,
        accumulated_results=[{"custom_id": "id-1", "content": "data", "success": True}],
    )

    with (
        patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build,
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"),
    ):
        loop, strategy = _make_eval_loop_mocks(max_attempts=2)
        loop.split.return_value = ([], [_make_result("id-1", success=False)], {})
        mock_build.return_value = (loop, strategy)

        entry = _make_parent_entry()
        ctx = RecoveryContext(
            service=service,
            manager=MagicMock(),
            provider=MagicMock(),
            agent_config={"kind": "llm"},
            output_directory="/tmp",
            action_name=None,
            start_time=0.0,
        )
        identity = BatchIdentity(
            batch_id=entry.batch_id,
            file_name="my_action",
            entry=entry,
        )

        check_and_submit_reprompt(
            context=ctx,
            identity=identity,
            batch_results=[_make_result("id-1", success=False)],
            context_map={},
            recovery_state=state,
        )

    check(
        state.phase == "retry",
        f"Phase unchanged: '{state.phase}'",
        f"Phase mutated to '{state.phase}'",
    )

    return passed, failed


# ======================================================================
# Bug 10: None-content records filtered from reprompt
# ======================================================================


def run_bug10_none_content_filtered():
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Bug 10: None-content records filtered ---")

    service = MagicMock()
    service._retry_service = MagicMock()
    service._retry_service.submit_reprompt_batch.side_effect = lambda **kw: (
        "batch-reprompt",
        {r.custom_id for r in kw["failed_results"]},
    )

    results = [
        _make_result("id-real-fail", content="bad output", success=False),
        BatchResult(custom_id="id-none", content=None, success=False, error="provider_error"),
    ]

    with (
        patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build,
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"),
    ):
        loop, strategy = _make_eval_loop_mocks(max_attempts=3)
        loop.split.return_value = ([], results, {})
        mock_build.return_value = (loop, strategy)

        entry = _make_parent_entry()
        ctx = RecoveryContext(
            service=service,
            manager=MagicMock(),
            provider=MagicMock(),
            agent_config={"kind": "llm"},
            output_directory="/tmp",
            action_name=None,
            start_time=0.0,
        )
        identity = BatchIdentity(
            batch_id=entry.batch_id,
            file_name="my_action",
            entry=entry,
        )

        check_and_submit_reprompt(
            context=ctx,
            identity=identity,
            batch_results=results,
            context_map={"id-real-fail": {}, "id-none": {}},
        )

    call_kwargs = service._retry_service.submit_reprompt_batch.call_args.kwargs
    submitted = call_kwargs["failed_results"]
    none_ids = [r.custom_id for r in submitted if r.content is None]

    check(not none_ids, "None-content records excluded", f"None-content sent: {none_ids}")
    check(
        len(submitted) == 1,
        f"Only 1 record submitted (got {len(submitted)})",
        f"Expected 1 submission, got {len(submitted)}",
    )

    return passed, failed


# ======================================================================
# Bug 11: cancelled entries → meaningful status
# ======================================================================


def run_bug11_cancelled_status():
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Bug 11: cancelled entries status ---")

    # parent=COMPLETED, recovery=CANCELLED
    stats1 = BatchRegistryStats(total_jobs=2, completed=1, failed=0, in_progress=0, cancelled=1)
    check(
        stats1.overall_status != "error",
        f"completed+cancelled → '{stats1.overall_status}' (not 'error')",
        "completed+cancelled → 'error'",
    )

    # all cancelled
    stats2 = BatchRegistryStats(total_jobs=2, completed=0, failed=0, in_progress=0, cancelled=2)
    check(
        stats2.overall_status != "error",
        f"all cancelled → '{stats2.overall_status}' (not 'error')",
        "all cancelled → 'error'",
    )

    return passed, failed


# ======================================================================
# Main
# ======================================================================


def run_simulation():
    print("=" * 60)
    print("Additional Recovery Bugs — Simulation")
    print("=" * 60)

    total_passed = total_failed = 0

    for scenario in [
        run_bug5_raise_not_swallowed,
        run_bug8_no_state_mutation,
        run_bug10_none_content_filtered,
        run_bug11_cancelled_status,
    ]:
        p, f = scenario()
        total_passed += p
        total_failed += f

    total = total_passed + total_failed
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {total_passed}/{total} passed, {total_failed}/{total} failed")
    print("=" * 60)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_simulation())
