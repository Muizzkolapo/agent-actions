# Operator Registry Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | All registry helpers live at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Re-exports base classes, builtin comparison/logical/function operators, and the registry helpers for WHERE clause logic. | `parsing`, `filtering` |
| `base.py` | Module | Abstract operator base classes (`BaseOperator`, `ComparisonOperator`, `LogicalOperator`, `FunctionOperator`) plus metadata types (`OperatorInfo`, `OperatorType`). | `parsing`, `validation` |
| `comparison.py` | Module | Equality, relational, membership, string-pattern, range, and null comparison operator implementations with their metadata. | `parsing`, `filtering`, `validation` |
| `logical.py` | Module | Logical operators (`AndOperator`, `OrOperator`, `NotOperator`) that short-circuit using the registry. | `parsing`, `filtering` |
| `functions.py` | Module | Function operators such as `LengthFunction`, `UpperFunction`, `LowerFunction`, `TrimFunction` exposed via WHERE clauses. | `parsing`, `filtering`, `skills` |
| `registry.py` | Module | `OperatorRegistry` implementation plus `get_global_registry` singleton used by the parser and evaluator. | `parsing`, `filtering`, `configuration` |
