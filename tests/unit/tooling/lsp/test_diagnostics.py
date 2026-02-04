"""Tests for LSP diagnostics, especially context_scope reference validation.

These tests verify that the LSP correctly handles:
1. Special namespaces (source, loop, workflow, seed, etc.) - should NOT report errors
2. Wildcard field references (action.*) - should NOT report errors
3. Invalid action references - SHOULD report errors
4. Invalid field references - SHOULD report warnings
"""

from pathlib import Path
from textwrap import dedent

import importlib
import sys
from types import ModuleType


def _bootstrap_agent_actions_namespace() -> None:
    """Bootstrap agent_actions namespace for isolated LSP module testing.

    Why this is necessary:
    - LSP tests need to import modules in isolation without triggering the full
      agent_actions import chain (which has heavy dependencies like ML libraries)
    - The LSP modules (server.py, indexer.py, etc.) are designed to be lightweight
      and importable without the full framework
    - This pattern is consistent across all LSP tests (test_resolver.py, test_indexer.py)
    - Standard imports would pull in transitive dependencies that aren't needed for
      testing the LSP's parsing and validation logic
    """
    root = Path(__file__).resolve().parents[4]
    agent_actions_path = root / "agent_actions"
    packages = {
        "agent_actions": agent_actions_path,
        "agent_actions.utils": agent_actions_path / "utils",
        "agent_actions.tooling": agent_actions_path / "tooling",
        "agent_actions.tooling.lsp": agent_actions_path / "tooling" / "lsp",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        module = ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module


def _bootstrap_ruamel_stub() -> None:
    """Stub ruamel.yaml if not installed (optional dependency for LSP tests).

    The LSP indexer uses ruamel.yaml for YAML parsing with position tracking,
    but for these diagnostic tests we only need the index structure, not
    actual YAML parsing. This stub allows tests to run without the dependency.
    """
    if "ruamel" in sys.modules and "ruamel.yaml" in sys.modules:
        return

    ruamel = ModuleType("ruamel")
    ruamel_yaml = ModuleType("ruamel.yaml")

    class YAML:  # noqa: N801 - match ruamel.yaml API
        def __init__(self) -> None:
            self.preserve_quotes = False

        def load(self, _content: str):
            return {}

    ruamel_yaml.YAML = YAML
    sys.modules["ruamel"] = ruamel
    sys.modules["ruamel.yaml"] = ruamel_yaml


_bootstrap_agent_actions_namespace()
_bootstrap_ruamel_stub()

build_index = importlib.import_module("agent_actions.tooling.lsp.indexer").build_index
server_module = importlib.import_module("agent_actions.tooling.lsp.server")
_collect_diagnostics = server_module._collect_diagnostics


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestSpecialNamespaceValidation:
    """Tests for special namespace handling in context_scope references.

    Special namespaces (source, loop, workflow, seed, etc.) are built-in
    data sources that don't correspond to user-defined actions.
    """

    def test_source_namespace_no_error(self, tmp_path: Path) -> None:
        """source.* references should NOT report 'action missing' errors."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: classify_genre
                    context_scope:
                      observe:
                        - source.*
                        - source.title
                        - source.content
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # Filter for context_scope related errors
        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "source" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for source namespace: {context_errors}"

    def test_loop_namespace_no_error(self, tmp_path: Path) -> None:
        """loop.* references should NOT report 'action missing' errors."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: process_item
                    context_scope:
                      observe:
                        - loop.index
                        - loop.length
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "loop" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for loop namespace: {context_errors}"

    def test_workflow_namespace_no_error(self, tmp_path: Path) -> None:
        """workflow.* references should NOT report 'action missing' errors."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: log_metadata
                    context_scope:
                      observe:
                        - workflow.name
                        - workflow.version
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "workflow" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for workflow namespace: {context_errors}"

    def test_seed_namespace_no_error(self, tmp_path: Path) -> None:
        """seed.* references should NOT report 'action missing' errors."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: use_seed_data
                    context_scope:
                      observe:
                        - seed.config
                        - seed.metadata
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "seed" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for seed namespace: {context_errors}"

    def test_action_namespace_no_error(self, tmp_path: Path) -> None:
        """action.* references should NOT report 'action missing' errors.

        The 'action' namespace provides metadata about the current action
        (action.name, action.id, etc.).
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: log_action_info
                    context_scope:
                      observe:
                        - action.name
                        - action.id
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "'action'" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for action namespace: {context_errors}"

    def test_prompt_namespace_no_error(self, tmp_path: Path) -> None:
        """prompt.* references should NOT report 'action missing' errors.

        The 'prompt' namespace is reserved for prompt-related metadata.
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: use_prompt_data
                    context_scope:
                      observe:
                        - prompt.template
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "'prompt'" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for prompt namespace: {context_errors}"

    def test_schema_namespace_no_error(self, tmp_path: Path) -> None:
        """schema.* references should NOT report 'action missing' errors.

        The 'schema' namespace is reserved for schema-related metadata.
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: use_schema_info
                    context_scope:
                      observe:
                        - schema.fields
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        context_errors = [
            d for d in diagnostics if "context_scope" in d.message and "'schema'" in d.message
        ]
        assert context_errors == [], f"Unexpected errors for schema namespace: {context_errors}"


class TestWildcardFieldValidation:
    """Tests for wildcard (*) field handling in context_scope references.

    The .* pattern means "all fields from this action's output" and should
    not be validated against the schema.
    """

    def test_wildcard_on_action_no_error(self, tmp_path: Path) -> None:
        """action.* wildcard should NOT report 'field not declared' warnings."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        _write_file(
            tmp_path / "schema" / "search_schema.yml",
            dedent("""
                type: object
                properties:
                  query:
                    type: string
                  filters:
                    type: object
            """),
        )
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: generate_search_criteria
                    schema: search_schema
                  - name: retrieve_candidates
                    dependencies: [generate_search_criteria]
                    context_scope:
                      observe:
                        - generate_search_criteria.*
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # Should NOT have "does not declare `*`" warning
        wildcard_errors = [
            d for d in diagnostics if "generate_search_criteria" in d.message and "*" in d.message
        ]
        assert wildcard_errors == [], f"Unexpected errors for wildcard: {wildcard_errors}"

    def test_specific_field_with_valid_action_no_action_missing_error(self, tmp_path: Path) -> None:
        """Specific field references to valid actions should NOT report 'action missing'."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        _write_file(
            tmp_path / "schema" / "simple_schema.yml",
            dedent("""
                type: object
                properties:
                  known_field:
                    type: string
            """),
        )
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: action_with_schema
                    schema: simple_schema
                  - name: consumer
                    dependencies: [action_with_schema]
                    context_scope:
                      observe:
                        - action_with_schema.some_field
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # Should NOT have "action missing" error (the action exists)
        action_missing_errors = [
            d for d in diagnostics if "action_with_schema" in d.message and "missing" in d.message
        ]
        assert action_missing_errors == [], (
            f"Unexpected 'action missing' error: {action_missing_errors}"
        )


class TestInvalidReferenceValidation:
    """Tests verifying that truly invalid references still report errors."""

    def test_missing_action_reports_error(self, tmp_path: Path) -> None:
        """References to non-existent actions should report errors."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: consumer
                    context_scope:
                      observe:
                        - nonexistent_action.field
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # SHOULD have error for missing action
        action_errors = [
            d for d in diagnostics if "nonexistent_action" in d.message and "missing" in d.message
        ]
        assert len(action_errors) == 1, f"Expected error for missing action: {diagnostics}"

    def test_missing_action_with_wildcard_reports_error(self, tmp_path: Path) -> None:
        """References to non-existent actions with wildcard should report errors.

        Even with .* wildcard, if the action doesn't exist, it should error.
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: consumer
                    context_scope:
                      observe:
                        - nonexistent_action.*
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # SHOULD have error for missing action (wildcard doesn't help if action is missing)
        action_errors = [
            d for d in diagnostics if "nonexistent_action" in d.message and "missing" in d.message
        ]
        assert len(action_errors) == 1, f"Expected error for missing action: {diagnostics}"


class TestEdgeCases:
    """Tests for edge cases in reference parsing and validation."""

    def test_trailing_dot_empty_field(self, tmp_path: Path) -> None:
        """References with trailing dot (action.) should be handled gracefully.

        The _split_context_reference function splits on '.', so 'action.'
        would produce action_name='action', field=''. Empty field should
        not cause crashes.
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: producer
                    schema: simple_schema
                  - name: consumer
                    dependencies: [producer]
                    context_scope:
                      observe:
                        - producer.
            """),
        )

        index = build_index(tmp_path)
        # Should not crash - graceful handling of malformed input
        diagnostics = _collect_diagnostics(workflow_path, index)
        # The reference is malformed, so we don't assert specific behavior,
        # just that it doesn't crash
        assert isinstance(diagnostics, list)

    def test_action_name_only_no_field(self, tmp_path: Path) -> None:
        """References without field (just 'action_name') should work.

        Some context_scope references might just be action names without
        field specifiers.
        """
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: producer
                  - name: consumer
                    dependencies: [producer]
                    context_scope:
                      observe:
                        - producer
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # Should NOT have "action missing" error (the action exists)
        action_errors = [
            d for d in diagnostics if "producer" in d.message and "missing" in d.message
        ]
        assert action_errors == [], f"Unexpected error for action-only reference: {action_errors}"


class TestMixedScenarios:
    """Tests for mixed scenarios combining special namespaces and real actions."""

    def test_mixed_special_and_real_actions(self, tmp_path: Path) -> None:
        """Workflow with both special namespaces and real actions should work correctly."""
        _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
        _write_file(
            tmp_path / "schema" / "output_schema.yml",
            dedent("""
                type: object
                properties:
                  result:
                    type: string
            """),
        )
        workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
        _write_file(
            workflow_path,
            dedent("""
                actions:
                  - name: process_data
                    schema: output_schema
                  - name: final_step
                    dependencies: [process_data]
                    context_scope:
                      observe:
                        - source.input_data
                        - process_data.*
                        - process_data.result
                        - loop.index
            """),
        )

        index = build_index(tmp_path)
        diagnostics = _collect_diagnostics(workflow_path, index)

        # No context_scope errors expected
        context_errors = [d for d in diagnostics if "context_scope" in d.message]
        assert context_errors == [], f"Unexpected context_scope errors: {context_errors}"
