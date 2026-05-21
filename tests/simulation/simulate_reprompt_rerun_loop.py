"""Simulation: async batch reprompt recovery loop fix verification.

Verifies that the recovery loop completes correctly:
1. Recovery entries are consumed (not skipped forever)
2. max_attempts is enforced across multiple runs
3. Graduated pool persists across reruns
4. Attempt counter increments (not stuck at 0)

Run:
    python tests/simulation/simulate_reprompt_rerun_loop.py
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
)
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


# ======================================================================
# Scenario 1: Recovery entry is processed, not skipped
# ======================================================================


def run_recovery_entry_consumed(work_dir):
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Scenario 1: Recovery entry is consumed ---")

    parent_entry = BatchJobEntry(
        batch_id="batch-parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=10,
        file_name="my_action",
    )
    recovery_entry = BatchJobEntry(
        batch_id="batch-recovery",
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-01T00:01:00Z",
        provider="openai",
        record_count=3,
        file_name="my_action_reprompt_1",
        parent_file_name="my_action",
        recovery_type="reprompt",
        recovery_attempt=1,
    )

    manager = MagicMock()
    manager.get_all_jobs.return_value = {
        "my_action": parent_entry,
        "my_action_reprompt_1": recovery_entry,
    }

    svc = BatchProcessingService.__new__(BatchProcessingService)
    svc._registry_manager_factory = MagicMock(return_value=manager)
    svc._action_name = "test_action"
    svc._is_batch_ready_for_processing = MagicMock(return_value=True)

    calls_received = []
    svc._process_single_batch_file = MagicMock(
        side_effect=lambda **kwargs: calls_received.append(kwargs["file_name"])
        or "/tmp/output.json"
    )

    svc.process_all_batch_results(str(work_dir), action_name="test_action")

    check(
        "my_action" in calls_received,
        "Parent entry was processed",
        f"Parent entry missing from {calls_received}",
    )
    check(
        "my_action_reprompt_1" in calls_received,
        "Recovery entry was processed (not skipped)",
        f"Recovery entry skipped! Only processed: {calls_received}",
    )

    return passed, failed


# ======================================================================
# Scenario 2: max_attempts enforced across runs
# ======================================================================


def run_max_attempts_enforced(work_dir):
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Scenario 2: max_attempts enforced across runs ---")

    service = MagicMock()
    service._retry_service = MagicMock()
    service._retry_service.submit_reprompt_batch.return_value = ("batch-reprompt", 1)
    service._retry_service.apply_exhausted_reprompt_metadata = MagicMock()

    entry = BatchJobEntry(
        batch_id="batch-parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=1,
        file_name="my_action",
    )
    results = [_make_result("id-fail", success=False)]

    # Run 1: attempt=0, max=2 → submits with attempt=1
    with (
        patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build,
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager") as mgr,
    ):
        loop, strategy = _make_eval_loop_mocks(max_attempts=2)
        loop.split.return_value = ([], results, {})
        mock_build.return_value = (loop, strategy)

        should_continue = check_and_submit_reprompt(
            service,
            batch_results=results,
            context_map={"id-fail": {}},
            output_directory=str(work_dir),
            file_name="my_action",
            entry=entry,
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=None,
        )

        check(not should_continue, "Run 1: reprompt submitted", "Run 1: expected submission")
        saved_state = mgr.save.call_args[0][2]
        check(
            saved_state.reprompt_attempt == 1,
            f"Run 1: attempt=1 (got {saved_state.reprompt_attempt})",
            f"Run 1: expected attempt=1, got {saved_state.reprompt_attempt}",
        )

    # Run 2: attempt=1, max=2 → submits with attempt=2
    state_run2 = RecoveryState(phase="reprompt", reprompt_attempt=1, reprompt_max_attempts=2)
    with (
        patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build,
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager") as mgr,
    ):
        loop, strategy = _make_eval_loop_mocks(max_attempts=2)
        loop.split.return_value = ([], results, {})
        mock_build.return_value = (loop, strategy)

        should_continue = check_and_submit_reprompt(
            service,
            batch_results=results,
            context_map={"id-fail": {}},
            output_directory=str(work_dir),
            file_name="my_action",
            entry=entry,
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=state_run2,
        )

        check(not should_continue, "Run 2: reprompt submitted", "Run 2: expected submission")
        saved_state = mgr.save.call_args[0][2]
        check(
            saved_state.reprompt_attempt == 2,
            f"Run 2: attempt=2 (got {saved_state.reprompt_attempt})",
            f"Run 2: expected attempt=2, got {saved_state.reprompt_attempt}",
        )

    # Run 3: attempt=2, max=2 → exhausted, no submission
    state_run3 = RecoveryState(phase="reprompt", reprompt_attempt=2, reprompt_max_attempts=2)
    with patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build:
        loop, strategy = _make_eval_loop_mocks(max_attempts=2)
        loop.split.return_value = ([], results, {})
        mock_build.return_value = (loop, strategy)

        should_continue = check_and_submit_reprompt(
            service,
            batch_results=results,
            context_map={},
            output_directory=str(work_dir),
            file_name="my_action",
            entry=entry,
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=state_run3,
        )

        check(
            should_continue is True,
            "Run 3: exhaustion triggered (no more submissions)",
            "Run 3: expected exhaustion but got submission",
        )
        check(
            service._retry_service.apply_exhausted_reprompt_metadata.called,
            "Run 3: exhaustion metadata applied",
            "Run 3: exhaustion metadata NOT applied",
        )

    total_submissions = service._retry_service.submit_reprompt_batch.call_count
    check(
        total_submissions == 2,
        f"Exactly 2 reprompt batches submitted (got {total_submissions})",
        f"Expected 2 submissions, got {total_submissions}",
    )

    return passed, failed


# ======================================================================
# Scenario 3: Graduated pool persists across reruns
# ======================================================================


def run_graduated_pool_persists(work_dir):
    passed = failed = 0

    def check(cond, pass_msg, fail_msg):
        nonlocal passed, failed
        if cond:
            print(f"  PASS: {pass_msg}")
            passed += 1
        else:
            print(f"  FAIL: {fail_msg}")
            failed += 1

    print("\n--- Scenario 3: Graduated pool persists across reruns ---")

    service = MagicMock()
    service._retry_service = MagicMock()
    service._retry_service.submit_reprompt_batch.return_value = ("batch-reprompt", 1)

    entry = BatchJobEntry(
        batch_id="batch-parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=3,
        file_name="my_action",
    )

    # State from prior run: 1 record already graduated
    prior_state = RecoveryState(
        phase="reprompt",
        reprompt_attempt=1,
        reprompt_max_attempts=3,
        graduated_results=[{"custom_id": "id-ok", "content": "good", "success": True}],
    )

    results = [_make_result("id-still-bad", success=False)]

    with (
        patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop") as mock_build,
        patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager") as mgr,
    ):
        loop, strategy = _make_eval_loop_mocks(max_attempts=3)
        loop.split.return_value = ([], results, {})
        mock_build.return_value = (loop, strategy)

        check_and_submit_reprompt(
            service,
            batch_results=results,
            context_map={"id-still-bad": {}},
            output_directory=str(work_dir),
            file_name="my_action",
            entry=entry,
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=prior_state,
        )

        saved_state = mgr.save.call_args[0][2]

        check(
            len(saved_state.graduated_results) > 0,
            f"Graduated results present in saved state ({len(saved_state.graduated_results)} records)",
            "Graduated results lost — empty list saved",
        )
        check(
            saved_state.reprompt_attempt == 2,
            f"Attempt incremented to 2 (got {saved_state.reprompt_attempt})",
            f"Attempt wrong: {saved_state.reprompt_attempt}",
        )

    # Verify original state was NOT mutated (Bug 8 fix)
    check(
        prior_state.phase == "reprompt",
        f"Original state phase unchanged: '{prior_state.phase}'",
        f"Original state mutated! phase='{prior_state.phase}'",
    )

    return passed, failed


# ======================================================================
# Main
# ======================================================================


def run_simulation():
    print("=" * 60)
    print("Reprompt Recovery Loop — Simulation")
    print("=" * 60)

    total_passed = total_failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)

        p, f = run_recovery_entry_consumed(work / "s1")
        total_passed += p
        total_failed += f

        p, f = run_max_attempts_enforced(work / "s2")
        total_passed += p
        total_failed += f

        p, f = run_graduated_pool_persists(work / "s3")
        total_passed += p
        total_failed += f

    total = total_passed + total_failed
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {total_passed}/{total} passed, {total_failed}/{total} failed")
    print("=" * 60)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_simulation())
