"""Checks of a retrieve step that searches the records of an earlier action."""

from typing import Any

from agent_actions.llm.providers.tools.builtin import (
    RETRIEVE,
    builtin_tool,
    searches_base,
    step_label,
)

from .data_flow_graph import DataFlowGraph, OutputSchema
from .errors import FieldLocation, StaticTypeError


class RetrieveChecksMixin:
    workflow_config: dict[str, Any]
    graph: DataFlowGraph

    def _check_retrieve_corpus_fields(self) -> list[StaticTypeError]:
        """Each field a step reads of its ``from:`` action is an output field of that action.

        A ``text`` field must hold text, numbers or a list of them, not an object.
        """
        errors: list[StaticTypeError] = []
        for action in self.workflow_config.get("actions", []):
            spec = builtin_tool(action) if isinstance(action, dict) else None
            if spec is None or spec["tool"] != RETRIEVE or searches_base(spec):
                continue
            corpus = spec["corpus"]
            node = self.graph.get_node(corpus["action"])
            schema = node.output_schema if node is not None else None
            if schema is None or schema.is_dynamic or schema.is_schemaless or schema.load_error:
                continue
            fields = schema.schema_fields | schema.passthrough_fields
            named = [("text", f) for f in corpus["text"]]
            named += [(key, corpus[key]) for key in ("title", "id") if corpus.get(key)]
            named += [("where", f) for f in spec.get("where") or {}]
            for key, field in named:
                problem = _problem(schema, fields, key, field)
                if problem is None:
                    continue
                errors.append(
                    StaticTypeError(
                        message=f"{step_label(spec, action['name'])}: '{key}' names "
                        f"'{field}', {problem}",
                        location=FieldLocation(
                            agent_name=spec["action"],
                            config_field=f"context_scope.retrieve.{spec['entry']}.{key}",
                        ),
                        referenced_agent=corpus["action"],
                        referenced_field=field,
                        available_fields=fields,
                    )
                )
        return errors


def _problem(schema: OutputSchema, fields: set[str], key: str, field: str) -> str | None:
    if field not in fields:
        return "which is no output field of the action it searches."
    if key != "text":
        return None
    declared = _declared(schema.json_schema or {}, field)
    if not isinstance(declared, dict):
        return None
    items: dict[str, Any] = declared["items"] if isinstance(declared.get("items"), dict) else {}
    if declared.get("type") == "object" or (
        declared.get("type") == "array" and items.get("type") == "object"
    ):
        return (
            "which holds an object. A text field holds text, numbers or a list of them; "
            "search a field of text, or add one to the action's output."
        )
    return None


def _declared(schema: dict[str, Any], field: str) -> Any:
    """How *schema* declares *field*: a JSON Schema property, or an item of ``fields:``."""
    properties = schema.get("properties")
    if isinstance(properties, dict) and field in properties:
        return properties[field]
    listed = schema.get("fields")
    if not isinstance(listed, list):
        items = schema.get("items")
        listed = items if schema.get("type") == "array" and isinstance(items, list) else []
    return next((f for f in listed if isinstance(f, dict) and f.get("id") == field), None)
