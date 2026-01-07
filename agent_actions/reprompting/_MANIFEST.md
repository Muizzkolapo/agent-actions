# Reprompting Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config.py` | Module | Configuration for reprompting system with preset support. | - |
| `RepromptConfig` | Class | Simple configuration for reprompting with preset support. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_yaml` | Method | Parse reprompt config from YAML value. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_critique` | Method | Check if LLM critique should be used for this attempt. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_reflection` | Method | Check if self-reflection should be used for this attempt. | - |
| `constraints.py` | Module | Built-in constraint validators for reprompting system. | - |
| `ConstraintResult` | Class | Result of constraint validation. | - |
| `ConstraintValidator` | Class | Validates responses against a list of constraints. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register` | Method | Register a custom constraint function. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate` | Method | Validate response against all constraints. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_constraint_names` | Method | Get list of registered constraint names. | - |
| `engine.py` | Module | Core reprompt engine that orchestrates JSON repair, constraints, and prompt improvement. | `reprompting` |
| `RepromptResult` | Class | Result of reprompt processing. | - |
| `RepromptEngine` | Class | Core reprompt logic that orchestrates repair, validation, and prompt improvement. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_response` | Method | Process a response through repair and validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `generate_improved_prompt` | Method | Generate an improved prompt based on the failure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_critique` | Method | Check if LLM critique should be used for this attempt. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_use_reflection` | Method | Check if self-reflection should be used for this attempt. | - |
| `interceptor.py` | Module | Reprompt interceptor that integrates with the response interceptor system. | `reprompting`, `response_processing` |
| `RepromptInterceptor` | Class | Interceptor that handles reprompting using the new RepromptEngine. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure` | Method | Configure the interceptor from action config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `intercept` | Method | Process response through reprompt engine. | - |
| `json_repair.py` | Module | JSON repair strategies for fixing common LLM JSON output errors. | - |
| `RepairResult` | Class | Result of JSON repair attempt. | - |
| `JSONRepairStrategy` | Class | Multi-stage JSON repair before reprompting. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `attempt_repair` | Method | Try all repair strategies in order. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `repair_and_parse` | Method | Convenience method: repair and return (data, repair_method) or (None, error). | - |
