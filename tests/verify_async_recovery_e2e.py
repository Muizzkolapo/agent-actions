"""End-to-end manual verification for async batch recovery (#942).

Wires up real BatchProcessingService, real BatchRegistryManager, real
RecoveryStateManager — only fakes provider responses.

Simulates the full multi-pass workflow:
  Pass 1: Original batch completed, record "b" missing → async retry submitted
  Pass 2: Retry batch completed, "b" returned → finalized (or reprompt if configured)
  Pass 3: (reprompt variant) Reprompt batch completed → finalized

Run: pytest tests/verify_async_recovery_e2e.py -v
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.retry import BatchRetryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(custom_id, content="ok", success=True):
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_context_map(*ids):
    """Build a context map with included records for the given IDs."""
    return {
        cid: {
            "target_id": cid,
            "_batch_filter_status": "included",
            "user_content": f"prompt for {cid}",
        }
        for cid in ids
    }


def _build_service(tmp_path, provider, context_map, result_processor=None):
    """Build a BatchProcessingService with a real registry and mocked deps.

    Uses a single shared BatchRegistryManager instance so the service and
    the test both see the same registry state (shared cache).
    """
    registry_path = tmp_path / "batch" / ".batch_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    shared_manager = BatchRegistryManager(registry_path)

    def registry_factory(output_dir):
        return shared_manager

    client_resolver = MagicMock()
    client_resolver.get_for_batch_id.return_value = provider

    context_manager = MagicMock()
    context_manager.load_batch_context_map.return_value = context_map

    rp = result_processor or MagicMock()
    if not result_processor:
        # Default: pass through batch results as dicts
        rp.process.side_effect = lambda batch_results, **kw: [
            {"custom_id": r.custom_id, "content": r.content, "success": r.success}
            for r in batch_results
        ]

    mock_storage = MagicMock()

    service = BatchProcessingService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        result_processor=rp,
        registry_manager_factory=registry_factory,
        storage_backend=mock_storage,
        action_name="test_agent",
    )

    return service, shared_manager


# ---------------------------------------------------------------------------
# Test: Full retry lifecycle (2-pass)
# ---------------------------------------------------------------------------


class TestRetryLifecycleE2E:
    """Simulate: original batch → missing "b" → async retry → retry completes → finalize."""

    def test_pass1_submits_retry_without_blocking(self, tmp_path):
        """Pass 1: Original batch is completed but record 'b' is missing.
        Should submit an async retry batch and return [] (recovery pending).
        """
        context_map = _make_context_map("a", "b")

        # Provider returns only "a", "b" is missing
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [_make_result("a")]
        provider.submit_batch.return_value = ("retry-batch-1", "submitted")

        service, manager = _build_service(tmp_path, provider, context_map)

        # Seed the registry with the original completed batch
        original_entry = BatchJobEntry(
            batch_id="orig-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
            record_count=2,
            file_name="input.jsonl",
        )
        manager.save_batch_job("input.jsonl", original_entry)

        agent_config = {"retry": {"enabled": True, "max_attempts": 2}}

        # Patch BatchTaskPreparator to avoid real task preparation
        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "retry_b"}])
            mock_prep_cls.return_value = mock_prep

            result = service.process_all_batch_results(str(tmp_path), agent_config=agent_config)

        # No output files yet — recovery is pending
        assert result == [], f"Expected empty, got {result}"

        # Verify: retry batch was registered in registry
        all_jobs = manager.get_all_jobs()
        recovery_entries = {k: v for k, v in all_jobs.items() if v.parent_file_name is not None}
        assert len(recovery_entries) == 1, f"Expected 1 recovery entry, got {len(recovery_entries)}"

        recovery_key = list(recovery_entries.keys())[0]
        recovery_entry = recovery_entries[recovery_key]
        assert recovery_entry.recovery_type == "retry"
        assert recovery_entry.recovery_attempt == 1
        assert recovery_entry.parent_file_name == "input.jsonl"
        assert recovery_entry.batch_id == "retry-batch-1"

        # Verify: recovery state was persisted
        assert RecoveryStateManager.exists(str(tmp_path), "input.jsonl")
        state = RecoveryStateManager.load(str(tmp_path), "input.jsonl")
        assert state is not None
        assert state.phase == "retry"
        assert "b" in state.missing_ids
        assert len(state.accumulated_results) == 1  # "a" is accumulated
        assert state.accumulated_results[0]["custom_id"] == "a"

        # Verify: provider.check_status was NOT called in a polling loop
        # (it was called once by _is_batch_ready_for_processing, that's fine)
        assert provider.check_status.call_count <= 1

        print("  PASS 1: Retry submitted without blocking, state persisted")

    def test_full_lifecycle_via_individual_methods(self, tmp_path):
        """Test the full lifecycle calling methods individually (as the
        corrected process_all_batch_results would)."""
        context_map = _make_context_map("a", "b")

        # --- Pass 1: Original batch, "b" missing ---
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [_make_result("a")]
        provider.submit_batch.return_value = ("retry-batch-1", "submitted")

        service, manager = _build_service(tmp_path, provider, context_map)

        original_entry = BatchJobEntry(
            batch_id="orig-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
            record_count=2,
            file_name="input.jsonl",
        )
        manager.save_batch_job("input.jsonl", original_entry)

        agent_config = {"retry": {"enabled": True, "max_attempts": 2}}

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
        ) as mock_prep_cls:
            mock_prep = MagicMock()
            mock_prep.prepare_tasks.return_value = MagicMock(tasks=[{"body": "retry_b"}])
            mock_prep_cls.return_value = mock_prep

            output = service._process_single_batch_file(
                batch_id="orig-batch-1",
                file_name="input.jsonl",
                entry=original_entry,
                output_directory=str(tmp_path),
                agent_config=agent_config,
                manager=manager,
                action_name="test_agent",
            )

        assert output is None, "Pass 1 should return None (recovery pending)"

        # Verify state
        state = RecoveryStateManager.load(str(tmp_path), "input.jsonl")
        assert state is not None
        assert state.phase == "retry"
        assert "b" in state.missing_ids

        # Verify recovery entry in registry
        all_jobs = manager.get_all_jobs()
        assert any(e.recovery_type == "retry" for e in all_jobs.values())

        retry_key = [k for k, v in all_jobs.items() if v.recovery_type == "retry"][0]
        retry_entry = all_jobs[retry_key]
        assert retry_entry.batch_id == "retry-batch-1"

        print("  PASS 1: Retry submitted, state persisted, recovery entry registered")

        # --- Pass 2: Retry batch completed, "b" is returned ---
        provider.retrieve_results.return_value = [_make_result("b")]

        output = service._process_single_batch_file(
            batch_id="retry-batch-1",
            file_name=retry_key,
            entry=retry_entry,
            output_directory=str(tmp_path),
            agent_config=agent_config,
            manager=manager,
            action_name="test_agent",
        )

        assert output is not None, f"Pass 2 should return output path, got None"
        assert Path(output).name.endswith(".json"), f"Unexpected output: {output}"

        # Verify state was cleaned up
        assert not RecoveryStateManager.exists(str(tmp_path), "input.jsonl"), (
            "Recovery state should be deleted after finalization"
        )

        # Verify recovery entries were cleaned up from registry
        all_jobs = manager.get_all_jobs()
        recovery_entries = {k: v for k, v in all_jobs.items() if v.parent_file_name is not None}
        assert len(recovery_entries) == 0, (
            f"Recovery entries should be cleaned up, but found: {list(recovery_entries.keys())}"
        )

        print("  PASS 2: Retry processed, output written, state and entries cleaned up")


# ---------------------------------------------------------------------------
# Test: Retry exhaustion → output with recovery metadata
# ---------------------------------------------------------------------------


class TestRetryExhaustionE2E:
    """Simulate: retry exhausts all attempts → output includes recovery metadata."""

    def test_exhausted_retry_still_produces_output(self, tmp_path):
        """When all retry attempts fail, output is written with recovery metadata."""
        context_map = _make_context_map("a", "b")

        # Retry batch returns empty — "b" never comes back
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = []

        service, manager = _build_service(tmp_path, provider, context_map)

        # Registry: original + retry_2 (final attempt)
        original_entry = BatchJobEntry(
            batch_id="orig-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
            record_count=2,
            file_name="input.jsonl",
        )
        retry_entry = BatchJobEntry(
            batch_id="retry-batch-2",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:02:00Z",
            provider="openai",
            record_count=1,
            file_name="input.jsonl_retry_2",
            parent_file_name="input.jsonl",
            recovery_type="retry",
            recovery_attempt=2,
        )
        manager.save_batch_job("input.jsonl", original_entry)
        manager.save_batch_job("input.jsonl_retry_2", retry_entry)

        # State: attempt 2 of max 2 (final attempt)
        state = RecoveryState(
            phase="retry",
            retry_attempt=2,
            retry_max_attempts=2,
            missing_ids=["b"],
            record_failure_counts={"b": 2},
            accumulated_results=BatchRetryService.serialize_results([_make_result("a")]),
        )
        RecoveryStateManager.save(str(tmp_path), "input.jsonl", state)

        agent_config = {"retry": {"enabled": True, "max_attempts": 2}}

        output = service._process_single_batch_file(
            batch_id="retry-batch-2",
            file_name="input.jsonl_retry_2",
            entry=retry_entry,
            output_directory=str(tmp_path),
            agent_config=agent_config,
            manager=manager,
            action_name="test_agent",
        )

        assert output is not None, "Should produce output even with exhausted retries"
        assert not RecoveryStateManager.exists(str(tmp_path), "input.jsonl")

        # Verify the result_processor received exhausted_recovery metadata
        rp = service._result_processor
        call_kwargs = rp.process.call_args
        exhausted = call_kwargs.kwargs.get("exhausted_recovery") or call_kwargs[1].get(
            "exhausted_recovery"
        )
        assert exhausted is not None, "exhausted_recovery should be passed to result_processor"
        assert "b" in exhausted
        assert exhausted["b"].retry.succeeded is False
        # Failure count: 2 (from state) + 1 (this attempt returned empty) = 3
        assert exhausted["b"].retry.failures == 3

        print("  PASS: Exhausted retry produces output with recovery metadata")


# ---------------------------------------------------------------------------
# Test: Reprompt lifecycle
# ---------------------------------------------------------------------------


class TestRepromptLifecycleE2E:
    """Simulate: all records received but validation fails → async reprompt."""

    def test_reprompt_submitted_without_blocking(self, tmp_path):
        """Pass 1: All records received, validation fails → reprompt submitted."""
        context_map = _make_context_map("a")

        # Provider returns "a" but it will fail validation
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [_make_result("a", content="bad json")]
        provider.submit_batch.return_value = ("reprompt-batch-1", "submitted")

        service, manager = _build_service(tmp_path, provider, context_map)

        original_entry = BatchJobEntry(
            batch_id="orig-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
            record_count=1,
            file_name="input.jsonl",
        )
        manager.save_batch_job("input.jsonl", original_entry)

        agent_config = {
            "reprompt": {
                "validation": "check_json",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            }
        }

        # Mock validate_results to return the failed result
        failed_result = _make_result("a", content="bad json", success=False)
        with (
            patch.object(
                service._retry_service,
                "validate_results",
                return_value=([failed_result], "check_json"),
            ),
            patch.object(
                service._retry_service,
                "submit_reprompt_batch",
                return_value=("reprompt-batch-1", 1),
            ),
        ):
            output = service._process_single_batch_file(
                batch_id="orig-batch-1",
                file_name="input.jsonl",
                entry=original_entry,
                output_directory=str(tmp_path),
                agent_config=agent_config,
                manager=manager,
                action_name="test_agent",
            )

        assert output is None, "Should return None (reprompt pending)"

        # Verify reprompt entry registered
        all_jobs = manager.get_all_jobs()
        reprompt_entries = {k: v for k, v in all_jobs.items() if v.recovery_type == "reprompt"}
        assert len(reprompt_entries) == 1
        entry = list(reprompt_entries.values())[0]
        assert entry.batch_id == "reprompt-batch-1"
        assert entry.parent_file_name == "input.jsonl"

        # Verify state
        state = RecoveryStateManager.load(str(tmp_path), "input.jsonl")
        assert state is not None
        assert state.phase == "reprompt"
        assert state.reprompt_attempt == 1

        print("  PASS: Reprompt submitted without blocking, state persisted")


# ---------------------------------------------------------------------------
# Test: Recovery state cleanup on finalization
# ---------------------------------------------------------------------------


class TestRecoveryCleanupE2E:
    """Verify state files and registry entries are cleaned up after finalization."""

    def test_cleanup_after_successful_finalization(self, tmp_path):
        """After finalization, recovery state and registry entries should be gone."""
        context_map = _make_context_map("a", "b")

        # Retry returns "b" successfully
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [_make_result("b")]

        service, manager = _build_service(tmp_path, provider, context_map)

        original_entry = BatchJobEntry(
            batch_id="orig-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:00:00Z",
            provider="openai",
            record_count=2,
            file_name="input.jsonl",
        )
        retry_entry = BatchJobEntry(
            batch_id="retry-batch-1",
            status=BatchStatus.COMPLETED,
            timestamp="2024-01-01T00:01:00Z",
            provider="openai",
            record_count=1,
            file_name="input.jsonl_retry_1",
            parent_file_name="input.jsonl",
            recovery_type="retry",
            recovery_attempt=1,
        )
        manager.save_batch_job("input.jsonl", original_entry)
        manager.save_batch_job("input.jsonl_retry_1", retry_entry)

        state = RecoveryState(
            phase="retry",
            retry_attempt=1,
            retry_max_attempts=2,
            missing_ids=["b"],
            record_failure_counts={"b": 1},
            accumulated_results=BatchRetryService.serialize_results([_make_result("a")]),
        )
        RecoveryStateManager.save(str(tmp_path), "input.jsonl", state)

        # Pre-check: state and recovery entry exist
        assert RecoveryStateManager.exists(str(tmp_path), "input.jsonl")
        assert len([v for v in manager.get_all_jobs().values() if v.parent_file_name]) == 1

        # Process the retry entry (Branch B)
        output = service._process_single_batch_file(
            batch_id="retry-batch-1",
            file_name="input.jsonl_retry_1",
            entry=retry_entry,
            output_directory=str(tmp_path),
            agent_config={"retry": {"enabled": True, "max_attempts": 2}},
            manager=manager,
            action_name="test_agent",
        )

        assert output is not None

        # Post-check: state file cleaned up
        assert not RecoveryStateManager.exists(str(tmp_path), "input.jsonl"), (
            "Recovery state file should be deleted"
        )

        # Post-check: recovery registry entries cleaned up
        remaining_recovery = [
            v for v in manager.get_all_jobs().values() if v.parent_file_name is not None
        ]
        assert len(remaining_recovery) == 0, (
            f"Recovery entries should be removed, found: {remaining_recovery}"
        )

        print("  PASS: State file and registry entries cleaned up after finalization")


# ---------------------------------------------------------------------------
# Test: Workflow manager re-check pattern
# ---------------------------------------------------------------------------


class TestWorkflowManagerRecheck:
    """Verify handle_batch_agent returns 'in_progress' when recovery is pending."""

    def test_returns_in_progress_after_recovery_submission(self, tmp_path):
        """After processing submits a recovery batch, handle_batch_agent should
        detect the new in_progress entry and return (None, 'in_progress')."""
        from agent_actions.workflow.managers.batch import BatchLifecycleManager

        batch_service = MagicMock()

        # First call: registry says completed
        # After processing: registry says in_progress (recovery batch submitted)
        batch_service.get_batch_registry_status.side_effect = [
            "completed",
            "in_progress",
        ]
        batch_service.process_all_batch_results.return_value = []

        lifecycle = BatchLifecycleManager(batch_service, storage_backend=MagicMock())

        output_folder, status = lifecycle.handle_batch_agent(
            agent_name="test_agent",
            output_directory=str(tmp_path),
            agent_config={"retry": {"enabled": True}},
        )

        assert output_folder is None
        assert status == "in_progress"

        # Verify process_all_batch_results was called
        batch_service.process_all_batch_results.assert_called_once()

        print("  PASS: Workflow manager detects recovery and returns in_progress")
