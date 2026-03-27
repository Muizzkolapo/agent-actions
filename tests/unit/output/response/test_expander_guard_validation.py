"""Tests for guard reference validation in the expander pipeline.

Covers validate_agent_guards, validate_guard_references, and build_schema_registry
from agent_actions.output.response.expander_guard_validation.

Regression coverage for the validate_with_schemas call signature fix (#1107).
"""

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.field_resolution import ReferenceValidator
from agent_actions.output.response.config_schema import WhereClauseConfig
from agent_actions.output.response.expander_guard_validation import (
    build_schema_registry,
    validate_agent_guards,
    validate_guard_references,
)

# =============================================================================
# build_schema_registry
# =============================================================================


class TestBuildSchemaRegistry:
    """build_schema_registry extracts json_output_schema from agent configs."""

    def test_collects_schemas_by_agent_name(self):
        agents = [
            {"agent_type": "extract", "json_output_schema": {"type": "object"}},
            {"agent_type": "classify", "json_output_schema": {"type": "string"}},
        ]
        registry = build_schema_registry(agents)
        assert registry == {
            "extract": {"type": "object"},
            "classify": {"type": "string"},
        }

    def test_skips_agents_without_schema(self):
        agents = [
            {"agent_type": "extract", "json_output_schema": {"type": "object"}},
            {"agent_type": "summarize"},
        ]
        registry = build_schema_registry(agents)
        assert "summarize" not in registry
        assert "extract" in registry

    def test_falls_back_to_name_key(self):
        agents = [{"name": "fallback_agent", "json_output_schema": {"type": "object"}}]
        registry = build_schema_registry(agents)
        assert "fallback_agent" in registry

    def test_empty_agents_list(self):
        assert build_schema_registry([]) == {}


# =============================================================================
# validate_agent_guards — regression for #1107 call signature fix
# =============================================================================


class TestValidateAgentGuards:
    """validate_agent_guards must call validate_with_schemas with correct signature."""

    @pytest.fixture
    def validator(self):
        return ReferenceValidator(strict_dependencies=True)

    @pytest.fixture
    def agent_indices(self):
        return {"extract": 0, "classify": 1}

    @pytest.fixture
    def action_schemas(self):
        return {
            "extract": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            }
        }

    def test_valid_guard_reference_no_errors(self, validator, agent_indices, action_schemas):
        """Agent with a guard referencing a valid upstream action produces no errors."""
        agent = {
            "agent_type": "classify",
            "dependencies": ["extract"],
            "guard": {"clause": "extract.count > 0", "scope": "item"},
        }
        errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        assert errors == []

    def test_invalid_guard_reference_returns_errors(self, validator, agent_indices, action_schemas):
        """Agent referencing a non-existent upstream action produces errors."""
        agent = {
            "agent_type": "classify",
            "guard": {"clause": "nonexistent.count > 0", "scope": "item"},
        }
        errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        assert len(errors) > 0
        assert any("nonexistent" in e for e in errors)

    def test_no_guard_returns_empty(self, validator, agent_indices, action_schemas):
        """Agent without a guard clause produces no errors."""
        agent = {"agent_type": "classify"}
        errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        assert errors == []

    def test_conditional_clause_validated(self, validator, agent_indices, action_schemas):
        """UDF conditional_clause references are also validated."""
        agent = {
            "agent_type": "classify",
            "dependencies": ["extract"],
            "conditional_clause": "extract.count > 0",
        }
        errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        assert errors == []

    def test_conditional_clause_invalid_reference(self, validator, agent_indices, action_schemas):
        """Invalid reference in conditional_clause produces errors."""
        agent = {
            "agent_type": "classify",
            "conditional_clause": "missing_action.field > 0",
        }
        errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        assert len(errors) > 0
        assert any("missing_action" in e for e in errors)


# =============================================================================
# validate_guard_references (end-to-end)
# =============================================================================


class TestValidateGuardReferences:
    """End-to-end validation of guard references across a list of agents."""

    def test_valid_workflow_no_errors(self):
        """Workflow with valid guard references returns empty error list."""
        agents = [
            {
                "agent_type": "extract",
                "json_output_schema": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                },
            },
            {
                "agent_type": "classify",
                "dependencies": ["extract"],
                "guard": {"clause": "extract.count > 0", "scope": "item"},
            },
        ]
        errors = validate_guard_references(agents, strict=False)
        assert errors == []

    def test_invalid_reference_strict_raises(self):
        """Strict mode raises ConfigValidationError on invalid references."""
        agents = [
            {"agent_type": "extract"},
            {
                "agent_type": "classify",
                "guard": {"clause": "nonexistent.count > 0", "scope": "item"},
            },
        ]
        with pytest.raises(ConfigValidationError):
            validate_guard_references(agents, strict=True)

    def test_invalid_reference_non_strict_returns_errors(self):
        """Non-strict mode returns error list instead of raising."""
        agents = [
            {"agent_type": "extract"},
            {
                "agent_type": "classify",
                "guard": {"clause": "nonexistent.count > 0", "scope": "item"},
            },
        ]
        errors = validate_guard_references(agents, strict=False)
        assert len(errors) > 0
        assert any("nonexistent" in e for e in errors)

    def test_no_guards_no_errors(self):
        """Workflow with no guard clauses validates cleanly."""
        agents = [
            {"agent_type": "extract"},
            {"agent_type": "classify"},
        ]
        errors = validate_guard_references(agents, strict=False)
        assert errors == []

    def test_empty_agents_list(self):
        """Empty agent list validates cleanly."""
        errors = validate_guard_references([], strict=False)
        assert errors == []

    def test_empty_agent_name_uses_indexed_fallback(self):
        """Agents with empty string names get distinct unknown_N keys in validate_guard_references."""
        agents = [
            {
                "name": "",
                "json_output_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
            },
            {
                "name": "",
                "dependencies": ["unknown_0"],
                "guard": {"clause": "unknown_0.x > 0", "scope": "item"},
            },
        ]
        # validate_guard_references uses `or f"unknown_{idx}"` for empty names
        errors = validate_guard_references(agents, strict=False)
        assert errors == []


# =============================================================================
# WhereClauseConfig.validate_clause — None guard coverage
# =============================================================================


class TestWhereClauseConfigNoneGuard:
    """Defensive None guard in validate_clause returns None without AttributeError."""

    def test_none_clause_returns_none(self):
        """Calling the validator directly with None returns None (defensive guard)."""
        result = WhereClauseConfig.validate_clause(None)
        assert result is None
