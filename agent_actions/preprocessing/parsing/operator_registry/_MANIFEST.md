# Operator Registry Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Base classes and types for the operator registry system. | - |
| `OperatorType` | Class | Types of operators in the registry. | - |
| `OperatorInfo` | Class | Information about a registered operator. | - |
| `BaseOperator` | Class | Base class for all operators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Evaluate the operator with given operands. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | Get operator information. | - |
| `ComparisonOperator` | Class | Base class for comparison operators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Evaluate the comparison operator with given operands. | - |
| `LogicalOperator` | Class | Base class for logical operators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Evaluate the logical operator with given operands. | - |
| `FunctionOperator` | Class | Base class for function operators. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_function` | Method | Evaluate the function with given arguments. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Wrapper for function evaluation. | - |
| `comparison.py` | Module | Comparison operators for the operator registry. | - |
| `EqualOperator` | Class | Equality comparison operator (==). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotEqualOperator` | Class | Not equal comparison operator (!=). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `LessThanOperator` | Class | Less than comparison operator (<). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `LessEqualOperator` | Class | Less than or equal comparison operator (<=). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `GreaterThanOperator` | Class | Greater than comparison operator (>). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `GreaterEqualOperator` | Class | Greater than or equal comparison operator (>=). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `InOperator` | Class | In array/list operator (IN). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotInOperator` | Class | Not in array/list operator (NOT IN). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `ContainsOperator` | Class | String contains operator (CONTAINS). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotContainsOperator` | Class | String not contains operator (NOT CONTAINS). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `LikeOperator` | Class | SQL LIKE pattern matching operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotLikeOperator` | Class | SQL NOT LIKE pattern matching operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `BetweenOperator` | Class | BETWEEN range operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotBetweenOperator` | Class | NOT BETWEEN range operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `IsNullOperator` | Class | IS NULL operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `IsNotNullOperator` | Class | IS NOT NULL operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `functions.py` | Module | Function operators for the operator registry. | - |
| `LengthFunction` | Class | LENGTH function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_function` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `UpperFunction` | Class | UPPER function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_function` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `LowerFunction` | Class | LOWER function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_function` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `TrimFunction` | Class | TRIM function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate_function` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `logical.py` | Module | Logical operators for the operator registry. | - |
| `AndOperator` | Class | Logical AND operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `OrOperator` | Class | Logical OR operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `NotOperator` | Class | Logical NOT operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_info` | Method | - | - |
| `registry.py` | Module | Operator registry for managing and evaluating operators. | - |
| `OperatorRegistry` | Class | Registry for managing operators and functions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_operator` | Method | Register a new operator. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_operator` | Method | Get an operator by name or symbol. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_operator_info` | Method | Get operator information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_operators` | Method | List all registered operators. | - |
| `get_global_registry` | Function | Get the global operator registry. | - |
