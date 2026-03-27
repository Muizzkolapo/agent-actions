"""WHERE clause parser using pyparsing with AST construction and LRU caching."""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

try:
    from pyparsing import (
        CaselessKeyword,
        Forward,
        Literal,
        OpAssoc,
        ParseException,
        ParserElement,
        QuotedString,
        Regex,
        Suppress,
        Word,
        ZeroOrMore,
        alphanums,
        alphas,
        infix_notation,
        pyparsing_common,
    )
    from pyparsing import (
        Optional as PyOptional,
    )
except ImportError as exc:
    raise ImportError(
        "pyparsing library is required for WHERE clause parsing. "
        "Install it with: uv pip install pyparsing"
    ) from exc

from .ast_nodes import (
    ASTNode,
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    FunctionNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    WhereClauseAST,
)
from .operators import get_operator_info, list_operators

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
    ast: WhereClauseAST | None = None
    error: ParseError | None = None
    warnings: list[str] | None = None


class WhereClauseParser:
    """Grammar-based WHERE clause parser with operator precedence and LRU caching."""

    def __init__(self):
        self._grammar = None
        self._build_grammar()

    def _build_basic_tokens(self):
        """Build punctuation token suppressors."""
        return {
            "lpar": Suppress("("),
            "rpar": Suppress(")"),
            "comma": Suppress(","),
            "lbracket": Suppress("["),
            "rbracket": Suppress("]"),
        }

    def _build_literals(self):
        """Build literal parsers (string, number, boolean, null)."""
        string_literal = QuotedString('"', esc_char="\\") | QuotedString("'", esc_char="\\")
        string_literal.add_parse_action(lambda t: LiteralNode(t[0]))

        number = pyparsing_common.number()
        number.add_parse_action(lambda t: LiteralNode(t[0]))

        boolean = CaselessKeyword("TRUE") | CaselessKeyword("FALSE")
        boolean.add_parse_action(lambda t: LiteralNode(t[0].upper() == "TRUE"))

        null = CaselessKeyword("NULL")
        null.add_parse_action(lambda t: LiteralNode(None))

        return string_literal, number, boolean, null

    def _build_grammar(self):
        """Build the pyparsing grammar for WHERE clauses."""
        tokens = self._build_basic_tokens()

        string_literal, number, boolean, null = self._build_literals()

        # Reserved keywords must not be matched as field names.
        # Using ~reserved_words ensures field_name fails on keywords regardless
        # of its position in the operand alternation.
        reserved_words = (
            CaselessKeyword("TRUE")
            | CaselessKeyword("FALSE")
            | CaselessKeyword("NULL")
            | CaselessKeyword("AND")
            | CaselessKeyword("OR")
            | CaselessKeyword("NOT")
            | CaselessKeyword("IN")
            | CaselessKeyword("IS")
            | CaselessKeyword("LIKE")
            | CaselessKeyword("BETWEEN")
            | CaselessKeyword("CONTAINS")
        )
        field_name = ~reserved_words + Regex(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")
        field_name.add_parse_action(lambda t: FieldNode(field_path=t[0]))

        array_element = Forward()
        array_element <<= string_literal | number | boolean | null

        array_literal = (
            tokens["lbracket"]
            + PyOptional(array_element + ZeroOrMore(tokens["comma"] + array_element))
            + tokens["rbracket"]
        )
        array_literal.add_parse_action(self._parse_array)

        function_name = Word(alphas.upper(), alphanums + "_")
        function_args = Forward()
        function_args <<= (
            tokens["lpar"]
            + PyOptional(array_element + ZeroOrMore(tokens["comma"] + array_element))
            + tokens["rpar"]
        )

        function_call = function_name + function_args
        function_call.add_parse_action(self._parse_function)

        operand = (
            function_call | boolean | null | array_literal | string_literal | number | field_name
        )

        comparison_ops = self._build_comparison_operators()

        where_expr = infix_notation(
            operand,
            [
                (CaselessKeyword("NOT"), 1, OpAssoc.RIGHT, self._parse_not),
                (comparison_ops, 2, OpAssoc.LEFT, self._parse_comparison),
                (CaselessKeyword("AND"), 2, OpAssoc.LEFT, self._parse_and),
                (CaselessKeyword("OR"), 2, OpAssoc.LEFT, self._parse_or),
            ],
        )

        self._grammar = where_expr
        ParserElement.enable_packrat()

    def _collect_comparison_operators(self):
        """Collect comparison operators sorted longest-first to avoid partial matches."""
        comparison_ops = [
            (info.symbol, info.name)
            for info in list_operators()
            if info.operator_type.value == "comparison" and info.arity in (1, 2)
        ]
        comparison_ops.sort(key=lambda x: len(x[0]), reverse=True)
        return comparison_ops

    def _create_operator_literal(self, symbol: str, name: str):
        """Create a pyparsing literal for a single operator."""
        op_literal: ParserElement
        if " " in symbol:
            words = symbol.split()
            op_literal = CaselessKeyword(words[0])
            for word in words[1:]:
                op_literal = op_literal + CaselessKeyword(word)
        else:
            op_literal = Literal(symbol)
        op_literal.add_parse_action(lambda t, name=name: name)
        return op_literal

    def _build_comparison_operators(self):
        """Build comparison operators from the registry."""
        comparison_ops = self._collect_comparison_operators()
        op_literals = [
            self._create_operator_literal(symbol, name) for symbol, name in comparison_ops
        ]

        if not op_literals:
            return Literal("==")  # Fallback

        result = op_literals[0]
        for op in op_literals[1:]:
            result = result | op
        return result

    def _parse_array(self, tokens):
        """Parse array literal tokens into LiteralNode."""
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
        args: list[ASTNode] = []

        for token in tokens[1:]:
            if isinstance(token, FieldNode | LiteralNode | FunctionNode):
                args.append(token)

        return FunctionNode(func_name, args)

    def _parse_not(self, tokens):
        """Parse NOT operator."""
        operand = tokens[0][1]  # Skip the NOT keyword
        return LogicalNode(LogicalOperator.NOT, operand)

    def _parse_comparison(self, tokens):
        """Parse comparison operations."""
        result = tokens[0][0]

        i = 1
        while i < len(tokens[0]):
            operator_name = tokens[0][i]

            try:
                info = get_operator_info(operator_name)
                operator_enum = (
                    ComparisonOperator(info.symbol)
                    if info
                    else self._map_operator_name(operator_name)
                )
            except (ValueError, AttributeError) as e:
                logger.warning(
                    "Failed to map operator '%s', using fallback mapping: %s",
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
        return ComparisonOperator.EQ

    @lru_cache(maxsize=1000)  # noqa: B019
    def parse_cached(self, where_clause: str) -> ParseResult:
        """Parse a WHERE clause with LRU caching."""
        return self.parse(where_clause)

    def _validate_clause_input(self, where_clause: str) -> ParseResult | None:
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
        if self._grammar is None:
            raise RuntimeError(
                "WhereClauseParser._grammar is None; _build_grammar() must complete before parsing"
            )
        parsed = self._grammar.parse_string(where_clause, parse_all=True)

        if not parsed:
            return ParseResult(
                success=False, error=ParseError("Failed to parse WHERE clause", 1, 1, "ParseFailed")
            )

        root_node = parsed[0]
        parsed_ast = WhereClauseAST(root_node)
        return ParseResult(success=True, ast=parsed_ast)

    def parse(self, where_clause: str) -> ParseResult:
        """Parse a WHERE clause into an AST."""
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

    _FIELD_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*")
    _OPERATOR_SPLIT_PATTERN = re.compile(
        r"[=!<>]|\b(?:and|or|not|in|like|between|is|null|contains)\b",
        flags=re.IGNORECASE,
    )

    def _is_valid_field_token(self, token: str) -> bool:
        """Check if a token is a valid field name."""
        token = token.strip()
        if not token or token.startswith('"') or token.startswith("'"):
            return True  # Skip empty, string literals
        if not re.match(r"^[a-zA-Z_]", token):
            return True  # Not a field name, skip
        return bool(self._FIELD_PATTERN.fullmatch(token.split()[0]))

    def _validate_field_names(self, where_clause: str) -> bool:
        """Validate field names against injection patterns."""
        tokens = self._OPERATOR_SPLIT_PATTERN.split(where_clause)
        return all(self._is_valid_field_token(token) for token in tokens)

    def clear_cache(self):
        """Clear the parsing cache."""
        self.parse_cached.cache_clear()

    def get_cache_info(self) -> dict[str, Any]:
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
