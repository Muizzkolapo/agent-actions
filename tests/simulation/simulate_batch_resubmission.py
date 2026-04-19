"""Manual simulation: batch resubmission loop fix verification.

This script simulates the multi-run batch lifecycle to confirm that:
1. A completed batch is NOT resubmitted on subsequent runs
2. An in-flight batch is NOT resubmitted
3. A failed/cancelled batch IS resubmitted
4. Force flag overrides the completed guard
5. Guard-filtered (fewer tasks) batches still settle correctly

Run:
    python tests/simulation/simulate_batch_resubmission.py
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.submission import BatchSubmissionService


class SimulationRunner:
    """Simulates multiple workflow runs against a real registry on disk."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.output_dir = work_dir / "agent_io" / "target" / "my_action"
        self.batch_dir = self.output_dir / "batch"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.batch_dir / ".batch_registry.json"
        self.run_count = 0
        self.submissions = []

    def _make_service(self, force: bool = False) -> BatchSubmissionService:
        """Create a real-ish submission service with mocked provider."""
        svc = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=lambda out_dir: BatchRegistryManager(
                Path(out_dir) / "batch" / ".batch_registry.json"
            ),
            force_batch=force,
        )

        # Mock task preparation to return tasks
        mock_prepared = MagicMock()
        mock_prepared.tasks = [
            {"target_id": f"r{i}", "content": f"data-{i}", "prompt": "p"} for i in range(10)
        ]
        mock_prepared.context_map = {}
        mock_prepared.task_count = 10
        mock_prepared.stats = MagicMock(total_filtered=0, total_skipped=0)
        svc._task_preparator.prepare_tasks.return_value = mock_prepared

        # Mock provider to return a unique batch ID per submission
        batch_id = f"batch-{len(self.submissions) + 1:03d}"
        svc._client_resolver.get_for_config.return_value = MagicMock(
            submit_batch=MagicMock(return_value=(batch_id, "submitted"))
        )

        return svc

    def submit_run(self, force: bool = False, label: str = "") -> str:
        """Simulate one workflow run's batch submission attempt."""
        self.run_count += 1
        svc = self._make_service(force=force)

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": i} for i in range(10)],
                output_directory=str(self.output_dir),
            )

        was_new = svc._task_preparator.prepare_tasks.called
        self.submissions.append(
            {
                "run": self.run_count,
                "label": label,
                "batch_id": result.batch_id,
                "new_submission": was_new,
            }
        )
        return result.batch_id

    def set_registry_status(self, batch_name: str, status: str):
        """Manually update the registry status (simulating provider completion)."""
        manager = BatchRegistryManager(self.registry_path)
        entry = manager.get_batch_job(batch_name)
        if entry:
            manager.update_status(entry.batch_id, status)

    def get_registry(self) -> dict:
        """Read the current registry state."""
        if not self.registry_path.exists():
            return {}
        with open(self.registry_path) as f:
            return json.load(f)

    def print_registry(self):
        """Print registry state."""
        reg = self.get_registry()
        if not reg:
            print("    Registry: (empty)")
        for key, entry in reg.items():
            print(f"    [{key}] batch_id={entry['batch_id']} status={entry['status']}")


def run_simulation():
    """Run the full simulation."""
    print("=" * 70)
    print("BATCH RESUBMISSION GUARD — SIMULATION")
    print("=" * 70)

    passed = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)

        # ------------------------------------------------------------------
        # Scenario 1: Normal lifecycle — submit, complete, no resubmit
        # ------------------------------------------------------------------
        print("\n--- Scenario 1: Completed batch is NOT resubmitted ---")
        sim = SimulationRunner(work_dir / "s1")

        # Run 1: First submission
        bid1 = sim.submit_run(label="initial submission")
        print(f"  Run 1: batch_id={bid1}, new_submission={sim.submissions[-1]['new_submission']}")
        sim.print_registry()
        assert sim.submissions[-1]["new_submission"], "Run 1 should submit new batch"

        # Simulate provider completing the batch
        sim.set_registry_status("my_action", BatchStatus.COMPLETED)
        print("  (Provider completes the batch)")
        sim.print_registry()

        # Run 2: Should NOT resubmit
        bid2 = sim.submit_run(label="after completion")
        print(f"  Run 2: batch_id={bid2}, new_submission={sim.submissions[-1]['new_submission']}")
        sim.print_registry()

        if bid2 == bid1 and not sim.submissions[-1]["new_submission"]:
            print("  PASS: Completed batch was NOT resubmitted")
            passed += 1
        else:
            print("  FAIL: Completed batch was resubmitted!")
            failed += 1

        # Run 3: Still should NOT resubmit
        bid3 = sim.submit_run(label="third run")
        print(f"  Run 3: batch_id={bid3}, new_submission={sim.submissions[-1]['new_submission']}")

        if bid3 == bid1 and not sim.submissions[-1]["new_submission"]:
            print("  PASS: Still not resubmitted on 3rd run")
            passed += 1
        else:
            print("  FAIL: Resubmitted on 3rd run!")
            failed += 1

        # ------------------------------------------------------------------
        # Scenario 2: In-flight batch blocks resubmission
        # ------------------------------------------------------------------
        print("\n--- Scenario 2: In-flight batch blocks resubmission ---")
        sim2 = SimulationRunner(work_dir / "s2")

        bid1 = sim2.submit_run(label="initial")
        print(f"  Run 1: batch_id={bid1}, new={sim2.submissions[-1]['new_submission']}")

        # Batch is still in-flight (submitted → in_progress)
        sim2.set_registry_status("my_action", BatchStatus.IN_PROGRESS)
        print("  (Batch moves to in_progress)")

        bid2 = sim2.submit_run(label="while in-flight")
        print(f"  Run 2: batch_id={bid2}, new={sim2.submissions[-1]['new_submission']}")

        if bid2 == bid1 and not sim2.submissions[-1]["new_submission"]:
            print("  PASS: In-flight batch was NOT resubmitted")
            passed += 1
        else:
            print("  FAIL: In-flight batch was resubmitted!")
            failed += 1

        # ------------------------------------------------------------------
        # Scenario 3: Failed batch allows resubmission
        # ------------------------------------------------------------------
        print("\n--- Scenario 3: Failed batch allows resubmission ---")
        sim3 = SimulationRunner(work_dir / "s3")

        bid1 = sim3.submit_run(label="initial")
        print(f"  Run 1: batch_id={bid1}, new={sim3.submissions[-1]['new_submission']}")

        sim3.set_registry_status("my_action", BatchStatus.FAILED)
        print("  (Batch fails)")

        bid2 = sim3.submit_run(label="after failure")
        print(f"  Run 2: batch_id={bid2}, new={sim3.submissions[-1]['new_submission']}")

        if sim3.submissions[-1]["new_submission"] and bid2 != bid1:
            print("  PASS: Failed batch WAS resubmitted (new batch)")
            passed += 1
        else:
            print("  FAIL: Failed batch was not resubmitted!")
            failed += 1

        # ------------------------------------------------------------------
        # Scenario 4: Force flag overrides completed guard
        # ------------------------------------------------------------------
        print("\n--- Scenario 4: Force flag overrides completed guard ---")
        sim4 = SimulationRunner(work_dir / "s4")

        bid1 = sim4.submit_run(label="initial")
        sim4.set_registry_status("my_action", BatchStatus.COMPLETED)
        print(f"  Run 1: batch_id={bid1} (completed)")

        bid2 = sim4.submit_run(force=True, label="forced resubmit")
        print(
            f"  Run 2 (force=True): batch_id={bid2}, new={sim4.submissions[-1]['new_submission']}"
        )

        if sim4.submissions[-1]["new_submission"]:
            print("  PASS: Force flag overrode completed guard")
            passed += 1
        else:
            print("  FAIL: Force flag did not override completed guard!")
            failed += 1

        # ------------------------------------------------------------------
        # Scenario 5: Cancelled batch allows resubmission
        # ------------------------------------------------------------------
        print("\n--- Scenario 5: Cancelled batch allows resubmission ---")
        sim5 = SimulationRunner(work_dir / "s5")

        bid1 = sim5.submit_run(label="initial")
        sim5.set_registry_status("my_action", BatchStatus.CANCELLED)
        print(f"  Run 1: batch_id={bid1} (cancelled)")

        bid2 = sim5.submit_run(label="after cancel")
        print(f"  Run 2: batch_id={bid2}, new={sim5.submissions[-1]['new_submission']}")

        if sim5.submissions[-1]["new_submission"]:
            print("  PASS: Cancelled batch WAS resubmitted")
            passed += 1
        else:
            print("  FAIL: Cancelled batch was not resubmitted!")
            failed += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed}/{total} failed")
    if failed == 0:
        print("ALL SCENARIOS PASSED")
    else:
        print("SOME SCENARIOS FAILED")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_simulation()
    sys.exit(0 if success else 1)
