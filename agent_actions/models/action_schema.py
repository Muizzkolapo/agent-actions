"""Unified schema model for workflow actions.

Provides a single, consistent representation for action schemas used by
both the `schema` and `inspect` CLI commands, eliminating duplication.

Example:
    from agent_actions.models import ActionSchema, FieldInfo, FieldSource

    schema = ActionSchema(
        name="extractor",
        kind="llm",
        output_fields=[
            FieldInfo(name="summary", source=FieldSource.SCHEMA),
            FieldInfo(name="title", source=FieldSource.OBSERVE),
        ],
    )
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


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

    def to_dict(self) -> Dict[str, Any]:
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
    Replaces the duplicate InputRequirement and FieldReference classes.

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

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_agent": self.source_agent,
            "field_name": self.field_name,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class ActionSchema:  # pylint: disable=too-many-instance-attributes
    """Unified schema for any action type.

    Provides a consistent interface for all action types (llm, tool, source, seed),
    consolidating OutputSchema, OutputFieldInfo, InputSchema, and InputSchemaInfo
    into a single representation.

    Attributes:
        name: Action name
        kind: Type of action ('llm', 'tool', 'source', 'seed')
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
    kind: str
    upstream_refs: List[UpstreamReference] = field(default_factory=list)
    input_fields: List[FieldInfo] = field(default_factory=list)
    output_fields: List[FieldInfo] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    downstream: List[str] = field(default_factory=list)
    is_dynamic: bool = False
    is_schemaless: bool = False
    is_template_based: bool = False

    @property
    def available_outputs(self) -> List[str]:
        """Fields available to downstream agents (excludes dropped)."""
        return sorted(f.name for f in self.output_fields if not f.is_dropped)

    @property
    def dropped_outputs(self) -> List[str]:
        """Fields explicitly dropped from output."""
        return sorted(f.name for f in self.output_fields if f.is_dropped)

    @property
    def required_inputs(self) -> List[str]:
        """Required input field names (for tools)."""
        return sorted(f.name for f in self.input_fields if f.is_required)

    @property
    def optional_inputs(self) -> List[str]:
        """Optional input field names (for tools)."""
        return sorted(f.name for f in self.input_fields if not f.is_required)

    @property
    def uses_fields(self) -> List[str]:
        """Unique 'agent.field' references from upstream."""
        seen = set()
        result = []
        for ref in self.upstream_refs:
            key = f"{ref.source_agent}.{ref.field_name}"
            if key not in seen:
                seen.add(key)
                result.append(key)
        return sorted(result)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "kind": self.kind,
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
