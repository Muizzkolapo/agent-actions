"""Tests for seed_data/seed_path reference misuse detection in context_scope."""

import pytest

from agent_actions.validation.static_analyzer import analyze_workflow


class TestSeedReferenceMisuse:
    """Catch common misuse of seed_data/seed_path as a namespace in observe/drop."""

    @pytest.mark.parametrize(
        ("directive", "ref", "suggestion"),
        [
            ("observe", "seed_data.rubric", "seed.rubric"),
            ("observe", "seed_path.rubric", "seed.rubric"),
            ("observe", "static_data.rubric", "seed.rubric"),
            ("drop", "seed_data.secret", "seed.secret"),
            ("passthrough", "seed_data.metadata", "seed.metadata"),
        ],
        ids=[
            "seed_data-observe",
            "seed_path-observe",
            "static_data-observe",
            "seed_data-drop",
            "seed_data-passthrough",
        ],
    )
    def test_misused_namespace_dot_triggers_error(self, directive, ref, suggestion):
        """A retired seed namespace used as 'ns.field' errors and suggests 'seed.field'."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {
                        directive: [ref],
                    },
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        misuse_errors = [e for e in result.errors if ref in e.message]
        assert len(misuse_errors) == 1
        assert suggestion in misuse_errors[0].message

    def test_removed_seed_directive_reported_not_crashed(self):
        """A workflow still using the retired seed_path directive yields a collected
        validation error (analyze does not raise mid-pass)."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {"seed_path": {"rubric": "$file:rubric.json"}},
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        rename_errors = [
            e for e in result.errors if "seed_path" in e.message and "seed" in e.message
        ]
        assert len(rename_errors) >= 1

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
