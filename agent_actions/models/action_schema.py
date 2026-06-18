"""Unified schema model for workflow actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_actions.config.schema import ActionKind

__all__ = ["ActionKind", "ActionSchema", "FieldInfo", "FieldSource"]


class FieldSource(Enum):
    """Where a field comes from in the action's schema.

    Output-side values describe how the field is produced; ``INPUT`` marks
    fields consumed by the action (e.g. tool input schema entries) where the
    upstream production source is not known here.
    """

    SCHEMA = "schema"
    OBSERVE = "observe"
    PASSTHROUGH = "passthrough"
    TOOL_OUTPUT = "tool_output"
    INPUT = "input"


@dataclass
class FieldInfo:
    """Information about a single field."""

    name: str
    source: FieldSource
    is_required: bool = True
    is_dropped: bool = False
    field_type: str = "unknown"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.value,
            "is_required": self.is_required,
            "is_dropped": self.is_dropped,
            "field_type": self.field_type,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldInfo:
        return cls(
            name=data["name"],
            source=FieldSource(data["source"]),
            is_required=data.get("is_required", True),
            is_dropped=data.get("is_dropped", False),
            field_type=data.get("field_type", "unknown"),
            description=data.get("description", ""),
        )


@dataclass
class ActionSchema:
    """Unified schema for any action type (llm, tool, source, hitl)."""

    name: str
    kind: ActionKind
    input_fields: list[FieldInfo] = field(default_factory=list)
    output_fields: list[FieldInfo] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    is_dynamic: bool = False
    is_schemaless: bool = False
    is_template_based: bool = False

    @property
    def available_outputs(self) -> list[str]:
        """Fields available to downstream agents (excludes dropped)."""
        return sorted(f.name for f in self.output_fields if not f.is_dropped)

    @property
    def dropped_outputs(self) -> list[str]:
        """Fields explicitly dropped from output."""
        return sorted(f.name for f in self.output_fields if f.is_dropped)

    @property
    def required_inputs(self) -> list[str]:
        """Required input field names (for tools)."""
        return sorted(f.name for f in self.input_fields if f.is_required)

    @property
    def optional_inputs(self) -> list[str]:
        """Optional input field names (for tools)."""
        return sorted(f.name for f in self.input_fields if not f.is_required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "input_fields": [f.to_dict() for f in self.input_fields],
            "output_fields": [f.to_dict() for f in self.output_fields],
            "dependencies": self.dependencies,
            "is_dynamic": self.is_dynamic,
            "is_schemaless": self.is_schemaless,
            "is_template_based": self.is_template_based,
            "available_outputs": self.available_outputs,
            "dropped_outputs": self.dropped_outputs,
            "required_inputs": self.required_inputs,
            "optional_inputs": self.optional_inputs,
        }
