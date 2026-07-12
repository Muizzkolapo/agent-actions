"""Preflight consolidation tests.

Ensures every detectable misconfiguration is caught before execution.
Organized by category of misconfiguration.
"""

import logging

import pytest

from agent_actions.config.schema import ActionConfig, WorkflowConfig
from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.services.preflight_service import PreflightService
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

    def test_on_schema_mismatch_reprompt_requires_schema(self):
        """reprompt.on_schema_mismatch: reprompt without schema is caught."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "reprompt": {"on_schema_mismatch": "reprompt"},
                # no schema
            }
        )
        assert any("on_schema_mismatch" in e.lower() for e in errors)

    def test_on_schema_mismatch_reprompt_with_schema_passes(self):
        """reprompt.on_schema_mismatch: reprompt with schema passes validation."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "reprompt": {
                    "on_schema_mismatch": "reprompt",
                    "validation": "my_validator",
                },
                "schema": {"summary": "string"},
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

    def test_llm_file_granularity_blocked(self):
        """LLM action with granularity: file is rejected — FILE granularity is tool/hitl only."""
        errors, _ = _validate_entry(
            {
                "name": "extract",
                "agent_type": "llm",
                "model_name": "n/a",
                "kind": "llm",
                "granularity": "file",
            }
        )
        assert any("file granularity" in e.lower() for e in errors)

    def test_llm_without_kind_file_granularity_blocked(self):
        """Action with no kind and granularity: file is rejected (defaults to LLM behavior)."""
        errors, _ = _validate_entry(
            {
                "name": "extract",
                "agent_type": "llm",
                "model_name": "n/a",
                "granularity": "file",
            }
        )
        assert any("file granularity" in e.lower() for e in errors)

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
        """reprompt.on_schema_mismatch error tells the user what to add."""
        errors, _ = _validate_entry(
            {
                "name": "test",
                "agent_type": "llm",
                "model_name": "gpt-4",
                "reprompt": {"on_schema_mismatch": "reprompt"},
            }
        )
        reprompt_errors = [e for e in errors if "on_schema_mismatch" in e.lower()]
        assert len(reprompt_errors) > 0
        # Should suggest defining a schema
        assert any("schema" in e.lower() or "define" in e.lower() for e in reprompt_errors)


# ── TestPromptRequiredCrossCheck ─────────────────────────────────────


def _producer(required_b: bool) -> dict:
    """LLM producer with flat fields a (required) and b (required_b)."""
    return {
        "agent_type": "llm",
        "kind": "llm",
        "model_name": "gpt-4o-mini",
        "prompt": "Produce values a and b.",
        "context_scope": {"observe": ["source.*"]},
        "schema": {
            "fields": [
                {"id": "a", "type": "string", "required": True},
                {"id": "b", "type": "string", "required": required_b},
            ]
        },
    }


def _consumer(prompt: str) -> dict:
    """LLM consumer that observes both producer fields and renders `prompt`."""
    return {
        "agent_type": "llm",
        "kind": "llm",
        "model_name": "gpt-4o-mini",
        "depends_on": ["producer"],
        "prompt": prompt,
        "context_scope": {"observe": ["producer.a", "producer.b"]},
        "schema": {"fields": [{"id": "out", "type": "string", "required": True}]},
    }


def _preflight_warnings(action_configs: dict, caplog) -> list[str]:
    """Run PreflightService.validate() and return preflight warning messages."""
    logger_name = "agent_actions.services.preflight_service"
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger=logger_name):
            PreflightService(
                agent_name="wf",
                action_configs=action_configs,
                project_root=None,
                workflow_config_path="wf.yml",
                verify_keys=False,
            ).validate()
        return [r.getMessage() for r in caplog.records if r.name == logger_name]
    finally:
        aa_logger.propagate = original


class TestPromptRequiredCrossCheck:
    """Preflight must warn when a prompt references a producer field the
    producer does not mark required and no `{% if %}` guards it."""

    def test_unguarded_ref_to_non_required_field_warns(self, caplog):
        cfgs = {
            "producer": _producer(required_b=False),
            "consumer": _consumer("Use {{ producer.b }} here."),
        }
        warnings = _preflight_warnings(cfgs, caplog)
        assert any("producer.b" in w and "consumer" in w for w in warnings), warnings

    def test_ref_to_required_field_does_not_warn(self, caplog):
        cfgs = {
            "producer": _producer(required_b=True),
            "consumer": _consumer("Use {{ producer.b }} here."),
        }
        warnings = _preflight_warnings(cfgs, caplog)
        assert not any("producer.b" in w for w in warnings), warnings

    def test_guarded_ref_does_not_warn(self, caplog):
        cfgs = {
            "producer": _producer(required_b=False),
            "consumer": _consumer("{% if producer.b is defined %}{{ producer.b }}{% endif %}"),
        }
        warnings = _preflight_warnings(cfgs, caplog)
        assert not any("producer.b" in w for w in warnings), warnings

    def test_guard_on_other_field_still_warns(self, caplog):
        # Guard tests producer.a; body reads the unguarded producer.b.
        cfgs = {
            "producer": _producer(required_b=False),
            "consumer": _consumer("{% if producer.a is defined %}{{ producer.b }}{% endif %}"),
        }
        warnings = _preflight_warnings(cfgs, caplog)
        assert any("producer.b" in w for w in warnings), warnings

    def test_optional_ref_warns_exactly_once_and_does_not_raise(self, caplog):
        # Same field referenced twice — one warning, and validate() completes
        # (warn, never raise).
        cfgs = {
            "producer": _producer(required_b=False),
            "consumer": _consumer("Use {{ producer.b }} and again {{ producer.b }}."),
        }
        matches = [w for w in _preflight_warnings(cfgs, caplog) if "producer.b" in w]
        assert len(matches) == 1, matches


class TestDependencyObserveCheck:
    """Preflight must hard-fail when a declared dependency has no
    observe/passthrough reference in context_scope — the runtime treats
    that as fatal (scope_namespace), so inspect must not report green."""

    @staticmethod
    def _llm_action(**overrides) -> dict:
        base = {
            "agent_type": "llm",
            "kind": "llm",
            "model_name": "gpt-4o-mini",
            "prompt": "Do the thing.",
            "context_scope": {"observe": ["source.*"]},
            "schema": {"fields": [{"id": "out", "type": "string", "required": True}]},
        }
        base.update(overrides)
        return base

    def _validate(self, action_configs: dict) -> None:
        PreflightService(
            agent_name="wf",
            action_configs=action_configs,
            project_root=None,
            workflow_config_path="wf.yml",
            verify_keys=False,
        ).validate()

    def _producers(self) -> dict:
        return {
            "producer": self._llm_action(
                schema={"fields": [{"id": "a", "type": "string", "required": True}]}
            ),
            "other": self._llm_action(
                schema={"fields": [{"id": "b", "type": "string", "required": True}]}
            ),
        }

    def test_over_declared_dependency_raises(self):
        cfgs = {
            **self._producers(),
            "consumer": self._llm_action(
                dependencies=["producer", "other"],
                context_scope={"observe": ["producer.a"]},
            ),
        }
        with pytest.raises(PreFlightValidationError, match="'other'.*not referenced"):
            self._validate(cfgs)

    def test_all_offenders_reported_in_one_error(self):
        cfgs = {
            **self._producers(),
            "first_consumer": self._llm_action(
                dependencies=["producer", "other"],
                context_scope={"observe": ["producer.a"]},
            ),
            "second_consumer": self._llm_action(
                dependencies=["producer"],
                context_scope={"observe": ["source.*"]},
            ),
        }
        with pytest.raises(PreFlightValidationError) as excinfo:
            self._validate(cfgs)
        message = str(excinfo.value)
        assert "first_consumer" in message and "'other'" in message
        assert "second_consumer" in message and "'producer'" in message

    def test_dotless_ref_does_not_satisfy_dep(self):
        # observe: ["producer"] (no dot) is skipped by the runtime's
        # reference parser, so the dependency is unreferenced at runtime.
        cfgs = {
            **self._producers(),
            "consumer": self._llm_action(
                dependencies=["producer"],
                context_scope={"observe": ["producer"]},
            ),
        }
        with pytest.raises(PreFlightValidationError, match="'producer'.*not referenced"):
            self._validate(cfgs)

    def test_satisfied_deps_pass(self):
        cfgs = {
            **self._producers(),
            "consumer": self._llm_action(
                dependencies=["producer", "other"],
                context_scope={"observe": ["producer.a"], "passthrough": ["other.b"]},
            ),
        }
        self._validate(cfgs)  # completes without raising

    def test_version_base_dependency_passes(self):
        # Post-loader shape of version_consumption: the producer is expanded
        # into <base>_N actions, the consumer's observe refs are rewritten to
        # the branch names, but its dependencies keep the base name.
        branch = {
            "is_versioned_agent": True,
            "version_base_name": "producer",
            "schema": {"fields": [{"id": "a", "type": "string", "required": True}]},
        }
        cfgs = {
            "producer_1": self._llm_action(**branch),
            "producer_2": self._llm_action(**branch),
            "consumer": self._llm_action(
                dependencies=["producer"],
                context_scope={"observe": ["producer_1.*", "producer_2.*"]},
            ),
        }
        self._validate(cfgs)  # completes without raising


# Real module-level UDFs so inspect.getsource returns their true bodies.
def _passthrough_tool(data):
    out = []
    for candidate in data.get("upstream", []):
        out.append(candidate)
    return out


def _constructed_tool(data):
    return [{"key": item["key"]} for item in data.get("upstream", [])]


class TestToolPassthroughCrossCheck:
    """Preflight must warn when a kind:tool UDF passes upstream dicts through a
    strict output schema — the static signal for a runtime output-schema reject."""

    def _svc(self, action_configs: dict) -> PreflightService:
        return PreflightService(
            agent_name="wf",
            action_configs=action_configs,
            project_root=None,
            workflow_config_path="wf.yml",
            verify_keys=False,
        )

    def _tool(self, impl: str, additional_properties: bool = False) -> dict:
        return {
            "kind": "tool",
            "impl": impl,
            "json_output_schema": {"type": "object", "additionalProperties": additional_properties},
        }

    def _emit_warnings(self, cfgs: dict, caplog) -> list[str]:
        """Run the passthrough warning step and return its preflight messages.

        The ``agent_actions`` logger does not propagate by default, so caplog
        (which listens on root) needs propagation toggled on for the call."""
        logger_name = "agent_actions.services.preflight_service"
        aa_logger = logging.getLogger("agent_actions")
        original = aa_logger.propagate
        aa_logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger=logger_name):
                self._svc(cfgs)._warn_tool_passthrough_risks()
            return [r.getMessage() for r in caplog.records if r.name == logger_name]
        finally:
            aa_logger.propagate = original

    def test_expanded_config_model_name_is_used_as_impl(self):
        # Post-expansion tool configs carry the UDF name in model_name (the
        # expander maps impl -> model_name); impl does not survive. The check
        # must read model_name or it never fires on a real workflow.
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            cfgs = {
                "flatten": {
                    "kind": "tool",
                    "model_name": "_passthrough_tool",
                    "json_output_schema": {"type": "object", "additionalProperties": False},
                }
            }
            collected = self._svc(cfgs)._collect_tool_passthrough_inputs()
            assert "flatten" in collected
            assert "out.append(candidate)" in collected["flatten"]["source"]
        finally:
            clear_registry()

    def test_passthrough_tool_source_and_schema_collected(self):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            collected = self._svc(
                {"flatten": self._tool("_passthrough_tool")}
            )._collect_tool_passthrough_inputs()
            assert "flatten" in collected
            assert collected["flatten"]["additional_properties"] is False
            assert "out.append(candidate)" in collected["flatten"]["source"]
        finally:
            clear_registry()

    def test_passthrough_tool_under_strict_schema_is_flagged(self):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool
        from agent_actions.validation.udf_passthrough_validator import find_passthrough_schema_risks

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            collected = self._svc(
                {"flatten": self._tool("_passthrough_tool")}
            )._collect_tool_passthrough_inputs()
            assert find_passthrough_schema_risks(collected)
        finally:
            clear_registry()

    def test_additionalproperties_true_tool_not_flagged(self):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool
        from agent_actions.validation.udf_passthrough_validator import find_passthrough_schema_risks

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            collected = self._svc(
                {"flatten": self._tool("_passthrough_tool", additional_properties=True)}
            )._collect_tool_passthrough_inputs()
            assert collected["flatten"]["additional_properties"] is True
            assert find_passthrough_schema_risks(collected) == []
        finally:
            clear_registry()

    def test_constructed_tool_not_flagged(self):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool
        from agent_actions.validation.udf_passthrough_validator import find_passthrough_schema_risks

        clear_registry()
        udf_tool(_constructed_tool)
        try:
            collected = self._svc(
                {"build": self._tool("_constructed_tool")}
            )._collect_tool_passthrough_inputs()
            assert find_passthrough_schema_risks(collected) == []
        finally:
            clear_registry()

    def test_non_tool_action_not_collected(self):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            # llm action carries an impl too — only the kind filter should exclude it.
            cfgs = {
                "scorer": {"kind": "llm", "impl": "_passthrough_tool", "model_name": "gpt-4o-mini"}
            }
            assert self._svc(cfgs)._collect_tool_passthrough_inputs() == {}
        finally:
            clear_registry()

    def test_unregistered_impl_skipped_without_error(self):
        from agent_actions.utils.udf_management.registry import clear_registry

        clear_registry()
        collected = self._svc(
            {"ghost": self._tool("not_registered")}
        )._collect_tool_passthrough_inputs()
        assert collected == {}

    def test_missing_json_output_schema_is_skipped(self):
        # No compiled output schema means the runtime does no output validation
        # and cannot reject — so preflight must not warn. Parity with runtime.
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            cfgs = {"flatten": {"kind": "tool", "impl": "_passthrough_tool"}}
            assert self._svc(cfgs)._collect_tool_passthrough_inputs() == {}
        finally:
            clear_registry()

    def test_passthrough_tool_emits_preflight_warning(self, caplog):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            msgs = self._emit_warnings({"flatten": self._tool("_passthrough_tool")}, caplog)
            assert any("flatten" in m and "additionalProperties" in m for m in msgs), msgs
        finally:
            clear_registry()

    def test_additionalproperties_true_tool_emits_nothing(self, caplog):
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            cfgs = {"flatten": self._tool("_passthrough_tool", additional_properties=True)}
            assert not any("flatten" in m for m in self._emit_warnings(cfgs, caplog)), cfgs
        finally:
            clear_registry()

    def test_validate_emits_passthrough_warning_end_to_end(self, caplog):
        # Full validate() must reach the passthrough check and stay non-fatal.
        from agent_actions.utils.udf_management.registry import clear_registry, udf_tool

        clear_registry()
        udf_tool(_passthrough_tool)
        try:
            cfgs = {
                "flatten": {
                    "kind": "tool",
                    "impl": "_passthrough_tool",
                    "context_scope": {"observe": ["source.*"]},
                    "schema": {"type": "object", "properties": {"k": {"type": "string"}}},
                    "json_output_schema": {
                        "type": "object",
                        "properties": {"k": {"type": "string"}},
                        "additionalProperties": False,
                    },
                }
            }
            logger_name = "agent_actions.services.preflight_service"
            aa_logger = logging.getLogger("agent_actions")
            original = aa_logger.propagate
            aa_logger.propagate = True
            try:
                with caplog.at_level(logging.WARNING, logger=logger_name):
                    self._svc(cfgs).validate()  # completes without raising
                msgs = [r.getMessage() for r in caplog.records if r.name == logger_name]
            finally:
                aa_logger.propagate = original
            assert any("flatten" in m and "upstream dicts" in m for m in msgs), msgs
        finally:
            clear_registry()


class TestProducingSchemaCollection:
    """`_collect_producing_schemas` feeds the cross-check the right field set."""

    def _service(self, action_configs: dict, schemas: dict) -> PreflightService:
        from unittest.mock import MagicMock

        svc = PreflightService(
            agent_name="wf",
            action_configs=action_configs,
            project_root=None,
            workflow_config_path="wf.yml",
            verify_keys=False,
        )
        svc.schema_service = MagicMock()
        svc.schema_service.get_all_schemas.return_value = schemas
        return svc

    def test_dropped_field_is_excluded(self):
        from agent_actions.models.action_schema import (
            ActionKind,
            ActionSchema,
            FieldInfo,
            FieldSource,
        )

        schema = ActionSchema(
            name="producer",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="kept", source=FieldSource.SCHEMA, is_required=False),
                FieldInfo(
                    name="gone", source=FieldSource.SCHEMA, is_required=False, is_dropped=True
                ),
            ],
        )
        svc = self._service({"producer": {"kind": "llm"}}, {"producer": schema})
        ids = {f["id"] for f in svc._collect_producing_schemas()["producer"]["fields"]}
        assert ids == {"kept"}

    def test_versioned_producer_indexed_under_base_name(self):
        from agent_actions.models.action_schema import (
            ActionKind,
            ActionSchema,
            FieldInfo,
            FieldSource,
        )

        schema = ActionSchema(
            name="classify_1",
            kind=ActionKind.LLM,
            output_fields=[FieldInfo(name="label", source=FieldSource.SCHEMA, is_required=False)],
        )
        svc = self._service(
            {"classify_1": {"kind": "llm", "version_base_name": "classify"}},
            {"classify_1": schema},
        )
        collected = svc._collect_producing_schemas()
        assert "classify" in collected
        assert {f["id"] for f in collected["classify"]["fields"]} == {"label"}
