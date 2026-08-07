"""Preflight validation — standalone so runtime and inspect can both
call it without spinning up storage or execution services."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from agent_actions.errors import (
    ConfigValidationError,
    FunctionNotFoundError,
    PromptValidationError,
)
from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.models.action_schema import FieldSource
from agent_actions.prompt.formatter import PromptFormatter
from agent_actions.utils.constants import NON_PROMPT_ACTION_KINDS
from agent_actions.utils.udf_management.registry import get_udf_metadata
from agent_actions.validation.dag_schema_fit_validator import (
    DAG_FIT_REMEDY,
    find_dag_schema_compatibility_gaps,
)
from agent_actions.validation.dep_observe_validator import find_missing_observe_deps
from agent_actions.validation.preflight.guard_validation import validate_guard_conditions
from agent_actions.validation.preflight.resolution_service import (
    WorkflowResolutionService,
)
from agent_actions.validation.prompt_required_field_validator import (
    find_unguarded_required_refs,
)
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    apply_guard_nullable_schema_fixes,
)
from agent_actions.validation.udf_passthrough_validator import find_passthrough_schema_risks
from agent_actions.validation.udf_required_field_validator import (
    find_conditional_required_field_risks,
)
from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


class PreflightService:
    """Validate a workflow config without executing it.

    Mutates ``action_configs`` for guard-nullable schema fixes. Raises
    ``PreFlightValidationError`` on the first failed check. After
    success ``self.schema_service`` is reusable downstream."""

    def __init__(
        self,
        agent_name: str,
        action_configs: dict[str, dict[str, Any]],
        project_root: Path | None,
        workflow_config_path: str,
        verify_keys: bool = True,
    ):
        self.agent_name = agent_name
        self.action_configs = action_configs
        self.project_root = project_root
        self.workflow_config_path = workflow_config_path
        self.verify_keys = verify_keys
        self.schema_service: WorkflowSchemaService | None = None

    def validate(self) -> None:
        # 1. Schema validation
        self.schema_service = WorkflowSchemaService.from_action_configs(
            self.agent_name,
            self.action_configs,
            project_root=self.project_root,
            with_udf_registry=True,
        )
        schema_result = self.schema_service.validate()
        if schema_result.errors:
            raise PreFlightValidationError(
                schema_result.format_report(),
                hint="Fix the static type errors above before running the workflow.",
            )

        # 2. Guard-nullable schema fixes (mutates action_configs)
        guard_fixes = apply_guard_nullable_schema_fixes(self.action_configs)
        if guard_fixes:
            logger.info(
                "Auto-fixed %d guard-nullable schema field(s): %s",
                len(guard_fixes),
                ", ".join(guard_fixes),
            )

        # 3. Guard syntax validation
        guard_errors = validate_guard_conditions(self.action_configs)
        if guard_errors:
            raise PreFlightValidationError(
                "\n".join(guard_errors),
                hint="Fix the guard condition errors above before running the workflow.",
            )

        # 4. Dependency/observe consistency — fatal at runtime, so fatal here
        observe_errors = find_missing_observe_deps(self.action_configs)
        if observe_errors:
            raise PreFlightValidationError(
                "\n".join(observe_errors),
                hint="Add an observe or passthrough field for each dependency, "
                "or drop the unused dependency.",
            )

        # 5. Resolution checks (API keys, seed files, vendor batch)
        resolution_result = WorkflowResolutionService(
            action_configs=self.action_configs,
            workflow_config_path=self.workflow_config_path,
            project_root=self.project_root,
            verify_keys=self.verify_keys,
        ).resolve_all()
        resolution_result.raise_if_invalid()

        self._warn_findings(
            "resolution", [warning.message for warning in resolution_result.warnings]
        )

        # 6. Cross-check prompt refs against each producer's required set
        self._warn_findings(
            "prompt-contract",
            find_unguarded_required_refs(
                self._collect_prompts(), self._collect_producing_schemas()
            ),
        )

        # 7. Cross-check kind:tool passthrough UDFs against strict output schemas
        self._warn_tool_passthrough_risks()

        # 8. Cross-check kind:tool UDFs against their required output-schema fields
        self._check_tool_conditional_required_field_risks()

        # 9. DAG schema-fit: per producer/consumer edge, does the producer's schema
        # guarantee every field the tool consumer requires (implicit), or does the
        # consumer declare `defaults:` for it? (Spec 592 Phase 2, warn-only.)
        self._warn_dag_schema_compatibility_gaps()

    def _collect_prompts(self) -> dict[str, str]:
        """Resolved prompt text per prompt-bearing action, keyed by action name."""
        prompts: dict[str, str] = {}
        for name, config in self.action_configs.items():
            if config.get("kind") in NON_PROMPT_ACTION_KINDS:
                continue
            try:
                prompts[name] = PromptFormatter.get_raw_prompt(config)
            except (ConfigValidationError, PromptValidationError) as exc:
                logger.debug("Skipping prompt cross-check for %s: %s", name, exc)
        return prompts

    def _collect_producing_schemas(self) -> dict[str, dict[str, Any]]:
        """Available (non-dropped) schema-source fields per producing action.

        Fan-out versions are additionally indexed under their shared base name,
        which is how downstream prompts reference them.
        """
        if self.schema_service is None:
            return {}
        schemas: dict[str, dict[str, Any]] = {}
        for name, action_schema in self.schema_service.get_all_schemas().items():
            fields = [
                {"id": f.name, "required": f.is_required}
                for f in action_schema.output_fields
                if f.source is FieldSource.SCHEMA and not f.is_dropped
            ]
            schemas[name] = {"fields": fields}
            base = self.action_configs.get(name, {}).get("version_base_name")
            if base and base not in schemas:
                schemas[base] = {"fields": fields}
        return schemas

    def _collect_tool_passthrough_inputs(self) -> dict[str, dict[str, Any]]:
        """UDF source + output-schema strictness per kind:tool action.

        Actions whose impl is unregistered or has no readable source are skipped:
        this is an advisory warning and must never break inspect."""
        inputs: dict[str, dict[str, Any]] = {}
        for name, config in self.action_configs.items():
            if config.get("kind") != "tool":
                continue
            # Post-expansion, the UDF name lives in model_name (the expander maps
            # impl -> model_name); impl is the raw pre-expansion key.
            impl = config.get("model_name") or config.get("impl")
            if not impl:
                continue
            schema = config.get("json_output_schema")
            if not schema:
                # No compiled output schema → runtime does no output validation and
                # cannot reject, so there is nothing to warn about.
                continue
            try:
                source = inspect.getsource(get_udf_metadata(impl)["function"])
            except (FunctionNotFoundError, OSError, TypeError) as exc:
                logger.debug("Skipping passthrough check for '%s': %s", name, exc)
                continue
            inputs[name] = {
                "source": source,
                "additional_properties": bool(schema.get("additionalProperties", False)),
            }
        return inputs

    def _warn_tool_passthrough_risks(self) -> None:
        """Warn when a kind:tool UDF passes upstream dicts through a strict schema."""
        self._warn_findings(
            "tool-passthrough",
            find_passthrough_schema_risks(self._collect_tool_passthrough_inputs()),
        )

    def _collect_tool_required_field_inputs(self) -> dict[str, dict[str, Any]]:
        """UDF source + compiled required list per kind:tool action.

        Skipped when the UDF is unregistered, its source cannot be read, or
        the action has no compiled ``json_output_schema`` — the runtime does
        no output validation without one and cannot reject a missing field.
        """
        inputs: dict[str, dict[str, Any]] = {}
        for name, config in self.action_configs.items():
            if config.get("kind") != "tool":
                continue
            impl = config.get("model_name") or config.get("impl")
            if not impl:
                continue
            schema = config.get("json_output_schema")
            if not isinstance(schema, dict):
                # Anthropic-tool compiled schemas are lists; not the tool path,
                # but be defensive so the check never crashes preflight.
                continue
            required = schema.get("required") or []
            if not required:
                continue
            try:
                source = inspect.getsource(get_udf_metadata(impl)["function"])
            except (FunctionNotFoundError, OSError, TypeError) as exc:
                logger.debug("Skipping required-field check for '%s': %s", name, exc)
                continue
            inputs[name] = {
                "source": source,
                "required": list(required),
                "additional_properties": bool(schema.get("additionalProperties", False)),
            }
        return inputs

    def _check_tool_conditional_required_field_risks(self) -> None:
        """Refuse preflight when a kind:tool UDF only conditionally emits a required schema field."""
        findings = find_conditional_required_field_risks(self._collect_tool_required_field_inputs())
        if findings:
            raise PreFlightValidationError(
                "\n".join(findings),
                hint="Mark the field optional in the schema, "
                "or emit it unconditionally in the UDF.",
            )

    def _warn_dag_schema_compatibility_gaps(self) -> None:
        """Warn when a tool consumer's required output field is neither guaranteed by an upstream producer nor declared as synthesized via `defaults:`."""
        gaps = find_dag_schema_compatibility_gaps(self.action_configs)
        if not gaps:
            return
        total = sum(len(fields) for fields in gaps.values())
        self._warn_findings(
            "dag-fit",
            [f"{action}: {', '.join(fields)}" for action, fields in gaps.items()],
            header=(
                f"dag-fit — {total} required field(s) with no upstream guarantee "
                f"across {len(gaps)} action(s)"
            ),
            remedy=DAG_FIT_REMEDY,
        )

    @staticmethod
    def _warn_findings(
        label: str,
        findings: list[str],
        header: str | None = None,
        remedy: str | None = None,
    ) -> None:
        """Emit one grouped warning for a check's findings instead of one per finding.

        Renders a tree so a run's warning wall reads as a few scannable blocks:

            Pre-flight: dag-fit — 5 required field(s) ... across 2 action(s)
              ├─ flatten: category, key, steps
              ├─ assemble: id, items
              └─ Fix: mark the field optional in the consumer schema, ...
        """
        if not findings:
            return
        items = list(findings)
        if remedy:
            items.append(f"Fix: {remedy}")
        body = "\n".join(
            f"  {'└─' if i == len(items) - 1 else '├─'} {item}" for i, item in enumerate(items)
        )
        head = header or f"{label} — {len(findings)} warning(s)"
        logger.warning("Pre-flight: %s\n%s", head, body)
