# Errors Module Architecture

This document maps the error hierarchy, retry/terminal classification, and propagation patterns for `agent_actions/errors/` — the module that defines every exception type the framework can raise.

---

## Error Hierarchy

```
Exception
└── AgentActionsError                          base.py
    │
    ├── InvalidParameterError                  common.py
    │
    ├── ConfigurationError                     configuration.py
    │   ├── ConfigValidationError
    │   ├── DuplicateFunctionError
    │   ├── FunctionNotFoundError
    │   ├── UDFLoadError
    │   ├── AgentNotFoundError
    │   ├── ProjectNotFoundError
    │   └── RecordContextError                 (per-record recoverable)
    │
    ├── ExternalServiceError                   external_services.py
    │   ├── VendorAPIError
    │   │   ├── AnthropicError
    │   │   ├── RateLimitError                 (retryable)
    │   │   ├── PromptTooLargeError
    │   │   └── LLMResponseParseError
    │   └── NetworkError                       (retryable)
    │
    ├── FileSystemError                        filesystem.py
    │   ├── FileLoadError
    │   ├── FileWriteError
    │   └── DirectoryError
    │
    ├── OperationalError                       operations.py
    │   ├── AgentExecutionError
    │   └── TemplateRenderingError
    │       └── TemplateVariableError          (per-record recoverable)
    │
    ├── PreFlightValidationError               preflight.py
    │   ├── ContextStructureError
    │   ├── VendorConfigError
    │   └── PathValidationError
    │
    ├── ProcessingError                        processing.py
    │   ├── TransformationError
    │   ├── GenerationError
    │   ├── WorkflowError
    │   ├── SerializationError
    │   └── EmptyOutputError
    │
    ├── ResourceError                          resources.py
    │   └── DependencyError
    │
    └── ValidationError                        validation.py
        ├── PromptValidationError
        ├── DataValidationError
        └── SchemaValidationError
```

---

## Retryable vs Terminal Classification

The retry system lives in `processing/recovery/retry.py`. Only two error types trigger automatic retry with exponential backoff:

```python
RETRIABLE_ERRORS = (NetworkError, RateLimitError)
```

There is also a soft extension: `VendorAPIError` instances whose message matches a known transient pattern are treated as retryable. The current patterns are:

```python
_TRANSIENT_API_ERROR_PATTERNS = (
    "could not parse the json body",
    "we are currently processing your json schema",
)
```

### Classification table

| Error | Retryable? | Why |
|-------|-----------|-----|
| `NetworkError` | Yes | Transient connection/timeout failures |
| `RateLimitError` | Yes | HTTP 429 with optional retry-after header |
| `VendorAPIError` (transient pattern match) | Yes | Known intermittent provider bugs |
| `VendorAPIError` (all other) | No | Provider rejected the request (bad input, content filter, etc.) |
| `AnthropicError` | No | Subclass of VendorAPIError, not in RETRIABLE_ERRORS tuple |
| `PromptTooLargeError` | No | Deterministic — same prompt will always be too large |
| `LLMResponseParseError` | No | JSON parse failure — handled by reprompt, not retry |
| Everything else | No | Configuration, filesystem, validation errors are not transient |

### How `is_retriable_error()` decides

```
is_retriable_error(error)
  │
  ├── isinstance(error, (NetworkError, RateLimitError))?  ──► True
  │
  ├── isinstance(error, VendorAPIError)?
  │     └── message matches _TRANSIENT_API_ERROR_PATTERNS? ──► True
  │
  └── else ──► False (re-raised immediately by RetryService)
```

---

## Error Propagation Patterns

Errors propagate through three distinct paths depending on where they originate and whether they affect one record or the entire run.

### Pattern 1: Vendor SDK → Unified Error → Retry or Raise

LLM provider SDK exceptions are caught at the provider layer and converted to the unified hierarchy by `wrap_vendor_error()` in `llm/providers/error_wrapper.py`.

```
SDK exception (openai.RateLimitError, httpx.TimeoutException, etc.)
     │
     ▼
wrap_vendor_error()
     │
     ├── Type-based match (OpenAI, Anthropic, Groq)
     │     ├── rate_limit_types     → RateLimitError + fire RateLimitEvent
     │     ├── network_error_types  → NetworkError   + fire LLMErrorEvent
     │     └── base_api_error_type  → VendorAPIError + fire LLMErrorEvent
     │
     ├── Status-code match (Gemini, Cohere, Ollama)
     │     ├── 429                  → RateLimitError + fire RateLimitEvent
     │     ├── 500/502/503/504      → NetworkError   + fire LLMErrorEvent
     │     └── other codes          → VendorAPIError + fire LLMErrorEvent
     │
     └── extra_network_types (Python builtins, httpx)
           └── ConnectionError, etc → NetworkError   + fire LLMErrorEvent
     │
     ▼
RetryService.execute()
     │
     ├── is_retriable_error() = True  → exponential backoff → retry
     │     └── exhausted? → RetryResult(exhausted=True) or RetryExhaustedException
     │
     └── is_retriable_error() = False → re-raise immediately
```

### Pattern 2: Pre-flight Validation → CLI Abort

Pre-flight errors are raised before any LLM calls happen. They abort the entire run with a user-friendly message.

```
Config loading / validation
     │
     ├── Missing agent_actions.yml        → ProjectNotFoundError
     ├── Bad YAML config                  → ConfigValidationError
     ├── Missing vendor fields            → VendorConfigError
     ├── Invalid file paths               → PathValidationError
     ├── Mismatched context schema        → ContextStructureError
     ├── Missing SDK package              → DependencyError
     └── Duplicate UDF names              → DuplicateFunctionError
     │
     ▼
CLI catches AgentActionsError
     │
     └── PreFlightValidationError.__str__() calls format_user_message()
           └── _render_sections() builds a structured multi-line message
                 with Missing/Available/Hint/Agent/Mode sections
```

Pre-flight errors are never retried. They represent misconfiguration that must be fixed by the user.

### Pattern 3: Template Rendering → Per-Record Tombstone

Some errors affect a single record without terminating the pipeline. The record gets a tombstone disposition (FAILED) and processing continues for the remaining records.

```
Template rendering for record N
     │
     ├── Jinja2 UndefinedError
     │     └── caught → TemplateVariableError
     │           carries: missing_variables, available_variables,
     │                    namespace_context, storage_hints,
     │                    null_namespace_hints
     │           → record N gets FAILED disposition
     │           → records N+1... continue processing
     │
     └── RecordContextError
           └── record's context data incomplete
                 → record N gets FAILED disposition
                 → records N+1... continue processing
```

---

## Per-Record Recoverable Errors

Two errors are designed for per-record recovery rather than pipeline abort:

### RecordContextError

Raised when a single record's context data is incomplete (e.g., a required upstream field is missing for this record but present for others). The pipeline skips the record and continues.

Defined in `configuration.py` as a subclass of `ConfigurationError` — it is a configuration problem, but scoped to one record rather than the entire project.

### TemplateVariableError

Raised when Jinja2 template rendering fails for a specific record because a referenced variable is undefined. Carries rich diagnostic metadata:

- `missing_variables` / `available_variables` — what was expected vs what exists
- `namespace_context` — maps namespace names to their available fields
- `template_line` — line number in the template where the error occurred
- `field_context_metadata` — stored vs loaded fields per namespace
- `storage_hints` — when a field exists in storage but was not loaded (missing schema declaration)
- `null_namespace_hints` — when a namespace is null due to guard-filter at a fan-in point

Both errors result in a FAILED disposition for the affected record. The pipeline does not abort.

---

## The Base Class Contract

`AgentActionsError.__init__` defensively copies its `context` argument:

```python
self.context = dict(context) if isinstance(context, dict) else (context or {})
```

This means callers cannot mutate the error's context after construction by holding a reference to the original dict. Every subclass inherits this behavior.

### Helper functions

| Function | Purpose |
|----------|---------|
| `enrich_exception_context(exc, **kv)` | Attach additional key-value pairs to any exception's `.context` dict. Works on both `AgentActionsError` and stdlib exceptions. |
| `get_error_detail(error)` | Returns `error.detailed_str()` for `AgentActionsError` (message + context dict), otherwise `str(error)`. Use at structured-logging boundaries. |

---

## File Index

| File | What it defines |
|------|----------------|
| `__init__.py` | Centralized re-exports — every error class is importable from `agent_actions.errors` |
| `base.py` | `AgentActionsError`, `enrich_exception_context`, `get_error_detail` |
| `common.py` | `InvalidParameterError` — cross-cutting parameter validation |
| `configuration.py` | `ConfigurationError` tree: config validation, UDF loading, agent/project lookup, record context |
| `external_services.py` | `ExternalServiceError` tree: vendor API, rate limit, network, prompt size, parse errors |
| `filesystem.py` | `FileSystemError` tree: load, write, directory operations |
| `operations.py` | `OperationalError` tree: agent execution, template rendering, template variables |
| `preflight.py` | `PreFlightValidationError` tree: context structure, vendor config, path validation; plus `_render_sections()` |
| `processing.py` | `ProcessingError` tree: transformation, generation, workflow, serialization, empty output |
| `resources.py` | `ResourceError` tree: missing dependencies |
| `validation.py` | `ValidationError` tree: prompt, data, and schema validation |

---

## Caveats and Invariants

1. **`AnthropicError` is NOT retryable.** It subclasses `VendorAPIError`, not `RateLimitError` or `NetworkError`. The retry system checks `isinstance(error, RETRIABLE_ERRORS)` — `AnthropicError` does not match. Rate limits from Anthropic are wrapped as `RateLimitError` by `wrap_vendor_error()`, not as `AnthropicError`. If you catch `AnthropicError` expecting it to be retried, it will not be.

2. **`VendorAPIError` transient patterns are a soft extension.** `is_retriable_error()` checks message substrings for known intermittent provider bugs. These patterns are hardcoded in `_TRANSIENT_API_ERROR_PATTERNS` in `processing/recovery/retry.py`. Adding a new pattern there changes retry behavior globally. The match is case-insensitive (`.lower()` before comparison).

3. **`NetworkError` is a sibling of `VendorAPIError`, not a child.** Both inherit from `ExternalServiceError`. Code that catches `VendorAPIError` will NOT catch `NetworkError`. This is intentional — they have different retry semantics — but it means a broad `except VendorAPIError` will miss timeout and connection failures.

4. **`PreFlightValidationError` overrides `__str__`.** It calls `format_user_message()` which uses `_render_sections()` to produce a multi-line structured message. If you catch this error and call `str(e)`, you get the full formatted output, not just the header. `SchemaValidationError` (in `validation.py`) does the same.

5. **`TemplateVariableError` uses keyword-only `__init__`.** Unlike other errors in the hierarchy, it does not accept a positional `message` argument. It constructs its own message from `agent_name` and `missing_variables`. Calling `TemplateVariableError("some message")` will raise a `TypeError`.

6. **Context dict is always copied, never shared.** `AgentActionsError.__init__` does `dict(context)` on construction. Subclass `__init__` methods that build their own `ctx = dict(context) if context else {}` before calling `super().__init__` are doing a double-copy, which is harmless. But the invariant is: the `.context` attribute on any `AgentActionsError` instance is owned exclusively by that instance.

7. **`RecordContextError` lives under `ConfigurationError`, not `ProcessingError`.** This is a deliberate classification: a record's missing context is a configuration/data issue, not a processing failure. But its propagation behavior (per-record tombstone, pipeline continues) is more like a processing error. Do not move it without updating the callers that catch `ConfigurationError` subtypes.

8. **`LLMResponseParseError` is not retried by `RetryService`.** It subclasses `VendorAPIError` but does not match `RETRIABLE_ERRORS` or `_TRANSIENT_API_ERROR_PATTERNS`. JSON parse failures are handled by the reprompt loop (corrective feedback to the LLM), not by transport-layer retry. Conflating the two recovery mechanisms will cause parse failures to burn through retry attempts without sending corrective feedback.

9. **`RateLimitError` subclasses `VendorAPIError`.** This means `except VendorAPIError` will also catch rate limit errors. If you add error handling that catches `VendorAPIError` and treats it as terminal, you will accidentally suppress retry for rate limits. Always check for `RateLimitError` first, or use `is_retriable_error()`.

10. **`wrap_vendor_error()` returns the original exception if nothing matches.** If a vendor SDK raises an exception type not covered by the mapping, `wrap_vendor_error()` returns it unchanged. It does NOT wrap it in `VendorAPIError`. This means unknown vendor exceptions bypass the entire unified error handling and event-firing pipeline. Any new vendor SDK exception types must be added to the vendor's `VendorErrorMapping`.
