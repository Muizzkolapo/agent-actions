"""
Preprocessing module for Agent Actions framework.

This module provides data preprocessing, transformation, filtering, chunking,
and staging operations for agent-based workflows.

Submodules:
- parsing: WHERE clause AST parsing and operator registry
- filtering: Dataset filtering logic with WHERE clause support
- chunking: Field-level text splitting with strategies
- transformation: Data structure transformations (dict, string, response)
- context: Historical context preprocessing
- staging: Staging data loading and processing
- processing: Core data processor with registry
- utilities: Source path management
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
from .filtering.where_filter import WhereClauseFilter, FilterResult, FilterMetrics
from .filtering.filter_service import FilterService, FilterStatus
from .filtering.where_clause_handler import WhereClauseHandler, WhereClauseConfig, FilterBehavior

# Chunking submodule
from .chunking.field_chunking import FieldChunker, FieldAnalyzer, FieldAnalysisResult

# Transformation submodule
from .transformation.data_transformer import DataTransformer
from .transformation.string_transformer import StringProcessor, Tokenizer
from .transformation.response_transformer import ResponseTransformer

# Context submodule
from .context.context_preprocessor import ContextPreprocessor
from .context.historical_node_loader import HistoricalNodeDataLoader

# Staging submodule
from .staging.staging_loader import generate_staging
from .staging.staging_content import StagingContentLoader
from .staging.staging_processor import StagingProcessor

# Processing submodule
from .processing.data_processor import DataProcessor

# Utilities submodule
from .utilities.source_path_manager import SourcePathManager

__all__ = [
    # Parsing - AST Nodes
    'ASTNode',
    'FieldNode',
    'LiteralNode',
    'ComparisonNode',
    'LogicalNode',
    'FunctionNode',
    'NodeType',
    'LogicalOperator',
    'ComparisonOperator',
    'ASTVisitor',
    'EvaluationContext',
    'WhereClauseAST',
    'WhereClauseEvaluator',
    'ASTFormatter',
    'WhereClauseParser',
    'OperatorRegistry',
    # Filtering
    'WhereClauseFilter',
    'FilterResult',
    'FilterMetrics',
    'FilterService',
    'FilterStatus',
    'WhereClauseHandler',
    'WhereClauseConfig',
    'FilterBehavior',
    # Chunking
    'FieldChunker',
    'FieldAnalyzer',
    'FieldAnalysisResult',
    # Transformation
    'DataTransformer',
    'StringProcessor',
    'Tokenizer',
    'ResponseTransformer',
    # Context
    'ContextPreprocessor',
    'HistoricalNodeDataLoader',
    # Staging
    'generate_staging',
    'StagingContentLoader',
    'StagingProcessor',
    # Processing
    'DataProcessor',
    # Utilities
    'SourcePathManager',
]