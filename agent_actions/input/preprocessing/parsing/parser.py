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
        Group,
        Literal,
        OpAssoc,
        ParseBaseException,
        ParseException,
        ParseFatalException,
        ParserElement,
        ParseResults,
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
from .operators import list_operators

logger = logging.getLogger(__name__)

# Unified operator lookup: maps both enum name ("NE") and symbol/value ("!=")
# to ComparisonOperator members. Derived from the enum — single source of truth.
_OPERATOR_LOOKUP: dict[str, ComparisonOperator] = {}
for _member in ComparisonOperator:
    _OPERATOR_LOOKUP[_member.name] = _member  # "NE" -> ComparisonOperator.NE
    _OPERATOR_LOOKUP[_member.value] = _member  # "!=" -> ComparisonOperator.NE

# First words of multi-word operators, for greedy token consumption in _parse_comparison.
_MULTI_WORD_STARTS: set[str] = set()
for _key in _OPERATOR_LOOKUP:
    if " " in _key:
        _MULTI_WORD_STARTS.add(_key.split()[0].upper())

_RANGE_OPERATORS = (ComparisonOperator.BETWEEN, ComparisonOperator.NOT_BETWEEN)
_RANGE_REFUSAL = (
    "BETWEEN takes a range of two numbers or two strings: "
    "write `x BETWEEN a AND b` or `x BETWEEN [a, b]`"
)


def _bounds_a_value(end: Any) -> str | None:
    """The family a range end orders values in; a boolean or NULL end orders nothing."""
    if isinstance(end, bool):
        return None
    if isinstance(end, int | float):
        return "number"
    return "string" if isinstance(end, str) else None


def _is_not_a_range(operand: ASTNode) -> bool:
    """Whether an operand can never be a range. A field may hold one, so it is left to the record."""
    if isinstance(operand, FieldNode):
        return False
    if not (
        isinstance(operand, LiteralNode)
        and isinstance(operand.value, list)
        and len(operand.value) == 2
    ):
        return True
    low, high = (_bounds_a_value(end) for end in operand.value)
    return low is None or low != high


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
        unary_postfix_ops = self._build_unary_postfix_operators()

        # `x BETWEEN a AND b` is read whole, as a suffix of `x`, above the AND
        # level. A bound is any operand but an array, so `x BETWEEN [a, b] AND y`
        # still reads as the list form beside a second condition.
        range_bound = function_call | boolean | null | string_literal | number | field_name
        range_suffix = Group(
            PyOptional(CaselessKeyword("NOT"))
            + CaselessKeyword("BETWEEN")
            + range_bound
            + Suppress(CaselessKeyword("AND"))
            + range_bound
        )
        postfix_ops = unary_postfix_ops | range_suffix if unary_postfix_ops else range_suffix

        where_expr = infix_notation(
            operand,
            [
                (CaselessKeyword("NOT"), 1, OpAssoc.RIGHT, self._parse_not),
                (postfix_ops, 1, OpAssoc.LEFT, self._parse_comparison),
                (comparison_ops, 2, OpAssoc.LEFT, self._parse_comparison),
                (CaselessKeyword("AND"), 2, OpAssoc.LEFT, self._parse_and),
                (CaselessKeyword("OR"), 2, OpAssoc.LEFT, self._parse_or),
            ],
        )

        self._grammar = where_expr
        ParserElement.enable_packrat()

    def _collect_comparison_operators(self):
        """Collect binary comparison operators sorted longest-first to avoid partial matches."""
        comparison_ops = [
            (info.symbol, info.name)
            for info in list_operators()
            if info.operator_type.value == "comparison" and info.arity == 2
        ]
        comparison_ops.sort(key=lambda x: len(x[0]), reverse=True)
        return comparison_ops

    def _create_operator_literal(self, symbol: str):
        """Create a pyparsing literal for a single operator."""
        op_literal: ParserElement
        if " " in symbol:
            words = symbol.split()
            op_literal = CaselessKeyword(words[0])
            for word in words[1:]:
                op_literal = op_literal + CaselessKeyword(word)
        else:
            op_literal = Literal(symbol)
        return op_literal

    def _build_comparison_operators(self):
        """Build binary comparison operators from the registry."""
        comparison_ops = self._collect_comparison_operators()
        op_literals = [self._create_operator_literal(symbol) for symbol, _name in comparison_ops]

        if not op_literals:
            return Literal("==")  # Fallback

        result = op_literals[0]
        for op in op_literals[1:]:
            result = result | op
        return result

    def _build_unary_postfix_operators(self):
        """Build unary postfix comparison operators (IS NULL, IS NOT NULL).

        These must be separate from binary operators because pyparsing's
        infix_notation requires arity=1 + OpAssoc.LEFT for postfix unary,
        while binary operators use arity=2.
        """
        unary_ops = [
            (info.symbol, info.name)
            for info in list_operators()
            if info.operator_type.value == "comparison" and info.arity == 1
        ]
        # Longest first so IS NOT NULL matches before IS NULL
        unary_ops.sort(key=lambda x: len(x[0]), reverse=True)
        op_literals = [self._create_operator_literal(symbol) for symbol, _name in unary_ops]

        if not op_literals:
            return None

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

    def _range_comparison(self, left: ASTNode, suffix: ParseResults) -> ComparisonNode:
        """Build `x [NOT] BETWEEN a AND b` as the comparison the list form builds."""
        *negation, _between, low, high = suffix
        if not (isinstance(low, LiteralNode) and isinstance(high, LiteralNode)):
            raise ParseFatalException(_RANGE_REFUSAL)
        literal_range = LiteralNode([low.value, high.value])
        if _is_not_a_range(literal_range):
            raise ParseFatalException(_RANGE_REFUSAL)
        operator = ComparisonOperator.NOT_BETWEEN if negation else ComparisonOperator.BETWEEN
        return ComparisonNode(left, operator, literal_range)

    def _parse_comparison(self, tokens):
        """Parse comparison operations with unified operator lookup."""
        result = tokens[0][0]
        items = tokens[0]

        i = 1
        while i < len(items):
            raw_token = items[i]
            if isinstance(raw_token, ParseResults):
                result = self._range_comparison(result, raw_token)
                i += 1
                continue
            operator_key = raw_token.upper() if isinstance(raw_token, str) else str(raw_token)
            consumed = 1

            # Greedy multi-word matching: if this token starts a multi-word operator
            # (e.g., "NOT" in "NOT IN", "IS" in "IS NOT NULL"), accumulate tokens.
            if operator_key not in _OPERATOR_LOOKUP and operator_key in _MULTI_WORD_STARTS:
                candidate = operator_key
                for j in range(i + 1, len(items)):
                    next_tok = items[j]
                    if not isinstance(next_tok, str):
                        break
                    candidate = candidate + " " + next_tok.upper()
                    consumed += 1
                    if candidate in _OPERATOR_LOOKUP:
                        operator_key = candidate
                        break

            if operator_key not in _OPERATOR_LOOKUP:
                logger.error(
                    "Unknown comparison operator: '%s'",
                    raw_token,
                    extra={"operator_name": raw_token},
                )
                raise ParseException(f"Unknown comparison operator: '{raw_token}'")

            operator_enum = _OPERATOR_LOOKUP[operator_key]
            i += consumed

            if i < len(items):
                right_operand = items[i]
                if operator_enum in _RANGE_OPERATORS and _is_not_a_range(right_operand):
                    raise ParseFatalException(_RANGE_REFUSAL)
                result = ComparisonNode(result, operator_enum, right_operand)
                i += 1
            else:
                # Unary operator (IS NULL, IS NOT NULL)
                result = ComparisonNode(result, operator_enum)

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

        except ParseBaseException as e:
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
        cache_info = type(self).parse_cached.cache_info()
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
