"""AST nodes for WHERE clause parsing and evaluation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent_actions.utils.dict import get_nested_value

from .operators import FUNCTIONS, OPERATORS

logger = logging.getLogger(__name__)


class MissingFieldError(ValueError):
    """Raised when a guard condition references a field that doesn't exist in the data."""

    pass


def _field_exists(data: Any, field_path: str) -> bool:
    """Check if a field path exists in the data (distinguishes None value from missing)."""
    keys = field_path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return False
    return True


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
class ASTNode:
    """Base class for all AST nodes."""

    node_type: NodeType


@dataclass
class FieldNode(ASTNode):
    """Represents a field reference (e.g., 'user.name' or 'score')."""

    node_type: NodeType
    field_path: str

    def __init__(self, field_path: str, node_type: NodeType = NodeType.FIELD):
        super().__init__(node_type)
        self.field_path = field_path


@dataclass
class LiteralNode(ASTNode):
    """Represents a literal value (string, number, boolean, array, null)."""

    node_type: NodeType
    value: Any

    def __init__(self, value: Any, node_type: NodeType = NodeType.LITERAL):
        super().__init__(node_type)
        self.value = value


@dataclass
class ComparisonNode(ASTNode):
    """Represents a comparison operation (field operator value)."""

    node_type: NodeType
    left: ASTNode
    operator: ComparisonOperator
    right: ASTNode | None = None  # Optional for unary operators like IS NULL

    def __init__(
        self,
        left: ASTNode,
        operator: ComparisonOperator,
        right: ASTNode | None = None,
        node_type: NodeType = NodeType.COMPARISON,
    ):
        super().__init__(node_type)
        self.left = left
        self.operator = operator
        self.right = right


@dataclass
class LogicalNode(ASTNode):
    """Represents a logical operation (AND, OR, NOT)."""

    node_type: NodeType
    operator: LogicalOperator
    left: ASTNode
    right: ASTNode | None = None  # Optional for unary operators like NOT

    def __init__(
        self,
        operator: LogicalOperator,
        left: ASTNode,
        right: ASTNode | None = None,
        node_type: NodeType = NodeType.LOGICAL,
    ):
        super().__init__(node_type)
        self.operator = operator
        self.left = left
        self.right = right


@dataclass
class FunctionNode(ASTNode):
    """Represents a function call in the WHERE clause."""

    node_type: NodeType
    function_name: str
    arguments: list[ASTNode]

    def __init__(
        self, function_name: str, arguments: list[ASTNode], node_type: NodeType = NodeType.FUNCTION
    ):
        super().__init__(node_type)
        self.function_name = function_name
        self.arguments = arguments


def evaluate_node(
    node: ASTNode,
    data: dict[str, Any],
    functions: dict[str, Callable[..., Any]] | None = None,
) -> Any:
    """Recursively evaluate an AST node against data."""
    if isinstance(node, FieldNode):
        value = get_nested_value(data, node.field_path)
        if value is None and not _field_exists(data, node.field_path):
            available = (
                ", ".join(sorted(data.keys())) if isinstance(data, dict) else "(non-dict data)"
            )
            raise MissingFieldError(
                f"Guard condition references field '{node.field_path}' which does not exist "
                f"in the data. Available top-level fields: {available}"
            )
        return value

    if isinstance(node, LiteralNode):
        return node.value

    if isinstance(node, ComparisonNode):
        try:
            left_value = evaluate_node(node.left, data, functions)
        except MissingFieldError:
            if node.operator == ComparisonOperator.IS_NULL:
                return True
            if node.operator == ComparisonOperator.IS_NOT_NULL:
                return False
            raise

        op_fn = OPERATORS.get(node.operator.name)
        if not op_fn:
            raise ValueError(f"Unknown comparison operator: {node.operator}")

        if node.operator in (ComparisonOperator.IS_NULL, ComparisonOperator.IS_NOT_NULL):
            right_value = None
        elif node.right is None:
            raise ValueError(f"Binary operator {node.operator} requires a right operand")
        else:
            right_value = evaluate_node(node.right, data, functions)

        try:
            return op_fn(left_value, right_value)
        except (TypeError, ValueError):
            return False

    if isinstance(node, LogicalNode):
        left_result = evaluate_node(node.left, data, functions)

        if node.operator == LogicalOperator.NOT:
            return not left_result
        if node.operator == LogicalOperator.AND:
            if not left_result:
                return False
            if node.right is None:
                raise ValueError("AND operator requires a right operand")
            return evaluate_node(node.right, data, functions)
        if node.operator == LogicalOperator.OR:
            if left_result:
                return True
            if node.right is None:
                raise ValueError("OR operator requires a right operand")
            return evaluate_node(node.right, data, functions)
        raise ValueError(f"Unknown logical operator: {node.operator}")

    if isinstance(node, FunctionNode):
        args = [evaluate_node(arg, data, functions) for arg in node.arguments]
        all_funcs = {**FUNCTIONS, **(functions or {})}
        if node.function_name not in all_funcs:
            raise ValueError(f"Function '{node.function_name}' is not registered")
        func = all_funcs[node.function_name]
        # Built-in functions expect a list arg; custom functions expect *args
        if func is FUNCTIONS.get(node.function_name):
            return func(args)
        return func(*args)

    raise ValueError(f"Unknown node type: {type(node)}")


def _format_literal_value(value: Any) -> str:
    """Format a literal value for string representation."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, list | tuple):
        items = [_format_literal_value(item) for item in value]
        return f"[{', '.join(items)}]"
    return str(value)


def format_node(node: ASTNode) -> str:
    """Recursively format an AST node to a string representation."""
    if isinstance(node, FieldNode):
        return node.field_path

    if isinstance(node, LiteralNode):
        return _format_literal_value(node.value)

    if isinstance(node, ComparisonNode):
        left_str = format_node(node.left)
        if node.operator in (ComparisonOperator.IS_NULL, ComparisonOperator.IS_NOT_NULL):
            return f"{left_str} {node.operator.value}"
        if node.right is None:
            raise ValueError(f"Binary operator {node.operator.value} requires a right operand")
        right_str = format_node(node.right)
        return f"{left_str} {node.operator.value} {right_str}"

    if isinstance(node, LogicalNode):
        left_str = format_node(node.left)
        if node.operator == LogicalOperator.NOT:
            return f"NOT ({left_str})"
        if node.right is None:
            raise ValueError(f"Binary operator {node.operator.value} requires a right operand")
        right_str = format_node(node.right)
        return f"({left_str} {node.operator.value} {right_str})"

    if isinstance(node, FunctionNode):
        args_str = ", ".join(format_node(arg) for arg in node.arguments)
        return f"{node.function_name}({args_str})"

    raise ValueError(f"Unknown node type: {type(node)}")


class WhereClauseAST:
    """Container for a WHERE clause AST with evaluation capabilities."""

    def __init__(self, root: ASTNode):
        self.root = root

    def evaluate(
        self, data: dict[str, Any], functions: dict[str, Callable[..., Any]] | None = None
    ) -> bool:
        """Evaluate the WHERE clause against the given data."""
        result: bool = evaluate_node(self.root, data, functions)
        return result

    def __str__(self) -> str:
        return format_node(self.root)
