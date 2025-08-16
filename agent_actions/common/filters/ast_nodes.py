"""
Abstract Syntax Tree nodes for WHERE clause parsing.

This module defines the AST nodes that represent parsed WHERE clause expressions.
Each node can be evaluated against data using the visitor pattern.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum


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
    LT = "<"   # Less than
    LE = "<="  # Less than or equal
    GT = ">"   # Greater than
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
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor to process this node."""
        pass


@dataclass
class FieldNode(ASTNode):
    """Represents a field reference (e.g., 'user.name' or 'score')."""
    node_type: NodeType
    field_path: str
    
    def __init__(self, field_path: str, node_type: NodeType = NodeType.FIELD):
        self.node_type = node_type
        self.field_path = field_path
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        return visitor.visit_field(self)


@dataclass
class LiteralNode(ASTNode):
    """Represents a literal value (string, number, boolean, array, null)."""
    node_type: NodeType
    value: Any
    
    def __init__(self, value: Any, node_type: NodeType = NodeType.LITERAL):
        self.node_type = node_type
        self.value = value
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        return visitor.visit_literal(self)


@dataclass
class ComparisonNode(ASTNode):
    """Represents a comparison operation (field operator value)."""
    node_type: NodeType
    left: ASTNode
    operator: ComparisonOperator
    right: Optional[ASTNode] = None  # Optional for unary operators like IS NULL
    
    def __init__(self, left: ASTNode, operator: ComparisonOperator, right: Optional[ASTNode] = None, node_type: NodeType = NodeType.COMPARISON):
        self.node_type = node_type
        self.left = left
        self.operator = operator
        self.right = right
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        return visitor.visit_comparison(self)


@dataclass
class LogicalNode(ASTNode):
    """Represents a logical operation (AND, OR, NOT)."""
    node_type: NodeType
    operator: LogicalOperator
    left: ASTNode
    right: Optional[ASTNode] = None  # Optional for unary operators like NOT
    
    def __init__(self, operator: LogicalOperator, left: ASTNode, right: Optional[ASTNode] = None, node_type: NodeType = NodeType.LOGICAL):
        self.node_type = node_type
        self.operator = operator
        self.left = left
        self.right = right
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        return visitor.visit_logical(self)


@dataclass
class FunctionNode(ASTNode):
    """Represents a function call in the WHERE clause."""
    node_type: NodeType
    function_name: str
    arguments: List[ASTNode]
    
    def __init__(self, function_name: str, arguments: List[ASTNode], node_type: NodeType = NodeType.FUNCTION):
        self.node_type = node_type
        self.function_name = function_name
        self.arguments = arguments
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        return visitor.visit_function(self)


class ASTVisitor(ABC):
    """Visitor interface for processing AST nodes."""
    
    @abstractmethod
    def visit_field(self, node: FieldNode) -> Any:
        """Visit a field node."""
        pass
    
    @abstractmethod
    def visit_literal(self, node: LiteralNode) -> Any:
        """Visit a literal node."""
        pass
    
    @abstractmethod
    def visit_comparison(self, node: ComparisonNode) -> Any:
        """Visit a comparison node."""
        pass
    
    @abstractmethod
    def visit_logical(self, node: LogicalNode) -> Any:
        """Visit a logical node."""
        pass
    
    @abstractmethod
    def visit_function(self, node: FunctionNode) -> Any:
        """Visit a function node."""
        pass


class EvaluationContext:
    """Context for evaluating WHERE clause expressions."""
    
    def __init__(self, data: Dict[str, Any], functions: Optional[Dict[str, Any]] = None):
        """
        Initialize evaluation context.
        
        Args:
            data: The data dictionary to evaluate against
            functions: Optional dictionary of available functions
        """
        self.data = data
        self.functions = functions or {}
    
    def get_field_value(self, field_path: str) -> Any:
        """
        Get the value of a field using dot notation.
        
        Args:
            field_path: Field path like 'user.name' or 'score'
            
        Returns:
            The field value or None if not found
        """
        keys = field_path.split('.')
        value = self.data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
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
    
    def evaluate(self, data: Dict[str, Any], functions: Optional[Dict[str, Any]] = None) -> bool:
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
    
    def __init__(self, context: EvaluationContext):
        """
        Initialize the evaluator.
        
        Args:
            context: Evaluation context containing data and functions
        """
        self.context = context
    
    def visit_field(self, node: FieldNode) -> Any:
        """Get the value of a field from the context data."""
        return self.context.get_field_value(node.field_path)
    
    def visit_literal(self, node: LiteralNode) -> Any:
        """Return the literal value."""
        return node.value
    
    def visit_comparison(self, node: ComparisonNode) -> bool:
        """Evaluate a comparison operation."""
        left_value = node.left.accept(self)
        
        # Handle unary operators
        if node.operator in (ComparisonOperator.IS_NULL, ComparisonOperator.IS_NOT_NULL):
            if node.operator == ComparisonOperator.IS_NULL:
                return left_value is None
            else:  # IS_NOT_NULL
                return left_value is not None
        
        # Handle binary operators
        if node.right is None:
            raise ValueError(f"Binary operator {node.operator.value} requires a right operand")
        
        right_value = node.right.accept(self)
        
        try:
            if node.operator == ComparisonOperator.EQ:
                return left_value == right_value
            elif node.operator == ComparisonOperator.NE:
                return left_value != right_value
            elif node.operator == ComparisonOperator.LT:
                return left_value < right_value
            elif node.operator == ComparisonOperator.LE:
                return left_value <= right_value
            elif node.operator == ComparisonOperator.GT:
                return left_value > right_value
            elif node.operator == ComparisonOperator.GE:
                return left_value >= right_value
            elif node.operator == ComparisonOperator.IN:
                return left_value in right_value if isinstance(right_value, (list, tuple, set)) else False
            elif node.operator == ComparisonOperator.NOT_IN:
                return left_value not in right_value if isinstance(right_value, (list, tuple, set)) else True
            elif node.operator == ComparisonOperator.CONTAINS:
                return str(right_value) in str(left_value) if left_value is not None else False
            elif node.operator == ComparisonOperator.NOT_CONTAINS:
                return str(right_value) not in str(left_value) if left_value is not None else True
            elif node.operator == ComparisonOperator.LIKE:
                return self._evaluate_like(left_value, right_value)
            elif node.operator == ComparisonOperator.NOT_LIKE:
                return not self._evaluate_like(left_value, right_value)
            elif node.operator == ComparisonOperator.BETWEEN:
                if not isinstance(right_value, (list, tuple)) or len(right_value) != 2:
                    raise ValueError("BETWEEN operator requires array of exactly 2 values")
                return right_value[0] <= left_value <= right_value[1]
            elif node.operator == ComparisonOperator.NOT_BETWEEN:
                if not isinstance(right_value, (list, tuple)) or len(right_value) != 2:
                    raise ValueError("NOT BETWEEN operator requires array of exactly 2 values")
                return not (right_value[0] <= left_value <= right_value[1])
            else:
                raise ValueError(f"Unknown comparison operator: {node.operator}")
        except (TypeError, ValueError) as e:
            # Handle type errors gracefully (e.g., comparing string to number)
            return False
    
    def visit_logical(self, node: LogicalNode) -> bool:
        """Evaluate a logical operation."""
        left_result = node.left.accept(self)
        
        if node.operator == LogicalOperator.NOT:
            return not left_result
        elif node.operator == LogicalOperator.AND:
            if not left_result:
                return False  # Short-circuit evaluation
            if node.right is None:
                raise ValueError("AND operator requires a right operand")
            return node.right.accept(self)
        elif node.operator == LogicalOperator.OR:
            if left_result:
                return True  # Short-circuit evaluation
            if node.right is None:
                raise ValueError("OR operator requires a right operand")
            return node.right.accept(self)
        else:
            raise ValueError(f"Unknown logical operator: {node.operator}")
    
    def visit_function(self, node: FunctionNode) -> Any:
        """Evaluate a function call."""
        args = [arg.accept(self) for arg in node.arguments]
        return self.context.call_function(node.function_name, args)
    
    def _evaluate_like(self, text: Any, pattern: Any) -> bool:
        """
        Evaluate SQL LIKE pattern matching.
        
        Supports:
        - % for any sequence of characters
        - _ for any single character
        """
        if text is None or pattern is None:
            return False
        
        text_str = str(text)
        pattern_str = str(pattern)
        
        # Convert SQL LIKE pattern to regex
        import re
        
        # Escape special regex characters except % and _
        escaped = re.escape(pattern_str)
        
        # Replace escaped % and _ with regex equivalents
        regex_pattern = escaped.replace(r'\%', '.*').replace(r'\_', '.')
        
        # Add anchors to match the entire string
        regex_pattern = f'^{regex_pattern}$'
        
        try:
            return bool(re.match(regex_pattern, text_str, re.IGNORECASE))
        except re.error:
            return False


class ASTFormatter(ASTVisitor):
    """Formats AST nodes back to string representation."""
    
    def visit_field(self, node: FieldNode) -> str:
        return node.field_path
    
    def visit_literal(self, node: LiteralNode) -> str:
        if node.value is None:
            return "NULL"
        elif isinstance(node.value, str):
            return f'"{node.value}"'
        elif isinstance(node.value, bool):
            return "TRUE" if node.value else "FALSE"
        elif isinstance(node.value, (list, tuple)):
            items = [self.visit_literal(LiteralNode(item)) for item in node.value]
            return f"[{', '.join(items)}]"
        else:
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