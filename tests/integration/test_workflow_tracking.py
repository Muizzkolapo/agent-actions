"""
Integration tests for end-to-end workflow run tracking.

Tests the complete flow from workflow execution through run tracking
to runs.json persistence. Focuses on breaking changes only.
"""

import json
import pytest
from pathlib import Path


class TestWorkflowTracking:
    """Integration tests for workflow run tracking system."""

    def test_runs_json_structure_valid(self, tmp_path):
        """Test that runs.json has correct structure after tracking."""
        from agent_actions.docs.run_tracker import RunTracker

        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        # Simulate workflow tracking
        run_id = tracker.start_workflow_run('test_workflow', 'Test Workflow', 5)

        tracker.record_action_start(run_id, 'action1', 'llm', {
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        })
        tracker.record_action_complete(
            run_id, 'action1', 'success', 1.5,
            {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
            files_processed=1
        )

        tracker.record_action_start(run_id, 'action2', 'tool', {'impl': 'my_tool'})
        tracker.record_action_complete(run_id, 'action2', 'success', 0.5, None, 0)

        tracker.finalize_workflow_run(run_id, 'SUCCESS')

        # Verify structure
        runs_file = artefact_dir / 'runs.json'
        assert runs_file.exists()

        with open(runs_file) as f:
            data = json.load(f)

        # Verify top-level keys
        assert 'metadata' in data
        assert 'workflow_metrics' in data
        assert 'executions' in data

        # Verify run structure
        run = data['executions'][0]
        assert run['id'] == run_id
        assert run['workflow_id'] == 'test_workflow'
        assert run['status'] == 'SUCCESS'
        assert run['total_actions'] == 5
        assert run['successful_actions'] == 2
        assert 'actions' in run

        # Verify action tracking
        actions = run['actions']
        assert 'action1' in actions
        assert 'action2' in actions

        # LLM action has tokens
        assert actions['action1']['type'] == 'llm'
        assert actions['action1']['tokens']['total_tokens'] == 150

        # Tool action has no tokens
        assert actions['action2']['type'] == 'tool'
        assert actions['action2'].get('tokens') is None

    def test_multiple_actions_tracked(self, tmp_path):
        """Test tracking multiple actions with different statuses."""
        from agent_actions.docs.run_tracker import RunTracker

        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        run_id = tracker.start_workflow_run('multi_action_workflow', 'Multi Action', 4)

        # Success action
        tracker.record_action_start(run_id, 'success_action', 'llm', {})
        tracker.record_action_complete(run_id, 'success_action', 'success', 1.0,
                                      {'total_tokens': 100})

        # Failed action
        tracker.record_action_start(run_id, 'failed_action', 'llm', {})
        tracker.record_action_complete(run_id, 'failed_action', 'failed', 0.5,
                                      error='Test error')

        # Skipped action
        tracker.record_action_start(run_id, 'skipped_action', 'tool', {})
        tracker.record_action_complete(run_id, 'skipped_action', 'skipped', 0.0,
                                      skip_reason='WHERE clause not met')

        tracker.finalize_workflow_run(run_id, 'FAILED')

        # Verify counters
        runs_file = artefact_dir / 'runs.json'
        with open(runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['successful_actions'] == 1
        assert run['failed_actions'] == 1
        assert run['skipped_actions'] == 1
        assert run['status'] == 'FAILED'

        # Verify individual action statuses
        assert run['actions']['success_action']['status'] == 'success'
        assert run['actions']['failed_action']['status'] == 'failed'
        assert run['actions']['failed_action']['error'] == 'Test error'
        assert run['actions']['skipped_action']['status'] == 'skipped'
        assert run['actions']['skipped_action']['skip_reason'] == 'WHERE clause not met'

    def test_workflow_metrics_calculated(self, tmp_path):
        """Test that workflow_metrics are calculated correctly."""
        from agent_actions.docs.run_tracker import RunTracker

        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        workflow_id = 'metrics_test_workflow'

        # First run - success
        run1 = tracker.start_workflow_run(workflow_id, 'Metrics Test', 2)
        tracker.record_action_start(run1, 'action1', 'llm', {})
        tracker.record_action_complete(run1, 'action1', 'success', 1.0,
                                      {'total_tokens': 1000})
        tracker.finalize_workflow_run(run1, 'SUCCESS')

        # Second run - failed
        run2 = tracker.start_workflow_run(workflow_id, 'Metrics Test', 2)
        tracker.record_action_start(run2, 'action1', 'llm', {})
        tracker.record_action_complete(run2, 'action1', 'failed', 0.5,
                                      error='Failed')
        tracker.finalize_workflow_run(run2, 'FAILED')

        # Third run - success
        run3 = tracker.start_workflow_run(workflow_id, 'Metrics Test', 2)
        tracker.record_action_start(run3, 'action1', 'llm', {})
        tracker.record_action_complete(run3, 'action1', 'success', 1.5,
                                      {'total_tokens': 2000})
        tracker.finalize_workflow_run(run3, 'SUCCESS')

        # Verify metrics
        runs_file = artefact_dir / 'runs.json'
        with open(runs_file) as f:
            data = json.load(f)

        metrics = data['workflow_metrics'][workflow_id]
        assert metrics['total_runs'] == 3
        assert metrics['successful_runs'] == 2
        assert metrics['failed_runs'] == 1
        assert metrics['success_rate'] == pytest.approx(0.67, abs=0.01)
        assert metrics['total_tokens'] == 3000  # 1000 + 2000 (only successful)

    def test_token_aggregation(self, tmp_path):
        """Test that tokens are correctly aggregated at run level."""
        from agent_actions.docs.run_tracker import RunTracker

        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        run_id = tracker.start_workflow_run('token_test', 'Token Test', 3)

        # LLM action 1
        tracker.record_action_start(run_id, 'llm1', 'llm', {})
        tracker.record_action_complete(run_id, 'llm1', 'success', 1.0,
                                      {'total_tokens': 500})

        # Tool action (no tokens)
        tracker.record_action_start(run_id, 'tool1', 'tool', {})
        tracker.record_action_complete(run_id, 'tool1', 'success', 0.5, None)

        # LLM action 2
        tracker.record_action_start(run_id, 'llm2', 'llm', {})
        tracker.record_action_complete(run_id, 'llm2', 'success', 1.5,
                                      {'total_tokens': 1500})

        tracker.finalize_workflow_run(run_id, 'SUCCESS')

        # Verify aggregation
        runs_file = artefact_dir / 'runs.json'
        with open(runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['total_tokens'] == 2000  # 500 + 1500

    def test_none_tokens_dont_break(self, tmp_path):
        """Test that tool actions with None tokens don't crash."""
        from agent_actions.docs.run_tracker import RunTracker

        artefact_dir = tmp_path / 'artefact'
        tracker = RunTracker(artefact_dir=artefact_dir)

        run_id = tracker.start_workflow_run('none_tokens_test', 'None Tokens', 2)

        # Tool actions should handle None tokens
        tracker.record_action_start(run_id, 'tool1', 'tool', {})
        tracker.record_action_complete(run_id, 'tool1', 'success', 0.5, None)

        tracker.record_action_start(run_id, 'tool2', 'tool', {})
        tracker.record_action_complete(run_id, 'tool2', 'success', 0.3, None)

        tracker.finalize_workflow_run(run_id, 'SUCCESS')

        # Should not crash and total_tokens should be 0
        runs_file = artefact_dir / 'runs.json'
        with open(runs_file) as f:
            data = json.load(f)

        run = data['executions'][0]
        assert run['total_tokens'] == 0
        assert run['actions']['tool1'].get('tokens') is None
        assert run['actions']['tool2'].get('tokens') is None
