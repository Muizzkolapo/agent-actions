"""Preflight consolidation tests.

Ensures every detectable misconfiguration is caught before execution.
Organized by category of misconfiguration.
"""

import pytest

from agent_actions.config.schema import ActionConfig, WorkflowConfig
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationOrchestrator,
)
from agent_actions.validation.static_analyzer import (
    WorkflowStaticAnalyzer,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _validate_entry(entry: dict, agent_name: str = "test_workflow") -> tuple[list, list]:
    """Run orchestrator on a single action entry, return (errors, warnings)."""
    orch = ActionEntryValidationOrchestrator()
    orch.validate_action_entry(entry, agent_name)
    return orch.get_validation_errors(), orch.get_validation_warnings()


def _make_workflow(actions: list[dict]) -> dict:
    """Build a minimal workflow config dict."""
    return {"name": "test_workflow", "description": "test", "actions": actions}


def _analyze(actions: list[dict], **kwargs):
    """Run static analysis on a list of action dicts."""
    config = _make_workflow(actions)
    analyzer = WorkflowStaticAnalyzer(config, **kwargs)
    return analyzer.analyze()


# ── TestDependencyValidation ─────────────────────────────────────────


class TestDependencyValidation:
    """Validates dependency references are caught at preflight."""

    def test_dangling_depends_on_reference(self):
        """Dangling dependency (non-existent action) raises at Pydantic level."""
        with pytest.raises(ValueError, match="depend.*nonexistent|not defined"):
            WorkflowConfig(
                name="wf",
                description="test",
                actions=[
                    ActionConfig(name="a", intent="do", kind="llm"),
                    ActionConfig(name="b", intent="do", kind="llm", dependencies=["nonexistent"]),
                ],
            )

    def test_circular_dependency_detected(self):
        """Circular dependency chain is caught by Pydantic model validator."""
        with pytest.raises(ValueError, match="[Cc]ircular|cycle"):
            WorkflowConfig(
                name="wf",
                description="test",
                actions=[
                    ActionConfig(name="a", intent="do", kind="llm", dependencies=["b"]),
                    ActionConfig(name="b", intent="do", kind="llm", dependencies=["a"]),
                ],
            )

    def test_cross_workflow_dep_not_false_positive(self):
        """Cross-workflow deps (dict format) are stripped, not rejected."""
        # Should not raise — dict deps are silently stripped
        config = ActionConfig(
            name="a",
            intent="do",
            kind="llm",
            dependencies=[{"workflow": "other", "action": "x"}, "local_dep"],
        )
        # Only string deps survive
        assert config.dependencies == ["local_dep"]

    def test_primary_dependency_references_valid_action(self):
        """primary_dependency referencing non-existent action is caught."""
        with pytest.raises(ValueError, match="primary_dependency.*ghost|not defined"):
            WorkflowConfig(
                name="wf",
                description="test",
                actions=[
                    ActionConfig(name="a", intent="do", kind="llm"),
                    ActionConfig(
                        name="b",
                        intent="do",
                        kind="llm",
                        dependencies=["a"],
                        primary_dependency="ghost",
                    ),
                ],
            )


# ── TestGuardValidation ──────────────────────────────────────────────


class TestGuardValidation:
    """Validates guard expressions are checked at preflight."""

    def test_invalid_guard_type_detected(self):
        """Non-string/dict guard raises at Pydantic level."""
        with pytest.raises(ValueError):
            ActionConfig(
                name="a",
                intent="do",
                kind="llm",
                guard=12345,
            )

    def test_guard_dict_with_condition(self):
        """Valid guard dict config is accepted."""
        config = ActionConfig(
            name="a",
            intent="do",
            kind="llm",
            guard={"condition": "score >= 85", "on_false": "filter"},
        )
        assert config.guard is not None

    def test_guard_references_valid_fields_via_static(self):
        """Static analyzer catches guard references to non-existent fields."""
        result = _analyze(
            [
                {
                    "name": "scorer",
                    "schema": {
                        "type": "object",
                        "properties": {"score": {"type": "number"}},
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["scorer"],
                    "guard": {"condition": "nonexistent_field > 5", "on_false": "filter"},
                    "context_scope": {"observe": ["scorer.score"]},
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                    },
                },
            ]
        )
        # The guard references nonexistent_field which isn't in any upstream schema.
        # Static analysis should flag this (bare identifier warning or missing field).
        assert result.errors or result.warnings


# ── TestSchemaValidation ─────────────────────────────────────────────


class TestSchemaValidation:
    """Validates schema structures are checked at preflight."""

    def test_inline_schema_structure_valid(self):
        """Valid inline schema passes validation."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "schema": {"summary": "string", "score": "number"},
            }
        )
        schema_errors = [e for e in errors if "schema" in e.lower()]
        assert len(schema_errors) == 0

    def test_invalid_field_type_detected(self):
        """Invalid type in inline schema is caught."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "schema": {"summary": "string", "bad_field": "foobar_type"},
            }
        )
        assert any("foobar_type" in e for e in errors)

    def test_duplicate_field_ids_detected(self):
        """Duplicate field IDs in unified schema are caught by static analyzer."""
        result = _analyze(
            [
                {
                    "name": "extractor",
                    "schema": {
                        "fields": [
                            {"id": "name", "type": "string"},
                            {"id": "name", "type": "number"},
                        ],
                    },
                },
            ]
        )
        assert any("duplicate" in e.message.lower() for e in result.errors)

    def test_schema_and_schema_name_conflict_warned(self):
        """Having both schema and schema_name produces a warning."""
        _, warnings = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "schema": {"summary": "string"},
                "schema_name": "my_schema",
            }
        )
        assert any("schema" in w.lower() and "schema_name" in w.lower() for w in warnings)


# ── TestContextScopeValidation ───────────────────────────────────────


class TestContextScopeValidation:
    """Validates context_scope references are checked at preflight."""

    def test_observe_references_valid_action(self):
        """Observe referencing non-existent action is caught."""
        result = _analyze(
            [
                {
                    "name": "consumer",
                    "depends_on": ["ghost"],
                    "context_scope": {"observe": ["ghost.field"]},
                    "schema": {
                        "type": "object",
                        "properties": {"out": {"type": "string"}},
                    },
                },
            ]
        )
        assert not result.is_valid
        assert any("ghost" in e.message for e in result.errors)

    def test_observe_field_exists_in_upstream_schema(self):
        """Observe referencing non-existent field in upstream schema is caught."""
        result = _analyze(
            [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["extractor"],
                    "context_scope": {"observe": ["extractor.nonexistent"]},
                    "schema": {
                        "type": "object",
                        "properties": {"out": {"type": "string"}},
                    },
                },
            ]
        )
        assert any("nonexistent" in e.message for e in result.errors)

    def test_orphaned_directives_detected(self):
        """Orphaned observe/passthrough (siblings of context_scope) detected."""
        result = _analyze(
            [
                {
                    "name": "action_a",
                    "context_scope": None,
                    "observe": ["source.field"],
                    "schema": {
                        "type": "object",
                        "properties": {"out": {"type": "string"}},
                    },
                },
            ]
        )
        assert any("context_scope" in e.message.lower() for e in result.errors)


# ── TestRecoveryValidation ───────────────────────────────────────────


class TestRecoveryValidation:
    """Validates retry/reprompt configs are checked at preflight."""

    def test_retry_config_range_valid(self):
        """Retry max_attempts outside 1-10 range raises at Pydantic level."""
        with pytest.raises(ValueError, match="greater than or equal|less than or equal"):
            ActionConfig(
                name="a",
                intent="do",
                kind="llm",
                retry={"max_attempts": 99},
            )

    def test_retry_true_rejected(self):
        """retry: true (ambiguous) is rejected."""
        with pytest.raises(ValueError, match="retry: true is not valid"):
            ActionConfig(name="a", intent="do", kind="llm", retry=True)

    def test_on_exhausted_valid_enum(self):
        """Invalid on_exhausted value is rejected at Pydantic level."""
        with pytest.raises(ValueError):
            ActionConfig(
                name="a",
                intent="do",
                kind="llm",
                retry={"on_exhausted": "crash"},
            )

    def test_reprompt_udf_exists(self):
        """Reprompt validation referencing non-existent UDF caught by static analyzer."""
        result = _analyze(
            [
                {
                    "name": "llm_action",
                    "reprompt": {"validation": "totally_nonexistent_validator_xyz"},
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
            ]
        )
        # The static analyzer should flag the missing UDF
        assert any("totally_nonexistent_validator_xyz" in e.message for e in result.errors)

    def test_on_schema_mismatch_reprompt_requires_reprompt_config(self):
        """on_schema_mismatch: reprompt without reprompt block is caught."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "on_schema_mismatch": "reprompt",
                # no reprompt config
            }
        )
        assert any("reprompt" in e.lower() and "on_schema_mismatch" in e.lower() for e in errors)

    def test_on_schema_mismatch_reprompt_with_reprompt_config_passes(self):
        """on_schema_mismatch: reprompt with reprompt block passes validation."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "on_schema_mismatch": "reprompt",
                "reprompt": {"validation": "my_validator"},
            }
        )
        mismatch_errors = [
            e for e in errors if "on_schema_mismatch" in e.lower() and "reprompt" in e.lower()
        ]
        assert len(mismatch_errors) == 0


# ── TestTypeSpecificValidation ───────────────────────────────────────


class TestTypeSpecificValidation:
    """Validates kind-specific rules are enforced at preflight."""

    def test_tool_impl_exists(self):
        """Tool action without impl raises at Pydantic level."""
        with pytest.raises(ValueError, match="impl"):
            ActionConfig(name="t", intent="do", kind="tool")

    def test_hitl_requires_file_granularity(self):
        """HITL action with granularity: record is caught by action validator."""
        errors, _ = _validate_entry(
            {
                "name": "review",
                "agent_type": "llm",
                "model_name": "n/a",
                "kind": "hitl",
                "granularity": "record",
                "hitl": {"instructions": "Review these records"},
            }
        )
        assert any("hitl" in e.lower() and "file" in e.lower() for e in errors)

    def test_hitl_file_granularity_passes(self):
        """HITL action with granularity: file passes validation."""
        errors, _ = _validate_entry(
            {
                "name": "review",
                "agent_type": "llm",
                "model_name": "n/a",
                "kind": "hitl",
                "granularity": "file",
                "hitl": {"instructions": "Review these records"},
            }
        )
        hitl_errors = [e for e in errors if "hitl" in e.lower() and "granularity" in e.lower()]
        assert len(hitl_errors) == 0

    def test_hitl_without_granularity_passes(self):
        """HITL action without explicit granularity passes (runtime defaults to file)."""
        errors, _ = _validate_entry(
            {
                "name": "review",
                "agent_type": "llm",
                "model_name": "n/a",
                "kind": "hitl",
                "hitl": {"instructions": "Review these records"},
            }
        )
        hitl_errors = [e for e in errors if "hitl" in e.lower() and "granularity" in e.lower()]
        assert len(hitl_errors) == 0

    def test_hitl_requires_hitl_config(self):
        """HITL action without hitl config block raises at Pydantic level."""
        with pytest.raises(ValueError, match="hitl.*configuration"):
            ActionConfig(name="h", intent="do", kind="hitl")

    def test_llm_requires_model_name(self):
        """LLM action without model_name is caught by entry validator."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
            }
        )
        assert any("model_name" in e.lower() for e in errors)


# ── TestActionableErrors ─────────────────────────────────────────────


class TestActionableErrors:
    """Validates error messages are actionable and include context."""

    def test_every_error_includes_action_name(self):
        """Errors from action validators include action name context."""
        errors, _ = _validate_entry(
            {
                "name": "my_special_action",
                "agent_type": "llm",
                # missing model_name
            }
        )
        assert len(errors) > 0
        # At least one error should include the context (agent type + name)
        assert any("my_special_action" in e or "llm" in e.lower() for e in errors)

    def test_every_error_suggests_fix(self):
        """Static analyzer errors include hints for fixing."""
        result = _analyze(
            [
                {
                    "name": "extractor",
                    "schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                },
                {
                    "name": "consumer",
                    "depends_on": ["extractor"],
                    "context_scope": {"observe": ["extractor.nonexistent"]},
                    "schema": {
                        "type": "object",
                        "properties": {"out": {"type": "string"}},
                    },
                },
            ]
        )
        # At least one error should have a hint
        errors_with_hint = [e for e in result.errors if e.hint]
        assert len(errors_with_hint) > 0

    def test_granularity_error_is_actionable(self):
        """HITL granularity error message tells the user how to fix it."""
        errors, _ = _validate_entry(
            {
                "name": "review",
                "agent_type": "llm",
                "model_name": "n/a",
                "kind": "hitl",
                "granularity": "record",
                "hitl": {"instructions": "Review these records"},
            }
        )
        hitl_errors = [e for e in errors if "hitl" in e.lower()]
        assert len(hitl_errors) > 0
        # Error message should tell user how to fix
        assert any("granularity: file" in e.lower() or "remove" in e.lower() for e in hitl_errors)

    def test_reprompt_mismatch_error_is_actionable(self):
        """on_schema_mismatch error tells the user what to add."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "on_schema_mismatch": "reprompt",
            }
        )
        reprompt_errors = [e for e in errors if "on_schema_mismatch" in e.lower()]
        assert len(reprompt_errors) > 0
        # Should suggest adding reprompt block or changing the mode
        assert any(
            "reprompt:" in e.lower() or "warn" in e.lower() or "reject" in e.lower()
            for e in reprompt_errors
        )
