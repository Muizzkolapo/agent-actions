"""
Abstract Syntax Tree nodes for WHERE clause parsing.

This module defines the AST nodes that represent parsed WHERE clause expressions.
Each node can be evaluated against data using the visitor pattern.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from agent_actions.utilities.dict_utils import get_nested_value
from .operator_registry import OperatorRegistry, get_global_registry

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """Types of AST nodes in the WHERE clause tree."""

    COMPARISON = "comparison"
    LOGICAL = "logical"
    FIELD = "field"
    LITERAL = "literal"
    FUNCTION = "function"


class LogicalOperator(Enum):
    """Logical operators for combining expressions."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class ComparisonOperator(Enum):
    """Comparison operators for field comparisons."""

    EQ = "=="  # Equal
    NE = "!="  # Not equal
    LT = "<"  # Less than
    LE = "<="  # Less than or equal
    GT = ">"  # Greater than
    GE = ">="  # Greater than or equal
    IN = "IN"  # In array
    NOT_IN = "NOT IN"  # Not in array
    CONTAINS = "CONTAINS"  # String contains
    NOT_CONTAINS = "NOT CONTAINS"  # String does not contain
    LIKE = "LIKE"  # SQL-like pattern matching
    NOT_LIKE = "NOT LIKE"  # SQL-like pattern not matching
    BETWEEN = "BETWEEN"  # Between two values
    NOT_BETWEEN = "NOT BETWEEN"  # Not between two values
    IS_NULL = "IS NULL"  # Is null/None
    IS_NOT_NULL = "IS NOT NULL"  # Is not null/None


@dataclass
class ASTNode(ABC):
    """Base class for all AST nodes."""

    node_type: NodeType

    @abstractmethod
    def accept(self, visitor: "ASTVisitor") -> Any:
        """Accept a visitor to process this node."""


@dataclass
class FieldNode(ASTNode):
    """Represents a field reference (e.g., 'user.name' or 'score')."""

    node_type: NodeType
    field_path: str

    def __init__(self, field_path: str, node_type: NodeType = NodeType.FIELD):
        super().__init__(node_type)
        self.field_path = field_path

    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_field(self)


@dataclass
class LiteralNode(ASTNode):
    """Represents a literal value (string, number, boolean, array, null)."""

    node_type: NodeType
    value: Any

    def __init__(self, value: Any, node_type: NodeType = NodeType.LITERAL):
        super().__init__(node_type)
        self.value = value

    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_literal(self)


@dataclass
class ComparisonNode(ASTNode):
    """Represents a comparison operation (field operator value)."""

    node_type: NodeType
    left: ASTNode
    operator: ComparisonOperator
    right: Optional[ASTNode] = None  # Optional for unary operators like IS NULL

    def __init__(
        self,
        left: ASTNode,
        operator: ComparisonOperator,
        right: Optional[ASTNode] = None,
        node_type: NodeType = NodeType.COMPARISON,
    ):
        super().__init__(node_type)
        self.left = left
        self.operator = operator
        self.right = right

    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_comparison(self)


@dataclass
class LogicalNode(ASTNode):
    """Represents a logical operation (AND, OR, NOT)."""

    node_type: NodeType
    operator: LogicalOperator
    left: ASTNode
    right: Optional[ASTNode] = None  # Optional for unary operators like NOT

    def __init__(
        self,
        operator: LogicalOperator,
        left: ASTNode,
        right: Optional[ASTNode] = None,
        node_type: NodeType = NodeType.LOGICAL,
    ):
        super().__init__(node_type)
        self.operator = operator
        self.left = left
        self.right = right

    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_logical(self)


@dataclass
class FunctionNode(ASTNode):
    """Represents a function call in the WHERE clause."""

    node_type: NodeType
    function_name: str
    arguments: List[ASTNode]

    def __init__(
        self, function_name: str, arguments: List[ASTNode], node_type: NodeType = NodeType.FUNCTION
    ):
        super().__init__(node_type)
        self.function_name = function_name
        self.arguments = arguments

    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_function(self)


class ASTVisitor(ABC):
    """Visitor interface for processing AST nodes."""

    @abstractmethod
    def visit_field(self, node: FieldNode) -> Any:
        """Visit a field node."""

    @abstractmethod
    def visit_literal(self, node: LiteralNode) -> Any:
        """Visit a literal node."""

    @abstractmethod
    def visit_comparison(self, node: ComparisonNode) -> Any:
        """Visit a comparison node."""

    @abstractmethod
    def visit_logical(self, node: LogicalNode) -> Any:
        """Visit a logical node."""

    @abstractmethod
    def visit_function(self, node: FunctionNode) -> Any:
        """Visit a function node."""


class EvaluationContext:
    """Context for evaluating WHERE clause expressions."""

    def __init__(
        self,
        data: Dict[str, Any],
        functions: Optional[Dict[str, Callable[..., Any]]] = None,
        debug: bool = False,
    ):
        """
        Initialize evaluation context.

        Args:
            data: The data dictionary to evaluate against
            functions: Optional dictionary of available functions
            debug: Enable debug logging for comparison failures (default: False)
        """
        self.data = data
        self.functions = functions or {}
        self.debug = debug

    def get_field_value(self, field_path: str) -> Any:
        """
        Get the value of a field using dot notation.

        Args:
            field_path: Field path like 'user.name' or 'score'

        Returns:
            The field value or None if not found
        """
        return get_nested_value(self.data, field_path)

    def call_function(self, function_name: str, args: List[Any]) -> Any:
        """
        Call a registered function.

        Args:
            function_name: Name of the function to call
            args: Arguments to pass to the function

        Returns:
            The function result

        Raises:
            ValueError: If function is not registered
        """
        if function_name not in self.functions:
            raise ValueError(f"Function '{function_name}' is not registered")

        func = self.functions[function_name]
        return func(*args)


class WhereClauseAST:
    """Container for a WHERE clause AST with evaluation capabilities."""

    def __init__(self, root: ASTNode):
        """
        Initialize the AST.

        Args:
            root: The root node of the AST
        """
        self.root = root

    def evaluate(
        self, data: Dict[str, Any], functions: Optional[Dict[str, Callable[..., Any]]] = None
    ) -> bool:
        """
        Evaluate the WHERE clause against the given data.

        Args:
            data: Data dictionary to evaluate against
            functions: Optional dictionary of available functions

        Returns:
            True if the WHERE clause matches, False otherwise
        """
        context = EvaluationContext(data, functions)
        evaluator = WhereClauseEvaluator(context)
        return self.root.accept(evaluator)

    def __str__(self) -> str:
        """Return a string representation of the AST."""
        formatter = ASTFormatter()
        return self.root.accept(formatter)


class WhereClauseEvaluator(ASTVisitor):
    """Evaluates WHERE clause AST nodes against data."""

    def __init__(
        self, context: EvaluationContext, operator_registry: Optional[OperatorRegistry] = None
    ):
        """
        Initialize the evaluator.

        Args:
            context: Evaluation context containing data and functions
            operator_registry: Optional operator registry (uses global if not provided)
        """
        self.context = context
        self.registry = operator_registry or get_global_registry()

        # Map ComparisonOperator enum values to operator registry names
        self._operator_map = {
            ComparisonOperator.EQ: "EQ",
            ComparisonOperator.NE: "NE",
            ComparisonOperator.LT: "LT",
            ComparisonOperator.LE: "LE",
            ComparisonOperator.GT: "GT",
            ComparisonOperator.GE: "GE",
            ComparisonOperator.IN: "IN",
            ComparisonOperator.NOT_IN: "NOT_IN",
            ComparisonOperator.CONTAINS: "CONTAINS",
            ComparisonOperator.NOT_CONTAINS: "NOT_CONTAINS",
            ComparisonOperator.LIKE: "LIKE",
            ComparisonOperator.NOT_LIKE: "NOT_LIKE",
            ComparisonOperator.BETWEEN: "BETWEEN",
            ComparisonOperator.NOT_BETWEEN: "NOT_BETWEEN",
            ComparisonOperator.IS_NULL: "IS_NULL",
            ComparisonOperator.IS_NOT_NULL: "IS_NOT_NULL",
        }

        # Performance optimization: Pre-cache operator instances to eliminate registry lookups
        # This reduces overhead on every comparison evaluation
        self._operator_cache = {
            op_enum: self.registry.get_operator(name)
            for op_enum, name in self._operator_map.items()
        }

    def visit_field(self, node: FieldNode) -> Any:
        """Get the value of a field from the context data."""
        return self.context.get_field_value(node.field_path)

    def visit_literal(self, node: LiteralNode) -> Any:
        """Return the literal value."""
        return node.value

    def visit_comparison(self, node: ComparisonNode) -> bool:
        """
        Evaluate a comparison operation using the operator registry.

        This method delegates to the operator registry for evaluation,
        reducing complexity from CC 27 to CC 3.

        Improvements:
        - Uses pre-cached operator instances (eliminates registry lookups)
        - Explicit null safety for unary vs binary operators
        - Passes evaluation context to operators for future extensibility
        - Graceful error handling with optional debug logging

        Example:
            node = ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(21))
            result = evaluator.visit_comparison(node)  # Delegates to GreaterThanOperator

        Args:
            node: ComparisonNode to evaluate

        Returns:
            Boolean result of the comparison

        Raises:
            ValueError: If operator is unknown or not found in cache
        """
        left_value = node.left.accept(self)

        # Get operator from pre-cached instances (performance optimization)
        operator = self._operator_cache.get(node.operator)
        if not operator:
            raise ValueError(f"Unknown comparison operator: {node.operator}")

        # Null safety: Explicit handling for unary vs binary operators
        if node.operator in (ComparisonOperator.IS_NULL, ComparisonOperator.IS_NOT_NULL):
            # Unary operators don't need a right operand
            right_value = None
        elif node.right is None:
            # Binary operators require a right operand
            raise ValueError(f"Binary operator {node.operator} requires a right operand")
        else:
            # Evaluate right operand for binary operators
            right_value = node.right.accept(self)

        try:
            # Pass context to operators for future extensibility
            return operator.evaluate(left_value, right_value, context=self.context)
        except (TypeError, ValueError) as e:
            # Handle type errors gracefully (e.g., comparing string to number)
            # Optional debug logging if enabled
            if hasattr(self.context, "debug") and self.context.debug:
                logger.debug(
                    "Comparison failed: %s on %r, %r: %s", node.operator, left_value, right_value, e
                )
            # Maintain backward-compatible fail-safe behavior
            return False

    def visit_logical(self, node: LogicalNode) -> bool:
        """Evaluate a logical operation."""
        left_result = node.left.accept(self)

        if node.operator == LogicalOperator.NOT:
            return not left_result
        if node.operator == LogicalOperator.AND:
            if not left_result:
                return False  # Short-circuit evaluation
            if node.right is None:
                raise ValueError("AND operator requires a right operand")
            return node.right.accept(self)
        if node.operator == LogicalOperator.OR:
            if left_result:
                return True  # Short-circuit evaluation
            if node.right is None:
                raise ValueError("OR operator requires a right operand")
            return node.right.accept(self)
        raise ValueError(f"Unknown logical operator: {node.operator}")

    def visit_function(self, node: FunctionNode) -> Any:
        """Evaluate a function call."""
        args = [arg.accept(self) for arg in node.arguments]
        return self.context.call_function(node.function_name, args)


class ASTFormatter(ASTVisitor):
    """Formats AST nodes back to string representation."""

    def visit_field(self, node: FieldNode) -> str:
        return node.field_path

    def visit_literal(self, node: LiteralNode) -> str:
        if node.value is None:
            return "NULL"
        if isinstance(node.value, str):
            return f'"{node.value}"'
        if isinstance(node.value, bool):
            return "TRUE" if node.value else "FALSE"
        if isinstance(node.value, (list, tuple)):
            items = [self.visit_literal(LiteralNode(item)) for item in node.value]
            return f"[{', '.join(items)}]"
        return str(node.value)

    def visit_comparison(self, node: ComparisonNode) -> str:
        left_str = node.left.accept(self)

        if node.operator in (ComparisonOperator.IS_NULL, ComparisonOperator.IS_NOT_NULL):
            return f"{left_str} {node.operator.value}"

        if node.right is None:
            raise ValueError(f"Binary operator {node.operator.value} requires a right operand")

        right_str = node.right.accept(self)
        return f"{left_str} {node.operator.value} {right_str}"

    def visit_logical(self, node: LogicalNode) -> str:
        left_str = node.left.accept(self)

        if node.operator == LogicalOperator.NOT:
            return f"NOT ({left_str})"

        if node.right is None:
            raise ValueError(f"Binary operator {node.operator.value} requires a right operand")

        right_str = node.right.accept(self)
        return f"({left_str} {node.operator.value} {right_str})"

    def visit_function(self, node: FunctionNode) -> str:
        args_str = ", ".join(arg.accept(self) for arg in node.arguments)
        return f"{node.function_name}({args_str})"
