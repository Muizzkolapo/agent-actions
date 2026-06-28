"""Preflight validation for workflow configs.

Standalone so both the runtime coordinator and the read-only inspect
CLI can call it without spinning up storage or execution services.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.validation.preflight.guard_validation import validate_guard_conditions
from agent_actions.validation.preflight.resolution_service import (
    WorkflowResolutionService,
)
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    apply_guard_nullable_schema_fixes,
)
from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


class PreflightService:
    """Validate a workflow config without executing it.

    Runs schema, guard syntax, and resolution checks. Mutates
    ``action_configs`` for guard-nullable schema fixes. Pass-or-raise:
    ``validate()`` returns nothing on success and raises
    ``PreFlightValidationError`` on the first failed check.
    Callers can read ``self.schema_service`` after success to reuse the
    rebuilt service for downstream work.
    """

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

        # 4. Resolution checks (API keys, seed files, vendor batch)
        resolution_result = WorkflowResolutionService(
            action_configs=self.action_configs,
            workflow_config_path=self.workflow_config_path,
            project_root=self.project_root,
            verify_keys=self.verify_keys,
        ).resolve_all()
        resolution_result.raise_if_invalid()

        for warning in resolution_result.warnings:
            logger.warning("Pre-flight: %s", warning.message)
