"""Tests for seed_data/seed_path reference misuse detection in context_scope."""

from agent_actions.validation.static_analyzer import analyze_workflow


class TestSeedReferenceMisuse:
    """Catch common misuse of seed_data/seed_path as a namespace in observe/drop."""

    def test_seed_data_dot_in_observe_triggers_error(self):
        """Using 'seed_data.field' in observe should produce an error."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "observe": ["seed_data.rubric"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [e for e in result.errors if "seed_data.rubric" in e.message]
        assert len(misuse_errors) == 1
        assert "seed.rubric" in misuse_errors[0].message

    def test_seed_path_dot_in_observe_triggers_error(self):
        """Using 'seed_path.field' in observe should produce an error."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "observe": ["seed_path.rubric"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [e for e in result.errors if "seed_path.rubric" in e.message]
        assert len(misuse_errors) == 1
        assert "seed.rubric" in misuse_errors[0].message

    def test_seed_dot_in_observe_no_error(self):
        """Using correct 'seed.field' in observe should not trigger a misuse error."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "observe": ["seed.rubric"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [
            e for e in result.errors if "seed_data" in e.message or "seed_path" in e.message
        ]
        assert len(misuse_errors) == 0

    def test_seed_data_dot_in_drop_triggers_error(self):
        """Using 'seed_data.field' in drop should produce an error."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "drop": ["seed_data.secret"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [e for e in result.errors if "seed_data.secret" in e.message]
        assert len(misuse_errors) == 1
        assert "seed.secret" in misuse_errors[0].message

    def test_seed_data_dot_in_passthrough_triggers_error(self):
        """Using 'seed_data.field' in passthrough should produce an error."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        "passthrough": ["seed_data.metadata"],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [e for e in result.errors if "seed_data.metadata" in e.message]
        assert len(misuse_errors) == 1
        assert "seed.metadata" in misuse_errors[0].message
