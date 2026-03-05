"""
Preprocessing module for Agent Actions framework.
"""

# Parsing submodule
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

# Filtering submodule
from .filtering.guard_filter import GuardFilter, FilterResult, FilterMetrics

# Chunking submodule
from .chunking.field_chunking import FieldChunker, FieldAnalyzer, FieldAnalysisResult

# Transformation submodule
from .transformation.transformer import DataTransformer
from .transformation.string_transformer import StringProcessor, Tokenizer

# Context submodule
from agent_actions.input.context.context_preprocessor import ContextPreprocessor
from agent_actions.input.context.historical import HistoricalNodeDataLoader

# Initial stage pipeline - Lazy imports to avoid circular dependencies
# These imports are deferred because initial_stage_pipeline imports BatchService,
# which imports DataTransformer, creating a circular dependency chain.
# Use: from agent_actions.input.preprocessing.staging.initial_pipeline import process_initial_stage
# from .staging.initial_pipeline import process_initial_stage

# Processing submodule - Lazy import to avoid circular dependencies
# DataProcessor imports from processor_helpers, which imports agent_builder,
# which imports prompt_utils, which imports StringProcessor from preprocessing.
# Use: from agent_actions.input.preprocessing.processing.data_processor import DataProcessor
# from .processing.data_processor import DataProcessor

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
