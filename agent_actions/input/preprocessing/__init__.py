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
    ASTVisitor,
    EvaluationContext,
    WhereClauseAST,
    WhereClauseEvaluator,
    ASTFormatter,
)
from .parsing.parser import WhereClauseParser
from .parsing.operator_registry import OperatorRegistry

# Filtering submodule
from .filtering.guard_filter import GuardFilter, FilterResult, FilterMetrics
from .filtering.filter_service import FilterService, FilterStatus
from .filtering.guard_handler import GuardHandler, GuardConfig, FilterBehavior

# Chunking submodule
from .chunking.field_chunking import FieldChunker, FieldAnalyzer, FieldAnalysisResult

# Transformation submodule
from .transformation.data_transformer import DataTransformer
from .transformation.string_transformer import StringProcessor, Tokenizer

# Context submodule
from .context.context_preprocessor import ContextPreprocessor
from .context.historical_node_loader import HistoricalNodeDataLoader

# Initial stage pipeline - Lazy imports to avoid circular dependencies
# These imports are deferred because initial_stage_pipeline imports BatchService,
# which imports DataTransformer, creating a circular dependency chain.
# Use: from agent_actions.input.preprocessing.staging.initial_stage_pipeline import process_initial_stage
# from .staging.initial_stage_pipeline import process_initial_stage

# Processing submodule - Lazy import to avoid circular dependencies
# DataProcessor imports from processor_helpers, which imports agent_builder,
# which imports prompt_utils, which imports StringProcessor from preprocessing.
# Use: from agent_actions.input.preprocessing.processing.data_processor import DataProcessor
# from .processing.data_processor import DataProcessor

# Utilities submodule
from .utilities.source_path_manager import SourcePathManager

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
    "ASTVisitor",
    "EvaluationContext",
    "WhereClauseAST",
    "WhereClauseEvaluator",
    "ASTFormatter",
    "WhereClauseParser",
    "OperatorRegistry",
    # Filtering
    "GuardFilter",
    "FilterResult",
    "FilterMetrics",
    "FilterService",
    "FilterStatus",
    "GuardHandler",
    "GuardConfig",
    "FilterBehavior",
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
    # Import directly: from agent_actions.input.preprocessing.staging.initial_stage_pipeline
    # import process_initial_stage
    # Processing - Not exported to avoid circular imports
    # Import directly: from agent_actions.input.preprocessing.processing.data_processor
    # import DataProcessor
    # Utilities
    "SourcePathManager",
]
