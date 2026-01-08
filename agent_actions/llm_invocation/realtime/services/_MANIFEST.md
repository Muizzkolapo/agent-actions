# Services Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `client_invocation_service.py` | Module | Client invocation service for agent builder. | `llm_invocation` |
| `ClientInvocationService` | Class | Handles client routing and invocation for agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `invoke_client` | Method | Delegate to the specific client and normalize the response. | - |
| `context_service.py` | Module | Context preparation service for agent builder. | `utilities` |
| `ContextService` | Class | Handles context preparation and transformation for agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_field_context` | Method | Build field_context dict from context_data for field reference replacement. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_context_data` | Method | Prepare context data for LLM/tool invocation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_tool_context` | Method | Prepare tool context as JSON string for tool injection. | - |
| `interceptor_service.py` | Module | Interceptor execution service for agent builder. | `reprompting`, `response_processing`, `utilities` |
| `InterceptorService` | Class | Handles interceptor pipeline execution with validation and reprompting. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_with_interceptors` | Method | Execute the agent with validation and reprompt interceptors. | - |
| `prompt_service.py` | Module | Prompt preparation service for agent builder. | `prompt_generation` |
| `PromptService` | Class | Handles prompt loading and preparation for agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_prompt` | Method | Return an actual prompt string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `debug_print_prompt` | Method | Print prompt for debugging if enabled. | - |
| `schema_service.py` | Module | Schema preparation service for agent builder. | `response_processing` |
| `SchemaService` | Class | Handles schema preparation for agents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_schema` | Method | Prepare schema for the given vendor. | - |
