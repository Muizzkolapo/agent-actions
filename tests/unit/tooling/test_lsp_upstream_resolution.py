"""Tests for LSP upstream action resolution (spec 153).

The LSP indexer must parse upstream: blocks from workflow YAML and register
imported action names so diagnostics, completions, and go-to-definition
resolve cross-workflow references correctly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index


def _create_workflow_project(
    tmp_path: Path,
    workflow_name: str,
    yaml_content: str,
) -> tuple[Path, Path]:
    """Create a minimal agent-actions project. Returns (yaml_file, project_root)."""
    project_root = tmp_path / "project"
    project_root.mkdir(exist_ok=True)
    (project_root / "agent_actions.yml").write_text("version: '1'\n")

    workflow_dir = project_root / "agent_workflow" / workflow_name / "agent_config"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    yaml_file = workflow_dir / "pipeline.yml"
    yaml_file.write_text(textwrap.dedent(yaml_content))
    return yaml_file, project_root


class TestUpstreamActionResolution:
    """Upstream actions declared in upstream: blocks resolve within the declaring workflow."""

    def test_upstream_action_resolves_in_dependencies(self, tmp_path):
        """Action declared in upstream: block resolves when used in dependencies."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Consumes upstream
            upstream:
              - workflow: producer
                actions: [format_quiz_text]
            actions:
              - name: process_quiz
                dependencies: [format_quiz_text]
            """,
        )
        index = build_index(project_root)
        location = index.get_action("format_quiz_text", yaml_file)
        assert location is not None
        assert location.file_path == yaml_file

    def test_upstream_action_resolves_in_context_scope_observe(self, tmp_path):
        """Upstream action resolves when referenced in context_scope.observe."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Consumes upstream
            upstream:
              - workflow: producer
                actions: [format_quiz_text]
            actions:
              - name: process_quiz
                dependencies: [format_quiz_text]
                context_scope:
                  observe:
                    - format_quiz_text.*
            """,
        )
        index = build_index(project_root)

        diagnostics = collect_diagnostics(yaml_file, index)
        error_diagnostics = [d for d in diagnostics if d.severity == lsp.DiagnosticSeverity.Error]
        assert len(error_diagnostics) == 0

    def test_upstream_action_does_not_leak_to_other_workflow(self, tmp_path):
        """Upstream actions scoped to declaring workflow only — not visible elsewhere."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "agent_actions.yml").write_text("version: '1'\n")

        # Workflow A declares upstream action
        wf_a_dir = project_root / "agent_workflow" / "workflow_a" / "agent_config"
        wf_a_dir.mkdir(parents=True)
        wf_a_file = wf_a_dir / "pipeline.yml"
        wf_a_file.write_text(
            textwrap.dedent("""\
            name: workflow_a
            description: Has upstream
            upstream:
              - workflow: producer
                actions: [shared_action]
            actions:
              - name: step_a
                dependencies: [shared_action]
            """)
        )

        # Workflow B does NOT declare upstream — should not see shared_action
        wf_b_dir = project_root / "agent_workflow" / "workflow_b" / "agent_config"
        wf_b_dir.mkdir(parents=True)
        wf_b_file = wf_b_dir / "pipeline.yml"
        wf_b_file.write_text(
            textwrap.dedent("""\
            name: workflow_b
            description: No upstream
            actions:
              - name: step_b
                dependencies: [shared_action]
            """)
        )

        index = build_index(project_root)

        # Resolves in workflow A
        assert index.get_action("shared_action", wf_a_file) is not None

        # Does NOT resolve in workflow B
        assert index.get_action("shared_action", wf_b_file) is None

        # Workflow B should get an error diagnostic for the unresolved ref
        diagnostics_b = collect_diagnostics(wf_b_file, index)
        error_msgs = [
            d.message for d in diagnostics_b if d.severity == lsp.DiagnosticSeverity.Error
        ]
        assert any("shared_action" in msg for msg in error_msgs)

    def test_local_action_takes_priority_over_upstream(self, tmp_path):
        """When a local action has the same name as an upstream, local wins."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Has both local and upstream with same name
            upstream:
              - workflow: producer
                actions: [colliding_action]
            actions:
              - name: colliding_action
                dependencies: []
            """,
        )
        index = build_index(project_root)

        location = index.get_action("colliding_action", yaml_file)
        assert location is not None
        # Should resolve to a specific line (the local action definition), not line 0 (upstream)
        assert location.line > 0

    def test_upstream_action_metadata_resolves(self, tmp_path):
        """get_action_metadata returns minimal ActionMetadata for upstream actions."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Consumes upstream
            upstream:
              - workflow: producer
                actions: [format_quiz_text]
            actions:
              - name: process_quiz
                dependencies: [format_quiz_text]
            """,
        )
        index = build_index(project_root)

        meta = index.get_action_metadata("format_quiz_text", yaml_file)
        assert meta is not None
        assert meta.name == "format_quiz_text"
        assert meta.location.file_path == yaml_file

    def test_multiple_upstream_workflows(self, tmp_path):
        """Actions from multiple upstream workflows all resolve."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Multi-upstream
            upstream:
              - workflow: producer_a
                actions: [action_from_a]
              - workflow: producer_b
                actions: [action_from_b]
            actions:
              - name: process
                dependencies: [action_from_a, action_from_b]
            """,
        )
        index = build_index(project_root)

        assert index.get_action("action_from_a", yaml_file) is not None
        assert index.get_action("action_from_b", yaml_file) is not None

    def test_no_upstream_block_unchanged_behavior(self, tmp_path):
        """Workflows without upstream: continue to work exactly as before."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "simple",
            """\
            name: simple
            description: No upstream
            actions:
              - name: step_one
                dependencies: []
              - name: step_two
                dependencies: [step_one]
            """,
        )
        index = build_index(project_root)

        assert index.get_action("step_one", yaml_file) is not None
        assert index.get_action("step_two", yaml_file) is not None
        assert "simple" not in index.upstream_actions

    def test_malformed_upstream_ignored(self, tmp_path):
        """Malformed upstream entries are silently skipped, not crashes."""
        yaml_file, project_root = _create_workflow_project(
            tmp_path,
            "consumer",
            """\
            name: consumer
            description: Bad upstream
            upstream:
              - not_a_dict
              - workflow: producer
                actions: not_a_list
              - workflow: valid_producer
                actions: [valid_action]
            actions:
              - name: process
                dependencies: [valid_action]
            """,
        )
        index = build_index(project_root)

        # Only the valid entry should be indexed
        assert index.get_action("valid_action", yaml_file) is not None
        # The index should have exactly 1 upstream action for this workflow
        assert len(index.upstream_actions.get("consumer", {})) == 1
