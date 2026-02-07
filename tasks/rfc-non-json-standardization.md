# RFC: Standardize Non-JSON Output Handling Across All LLM Providers

**Status:** Draft
**Author:** Engineering
**Date:** 2026-02-06
**Scope:** `agent_actions/llm/providers/*`, `agent_actions/output/response/schema.py`

---

## 1. Problem Statement

The platform supports 8 LLM providers. When `json_mode=False`, the provider's `call_non_json()` method is responsible for returning the raw LLM text wrapped in a consistent shape so the rest of the pipeline (enrichment, saving, file writing) works uniformly.

**The contract defined by `BaseClient` (client_base.py:140-159):**

```python
@abstractmethod
def call_non_json(...) -> List[Dict[str, str]]:
```

**Current reality:**

| Provider | `call_non_json` exists? | Returns correct `List[Dict]`? | Other issues |
|---|---|---|---|
| OpenAI | Yes | Yes — `[{output_field: text}]` | None |
| Anthropic | **No — raises ConfigurationError** | N/A | Blocks non-JSON entirely |
| Gemini | Yes | **No — `[str]`** | Still requests JSON (bug) |
| Cohere | Yes | **No — `[str]`** | Dual SDK versions; `schema.keys()` bug in `call_json` |
| Groq | Yes | **No — `[str]`** | Hardcoded temperature/max_tokens |
| Mistral | Yes | **No — `[str]`** | None |
| Ollama | Yes | Yes — `[{output_field: text}]` | Token counts discarded |
| AGAC | Yes | Yes — `[{output_field: text}]` | None (mock) |

Only 3 of 8 providers honor the return contract. The batch result processor (`result_processor.py:275`) patches this downstream:

```python
if not ctx.json_mode and isinstance(generated_obj, str):
    generated_obj = {ctx.output_field: generated_obj}
```

But this safety net only applies in batch mode. Online mode passes the raw return through, meaning 4 providers return `List[str]` into a pipeline that expects `List[Dict]`.

Additionally, 3 providers (Cohere, Groq, Mistral) are missing from the `compile_unified_schema()` vendor whitelist, so their `call_json` receives `schema=None` — degrading JSON mode to prompt-only with no structured output enforcement.

---

## 2. Goals

1. **Every provider returns `List[Dict[str, str]]` from `call_non_json()`** — matching the `BaseClient` contract.
2. **Anthropic supports non-JSON mode** — no more `ConfigurationError`.
3. **Gemini non-JSON actually produces plain text** — not JSON.
4. **Cohere, Groq, Mistral added to schema compilation whitelist** — so JSON mode uses structured output where available.
5. **Cohere `call_json` schema bug fixed** — the `schema.keys()` call that crashes on compiled schema format.
6. **Ollama token counts extracted** — instead of hardcoded zeros.

## 3. Non-Goals

- Migrating Gemini from `google-generativeai` to `google-genai` SDK.
- Migrating Cohere from mixed v1/v2 to v2-only.
- Upgrading Anthropic `call_json` from tools-based to `output_config.format` structured outputs.
- Upgrading Gemini `call_json` from prompt-based to native `response_schema`.
- Adding `json_schema` mode (beyond `json_object`) to Cohere/Groq — these are enhancements, not fixes.

---

## 4. Provider-by-Provider Changes

### 4.1 Anthropic — Implement `call_non_json()`

**File:** `llm/providers/anthropic/client.py`

**Current (lines 193-206):**
```python
@staticmethod
def call_non_json(...) -> List[Dict[str, str]]:
    """Non-JSON mode is not implemented for Claude."""
    raise ConfigurationError(
        "Non-JSON mode not implemented for Claude",
        context={"vendor": "anthropic", "supported_modes": ["json"], ...},
    )
```

**Vendor docs confirm:** Plain text is the API default. Call `client.messages.create()` without `tools` parameter. Response text is at `response.content[0].text`.

**Change:** Replace the `raise` with an actual implementation:

```python
@staticmethod
def call_non_json(api_key, agent_config, prompt_config, context_data):
    model_name = agent_config[MODEL_NAME_KEY]
    client = anthropic.Anthropic(api_key=api_key)
    context_data_str = StringProcessor.process_as_string(context_data)
    prompt = f"""
        <|begin_of_user_instruction|>: {prompt_config} :<|end_of_user_instruction|>
        <|begin_of_text|>: {str(context_data_str)} :<|end_of_text|>
    """
    prompt_dedent = dedent(prompt)

    # No tools parameter — plain text mode
    api_args = {
        "model": model_name,
        "max_tokens": agent_config.get("max_tokens", 1024),
        "messages": [{"role": "user", "content": prompt_dedent}],
    }

    request_id = str(uuid.uuid4())

    # ... standard logging, fire_event, timing (same pattern as call_json) ...

    response = client.messages.create(**api_args)

    # Extract plain text from first TextBlock
    content = response.content[0].text

    output_field = agent_config.get("output_field", "raw_response")
    return [{output_field: content}]
```

**Key differences from `call_json`:**
- No `tools` in `api_args`
- Extract `.content[0].text` instead of looking for `.input` on tool-use blocks
- `stop_reason` will be `"end_turn"` (not `"tool_use"`)

**Secondary fix — normalize `call_json` return type:**

Current `call_json` returns `Union[Dict, List[Dict]]` (line 109). The `_extract_response_content` helper (line 81) returns whatever shape the tool use block contains. This should be normalized:

```python
# In call_json, after _extract_response_content:
result = AnthropicClient._extract_response_content(response, model_name)
return result if isinstance(result, list) else [result]
```

**Risk:** Low. The Anthropic Messages API has supported plain text since launch. This is the simplest call pattern.

**Tests needed:**
- Unit test: `call_non_json` returns `[{output_field: text}]`
- Unit test: `call_non_json` with empty response raises `VendorAPIError`
- Integration test: end-to-end non-JSON flow with Anthropic config

---

### 4.2 Gemini — Fix Broken Non-JSON

**File:** `llm/providers/gemini/client.py`

**Current `call_non_json` (lines 142-244):**
```python
llm = genai.GenerativeModel(
    model_name,
    system_instruction="Return only JSON",                    # BUG: asks for JSON
    generation_config={"response_mime_type": "application/json"},  # BUG: forces JSON
)
# ...
return [response_list]  # BUG: returns [str], not [{dict}]
```

**Vendor docs confirm:** Plain text is the default. Omit `response_mime_type` entirely. Omit `system_instruction` (or set something appropriate for the task, not "Return only JSON").

**Changes:**

1. Remove JSON directives:
```python
llm = genai.GenerativeModel(
    model_name,
    # No system_instruction forcing JSON
    # No response_mime_type — defaults to plain text
)
```

2. Fix return type:
```python
output_field = agent_config.get("output_field", "raw_response")
return [{output_field: response_temp.text}]
```

**Risk:** Low. We're removing incorrect configuration, not adding new behavior.

**Tests needed:**
- Unit test: `call_non_json` does NOT set `response_mime_type`
- Unit test: returns `[{output_field: text}]`

---

### 4.3 Cohere — Fix Return + Schema Bug

**File:** `llm/providers/cohere/client.py`

**Change 1 — Fix `call_non_json` return (line 236):**

```python
# Before:
return [response_message]

# After:
output_field = agent_config.get("output_field", "raw_response")
return [{output_field: response_message}]
```

**Change 2 — Fix `call_json` schema handling (line 75):**

The current prompt embeds `schema.keys()` which assumes `schema` is a flat dict of field names. But `compile_unified_schema` returns `{"name": "...", "schema": {"type": "object", "properties": {...}}}`. If schema compilation is enabled for Cohere, `.keys()` would yield `name, schema` — not the field names.

```python
# Before:
prompt = f"""... GENERATE JSON with the fields {", ".join([f"'{field}'" for field in schema.keys()])} ..."""

# After — extract actual field names from compiled schema:
if schema and isinstance(schema, dict):
    properties = schema.get("schema", schema).get("properties", schema)
    field_names = ", ".join([f"'{f}'" for f in properties.keys()])
else:
    field_names = "as specified"
prompt = f"""... GENERATE JSON with the fields {field_names} ..."""
```

**Risk:** Medium. The schema extraction logic needs care to handle both the compiled format and the current raw-dict format during transition.

**Tests needed:**
- Unit test: `call_non_json` returns `[{output_field: text}]`
- Unit test: `call_json` correctly extracts field names from compiled schema
- Unit test: `call_json` handles `schema=None` gracefully

---

### 4.4 Groq — Fix Return

**File:** `llm/providers/groq/client.py`

**Change — Fix `call_non_json` return (line 213):**

```python
# Before:
response_content = response.choices[0].message.content
return [response_content]

# After:
response_content = response.choices[0].message.content
output_field = agent_config.get("output_field", "raw_response")
return [{output_field: response_content}]
```

**Secondary — make temperature/max_tokens configurable (lines 159-160):**

```python
# Before:
"temperature": 0.7,
"max_tokens": 1000,

# After:
"temperature": agent_config.get("temperature", 0.7),
"max_tokens": agent_config.get("max_tokens", 1000),
```

**Risk:** Low. One-line return fix + config externalization.

**Tests needed:**
- Unit test: `call_non_json` returns `[{output_field: text}]`

---

### 4.5 Mistral — Fix Return

**File:** `llm/providers/mistral/client.py`

**Change — Fix `call_non_json` return (line 232):**

```python
# Before:
return [response_output]

# After:
output_field = agent_config.get("output_field", "raw_response")
return [{output_field: response_output}]
```

**Risk:** Low. Single-line fix.

**Tests needed:**
- Unit test: `call_non_json` returns `[{output_field: text}]`

---

### 4.6 Schema Compilation — Add Missing Vendors

**File:** `output/response/schema.py`, function `compile_unified_schema()` (lines 172-226)

**Current whitelist:** `openai`, `anthropic`, `gemini`, `ollama`, `agac-provider`
**Missing:** `cohere`, `groq`, `mistral`

All three use OpenAI-compatible schema format (`json_object` or `json_schema`). Vendor docs confirm:

- **Groq:** OpenAI-compatible. Uses `response_format={"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}`. Same compilation as OpenAI.
- **Mistral:** OpenAI-compatible. Uses `response_format={"type": "json_schema", "json_schema": {"name": "...", "strict": true, "schema": {...}}}`. Same compilation as OpenAI.
- **Cohere:** Native format differs — `response_format={"type": "json_object", "schema": {...}}` (schema at top level, not nested under `json_schema`). Needs its own compilation target.

**Change:**

```python
elif target in ("groq", "mistral"):
    # OpenAI-compatible format
    compiled = {
        "name": unified.get("name", ""),
        "schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }
elif target == "cohere":
    # Cohere native format — schema at top level of response_format
    compiled = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

Also update the error message valid systems list:

```python
"valid_systems": ["openai", "anthropic", "gemini", "ollama", "agac-provider", "cohere", "groq", "mistral"],
```

**Risk:** Low. Additive — no existing behavior changes.

**Tests needed:**
- Unit test: `compile_unified_schema("groq")` produces OpenAI-compatible format
- Unit test: `compile_unified_schema("mistral")` produces OpenAI-compatible format
- Unit test: `compile_unified_schema("cohere")` produces Cohere native format

---

### 4.7 Ollama — Extract Token Counts

**File:** `llm/providers/ollama/client.py`

**Current (lines 177-180, 281-284):** Token counts hardcoded to 0.

**Vendor docs confirm:** Token counts are available at `response.prompt_eval_count` (input) and `response.eval_count` (output).

**Change (both `call_json` and `call_non_json`):**

```python
# Before:
prompt_tokens = 0
completion_tokens = 0
total_tokens = 0

# After:
prompt_tokens = getattr(response, "prompt_eval_count", 0) or 0
completion_tokens = getattr(response, "eval_count", 0) or 0
total_tokens = prompt_tokens + completion_tokens
```

**Risk:** Low. `getattr` with fallback handles any SDK version that might not have the field.

**Tests needed:**
- Unit test: token counts extracted when available
- Unit test: graceful fallback to 0 when fields are `None`

---

## 5. Execution Order

Changes are independent per provider but should be landed in order of risk and dependency:

1. **Gemini, Groq, Mistral return fixes** — smallest changes, highest confidence
2. **Schema compilation whitelist** — additive, no behavior change for existing vendors
3. **Cohere return fix + schema.keys() bug** — slightly more involved
4. **Anthropic `call_non_json` implementation** — new code, needs most testing
5. **Ollama token counts** — low priority, non-breaking improvement
6. **Anthropic `call_json` return normalization** — lowest priority

Each can be a separate PR or grouped logically (e.g., all return-type fixes in one PR, Anthropic in its own).

---

## 6. Verification Plan

### Per-provider unit tests
Each provider's `call_non_json` should be tested with a mock SDK response to verify:
- Returns `List[Dict[str, str]]`
- Dict contains the configured `output_field` key
- Value is the raw text string from the API

### Integration test
End-to-end test with `json_mode=False` for each provider, verifying the full pipeline:
- Provider returns correct shape
- `ensure_list()` sees `List[Dict]` (not `List[str]`)
- Enrichment pipeline receives correct data
- Output writer can serialize to `.txt` and `.json`

### Batch mode regression
Verify `result_processor.py:275` safety net still works for edge cases, but is no longer the primary mechanism for wrapping non-JSON responses.

### Schema compilation tests
For each newly added vendor, verify `compile_unified_schema()` produces the expected format and the compiled schema is accepted by the provider's API (or mock).

---

## 7. Future Improvements (Out of Scope)

These are documented for follow-up work but explicitly excluded from this RFC:

| Improvement | Provider(s) | Notes |
|---|---|---|
| Upgrade to `output_config.format` for structured outputs | Anthropic | Replaces tools-based JSON hack with native JSON Schema |
| Upgrade to native `response_schema` | Gemini | Replaces prompt-based schema with controlled decoding |
| Migrate to `google-genai` SDK | Gemini | `google-generativeai` is deprecated |
| Migrate to `ClientV2` for all modes | Cohere | v1 `Client` is legacy |
| Add `json_schema` strict mode | Groq, Cohere | Native schema enforcement where supported |
| Configurable `max_tokens` for Anthropic | Anthropic | Currently hardcoded to 1024 in `call_json` |
