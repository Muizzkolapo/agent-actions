"""Static workflow analysis for compile-time type checking."""

from .data_flow_graph import (
    AgentKind,
    DataFlowEdge,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    InputSchema,
    OutputSchema,
)
from .errors import (
    ErrorSeverity,
    FieldLocation,
    StaticTypeError,
    StaticTypeIssue,
    StaticTypeWarning,
    StaticValidationResult,
)
from .reference_extractor import ReferenceExtractor
from .schema_extractor import SchemaExtractor
from .schema_structure_validator import SchemaStructureValidator
from .type_checker import StaticTypeChecker
from .workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
    analyze_workflow,
)
from .field_flow_analyzer import (
    FieldFlowAnalyzer,
    FieldLineage,
    FieldConsumer,
    FieldReference,
    ActionFlowInfo,
    InputSchemaInfo,
    OutputFieldInfo,
    WorkflowFlow,
)
from .conflict_detector import (
    ConflictDetector,
    ConflictAnalysisResult,
    Conflict,
    ConflictType,
    ConflictSeverity,
    FieldProducer,
    AffectedReference,
)

__all__ = [
    # Main entry points
    "WorkflowStaticAnalyzer",
    "analyze_workflow",
    # Graph components
    "DataFlowGraph",
    "DataFlowNode",
    "DataFlowEdge",
    "OutputSchema",
    "InputSchema",
    "InputRequirement",
    "AgentKind",
    # Extractors
    "SchemaExtractor",
    "ReferenceExtractor",
    # Type checker
    "StaticTypeChecker",
    # Schema structure validator
    "SchemaStructureValidator",
    # Field flow analyzer
    "FieldFlowAnalyzer",
    "FieldLineage",
    "FieldConsumer",
    "FieldReference",
    "ActionFlowInfo",
    "InputSchemaInfo",
    "OutputFieldInfo",
    "WorkflowFlow",
    # Errors
    "StaticValidationResult",
    "StaticTypeError",
    "StaticTypeWarning",
    "StaticTypeIssue",
    "FieldLocation",
    "ErrorSeverity",
    # Conflict detector
    "ConflictDetector",
    "ConflictAnalysisResult",
    "Conflict",
    "ConflictType",
    "ConflictSeverity",
    "FieldProducer",
    "AffectedReference",
]
