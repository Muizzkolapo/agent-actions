"""
Safe expression evaluator for agent workflow conditions.

This module provides a secure alternative to eval() for evaluating
simple expressions in agent workflow conditions and WHERE clauses.
"""

import logging
import re
from typing import Any, Dict, Union, List, Optional

try:
    from simpleeval import SimpleEval, InvalidExpression
    SIMPLEEVAL_AVAILABLE = True
except ImportError:
    SIMPLEEVAL_AVAILABLE = False
    SimpleEval = None
    InvalidExpression = Exception

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass


class ExpressionValidationError(Exception):
    """Raised when expression validation fails."""
    pass


class SafeExpressionEvaluator:
    """
    A secure expression evaluator that replaces dangerous eval() usage.
    
    Uses simpleeval library for safe expression evaluation with restricted
    context and function access.
    """
    
    # Maximum expression length to prevent DoS attacks
    MAX_EXPRESSION_LENGTH = 1000
    
    # Maximum nesting depth for field access (e.g., a.b.c.d.e)
    MAX_FIELD_DEPTH = 10
    
    # Allowed operators and functions
    ALLOWED_OPERATORS = {
        '==', '!=', '<', '>', '<=', '>=', 
        'and', 'or', 'not', 'in', 'is',
        '+', '-', '*', '/', '%', '//'
    }
    
    # Pattern to detect potentially dangerous expressions
    DANGEROUS_PATTERNS = [
        r'__.*__',  # Dunder methods
        r'import\s+',  # Import statements
        r'exec\s*\(',  # Exec calls
        r'eval\s*\(',  # Eval calls
        r'open\s*\(',  # File operations
        r'compile\s*\(',  # Code compilation
        r'globals\s*\(',  # Globals access
        r'locals\s*\(',  # Locals access
        r'vars\s*\(',  # Vars access
        r'dir\s*\(',  # Directory listing
        r'getattr\s*\(',  # Attribute access
        r'setattr\s*\(',  # Attribute setting
        r'delattr\s*\(',  # Attribute deletion
        r'hasattr\s*\(',  # Attribute checking
        r'callable\s*\(',  # Callable checking
        r'classmethod\s*\(',  # Class method access
        r'staticmethod\s*\(',  # Static method access
        r'property\s*\(',  # Property access
        r'super\s*\(',  # Super calls
        r'type\s*\(',  # Type access
        r'isinstance\s*\(',  # Instance checking
        r'issubclass\s*\(',  # Subclass checking
        r'\bclass\s+',  # Class definitions
        r'\bdef\s+',  # Function definitions
        r'\blambda\s+',  # Lambda expressions
        r'\bfor\s+.*\bin\s+',  # For loops
        r'\bwhile\s+',  # While loops
        r'\btry\s*:',  # Try blocks
        r'\bexcept\s+',  # Exception handling
        r'\bfinally\s*:',  # Finally blocks
        r'\bwith\s+',  # Context managers
        r'\byield\s+',  # Generators
        r'\basync\s+',  # Async operations
        r'\bawait\s+',  # Await operations
    ]
    
    def __init__(self):
        """Initialize the safe expression evaluator."""
        if not SIMPLEEVAL_AVAILABLE:
            raise ImportError(
                "simpleeval library is required for safe expression evaluation. "
                "Install it with: pip install simpleeval"
            )
        
        # Initialize SimpleEval with restricted context
        self.evaluator = SimpleEval()
        
        # Remove dangerous built-ins
        self.evaluator.names = {}
        
        # Add safe functions
        self.evaluator.functions = {
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'min': min,
            'max': max,
            'sum': sum,
            'abs': abs,
            'round': round,
        }
        
        # Compile dangerous patterns for performance
        self.dangerous_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS]
    
    def validate_expression(self, expression: str) -> None:
        """
        Validate expression for security issues.
        
        Args:
            expression: The expression to validate
            
        Raises:
            SecurityError: If security violation is detected
            ExpressionValidationError: If expression is invalid
        """
        if not expression or not isinstance(expression, str):
            raise ExpressionValidationError("Expression must be a non-empty string")
        
        # Check length
        if len(expression) > self.MAX_EXPRESSION_LENGTH:
            raise SecurityError(
                f"Expression too long: {len(expression)} > {self.MAX_EXPRESSION_LENGTH}"
            )
        
        # Check for dangerous patterns
        for pattern in self.dangerous_regex:
            if pattern.search(expression):
                raise SecurityError(
                    f"Dangerous pattern detected in expression: {pattern.pattern}"
                )
        
        # Check field access depth
        field_accesses = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*', expression)
        for field_access in field_accesses:
            depth = field_access.count('.')
            if depth > self.MAX_FIELD_DEPTH:
                raise SecurityError(
                    f"Field access too deep: {field_access} (depth: {depth} > {self.MAX_FIELD_DEPTH})"
                )
    
    def validate_context(self, context: Dict[str, Any]) -> None:
        """
        Validate context dictionary for security issues.
        
        Args:
            context: The context dictionary to validate
            
        Raises:
            SecurityError: If security violation is detected
        """
        if not isinstance(context, dict):
            raise SecurityError("Context must be a dictionary")
        
        # Check for dangerous keys
        for key in context.keys():
            if not isinstance(key, str):
                raise SecurityError(f"Context keys must be strings, got: {type(key)}")
            
            if key.startswith('__') and key.endswith('__'):
                raise SecurityError(f"Dangerous context key: {key}")
        
        # Recursively check values
        self._validate_context_values(context, max_depth=5)
    
    def _validate_context_values(self, obj: Any, max_depth: int, current_depth: int = 0) -> None:
        """
        Recursively validate context values.
        
        Args:
            obj: Object to validate
            max_depth: Maximum recursion depth
            current_depth: Current recursion depth
            
        Raises:
            SecurityError: If security violation is detected
        """
        if current_depth > max_depth:
            raise SecurityError(f"Context nesting too deep: {current_depth} > {max_depth}")
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                if not isinstance(key, (str, int, float)):
                    raise SecurityError(f"Invalid context key type: {type(key)}")
                self._validate_context_values(value, max_depth, current_depth + 1)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                self._validate_context_values(item, max_depth, current_depth + 1)
        elif hasattr(obj, '__call__'):
            raise SecurityError("Callable objects not allowed in context")
        elif hasattr(obj, '__class__') and hasattr(obj.__class__, '__module__'):
            # Allow basic types and avoid custom objects
            allowed_modules = {'builtins', 'datetime', 'decimal', 'fractions'}
            if obj.__class__.__module__ not in allowed_modules:
                raise SecurityError(f"Custom objects not allowed: {obj.__class__}")
    
    def safe_eval(self, expression: str, context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Safely evaluate an expression with given context.
        
        Args:
            expression: Expression to evaluate
            context: Context dictionary for variable lookup
            
        Returns:
            Result of expression evaluation
            
        Raises:
            SecurityError: If security violation is detected
            ExpressionValidationError: If expression is invalid
            ValueError: If evaluation fails
        """
        # Validate inputs
        self.validate_expression(expression)
        
        if context is None:
            context = {}
        
        self.validate_context(context)
        
        # Set up evaluation context
        self.evaluator.names = context.copy()
        
        try:
            result = self.evaluator.eval(expression)
            logger.debug(f"Safe evaluation successful: {expression} -> {result}")
            return result
        except InvalidExpression as e:
            raise ExpressionValidationError(f"Invalid expression: {e}")
        except Exception as e:
            raise ValueError(f"Expression evaluation failed: {e}")
    
    def is_safe_expression(self, expression: str) -> bool:
        """
        Check if an expression is safe without evaluating it.
        
        Args:
            expression: Expression to check
            
        Returns:
            True if expression appears safe, False otherwise
        """
        try:
            self.validate_expression(expression)
            return True
        except (SecurityError, ExpressionValidationError):
            return False


# Global instance for convenient access
safe_evaluator = SafeExpressionEvaluator()


def safe_eval(expression: str, context: Optional[Dict[str, Any]] = None) -> Any:
    """
    Convenience function for safe expression evaluation.
    
    Args:
        expression: Expression to evaluate
        context: Context dictionary for variable lookup
        
    Returns:
        Result of expression evaluation
        
    Raises:
        SecurityError: If security violation is detected
        ExpressionValidationError: If expression is invalid
        ValueError: If evaluation fails
    """
    return safe_evaluator.safe_eval(expression, context)


def validate_expression(expression: str) -> None:
    """
    Convenience function for expression validation.
    
    Args:
        expression: Expression to validate
        
    Raises:
        SecurityError: If security violation is detected
        ExpressionValidationError: If expression is invalid
    """
    safe_evaluator.validate_expression(expression)


def is_safe_expression(expression: str) -> bool:
    """
    Convenience function to check if expression is safe.
    
    Args:
        expression: Expression to check
        
    Returns:
        True if expression appears safe, False otherwise
    """
    return safe_evaluator.is_safe_expression(expression)