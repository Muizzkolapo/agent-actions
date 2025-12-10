"""Tests for RunTracker - Essential breaking change tests only."""
import pytest
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from agent_actions.docs.run_tracker import RunTracker


@pytest.fixture
def run_tracker(tmp_path):
    """Create RunTracker instance with temp file."""
    artefact_dir = tmp_path / 'artefact'
    return RunTracker(artefact_dir=artefact_dir)


class TestRunTrackerCore:
    """Test suite for RunTracker core functionality."""

    def test_start_workflow_run_creates_valid_structure(self, run_tracker):
        """Verify runs.json structure is valid."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test Workflow', 10)

        # Read file directly
        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        # Breaking change checks only
        assert 'metadata' in data
        assert 'workflow_metrics' in data
        assert 'executions' in data
        assert len(data['executions']) == 1
        assert data['executions'][0]['id'] == run_id
        assert data['executions'][0]['status'] == 'running'
        assert data['executions'][0]['actions'] == {}
        assert data['executions'][0]['total_actions'] == 10

    def test_record_action_start_creates_action_entry(self, run_tracker):
        """Verify action entry is created with correct fields."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)

        run_tracker.record_action_start(
            run_id, 'test_action', 'llm',
            {'model_vendor': 'openai', 'model_name': 'gpt-4'}
        )

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        actions = data['executions'][0]['actions']
        assert 'test_action' in actions
        assert actions['test_action']['status'] == 'running'
        assert actions['test_action']['type'] == 'llm'
        assert actions['test_action']['model_vendor'] == 'openai'
        assert actions['test_action']['model_name'] == 'gpt-4'

    def test_record_action_complete_success_updates_counters(self, run_tracker):
        """Verify successful action updates counters and tokens."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.record_action_start(run_id, 'action1', 'llm', {})

        run_tracker.record_action_complete(
            run_id, 'action1', 'success',
            duration_seconds=1.5,
            tokens={'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}
        )

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['successful_actions'] == 1
        assert run['total_tokens'] == 150
        assert run['actions']['action1']['status'] == 'success'
        assert run['actions']['action1']['tokens']['total_tokens'] == 150

    def test_record_action_complete_failed_updates_counters(self, run_tracker):
        """Verify failed action updates failed counter."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.record_action_start(run_id, 'action1', 'llm', {})

        run_tracker.record_action_complete(
            run_id, 'action1', 'failed',
            duration_seconds=1.0,
            error='Test error'
        )

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['failed_actions'] == 1
        assert run['actions']['action1']['status'] == 'failed'
        assert run['actions']['action1']['error'] == 'Test error'

    def test_record_action_complete_skipped_updates_counters(self, run_tracker):
        """Verify skipped action updates skipped counter."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.record_action_start(run_id, 'action1', 'llm', {})

        run_tracker.record_action_complete(
            run_id, 'action1', 'skipped',
            duration_seconds=0.1,
            skip_reason='WHERE clause'
        )

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['skipped_actions'] == 1
        assert run['actions']['action1']['status'] == 'skipped'
        assert run['actions']['action1']['skip_reason'] == 'WHERE clause'

    def test_finalize_workflow_run_sets_status(self, run_tracker):
        """Verify finalization sets status and timing."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)

        run_tracker.finalize_workflow_run(run_id, 'SUCCESS')

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['status'] == 'SUCCESS'
        assert run['ended_at'] is not None
        assert run['duration_seconds'] > 0

    def test_calculate_workflow_metrics_populates_correctly(self, run_tracker):
        """Verify workflow_metrics are calculated correctly."""
        # Create 2 successful runs
        run_id1 = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.finalize_workflow_run(run_id1, 'SUCCESS')

        run_id2 = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.finalize_workflow_run(run_id2, 'SUCCESS')

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        metrics = data['workflow_metrics']['test_wf']
        assert metrics['total_runs'] == 2
        assert metrics['successful_runs'] == 2
        assert metrics['success_rate'] == 1.0

    def test_tokens_none_doesnt_break(self, run_tracker):
        """Tool actions or providers without usage shouldn't crash."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 1)
        run_tracker.record_action_start(run_id, 'tool_action', 'tool', {})

        # No tokens provided (None)
        run_tracker.record_action_complete(
            run_id, 'tool_action', 'success',
            duration_seconds=0.5,
            tokens=None
        )

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['successful_actions'] == 1
        assert run['total_tokens'] == 0  # Not incremented

    def test_concurrent_writes_dont_corrupt(self, run_tracker):
        """Critical: Ensure file locks prevent corruption."""
        run_id = run_tracker.start_workflow_run('test_wf', 'Test', 10)

        def record_action(i):
            run_tracker.record_action_start(run_id, f'action_{i}', 'llm', {})
            run_tracker.record_action_complete(
                run_id, f'action_{i}', 'success',
                duration_seconds=0.1
            )

        # 10 concurrent writes
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(record_action, range(10)))

        with open(run_tracker.runs_file) as f:
            data = json.load(f)  # Must be valid JSON

        run = data['executions'][0]
        assert len(run['actions']) == 10  # All recorded
        assert run['successful_actions'] == 10

    def test_multiple_workflows_tracked_separately(self, run_tracker):
        """Verify multiple workflows have separate metrics."""
        run_id1 = run_tracker.start_workflow_run('workflow_a', 'Workflow A', 1)
        run_id2 = run_tracker.start_workflow_run('workflow_b', 'Workflow B', 1)

        run_tracker.finalize_workflow_run(run_id1, 'SUCCESS')
        run_tracker.finalize_workflow_run(run_id2, 'SUCCESS')

        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        assert len(data['executions']) == 2
        assert 'workflow_a' in data['workflow_metrics']
        assert 'workflow_b' in data['workflow_metrics']

    def test_file_created_if_not_exists(self, tmp_path):
        """Breaking: Must create file on first use."""
        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        assert not tracker.runs_file.exists()

        tracker.start_workflow_run('test_wf', 'Test', 1)

        assert tracker.runs_file.exists()

    def test_end_to_end_workflow_tracking(self, run_tracker):
        """Smoke test: Complete workflow lifecycle."""
        # Start
        run_id = run_tracker.start_workflow_run('quiz_gen', 'Quiz Generator', 3)

        # Track 3 actions
        for i in range(3):
            run_tracker.record_action_start(run_id, f'action_{i}', 'llm', {})
            run_tracker.record_action_complete(
                run_id, f'action_{i}', 'success',
                duration_seconds=1.0,
                tokens={'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}
            )

        # Finalize
        run_tracker.finalize_workflow_run(run_id, 'SUCCESS')

        # Verify complete structure
        with open(run_tracker.runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['status'] == 'SUCCESS'
        assert run['successful_actions'] == 3
        assert run['total_tokens'] == 450
        assert len(run['actions']) == 3
        assert data['workflow_metrics']['quiz_gen']['total_runs'] == 1
