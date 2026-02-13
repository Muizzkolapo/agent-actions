"""Unified schema model for workflow actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionKind(Enum):
    """Type of action in the workflow.

    Attributes:
        LLM: Language model action (generates structured output)
        TOOL: Tool/UDF action (calls external function)
        SOURCE: Source data (workflow input data)
        SEED: Seed data (static data defined in config)
        HITL: Human-in-the-loop action (blocks for human approval)
    """

    LLM = "llm"
    TOOL = "tool"
    SOURCE = "source"
    SEED = "seed"
    HITL = "hitl"


class FieldSource(Enum):
    """How a field is produced.

    Attributes:
        SCHEMA: Field from LLM output schema (output_schema in config)
        OBSERVE: Field passed through via context_scope.observe
        PASSTHROUGH: Field from context_scope.passthrough
        SOURCE: Field from source/seed data (dynamic at runtime)
        TOOL_OUTPUT: Field from tool function return type
    """

    SCHEMA = "schema"
    OBSERVE = "observe"
    PASSTHROUGH = "passthrough"
    SOURCE = "source"
    TOOL_OUTPUT = "tool_output"


@dataclass
class FieldInfo:
    """Information about a single field.

    Attributes:
        name: Field name
        source: How the field is produced (schema, observe, passthrough, etc.)
        is_required: Whether the field is required (for input fields)
        is_dropped: Whether the field is excluded from output via drops
    """

    name: str
    source: FieldSource
    is_required: bool = True
    is_dropped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "source": self.source.value,
            "is_required": self.is_required,
            "is_dropped": self.is_dropped,
        }


@dataclass
class UpstreamReference:
    """Reference to an upstream agent's field.

    Represents a template reference like {{ action.extractor.summary }}.

    Attributes:
        source_agent: Name of the agent being referenced
        field_name: Name of the field being referenced
        location: Where it appears in config (prompt, guard, context_scope.observe, etc.)
        raw_reference: Original reference string (e.g., '{{ action.extractor.summary }}')
    """

    source_agent: str
    field_name: str
    location: str
    raw_reference: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_agent": self.source_agent,
            "field_name": self.field_name,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class ActionSchema:
    """Unified schema for any action type.

    Provides a consistent interface for all action types (llm, tool, source, seed).

    Attributes:
        name: Action name
        kind: Type of action (llm, tool, source, seed)
        upstream_refs: References to upstream agent fields (template references)
        input_fields: Input fields (for tools with TypedDict input)
        output_fields: Output fields with source tracking
        dependencies: Declared dependencies (depends_on)
        downstream: Actions that depend on this one
        is_dynamic: Output determined at runtime (source/seed)
        is_schemaless: No output schema defined
        is_template_based: LLM with template but no output schema
    """

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
        """Convert to dictionary for JSON serialization."""
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
            # Computed properties for convenience
            "available_outputs": self.available_outputs,
            "dropped_outputs": self.dropped_outputs,
            "required_inputs": self.required_inputs,
            "optional_inputs": self.optional_inputs,
            "uses_fields": self.uses_fields,
        }
