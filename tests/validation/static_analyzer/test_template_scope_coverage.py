"""Tests for _check_template_scope_coverage() in the static analyzer.

Verifies that template namespace references must be declared in
context_scope.observe or passthrough. Framework namespaces and source
are always available and should not trigger errors.
"""

from agent_actions.validation.static_analyzer import analyze_workflow


class TestTemplateScopeCoverage:
    """Static analyzer catches template namespaces not covered by context_scope."""

    def test_uncovered_dependency_in_template(self):
        """Template references dep not in context_scope → error."""
        workflow_config = {
            "actions": [
                {
                    "name": "classify",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Classify this",
                    "schema": {"category": "string"},
                },
                {
                    "name": "write_question",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Based on {{ classify.category }}, write a question about {{ source.text }}",
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [
            e for e in result.errors if "template references namespace 'classify'" in e.message
        ]
        assert len(coverage_errors) == 1
        assert "context_scope.observe" in coverage_errors[0].message
        assert "classify.*" in coverage_errors[0].hint

    def test_covered_dependency_no_error(self):
        """Template references dep declared in context_scope → no coverage error."""
        workflow_config = {
            "actions": [
                {
                    "name": "classify",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Classify this",
                    "schema": {"category": "string"},
                },
                {
                    "name": "write_question",
                    "context_scope": {
                        "observe": ["source.*", "classify.category"],
                    },
                    "prompt": "Based on {{ classify.category }}, write about {{ source.text }}",
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

    def test_framework_namespaces_not_flagged(self):
        """version, seed, workflow, loop should not trigger coverage errors."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": (
                        "Item {{ version.i }} of {{ version.length }}. "
                        "Seed: {{ seed.rubric }}. "
                        "Workflow: {{ workflow.name }}. "
                        "Loop: {{ loop.index }}."
                    ),
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

    def test_source_not_flagged(self):
        """source is a special namespace and should not trigger coverage errors."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Process {{ source.text }} with {{ source.title }}",
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

    def test_passthrough_namespace_not_flagged(self):
        """Namespaces in passthrough should not trigger coverage errors."""
        workflow_config = {
            "actions": [
                {
                    "name": "classify",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Classify this",
                    "schema": {"category": "string"},
                },
                {
                    "name": "writer",
                    "context_scope": {
                        "observe": ["source.*"],
                        "passthrough": ["classify.category"],
                    },
                    "prompt": "Write about {{ classify.category }}",
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

    def test_no_prompt_skipped(self):
        """Actions without a prompt (tool/hitl) should be skipped."""
        workflow_config = {
            "actions": [
                {
                    "name": "tool_action",
                    "kind": "tool",
                    "context_scope": {"observe": ["source.*"]},
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

    def test_no_context_scope_skipped(self):
        """Actions without context_scope are skipped (caught by _check_context_scope_required)."""
        workflow_config = {
            "actions": [
                {
                    "name": "processor",
                    "prompt": "{{ classify.category }}",
                    # no context_scope
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        # Should have context_scope_required error, not a coverage error
        coverage_errors = [e for e in result.errors if "template references namespace" in e.message]
        assert len(coverage_errors) == 0

        required_errors = [e for e in result.errors if "has no context_scope" in e.message]
        assert len(required_errors) == 1

    def test_multiple_uncovered_namespaces(self):
        """Multiple uncovered namespaces each get their own error."""
        workflow_config = {
            "actions": [
                {
                    "name": "classify",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Classify",
                    "schema": {"category": "string"},
                },
                {
                    "name": "summarize",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Summarize",
                    "schema": {"summary": "string"},
                },
                {
                    "name": "writer",
                    "context_scope": {"observe": ["source.*"]},
                    "prompt": "Use {{ classify.category }} and {{ summarize.summary }}",
                },
            ]
        }

        result = analyze_workflow(workflow_config)

        coverage_errors = [
            e
            for e in result.errors
            if "template references namespace" in e.message and e.location.agent_name == "writer"
        ]
        uncovered_ns = {e.referenced_agent for e in coverage_errors}
        assert "classify" in uncovered_ns
        assert "summarize" in uncovered_ns
