# Parsing Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | All parsing helpers live at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package docstring for the parsing helpers. | `preprocessing`, `filtering` |
| `ast_nodes.py` | Module | AST node classes (`FieldNode`, `LiteralNode`, `ComparisonNode`, `LogicalNode`, `FunctionNode`), `evaluate_node()` recursive evaluator, `format_node()` formatter, and `WhereClauseAST` container. | `filtering`, `processing`, `logging` |
| `operators.py` | Module | Flat operator module: `OPERATORS` dict (16 comparison operators), `FUNCTIONS` dict (LENGTH/UPPER/LOWER/TRIM), `OPERATOR_INFO` metadata, and the `list_operators()` helper for parser grammar construction. | `parsing`, `filtering` |
| `parser.py` | Module | `WhereClauseParser`, `ParseResult`, and convenience helpers that build ASTs from WHERE clauses with caching, validation, and modern pyparsing APIs. Reads `x BETWEEN a AND b` as the comparison `x BETWEEN [a, b]`, and fails the parse of a `BETWEEN` whose range is neither two numbers, two strings, nor a field. | `filtering`, `configuration`, `validation` |
