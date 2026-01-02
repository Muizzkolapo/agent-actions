"""
Advanced WHERE clause parser using pyparsing library.

This module provides a robust parser that builds AST nodes from WHERE clause
expressions with proper grammar handling and comprehensive error reporting.
"""

import re
import ast
from typing import Any, Dict, List, Optional
from functools import lru_cache
from dataclasses import dataclass
import logging

try:
    from pyparsing import (
        Word,
        Literal,
        Regex,
        QuotedString,
        alphas,
        alphanums,
        Forward,
        ZeroOrMore,
        Optional as PyOptional,
        CaselessKeyword,
        ParserElement,
        ParseException,
        infixNotation,
        opAssoc,
        pyparsing_common,
        Suppress,
    )
except ImportError as exc:
    raise ImportError(
        "pyparsing library is required for WHERE clause parsing. "
        "Install it with: pip install pyparsing"
    ) from exc

from .ast_nodes import (
    FieldNode,
    LiteralNode,
    ComparisonNode,
    LogicalNode,
    FunctionNode,
    ComparisonOperator,
    LogicalOperator,
    WhereClauseAST,
)
from .operator_registry import get_global_registry, OperatorRegistry

logger = logging.getLogger(__name__)


def _get_lru_cache_info(cached_func):
    """Get cache_info from an lru_cache-decorated function."""
    return cached_func.cache_info()


@dataclass
class ParseError:
    """Information about a parsing error."""

    message: str
    line: int
    column: int
    error_type: str


@dataclass
class ParseResult:
    """Result of parsing a WHERE clause."""

    success: bool
    ast: Optional[WhereClauseAST] = None
    error: Optional[ParseError] = None
    warnings: Optional[List[str]] = None


class WhereClauseParser:
    """
    Advanced WHERE clause parser using pyparsing.

    Features:
    - Proper grammar-based parsing
    - AST construction
    - Operator precedence handling
    - Function calls
    - Parentheses grouping
    - Comprehensive error reporting
    - LRU caching for performance
    """

    def __init__(self, operator_registry: Optional[OperatorRegistry] = None):
        """
        Initialize the parser.

        Args:
            operator_registry: Optional custom operator registry
        """
        self.registry = operator_registry or get_global_registry()
        self._grammar = None
        self._build_grammar()

    def _build_basic_tokens(self):
        """Build basic punctuation tokens."""
        return {
            "lpar": Suppress("("),
            "rpar": Suppress(")"),
            "comma": Suppress(","),
            "lbracket": Suppress("["),
            "rbracket": Suppress("]"),
        }

    def _build_literals(self):
        """Build literal parsers (string, number, boolean, null)."""
        string_literal = QuotedString('"', escChar="\\") | QuotedString("'", escChar="\\")
        string_literal.setParseAction(lambda t: LiteralNode(t[0]))

        number = pyparsing_common.number()
        number.setParseAction(lambda t: LiteralNode(t[0]))

        boolean = CaselessKeyword("TRUE") | CaselessKeyword("FALSE")
        boolean.setParseAction(lambda t: LiteralNode(t[0].upper() == "TRUE"))

        null = CaselessKeyword("NULL")
        null.setParseAction(lambda t: LiteralNode(None))

        return string_literal, number, boolean, null

    def _build_grammar(self):
        """Build the pyparsing grammar for WHERE clauses."""
        # Basic tokens
        tokens = self._build_basic_tokens()

        # Field identifier (with dot notation support)
        field_name = Regex(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")
        field_name.setParseAction(lambda t: FieldNode(field_path=t[0]))

        # Literals
        string_literal, number, boolean, null = self._build_literals()

        # Array literals
        array_element = Forward()
        array_element <<= string_literal | number | boolean | null

        array_literal = (
            tokens["lbracket"]
            + PyOptional(array_element + ZeroOrMore(tokens["comma"] + array_element))
            + tokens["rbracket"]
        )
        array_literal.setParseAction(self._parse_array)

        # Function calls
        function_name = Word(alphas.upper(), alphanums + "_")
        function_args = Forward()
        function_args <<= (
            tokens["lpar"]
            + PyOptional(array_element + ZeroOrMore(tokens["comma"] + array_element))
            + tokens["rpar"]
        )

        function_call = function_name + function_args
        function_call.setParseAction(self._parse_function)

        # Operands (field references, literals, function calls)
        operand = (
            function_call | field_name | array_literal | string_literal | number | boolean | null
        )

        # Comparison operators
        comparison_ops = self._build_comparison_operators()

        # Build expression using infixNotation for proper precedence
        where_expr = infixNotation(
            operand,
            [
                # Unary operators (highest precedence)
                (CaselessKeyword("NOT"), 1, opAssoc.RIGHT, self._parse_not),
                # Comparison operators
                (comparison_ops, 2, opAssoc.LEFT, self._parse_comparison),
                # Logical operators (lower precedence)
                (CaselessKeyword("AND"), 2, opAssoc.LEFT, self._parse_and),
                (CaselessKeyword("OR"), 2, opAssoc.LEFT, self._parse_or),
            ],
        )

        # Complete grammar
        self._grammar = where_expr

        # Enable packrat parsing for better performance
        ParserElement.enablePackrat()

    def _build_comparison_operators(self):
        """Build comparison operators from the registry."""
        # Get all comparison operators sorted by symbol length (longest first)
        comparison_ops = []
        for info in self.registry.list_operators():
            if info.operator_type.value == "comparison":
                if info.arity == 2:  # Binary operators
                    comparison_ops.append((info.symbol, info.name))
                elif info.arity == 1:  # Unary operators
                    comparison_ops.append((info.symbol, info.name))

        # Sort by length (longest first) to avoid partial matches
        comparison_ops.sort(key=lambda x: len(x[0]), reverse=True)

        # Create pyparsing alternatives
        op_literals = []
        for symbol, name in comparison_ops:
            if " " in symbol:
                # Multi-word operators like "IS NULL", "NOT IN"
                words = symbol.split()
                op_literal = CaselessKeyword(words[0])
                for word in words[1:]:
                    op_literal = op_literal + CaselessKeyword(word)
            else:
                # Single operators like "==", "!="
                op_literal = Literal(symbol)

            op_literal.setParseAction(lambda t, name=name: name)
            op_literals.append(op_literal)

        # Return the first match
        if op_literals:
            result = op_literals[0]
            for op in op_literals[1:]:
                result = result | op
            return result
        return Literal("==")  # Fallback

    def _parse_array(self, tokens):
        """Parse array literal tokens into LiteralNode."""
        # Extract values from the parsed tokens
        values = []
        for token in tokens:
            if isinstance(token, LiteralNode):
                values.append(token.value)
            else:
                values.append(token)
        return LiteralNode(values)

    def _parse_function(self, tokens):
        """Parse function call tokens into FunctionNode."""
        if len(tokens) < 1:
            raise ParseException("Invalid function call")

        func_name = tokens[0]
        args = []

        # Extract arguments
        for token in tokens[1:]:
            if isinstance(token, (FieldNode, LiteralNode, FunctionNode)):
                args.append(token)

        return FunctionNode(func_name, args)

    def _parse_not(self, tokens):
        """Parse NOT operator."""
        operand = tokens[0][1]  # Skip the NOT keyword
        return LogicalNode(LogicalOperator.NOT, operand)

    def _parse_comparison(self, tokens):
        """Parse comparison operations."""
        result = tokens[0][0]  # First operand

        # Process pairs of (operator, operand)
        i = 1
        while i < len(tokens[0]):
            operator_name = tokens[0][i]

            # Map operator name to enum
            try:
                operator_enum = ComparisonOperator(
                    self.registry.get_operator_info(operator_name).symbol
                )
            except (ValueError, AttributeError) as e:
                # Handle special cases or custom operators
                logger.warning(
                    "Failed to map operator '%s' from registry, using fallback mapping: %s",
                    operator_name,
                    e,
                    extra={"operator_name": operator_name},
                )
                operator_enum = self._map_operator_name(operator_name)

            if i + 1 < len(tokens[0]):
                right_operand = tokens[0][i + 1]
                result = ComparisonNode(result, operator_enum, right_operand)
                i += 2
            else:
                # Unary operator
                result = ComparisonNode(result, operator_enum)
                i += 1

        return result

    def _parse_and(self, tokens):
        """Parse AND operations."""
        result = tokens[0][0]
        i = 1
        while i < len(tokens[0]):
            if i + 1 < len(tokens[0]):
                right = tokens[0][i + 1]
                result = LogicalNode(LogicalOperator.AND, result, right)
                i += 2
            else:
                break
        return result

    def _parse_or(self, tokens):
        """Parse OR operations."""
        result = tokens[0][0]
        i = 1
        while i < len(tokens[0]):
            if i + 1 < len(tokens[0]):
                right = tokens[0][i + 1]
                result = LogicalNode(LogicalOperator.OR, result, right)
                i += 2
            else:
                break
        return result

    def _map_operator_name(self, operator_name: str) -> ComparisonOperator:
        """Map operator name to ComparisonOperator enum."""
        mapping = {
            "EQ": ComparisonOperator.EQ,
            "NE": ComparisonOperator.NE,
            "LT": ComparisonOperator.LT,
            "LE": ComparisonOperator.LE,
            "GT": ComparisonOperator.GT,
            "GE": ComparisonOperator.GE,
            "IN": ComparisonOperator.IN,
            "NOT_IN": ComparisonOperator.NOT_IN,
            "CONTAINS": ComparisonOperator.CONTAINS,
            "NOT_CONTAINS": ComparisonOperator.NOT_CONTAINS,
            "LIKE": ComparisonOperator.LIKE,
            "NOT_LIKE": ComparisonOperator.NOT_LIKE,
            "BETWEEN": ComparisonOperator.BETWEEN,
            "NOT_BETWEEN": ComparisonOperator.NOT_BETWEEN,
            "IS_NULL": ComparisonOperator.IS_NULL,
            "IS_NOT_NULL": ComparisonOperator.IS_NOT_NULL,
        }

        if operator_name in mapping:
            return mapping[operator_name]
        # Default fallback
        return ComparisonOperator.EQ

    @lru_cache(maxsize=1000)
    def parse_cached(self, where_clause: str) -> ParseResult:
        """
        Parse a WHERE clause with caching.

        Args:
            where_clause: The WHERE clause string to parse

        Returns:
            ParseResult containing the AST or error information
        """
        return self.parse(where_clause)

    def _validate_clause_input(self, where_clause: str) -> Optional[ParseResult]:
        """Validate input clause, return error ParseResult if invalid, None if valid."""
        if not where_clause or not where_clause.strip():
            return ParseResult(
                success=False, error=ParseError("Empty WHERE clause", 1, 1, "EmptyClause")
            )

        if len(where_clause) > 10000:
            return ParseResult(
                success=False,
                error=ParseError("WHERE clause too long (max 10000 characters)", 1, 1, "TooLong"),
            )

        if not self._validate_field_names(where_clause):
            return ParseResult(
                success=False,
                error=ParseError("Invalid field names detected", 1, 1, "InvalidFields"),
            )

        return None  # Valid

    def _parse_and_build_ast(self, where_clause: str) -> ParseResult:
        """Parse clause and build AST, returning ParseResult."""
        parsed = self._grammar.parseString(where_clause, parseAll=True)

        if not parsed:
            return ParseResult(
                success=False, error=ParseError("Failed to parse WHERE clause", 1, 1, "ParseFailed")
            )

        root_node = parsed[0]
        parsed_ast = WhereClauseAST(root_node)
        return ParseResult(success=True, ast=parsed_ast)

    def parse(self, where_clause: str) -> ParseResult:
        """
        Parse a WHERE clause into an AST.

        Args:
            where_clause: The WHERE clause string to parse

        Returns:
            ParseResult containing the AST or error information
        """
        # Validate input
        validation_error = self._validate_clause_input(where_clause)
        if validation_error:
            return validation_error

        try:
            return self._parse_and_build_ast(where_clause)

        except ParseException as e:
            return ParseResult(
                success=False,
                error=ParseError(f"Parse error: {e.msg}", e.lineno, e.column, "ParseException"),
            )
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.debug("Unexpected error parsing WHERE clause: %s", e, exc_info=True)
            return ParseResult(
                success=False,
                error=ParseError(f"Unexpected error: {str(e)}", 1, 1, "UnexpectedError"),
            )

    def _validate_field_names(self, where_clause: str) -> bool:
        """
        Validate field names to prevent injection attacks.

        Args:
            where_clause: The WHERE clause to validate

        Returns:
            True if field names are valid, False otherwise
        """
        # Allow only alphanumeric characters, underscores, and dots for field paths
        field_pattern = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")

        # Extract potential field names (before operators)
        # This is a simple heuristic - the real validation happens during parsing
        tokens = re.split(
            r"[=!<>]|\b(?:and|or|not|in|like|between|is|null|contains)\b",
            where_clause,
            flags=re.IGNORECASE,
        )

        for token in tokens:
            token = token.strip()
            if token and not token.startswith('"') and not token.startswith("'"):
                # Check if it could be a field name
                if re.match(r"^[a-zA-Z_]", token):
                    if not field_pattern.fullmatch(token.split()[0]):
                        return False

        return True

    def clear_cache(self):
        """Clear the parsing cache."""
        self.parse_cached.cache_clear()

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics."""
        cache_info = _get_lru_cache_info(type(self).parse_cached)
        return {
            "hits": cache_info.hits,
            "misses": cache_info.misses,
            "maxsize": cache_info.maxsize,
            "currsize": cache_info.currsize,
            "hit_ratio": (
                cache_info.hits / (cache_info.hits + cache_info.misses)
                if cache_info.hits + cache_info.misses > 0
                else 0
            ),
        }


class SafeExpressionEvaluator:
    """
    Safe expression evaluator to replace eval() usage.

    This evaluator only supports basic mathematical and logical operations
    without allowing arbitrary code execution.
    """

    def __init__(self):
        """Initialize the safe evaluator."""
        self.allowed_names = {
            # Safe built-in functions
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "round": round,
            # Safe constants
            "True": True,
            "False": False,
            "None": None,
        }

    def __repr__(self):
        """Return string representation of SafeExpressionEvaluator."""
        return "SafeExpressionEvaluator()"

    def evaluate(self, expression: str, context: Dict[str, Any]) -> Any:
        """
        Safely evaluate an expression with given context.

        Args:
            expression: The expression to evaluate
            context: Context variables for the expression

        Returns:
            The result of the evaluation

        Raises:
            ValueError: If the expression contains unsafe operations
            SyntaxError: If the expression has invalid syntax
        """
        # Validate the expression first
        if not self._is_safe_expression(expression):
            raise ValueError("Expression contains unsafe operations")

        # Combine allowed names with context
        safe_context = {**self.allowed_names, **context}

        try:
            # Use eval with restricted globals and locals (safe: no builtins, validated AST)
            # pylint: disable=eval-used
            return eval(expression, {"__builtins__": {}}, safe_context)  # nosec B307
        except Exception as e:
            raise ValueError(f"Error evaluating expression: {e}") from e

    def _is_safe_expression(self, expression: str) -> bool:
        """
        Check if an expression is safe to evaluate.

        Args:
            expression: The expression to check

        Returns:
            True if the expression is safe, False otherwise
        """
        try:
            # Parse the expression into an AST
            tree = ast.parse(expression, mode="eval")
        except SyntaxError:
            return False

        # Check for unsafe node types
        for node in ast.walk(tree):
            if isinstance(
                node,
                (
                    ast.Import,
                    ast.ImportFrom,
                    ast.FunctionDef,
                    ast.ClassDef,
                    ast.AsyncFunctionDef,
                    ast.Global,
                    ast.Nonlocal,
                    ast.Delete,
                ),
            ):
                return False

            # Allow only safe attribute access
            if isinstance(node, ast.Attribute):
                # Check if it's a safe attribute access
                if not self._is_safe_attribute(node):
                    return False

            # Restrict function calls to known safe functions
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id not in self.allowed_names:
                        return False
                else:
                    # Only allow calls to known safe functions
                    return False

        return True

    def _is_safe_attribute(self, node: ast.Attribute) -> bool:
        """
        Check if an attribute access is safe.

        Args:
            node: The AST attribute node

        Returns:
            True if the attribute access is safe
        """
        # Blocklist of dangerous attributes that could allow sandbox escape
        unsafe_attrs = frozenset(
            {
                "__class__",
                "__dict__",
                "__code__",
                "__globals__",
                "__bases__",
                "__subclasses__",
                "__mro__",
                "__new__",
                "__init__",
                "__del__",
                "__reduce__",
                "__reduce_ex__",
                "__getattribute__",
                "__setattr__",
                "__delattr__",
                "mro",
                "gi_frame",
                "gi_code",
                "f_globals",
                "f_locals",
            }
        )

        # Block dangerous attributes and all underscore-prefixed attrs
        if node.attr in unsafe_attrs or node.attr.startswith("_"):
            return False

        return True


# Global parser instance for convenience
_GLOBAL_PARSER = None


def get_global_parser() -> WhereClauseParser:
    """Get the global WHERE clause parser instance."""
    global _GLOBAL_PARSER  # pylint: disable=global-statement
    if _GLOBAL_PARSER is None:
        _GLOBAL_PARSER = WhereClauseParser()
    return _GLOBAL_PARSER


def evaluate_safe_expression(expression: str, context: Dict[str, Any]) -> Any:
    """
    Safely evaluate an expression (replacement for eval()).

    Args:
        expression: The expression to evaluate
        context: Context variables for the expression

    Returns:
        The result of the evaluation
    """
    evaluator = SafeExpressionEvaluator()
    return evaluator.evaluate(expression, context)
