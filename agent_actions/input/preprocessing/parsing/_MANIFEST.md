# Parsing Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [operator_registry](operator_registry/_MANIFEST.md) | Operator metadata, comparison/logical/function implementations, and registry helpers for WHERE clause evaluation. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package docstring for the parsing helpers. | `preprocessing`, `filtering` |
| `ast_nodes.py` | Module | AST node classes (`FieldNode`, `LiteralNode`, `ComparisonNode`, `LogicalNode`, `FunctionNode`), visitor interfaces, `WhereClauseAST`, evaluator, and formatter. | `filtering`, `processing`, `logging` |
| `parser.py` | Module | `WhereClauseParser`, `ParseResult`, `SafeExpressionEvaluator`, and convenience helpers that build ASTs from WHERE clauses with caching and validation. | `filtering`, `configuration`, `validation` |
