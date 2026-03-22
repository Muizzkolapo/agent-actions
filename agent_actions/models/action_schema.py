"""Unified schema model for workflow actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_actions.config.schema import ActionKind  # noqa: F401 — canonical enum, re-exported


class FieldSource(Enum):
    """How a field is produced."""

    SCHEMA = "schema"
    OBSERVE = "observe"
    PASSTHROUGH = "passthrough"
    TOOL_OUTPUT = "tool_output"


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
            "type": self.field_type,
            "description": self.description,
        }


@dataclass
class UpstreamReference:
    """Reference to an upstream agent's field used in templates."""

    source_agent: str
    field_name: str
    location: str
    raw_reference: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_agent": self.source_agent,
            "field_name": self.field_name,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class ActionSchema:
    """Unified schema for any action type (llm, tool, source, hitl)."""

    name: str
    kind: ActionKind
    upstream_refs: list[UpstreamReference] = field(default_factory=list)
    input_fields: list[FieldInfo] = field(default_factory=list)
    output_fields: list[FieldInfo] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
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

    @property
    def uses_fields(self) -> list[str]:
        """Unique 'agent.field' references from upstream."""
        return sorted({f"{ref.source_agent}.{ref.field_name}" for ref in self.upstream_refs})

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "upstream_refs": [r.to_dict() for r in self.upstream_refs],
            "input_fields": [f.to_dict() for f in self.input_fields],
            "output_fields": [f.to_dict() for f in self.output_fields],
            "dependencies": self.dependencies,
            "downstream": self.downstream,
            "is_dynamic": self.is_dynamic,
            "is_schemaless": self.is_schemaless,
            "is_template_based": self.is_template_based,
            "available_outputs": self.available_outputs,
            "dropped_outputs": self.dropped_outputs,
            "required_inputs": self.required_inputs,
            "optional_inputs": self.optional_inputs,
            "uses_fields": self.uses_fields,
        }
