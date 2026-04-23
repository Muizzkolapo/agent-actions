"""Reproduction script for bug 16: 7 false-positive preflight validation errors.

Each test function creates a minimal workflow config that previously triggered
a false positive, runs the relevant validator, and asserts the false positive
is gone while real errors are still caught.

Run::

    python tests/manual/repro_bug_16_preflight_issues.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Issue 1: Array fields missing ``items`` definition
# ---------------------------------------------------------------------------


def test_issue_1_array_without_items():
    """type: array without items should NOT produce an error."""
    from agent_actions.validation.static_analyzer.schema_structure_validator import (
        SchemaStructureValidator,
    )

    validator = SchemaStructureValidator()

    # Unified format
    schema = {
        "fields": [
            {"id": "options", "type": "array"},
        ],
    }
    errors = validator.validate_schema(schema, "test_action")
    assert not errors, f"Issue 1 (unified): unexpected errors: {errors}"

    # JSON Schema format
    schema = {"type": "array"}
    errors = validator.validate_schema(schema, "test_action")
    assert not errors, f"Issue 1 (json-schema): unexpected errors: {errors}"

    print("  PASS: Issue 1 — array without items accepted")


# ---------------------------------------------------------------------------
# Issue 2: Object array items missing ``properties``
# ---------------------------------------------------------------------------


def test_issue_2_object_items_without_properties():
    """items: {type: object} without properties should NOT produce an error."""
    from agent_actions.validation.static_analyzer.schema_structure_validator import (
        SchemaStructureValidator,
    )

    validator = SchemaStructureValidator()

    # Unified format
    schema = {
        "fields": [
            {"id": "records", "type": "array", "items": {"type": "object"}},
        ],
    }
    errors = validator.validate_schema(schema, "test_action")
    assert not errors, f"Issue 2 (unified): unexpected errors: {errors}"

    # JSON Schema format
    schema = {"type": "array", "items": {"type": "object"}}
    errors = validator.validate_schema(schema, "test_action")
    assert not errors, f"Issue 2 (json-schema): unexpected errors: {errors}"

    print("  PASS: Issue 2 — object items without properties accepted")


# ---------------------------------------------------------------------------
# Issue 3: camelCase field name mismatch (hitlStatus vs hitl_status)
# ---------------------------------------------------------------------------


def test_issue_3_camel_case_field_name():
    """camelCase field references should match snake_case schema fields."""
    from agent_actions.validation.static_analyzer.data_flow_graph import (
        ActionKind,
        DataFlowGraph,
        DataFlowNode,
        InputRequirement,
        OutputSchema,
    )
    from agent_actions.validation.static_analyzer.type_checker import StaticTypeChecker

    graph = DataFlowGraph()

    # Upstream action with snake_case field (e.g., HITL canonical schema)
    upstream_schema = OutputSchema(schema_fields={"hitl_status", "user_comment", "timestamp"})
    upstream = DataFlowNode(
        name="review", agent_kind=ActionKind.HITL, output_schema=upstream_schema
    )
    graph.add_node(upstream)

    # Downstream action references camelCase
    downstream = DataFlowNode(
        name="consumer",
        agent_kind=ActionKind.LLM,
        output_schema=OutputSchema(),
        input_requirements=[
            InputRequirement(
                source_agent="review",
                field_path="hitlStatus",
                raw_reference="{{ review.hitlStatus }}",
                location="prompt",
            ),
        ],
        dependencies={"review"},
    )
    graph.add_node(downstream)
    graph.build_edges_from_requirements()

    checker = StaticTypeChecker(graph)
    result = checker.check_all()

    assert result.is_valid, f"Issue 3: unexpected errors: {[str(e) for e in result.errors]}"
    print("  PASS: Issue 3 — camelCase field accepted (matches snake_case)")


# ---------------------------------------------------------------------------
# Issue 4: {{ loop.index }} treated as action reference
# ---------------------------------------------------------------------------


def test_issue_4_jinja_loop_builtin():
    """{{ loop.index }} inside {% for %} should NOT produce an action reference."""
    from agent_actions.validation.static_analyzer.reference_extractor import (
        ReferenceExtractor,
    )

    extractor = ReferenceExtractor()

    template = """{% for option in reconstruct_options.options %}
{{ loop.index }}. {{ option }}
{% endfor %}"""

    refs = extractor._extract_from_template(template, "test_action", "prompt")

    # Should have refs for reconstruct_options.options but NOT for loop.index
    sources = {r.source_agent for r in refs}
    assert "loop" not in sources, f"Issue 4: 'loop' extracted as action reference: {refs}"
    assert "reconstruct_options" in sources, "reconstruct_options should still be extracted"

    print("  PASS: Issue 4 — loop.index not treated as action reference")


# ---------------------------------------------------------------------------
# Issue 5: Inline schemas don't support dict syntax
# ---------------------------------------------------------------------------


def test_issue_5_inline_dict_schema():
    """Inline schema with dict values should NOT produce an error."""
    from agent_actions.validation.static_analyzer.schema_structure_validator import (
        SchemaStructureValidator,
    )

    validator = SchemaStructureValidator()

    schema = {
        "options": {"type": "array", "items": {"type": "string"}},
        "name": {"type": "string"},
    }
    errors = validator.validate_schema(schema, "test_action")
    assert not errors, f"Issue 5 (structure): unexpected errors: {errors}"

    # Also check the inline schema action validator
    from agent_actions.validation.action_validators.inline_schema_validator import (
        InlineSchemaValidator,
    )

    class FakeContext:
        normalized_entry = {
            "schema": {
                "options": {"type": "array", "items": {"type": "string"}},
                "title": "string",
            }
        }
        description = "test action"

    iv = InlineSchemaValidator()
    result = iv.validate(FakeContext())
    assert not result.errors, f"Issue 5 (inline): unexpected errors: {result.errors}"

    print("  PASS: Issue 5 — inline dict schema syntax accepted")


# ---------------------------------------------------------------------------
# Issue 6: ``name`` property rejected on root-array schemas
# ---------------------------------------------------------------------------


def test_issue_6_name_on_root_array():
    """``name`` property on root-array schemas should NOT be flagged as unknown."""
    from agent_actions.validation.schema_validator import SchemaValidator

    schema = {
        "type": "array",
        "name": "results",
        "items": {"type": "object", "properties": {"id": {"type": "string"}}},
    }
    issues = SchemaValidator._check_common_schema_issues_static(schema, "test_schema")

    # ``name`` should not appear in suspicious keys
    suspicious_msgs = [i for i in issues if "unknown/typo" in i]
    assert not suspicious_msgs, f"Issue 6: name flagged as suspicious: {suspicious_msgs}"

    print("  PASS: Issue 6 — name on root-array schema accepted")


# ---------------------------------------------------------------------------
# Issue 8: Duplicate prompt IDs across files
# ---------------------------------------------------------------------------


def test_issue_8_cross_file_prompt_duplicates():
    """Cross-file prompt ID duplicates should be warnings, not errors."""
    from agent_actions.validation.prompt_validator import PromptValidator

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create two prompt files with overlapping IDs
        (tmppath / "workflow_a.md").write_text(
            "# Workflow A\n\n{prompt Shared_Prompt}\nContent A\n{end_prompt}\n"
        )
        (tmppath / "workflow_b.md").write_text(
            "# Workflow B\n\n{prompt Shared_Prompt}\nContent B\n{end_prompt}\n"
        )

        validator = PromptValidator(fire_events=False)
        validator.validate(tmppath)

        errors = validator.get_errors()
        warnings = validator.get_warnings()

        # Cross-file duplicates should be warnings, not errors
        dup_errors = [e for e in errors if "duplicate" in str(e).lower()]
        dup_warnings = [w for w in warnings if "duplicate" in str(w).lower()]

        assert not dup_errors, f"Issue 8: cross-file duplicates still errors: {dup_errors}"
        assert dup_warnings, "Issue 8: expected a warning for cross-file duplicates"

    print("  PASS: Issue 8 — cross-file prompt duplicates are warnings, not errors")


# ---------------------------------------------------------------------------
# Negative tests: ensure real errors are still caught
# ---------------------------------------------------------------------------


def test_real_errors_still_caught():
    """Verify that legitimate validation errors are not suppressed."""
    from agent_actions.validation.static_analyzer.schema_structure_validator import (
        SchemaStructureValidator,
    )

    validator = SchemaStructureValidator()

    # Invalid type should still error
    schema = {"fields": [{"id": "x", "type": "foobar"}]}
    errors = validator.validate_schema(schema, "test")
    assert errors, "Invalid type 'foobar' should still produce an error"

    # Duplicate field IDs should still error
    schema = {"fields": [{"id": "x", "type": "string"}, {"id": "x", "type": "number"}]}
    errors = validator.validate_schema(schema, "test")
    assert errors, "Duplicate field IDs should still produce an error"

    # Non-existent field reference should still error
    from agent_actions.validation.static_analyzer.data_flow_graph import (
        ActionKind,
        DataFlowGraph,
        DataFlowNode,
        InputRequirement,
        OutputSchema,
    )
    from agent_actions.validation.static_analyzer.type_checker import StaticTypeChecker

    graph = DataFlowGraph()
    upstream = DataFlowNode(
        name="src",
        agent_kind=ActionKind.LLM,
        output_schema=OutputSchema(schema_fields={"real_field"}),
    )
    graph.add_node(upstream)
    downstream = DataFlowNode(
        name="dst",
        agent_kind=ActionKind.LLM,
        output_schema=OutputSchema(),
        input_requirements=[
            InputRequirement(
                source_agent="src",
                field_path="nonExistentField",
                raw_reference="{{ src.nonExistentField }}",
                location="prompt",
            ),
        ],
        dependencies={"src"},
    )
    graph.add_node(downstream)
    graph.build_edges_from_requirements()

    checker = StaticTypeChecker(graph)
    result = checker.check_all()
    assert not result.is_valid, "Reference to truly non-existent field should still error"

    print("  PASS: Negative tests — real errors still caught")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("Reproducing bug 16: 7 false-positive preflight validation errors\n")

    tests = [
        test_issue_1_array_without_items,
        test_issue_2_object_items_without_properties,
        test_issue_3_camel_case_field_name,
        test_issue_4_jinja_loop_builtin,
        test_issue_5_inline_dict_schema,
        test_issue_6_name_on_root_array,
        test_issue_8_cross_file_prompt_duplicates,
        test_real_errors_still_caught,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    else:
        print("All false positives resolved. Real errors still caught.")


if __name__ == "__main__":
    main()
