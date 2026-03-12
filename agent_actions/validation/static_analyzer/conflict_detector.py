"""Conflict detector for workflow field name collisions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .data_flow_graph import DataFlowGraph


class ConflictSeverity(Enum):
    """Severity level of a conflict."""

    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


class ConflictType(Enum):
    """Type of conflict detected."""

    SHADOWING = "shadowing"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    DROP_RECREATE = "drop_recreate"
    RESERVED_NAME = "reserved_name"


@dataclass
class FieldProducer:
    """Information about an action that produces a field."""

    action: str
    field_source: str  # 'schema', 'observe', 'passthrough'

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "action": self.action,
            "field_source": self.field_source,
        }


@dataclass
class AffectedReference:
    """A reference affected by a conflict."""

    action: str
    location: str
    raw_reference: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "action": self.action,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class Conflict:
    """Base class for all conflict types."""

    conflict_type: ConflictType
    severity: ConflictSeverity
    field_name: str
    message: str
    resolution: str
    producers: list[FieldProducer] = field(default_factory=list)
    affected_references: list[AffectedReference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.conflict_type.value,
            "severity": self.severity.value,
            "field_name": self.field_name,
            "message": self.message,
            "resolution": self.resolution,
            "producers": [p.to_dict() for p in self.producers],
            "affected_references": [r.to_dict() for r in self.affected_references],
        }


@dataclass
class ConflictAnalysisResult:
    """Result of conflict analysis."""

    workflow_name: str
    conflicts: list[Conflict] = field(default_factory=list)
    actions_analyzed: int = 0
    unique_fields: int = 0
    shadowed_fields: int = 0

    @property
    def has_conflicts(self) -> bool:
        """Check if any conflicts were detected."""
        return len(self.conflicts) > 0

    @property
    def error_count(self) -> int:
        """Count of error-level conflicts."""
        return sum(1 for c in self.conflicts if c.severity == ConflictSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level conflicts."""
        return sum(1 for c in self.conflicts if c.severity == ConflictSeverity.WARNING)

    def filter_by_action(self, action_name: str) -> "ConflictAnalysisResult":
        """Filter conflicts to those affecting a specific action."""
        filtered = []
        for conflict in self.conflicts:
            if any(p.action == action_name for p in conflict.producers):
                filtered.append(conflict)
                continue
            if any(r.action == action_name for r in conflict.affected_references):
                filtered.append(conflict)

        return ConflictAnalysisResult(
            workflow_name=self.workflow_name,
            conflicts=filtered,
            actions_analyzed=self.actions_analyzed,
            unique_fields=self.unique_fields,
            shadowed_fields=self.shadowed_fields,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "workflow_name": self.workflow_name,
            "has_conflicts": self.has_conflicts,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "summary": {
                "actions_analyzed": self.actions_analyzed,
                "unique_fields": self.unique_fields,
                "shadowed_fields": self.shadowed_fields,
            },
        }


# Reserved names that shouldn't be used as field names
RESERVED_NAMES = frozenset({"source", "seed", "loop", "workflow", "action"})


class ConflictDetector:
    """Detects field name conflicts such as shadowing and ambiguous references."""

    def __init__(self, graph: DataFlowGraph, workflow_name: str = ""):
        """Initialize the conflict detector."""
        self.graph = graph
        self.workflow_name = workflow_name

        self._field_producers: dict[str, list[FieldProducer]] = {}
        self._build_field_mapping()

    def _build_field_mapping(self) -> None:
        """Build mapping of field names to their producers."""
        for node in self.graph.nodes.values():
            if self.graph.is_special_namespace(node.name):
                continue

            output = node.output_schema

            # Track schema fields
            for field_name in output.schema_fields:
                if field_name not in output.dropped_fields:
                    self._add_producer(field_name, node.name, "schema")

            # Track observe fields
            for field_name in output.observe_fields:
                if field_name not in output.dropped_fields:
                    self._add_producer(field_name, node.name, "observe")

            # Track passthrough fields
            for field_name in output.passthrough_fields:
                if field_name not in output.dropped_fields:
                    self._add_producer(field_name, node.name, "passthrough")

    def _add_producer(self, field_name: str, action: str, source: str) -> None:
        """Add a producer for a field."""
        if field_name not in self._field_producers:
            self._field_producers[field_name] = []
        self._field_producers[field_name].append(FieldProducer(action, source))

    def detect_all(self) -> ConflictAnalysisResult:
        """Detect all conflicts in the workflow."""
        conflicts: list[Conflict] = []

        conflicts.extend(self._detect_shadowing())
        conflicts.extend(self._detect_ambiguous_references())
        conflicts.extend(self._detect_reserved_names())
        conflicts.extend(self._detect_drop_recreate())
        actions = [n for n in self.graph.nodes if not self.graph.is_special_namespace(n)]
        shadowed = [f for f, p in self._field_producers.items() if len(p) > 1]

        return ConflictAnalysisResult(
            workflow_name=self.workflow_name,
            conflicts=conflicts,
            actions_analyzed=len(actions),
            unique_fields=len(self._field_producers),
            shadowed_fields=len(shadowed),
        )

    def _detect_shadowing(self) -> list[Conflict]:
        """Detect fields produced by multiple actions."""
        conflicts = []

        for field_name, producers in self._field_producers.items():
            if len(producers) > 1:
                affected = self._find_field_references(field_name)

                producer_names = [p.action for p in producers]
                qualified_refs = " or ".join(
                    f"{{{{ action.{p}.{field_name} }}}}" for p in producer_names
                )

                conflicts.append(
                    Conflict(
                        conflict_type=ConflictType.SHADOWING,
                        severity=ConflictSeverity.WARNING,
                        field_name=field_name,
                        message=(
                            f"Field '{field_name}' is produced by multiple actions: "
                            f"{', '.join(producer_names)}"
                        ),
                        resolution=f"Use qualified reference: {qualified_refs}",
                        producers=producers,
                        affected_references=affected,
                    )
                )

        return conflicts

    def _detect_ambiguous_references(self) -> list[Conflict]:
        """Detect unqualified references to shadowed fields."""
        conflicts = []
        shadowed_fields = {f for f, p in self._field_producers.items() if len(p) > 1}

        for node in self.graph.nodes.values():
            if self.graph.is_special_namespace(node.name):
                continue

            for req in node.input_requirements:
                if req.field_path in shadowed_fields:
                    producers = self._field_producers[req.field_path]
                    producer_names = [p.action for p in producers]

                    if req.source_agent in ("source", "seed", "loop"):
                        qualified_refs = " or ".join(
                            f"{{{{ action.{p}.{req.field_path} }}}}" for p in producer_names
                        )

                        conflicts.append(
                            Conflict(
                                conflict_type=ConflictType.AMBIGUOUS_REFERENCE,
                                severity=ConflictSeverity.ERROR,
                                field_name=req.field_path,
                                message=(
                                    f"Ambiguous reference '{req.raw_reference}' in "
                                    f"action '{node.name}' could match multiple sources"
                                ),
                                resolution=f"Use qualified reference: {qualified_refs}",
                                producers=producers,
                                affected_references=[
                                    AffectedReference(
                                        action=node.name,
                                        location=req.location,
                                        raw_reference=req.raw_reference,
                                    )
                                ],
                            )
                        )

        return conflicts

    def _detect_reserved_names(self) -> list[Conflict]:
        """Detect fields using reserved namespace names."""
        conflicts = []

        for field_name, producers in self._field_producers.items():
            if field_name in RESERVED_NAMES:
                conflicts.append(
                    Conflict(
                        conflict_type=ConflictType.RESERVED_NAME,
                        severity=ConflictSeverity.WARNING,
                        field_name=field_name,
                        message=(
                            f"Field '{field_name}' uses a reserved name that may "
                            f"conflict with system namespaces"
                        ),
                        resolution="Consider renaming the field to avoid confusion",
                        producers=producers,
                        affected_references=[],
                    )
                )

        return conflicts

    def _detect_drop_recreate(self) -> list[Conflict]:
        """Detect fields that are dropped then recreated."""
        conflicts = []

        dropped_by: dict[str, str] = {}

        for node in self.graph.nodes.values():
            if self.graph.is_special_namespace(node.name):
                continue

            for field_name in node.output_schema.dropped_fields:
                dropped_by[field_name] = node.name

        for node in self.graph.nodes.values():
            if self.graph.is_special_namespace(node.name):
                continue

            for field_name in node.output_schema.schema_fields:
                if field_name in dropped_by and dropped_by[field_name] != node.name:
                    conflicts.append(
                        Conflict(
                            conflict_type=ConflictType.DROP_RECREATE,
                            severity=ConflictSeverity.INFO,
                            field_name=field_name,
                            message=(
                                f"Field '{field_name}' was dropped by "
                                f"'{dropped_by[field_name]}' and recreated by '{node.name}'"
                            ),
                            resolution="This may be intentional. Verify the workflow logic.",
                            producers=[FieldProducer(node.name, "schema")],
                            affected_references=[],
                        )
                    )

        return conflicts

    def _find_field_references(self, field_name: str) -> list[AffectedReference]:
        """Find all references to a field name."""
        references = []

        for node in self.graph.nodes.values():
            if self.graph.is_special_namespace(node.name):
                continue

            for req in node.input_requirements:
                if req.field_path == field_name:
                    references.append(
                        AffectedReference(
                            action=node.name,
                            location=req.location,
                            raw_reference=req.raw_reference,
                        )
                    )

        return references

    def get_shadowed_fields(self) -> dict[str, list[str]]:
        """Get mapping of shadowed field names to their producer action names."""
        return {
            field_name: [p.action for p in producers]
            for field_name, producers in self._field_producers.items()
            if len(producers) > 1
        }
