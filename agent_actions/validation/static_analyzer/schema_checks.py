"""Output-schema checks: named schemas load, structures are valid, json_mode sends them."""

from typing import Any

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import (
    DEFAULT_ACTION_KIND,
    JSON_MODE_KEY,
    SCHEMA_KEY,
    SCHEMA_NAME_KEY,
)

from .data_flow_graph import DataFlowGraph
from .errors import FieldLocation, StaticTypeError, StaticTypeWarning
from .schema_structure_validator import SchemaStructureValidator


class SchemaChecksMixin:
    workflow_config: dict[str, Any]
    graph: DataFlowGraph

    def _check_named_schemas_load(self) -> list[StaticTypeError]:
        """Return one error per action whose named schema cannot be loaded.

        The run would spend on every action upstream of it and then fail each of its
        records, or, for a tool, write output no schema ever checked.
        """
        errors: list[StaticTypeError] = []
        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict):
                continue
            name = action.get("name", "workflow")
            node = self.graph.get_node(name)
            if node is None or not node.output_schema.load_error:
                continue
            schema = node.output_schema.failed_schema or action.get("schema_name")
            errors.append(
                StaticTypeError(
                    message=(
                        f"Action '{name}' names schema '{schema}', which cannot be loaded: "
                        f"{node.output_schema.load_error}"
                    ),
                    location=FieldLocation(agent_name=name, config_field="schema"),
                    referenced_agent=name,
                    referenced_field="",
                    hint=(
                        f"Add {schema}.yml (or .yaml/.json) under the project's schema_path "
                        "or the workflow's schema/ folder, or correct the name."
                    ),
                )
            )
        return errors

    def _check_schema_structures(self) -> list[StaticTypeError]:
        """Validate schema definitions for structural correctness.

        Pre-flight validation that catches schema issues before LLM execution:
        - Empty or invalid schema structures
        - Missing required field definitions
        - Invalid type specifications
        - Array schemas without items definition

        Returns:
            List of StaticTypeError for invalid schema structures
        """
        errors: list[StaticTypeError] = []
        validator = SchemaStructureValidator()
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")

            # Check inline schema
            schema = action.get("schema")
            if schema and isinstance(schema, dict):
                schema_errors = validator.validate_schema(schema, action_name, "schema")
                errors.extend(schema_errors)

        return errors

    # ── json_mode / schema mismatch ─────────────────────────────────

    def _check_json_mode_schema_mismatch(self) -> list[StaticTypeWarning]:
        """Warn when json_mode=false but a schema is defined.

        The schema will be compiled but never sent to the LLM because
        ``BaseClient.invoke()`` routes to ``call_non_json()`` which does
        not accept a schema parameter.  The user likely expects schema
        enforcement but will silently get free-form text.
        """
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            name = action.get("name", "<unnamed>")
            kind = action.get("kind", DEFAULT_ACTION_KIND)
            if kind != "llm":
                continue

            json_mode = action.get(JSON_MODE_KEY, get_default(JSON_MODE_KEY))
            if json_mode:
                continue

            has_schema = bool(
                action.get(SCHEMA_KEY) or action.get("output_schema") or action.get(SCHEMA_NAME_KEY)
            )
            if not has_schema:
                continue

            warnings.append(
                StaticTypeWarning(
                    message=(
                        f"Action '{name}' has json_mode=false but defines a schema. "
                        "The schema will be compiled but not sent to the LLM. "
                        "Set json_mode=true to enable schema enforcement, or "
                        "remove the schema if text output is intended."
                    ),
                    location=FieldLocation(
                        agent_name=name,
                        config_field="json_mode",
                        raw_reference="json_mode: false",
                    ),
                    referenced_agent=name,
                    referenced_field="json_mode",
                    hint=(
                        "When json_mode is false, the schema is not included in the "
                        "LLM request. The LLM will return free-form text instead of "
                        "structured output."
                    ),
                )
            )

        return warnings
