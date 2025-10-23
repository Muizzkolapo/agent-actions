"""
Extensible operator registry for WHERE clause processing.

This module provides a registry system for operators that can be extended
with custom operators and functions.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import re


class OperatorType(Enum):
    """Types of operators in the registry."""
    COMPARISON = "comparison"
    LOGICAL = "logical"
    FUNCTION = "function"


@dataclass
class OperatorInfo:
    """Information about a registered operator."""
    name: str
    symbol: str
    operator_type: OperatorType
    precedence: int
    associativity: str  # "left", "right", "none"
    arity: int  # Number of operands (1 for unary, 2 for binary)
    description: str


class BaseOperator(ABC):
    """Base class for all operators."""
    
    @abstractmethod
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Evaluate the operator with given operands.
        
        Args:
            left: Left operand
            right: Right operand (None for unary operators)
            context: Optional evaluation context
            
        Returns:
            Result of the operation
        """
        pass
    
    @abstractmethod
    def get_info(self) -> OperatorInfo:
        """Get operator information."""
        pass


class ComparisonOperator(BaseOperator):
    """Base class for comparison operators."""
    pass


class LogicalOperator(BaseOperator):
    """Base class for logical operators."""
    pass


class FunctionOperator(BaseOperator):
    """Base class for function operators."""
    
    @abstractmethod
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Evaluate the function with given arguments.
        
        Args:
            args: List of function arguments
            context: Optional evaluation context
            
        Returns:
            Result of the function
        """
        pass
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> Any:
        """Wrapper for function evaluation."""
        args = [left] if right is None else [left, right]
        return self.evaluate_function(args, context)


# Built-in comparison operators
class EqualOperator(ComparisonOperator):
    """Equality comparison operator (==)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return left == right
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("EQ", "==", OperatorType.COMPARISON, 7, "left", 2, "Equality comparison")


class NotEqualOperator(ComparisonOperator):
    """Not equal comparison operator (!=)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return left != right
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NE", "!=", OperatorType.COMPARISON, 7, "left", 2, "Not equal comparison")


class LessThanOperator(ComparisonOperator):
    """Less than comparison operator (<)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return left < right
        except TypeError:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LT", "<", OperatorType.COMPARISON, 6, "left", 2, "Less than comparison")


class LessEqualOperator(ComparisonOperator):
    """Less than or equal comparison operator (<=)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return left <= right
        except TypeError:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LE", "<=", OperatorType.COMPARISON, 6, "left", 2, "Less than or equal comparison")


class GreaterThanOperator(ComparisonOperator):
    """Greater than comparison operator (>)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return left > right
        except TypeError:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("GT", ">", OperatorType.COMPARISON, 6, "left", 2, "Greater than comparison")


class GreaterEqualOperator(ComparisonOperator):
    """Greater than or equal comparison operator (>=)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        try:
            return left >= right
        except TypeError:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("GE", ">=", OperatorType.COMPARISON, 6, "left", 2, "Greater than or equal comparison")


class InOperator(ComparisonOperator):
    """In array/list operator (IN)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if not isinstance(right, (list, tuple, set)):
            return False
        return left in right
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("IN", "IN", OperatorType.COMPARISON, 7, "left", 2, "In array/list")


class NotInOperator(ComparisonOperator):
    """Not in array/list operator (NOT IN)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if not isinstance(right, (list, tuple, set)):
            return True
        return left not in right
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT_IN", "NOT IN", OperatorType.COMPARISON, 7, "left", 2, "Not in array/list")


class ContainsOperator(ComparisonOperator):
    """String contains operator (CONTAINS)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if left is None:
            return False
        return str(right) in str(left)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("CONTAINS", "CONTAINS", OperatorType.COMPARISON, 7, "left", 2, "String contains")


class NotContainsOperator(ComparisonOperator):
    """String not contains operator (NOT CONTAINS)."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if left is None:
            return True
        return str(right) not in str(left)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT_CONTAINS", "NOT CONTAINS", OperatorType.COMPARISON, 7, "left", 2, "String not contains")


class LikeOperator(ComparisonOperator):
    """SQL LIKE pattern matching operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if left is None or right is None:
            return False
        
        text = str(left)
        pattern = str(right)
        
        # Convert SQL LIKE pattern to regex
        escaped = re.escape(pattern)
        regex_pattern = escaped.replace(r'\%', '.*').replace(r'\_', '.')
        regex_pattern = f'^{regex_pattern}$'
        
        try:
            return bool(re.match(regex_pattern, text, re.IGNORECASE))
        except re.error:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LIKE", "LIKE", OperatorType.COMPARISON, 7, "left", 2, "SQL LIKE pattern matching")


class NotLikeOperator(ComparisonOperator):
    """SQL NOT LIKE pattern matching operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        like_op = LikeOperator()
        return not like_op.evaluate(left, right, context)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT_LIKE", "NOT LIKE", OperatorType.COMPARISON, 7, "left", 2, "SQL NOT LIKE pattern matching")


class BetweenOperator(ComparisonOperator):
    """BETWEEN range operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        if not isinstance(right, (list, tuple)) or len(right) != 2:
            return False
        try:
            return right[0] <= left <= right[1]
        except TypeError:
            return False
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("BETWEEN", "BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Between range")


class NotBetweenOperator(ComparisonOperator):
    """NOT BETWEEN range operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        between_op = BetweenOperator()
        return not between_op.evaluate(left, right, context)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT_BETWEEN", "NOT BETWEEN", OperatorType.COMPARISON, 7, "left", 2, "Not between range")


class IsNullOperator(ComparisonOperator):
    """IS NULL operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return left is None
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("IS_NULL", "IS NULL", OperatorType.COMPARISON, 8, "none", 1, "Is null/None")


class IsNotNullOperator(ComparisonOperator):
    """IS NOT NULL operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return left is not None
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("IS_NOT_NULL", "IS NOT NULL", OperatorType.COMPARISON, 8, "none", 1, "Is not null/None")


# Built-in logical operators
class AndOperator(LogicalOperator):
    """Logical AND operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return bool(left) and bool(right)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("AND", "AND", OperatorType.LOGICAL, 3, "left", 2, "Logical AND")


class OrOperator(LogicalOperator):
    """Logical OR operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return bool(left) or bool(right)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("OR", "OR", OperatorType.LOGICAL, 2, "left", 2, "Logical OR")


class NotOperator(LogicalOperator):
    """Logical NOT operator."""
    
    def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
        return not bool(left)
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("NOT", "NOT", OperatorType.LOGICAL, 9, "right", 1, "Logical NOT")


# Built-in function operators
class LengthFunction(FunctionOperator):
    """LENGTH function."""
    
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> int:
        if len(args) != 1:
            raise ValueError("LENGTH function requires exactly 1 argument")
        
        arg = args[0]
        if arg is None:
            return 0
        elif isinstance(arg, (list, tuple, dict, str)):
            return len(arg)
        else:
            return len(str(arg))
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LENGTH", "LENGTH", OperatorType.FUNCTION, 10, "none", 1, "Get length of value")


class UpperFunction(FunctionOperator):
    """UPPER function."""
    
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("UPPER function requires exactly 1 argument")
        
        arg = args[0]
        return str(arg).upper() if arg is not None else ""
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("UPPER", "UPPER", OperatorType.FUNCTION, 10, "none", 1, "Convert to uppercase")


class LowerFunction(FunctionOperator):
    """LOWER function."""
    
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("LOWER function requires exactly 1 argument")
        
        arg = args[0]
        return str(arg).lower() if arg is not None else ""
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("LOWER", "LOWER", OperatorType.FUNCTION, 10, "none", 1, "Convert to lowercase")


class TrimFunction(FunctionOperator):
    """TRIM function."""
    
    def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> str:
        if len(args) != 1:
            raise ValueError("TRIM function requires exactly 1 argument")
        
        arg = args[0]
        return str(arg).strip() if arg is not None else ""
    
    def get_info(self) -> OperatorInfo:
        return OperatorInfo("TRIM", "TRIM", OperatorType.FUNCTION, 10, "none", 1, "Trim whitespace")


class OperatorRegistry:
    """Registry for managing operators and functions."""
    
    def __init__(self):
        """Initialize the registry with built-in operators."""
        self._operators: Dict[str, BaseOperator] = {}
        self._symbols_to_names: Dict[str, str] = {}
        self._register_builtin_operators()
    
    def _register_builtin_operators(self):
        """Register all built-in operators."""
        # Comparison operators
        self.register_operator(EqualOperator())
        self.register_operator(NotEqualOperator())
        self.register_operator(LessThanOperator())
        self.register_operator(LessEqualOperator())
        self.register_operator(GreaterThanOperator())
        self.register_operator(GreaterEqualOperator())
        self.register_operator(InOperator())
        self.register_operator(NotInOperator())
        self.register_operator(ContainsOperator())
        self.register_operator(NotContainsOperator())
        self.register_operator(LikeOperator())
        self.register_operator(NotLikeOperator())
        self.register_operator(BetweenOperator())
        self.register_operator(NotBetweenOperator())
        self.register_operator(IsNullOperator())
        self.register_operator(IsNotNullOperator())
        
        # Logical operators
        self.register_operator(AndOperator())
        self.register_operator(OrOperator())
        self.register_operator(NotOperator())
        
        # Function operators
        self.register_operator(LengthFunction())
        self.register_operator(UpperFunction())
        self.register_operator(LowerFunction())
        self.register_operator(TrimFunction())
    
    def register_operator(self, operator: BaseOperator):
        """
        Register a new operator.
        
        Args:
            operator: The operator to register
        """
        info = operator.get_info()
        self._operators[info.name] = operator
        self._symbols_to_names[info.symbol] = info.name
    
    def unregister_operator(self, name: str):
        """
        Unregister an operator.
        
        Args:
            name: Name of the operator to unregister
        """
        if name in self._operators:
            operator = self._operators[name]
            info = operator.get_info()
            del self._operators[name]
            if info.symbol in self._symbols_to_names:
                del self._symbols_to_names[info.symbol]
    
    def get_operator(self, name_or_symbol: str) -> Optional[BaseOperator]:
        """
        Get an operator by name or symbol.
        
        Args:
            name_or_symbol: Operator name or symbol
            
        Returns:
            The operator instance or None if not found
        """
        # Try by name first
        if name_or_symbol in self._operators:
            return self._operators[name_or_symbol]
        
        # Try by symbol
        if name_or_symbol in self._symbols_to_names:
            name = self._symbols_to_names[name_or_symbol]
            return self._operators[name]
        
        return None
    
    def get_operator_info(self, name_or_symbol: str) -> Optional[OperatorInfo]:
        """
        Get operator information.
        
        Args:
            name_or_symbol: Operator name or symbol
            
        Returns:
            Operator information or None if not found
        """
        operator = self.get_operator(name_or_symbol)
        return operator.get_info() if operator else None
    
    def list_operators(self, operator_type: Optional[OperatorType] = None) -> List[OperatorInfo]:
        """
        List all registered operators.
        
        Args:
            operator_type: Optional filter by operator type
            
        Returns:
            List of operator information
        """
        operators = []
        for operator in self._operators.values():
            info = operator.get_info()
            if operator_type is None or info.operator_type == operator_type:
                operators.append(info)
        
        return sorted(operators, key=lambda x: (x.operator_type.value, x.precedence, x.name))
    
    def get_operators_by_precedence(self, operator_type: Optional[OperatorType] = None) -> List[Tuple[int, List[OperatorInfo]]]:
        """
        Get operators grouped by precedence level.
        
        Args:
            operator_type: Optional filter by operator type
            
        Returns:
            List of (precedence, operators) tuples sorted by precedence
        """
        operators = self.list_operators(operator_type)
        precedence_groups = {}
        
        for op in operators:
            if op.precedence not in precedence_groups:
                precedence_groups[op.precedence] = []
            precedence_groups[op.precedence].append(op)
        
        return sorted(precedence_groups.items(), key=lambda x: x[0], reverse=True)
    
    def evaluate_operator(self, name_or_symbol: str, left: Any, right: Any = None, 
                         context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Evaluate an operator with given operands.
        
        Args:
            name_or_symbol: Operator name or symbol
            left: Left operand
            right: Right operand (None for unary operators)
            context: Optional evaluation context
            
        Returns:
            Result of the operation
            
        Raises:
            ValueError: If operator is not found
        """
        operator = self.get_operator(name_or_symbol)
        if operator is None:
            raise ValueError(f"Unknown operator: {name_or_symbol}")
        
        return operator.evaluate(left, right, context)


# Global registry instance
_global_registry = OperatorRegistry()


def get_global_registry() -> OperatorRegistry:
    """Get the global operator registry."""
    return _global_registry


def register_custom_operator(operator: BaseOperator):
    """
    Register a custom operator in the global registry.
    
    Args:
        operator: The operator to register
    """
    _global_registry.register_operator(operator)


def create_custom_comparison_operator(name: str, symbol: str, eval_func: Callable[[Any, Any], bool], 
                                    description: str = "", precedence: int = 7) -> BaseOperator:
    """
    Create a custom comparison operator.
    
    Args:
        name: Operator name
        symbol: Operator symbol
        eval_func: Function to evaluate the operator
        description: Operator description
        precedence: Operator precedence
        
    Returns:
        Custom operator instance
    """
    class CustomComparisonOperator(ComparisonOperator):
        def evaluate(self, left: Any, right: Any = None, context: Optional[Dict[str, Any]] = None) -> bool:
            return eval_func(left, right)
        
        def get_info(self) -> OperatorInfo:
            return OperatorInfo(name, symbol, OperatorType.COMPARISON, precedence, "left", 2, description)
    
    return CustomComparisonOperator()


def create_custom_function(name: str, eval_func: Callable[[List[Any]], Any], 
                          description: str = "", arity: int = 1) -> BaseOperator:
    """
    Create a custom function operator.
    
    Args:
        name: Function name
        eval_func: Function to evaluate with list of arguments
        description: Function description
        arity: Number of arguments the function expects
        
    Returns:
        Custom function operator instance
    """
    class CustomFunction(FunctionOperator):
        def evaluate_function(self, args: List[Any], context: Optional[Dict[str, Any]] = None) -> Any:
            return eval_func(args)
        
        def get_info(self) -> OperatorInfo:
            return OperatorInfo(name, name, OperatorType.FUNCTION, 10, "none", arity, description)
    
    return CustomFunction()