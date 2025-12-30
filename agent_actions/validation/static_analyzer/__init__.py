"""Static workflow analysis for compile-time type checking.

This module provides TypeScript-like static type checking for workflow
configurations. It validates that all field references are valid before
any execution, catching errors at config load time rather than runtime.

Example:
    from agent_actions.validation.static_analyzer import (
        WorkflowStaticAnalyzer,
        analyze_workflow,
    )

    # Analyze a workflow config
    result = analyze_workflow(workflow_config)

    if not result.is_valid:
        print(result.format_report())
        raise ValueError("Static type checking failed")

    # Or use the class directly
    analyzer = WorkflowStaticAnalyzer(workflow_config)
    result = analyzer.analyze()

    # Get data flow summary
    summary = analyzer.get_data_flow_summary()
"""

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
from .type_checker import StaticTypeChecker
from .workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
    analyze_workflow,
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
    # Errors
    "StaticValidationResult",
    "StaticTypeError",
    "StaticTypeWarning",
    "StaticTypeIssue",
    "FieldLocation",
    "ErrorSeverity",
]
