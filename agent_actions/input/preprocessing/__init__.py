"""Preprocessing module for Agent Actions framework."""

from .parsing.ast_nodes import (
    ASTNode,
    FieldNode,
    LiteralNode,
    ComparisonNode,
    LogicalNode,
    FunctionNode,
    NodeType,
    LogicalOperator,
    ComparisonOperator,
    WhereClauseAST,
    evaluate_node,
    format_node,
)
from .parsing.parser import WhereClauseParser
from .filtering.guard_filter import GuardFilter, FilterResult, FilterMetrics
from .chunking.field_chunking import FieldChunker, FieldAnalyzer, FieldAnalysisResult
from .transformation.transformer import DataTransformer
from .transformation.string_transformer import StringProcessor, Tokenizer
from agent_actions.input.context.context_preprocessor import ContextPreprocessor
from agent_actions.input.context.historical import HistoricalNodeDataLoader

# Lazy imports to avoid circular dependencies:
# - staging.initial_pipeline: imports BatchService -> DataTransformer (circular)
# - processing.data_processor: imports processor_helpers -> agent_builder -> StringProcessor (circular)

__all__ = [
    # Parsing - AST Nodes
    "ASTNode",
    "FieldNode",
    "LiteralNode",
    "ComparisonNode",
    "LogicalNode",
    "FunctionNode",
    "NodeType",
    "LogicalOperator",
    "ComparisonOperator",
    "WhereClauseAST",
    "evaluate_node",
    "format_node",
    "WhereClauseParser",
    # Filtering
    "GuardFilter",
    "FilterResult",
    "FilterMetrics",
    # Chunking
    "FieldChunker",
    "FieldAnalyzer",
    "FieldAnalysisResult",
    # Transformation
    "DataTransformer",
    "StringProcessor",
    "Tokenizer",
    # Context
    "ContextPreprocessor",
    "HistoricalNodeDataLoader",
    # Initial stage pipeline - Not exported to avoid circular imports
    # Import directly: from agent_actions.input.preprocessing.staging.initial_pipeline
    # import process_initial_stage
    # Processing - Not exported to avoid circular imports
    # Import directly: from agent_actions.input.preprocessing.processing.data_processor
    # import DataProcessor
]
