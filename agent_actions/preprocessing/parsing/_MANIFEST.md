# Parsing Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [operator_registry](operator_registry/_MANIFEST.md) | Operator registry for WHERE clause processing. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `ast_nodes.py` | Module | Abstract Syntax Tree nodes for WHERE clause parsing. | `utilities` |
| `NodeType` | Class | Types of AST nodes in the WHERE clause tree. | - |
| `LogicalOperator` | Class | Logical operators for combining expressions. | - |
| `ComparisonOperator` | Class | Comparison operators for field comparisons. | - |
| `ASTNode` | Class | Base class for all AST nodes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | Accept a visitor to process this node. | - |
| `FieldNode` | Class | Represents a field reference (e.g., 'user.name' or 'score'). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | - | - |
| `LiteralNode` | Class | Represents a literal value (string, number, boolean, array, null). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | - | - |
| `ComparisonNode` | Class | Represents a comparison operation (field operator value). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | - | - |
| `LogicalNode` | Class | Represents a logical operation (AND, OR, NOT). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | - | - |
| `FunctionNode` | Class | Represents a function call in the WHERE clause. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accept` | Method | - | - |
| `ASTVisitor` | Class | Visitor interface for processing AST nodes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_field` | Method | Visit a field node. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_literal` | Method | Visit a literal node. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_comparison` | Method | Visit a comparison node. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_logical` | Method | Visit a logical node. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_function` | Method | Visit a function node. | - |
| `EvaluationContext` | Class | Context for evaluating WHERE clause expressions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_field_value` | Method | Get the value of a field using dot notation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_function` | Method | Call a registered function. | - |
| `WhereClauseAST` | Class | Container for a WHERE clause AST with evaluation capabilities. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Evaluate the WHERE clause against the given data. | - |
| `WhereClauseEvaluator` | Class | Evaluates WHERE clause AST nodes against data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_field` | Method | Get the value of a field from the context data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_literal` | Method | Return the literal value. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_comparison` | Method | Evaluate a comparison operation using the operator registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_logical` | Method | Evaluate a logical operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_function` | Method | Evaluate a function call. | - |
| `ASTFormatter` | Class | Formats AST nodes back to string representation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_field` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_literal` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_comparison` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_logical` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `visit_function` | Method | - | - |
| `parser.py` | Module | Advanced WHERE clause parser using pyparsing library. | - |
| `ParseError` | Class | Information about a parsing error. | - |
| `ParseResult` | Class | Result of parsing a WHERE clause. | - |
| `WhereClauseParser` | Class | Advanced WHERE clause parser using pyparsing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_cached` | Method | Parse a WHERE clause with caching. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse a WHERE clause into an AST. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Method | Clear the parsing cache. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_cache_info` | Method | Get cache statistics. | - |
| `SafeExpressionEvaluator` | Class | Safe expression evaluator to replace eval() usage. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `evaluate` | Method | Safely evaluate an expression with given context. | - |
| `get_global_parser` | Function | Get the global WHERE clause parser instance. | - |
| `evaluate_safe_expression` | Function | Safely evaluate an expression (replacement for eval()). | - |
