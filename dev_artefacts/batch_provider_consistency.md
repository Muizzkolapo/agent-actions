# Batch Provider Consistency - Visual Guide

## The Clean Code Principle

**"Drop in any LLM - same post-gen path"**

```
┌─────────────────────────────────────────────────────────────────┐
│  User Changes ONE Line in Config:                               │
│                                                                  │
│  model_vendor: openai  →  model_vendor: anthropic               │
│                                                                  │
│  Everything else works identically ✅                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Current Architecture (What's Working)

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   OpenAI    │   │  Anthropic  │   │   Ollama    │   │   Gemini    │
│  Provider   │   │  Provider   │   │  Provider   │   │  Provider   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │                 │
       │  All implement BatchProvider interface             │
       │                 │                 │                 │
       └─────────────────┴─────────────────┴─────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  6 Required Methods:    │
                    │  1. prepare_tasks       │
                    │  2. format_task         │
                    │  3. submit_batch        │
                    │  4. check_status        │
                    │  5. retrieve_results    │
                    │  6. parse_response      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  Returns BatchResult    │
                    │  (Standardized Format)  │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   BatchService          │
                    │   (Provider-Agnostic)   │
                    │                         │
                    │  ✅ Retry Logic         │
                    │  ✅ DLQ                 │
                    │  ✅ Manifests           │
                    │  ✅ Validation          │
                    │  ✅ output_field        │
                    │  ✅ Observe fields      │
                    │  ✅ Lineage tracking    │
                    └─────────────────────────┘
```

**This part is PERFECT ✅ - 100% shared code path**

---

## The Problem Areas (Pre-Processing)

### 1. json_mode Handling

```python
# ✅ OpenAI & Ollama (CORRECT)
def prepare_tasks(self, data, agent_config):
    json_mode = agent_config.get("json_mode", True)
    schema = agent_config.get("compiled_schema") if json_mode else None
    # Only use schema if json_mode: true

# ❌ Anthropic (MISSING)
def prepare_tasks(self, data, agent_config):
    schema = agent_config.get("compiled_schema")
    # Always uses schema! Doesn't check json_mode!
```

**Impact**:
```yaml
# This works:
model_vendor: openai
json_mode: false  # ✅ No schema enforcement

# This FAILS:
model_vendor: anthropic
json_mode: false  # ❌ Still enforces schema via tools!
```

---

### 2. None Value Handling

```python
# ✅ OpenAI (CORRECT)
if "max_tokens" in batch_task.model_config and batch_task.model_config["max_tokens"] is not None:
    body["max_tokens"] = batch_task.model_config["max_tokens"]
# Result: max_tokens only added if has value

# ✅ Ollama (CORRECT - Fixed)
max_tokens = batch_task.model_config.get("max_tokens")
if max_tokens is not None:
    body["max_tokens"] = max_tokens
# Result: max_tokens only added if has value

# ⚠️ Anthropic (USES DEFAULT)
params["max_tokens"] = batch_task.model_config.get("max_tokens", 1024)
# Result: ALWAYS adds max_tokens, uses 1024 if not provided
```

**Impact**:
- Can't omit max_tokens to use Anthropic's default
- Less flexible than OpenAI/Ollama

**Note**: Anthropic API **requires** max_tokens, so we need special handling:
```python
# Better approach:
max_tokens = batch_task.model_config.get("max_tokens")
if max_tokens is not None:
    params["max_tokens"] = max_tokens
else:
    # Anthropic requires max_tokens, use sensible default
    params["max_tokens"] = 4096  # Or read from config
```

---

### 3. Schema Implementation (This is OK!)

Different vendors have different APIs - this is EXPECTED:

```python
# OpenAI & Ollama: Native JSON schema
if schema:
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": schema
    }

# Anthropic: Tool calling
if schema:
    tools = self._create_json_tool_from_schema(schema)
    params["tools"] = tools
    params["tool_choice"] = {"type": "tool", "name": tool_name}
```

**This is CORRECT** ✅
- Each provider translates schema to vendor-specific format
- Post-processing doesn't care HOW schema was enforced
- Result is the same: structured JSON output

---

## Comparison Matrix

| Feature | OpenAI | Anthropic | Ollama | Status |
|---------|--------|-----------|--------|--------|
| **Interface** | ✅ | ✅ | ✅ | Perfect |
| **Post-Gen Path** | ✅ | ✅ | ✅ | Perfect |
| **json_mode: true** | ✅ | ✅ | ✅ | Works |
| **json_mode: false** | ✅ | ❌ | ✅ | **FIX NEEDED** |
| **None handling** | ✅ | ⚠️ | ✅ | **IMPROVE** |
| **Schema → vendor format** | ✅ | ✅ | ✅ | Perfect (different is OK) |
| **Retry logic** | ✅ | ✅ | ✅ | Shared code |
| **DLQ** | ✅ | ✅ | ✅ | Shared code |
| **Manifests** | ✅ | ✅ | ✅ | Shared code |
| **output_field** | ✅ | ✅ | ✅ | Shared code |

---

## The Fix (2 Changes to Anthropic)

### Change 1: Add json_mode Support

**File**: `agent_actions/integrations/providers/anthropic/provider.py`
**Method**: `prepare_tasks` (around line 340)

```python
def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks = []

    # ✅ ADD THIS (matching OpenAI/Ollama)
    json_mode = agent_config.get("json_mode", True)
    schema = agent_config.get("compiled_schema") if json_mode else None

    # REMOVE THIS:
    # schema = agent_config.get("compiled_schema")

    for row in data:
        batch_task = BatchTask(
            custom_id=row.get("target_id", row.get("id", "")),
            prompt=row.get("prompt", agent_config.get("prompt", "")),
            user_content=json.dumps(row.get("content", row)),
            model_config={
                "model_name": agent_config.get("model_name", "claude-3-5-sonnet-20241022"),
                "temperature": agent_config.get("temperature", 1.0),
                "max_tokens": agent_config.get("max_tokens")
            },
            metadata=row
        )

        task = self.format_task_for_provider(batch_task, schema)
        tasks.append(task)

    return tasks
```

### Change 2: Improve max_tokens Handling

**File**: `agent_actions/integrations/providers/anthropic/provider.py`
**Method**: `format_task_for_provider` (around line 103)

```python
params = {
    "model": batch_task.model_config.get("model_name", "claude-3-5-sonnet-20241022"),
    "messages": messages
}

# ✅ CHANGE THIS:
# params["max_tokens"] = batch_task.model_config.get("max_tokens", 1024)

# TO THIS:
max_tokens = batch_task.model_config.get("max_tokens")
if max_tokens is not None:
    params["max_tokens"] = max_tokens
else:
    # Anthropic API requires max_tokens - provide reasonable default
    params["max_tokens"] = 4096

# Add system message if prompt exists
if batch_task.prompt:
    params["system"] = batch_task.prompt
```

---

## After The Fix

```
┌─────────────────────────────────────────────────────────────────┐
│  TRUE DROP-IN REPLACEMENT ✅                                     │
│                                                                  │
│  model_vendor: openai     # Works with json_mode: true/false    │
│  model_vendor: anthropic  # Works with json_mode: true/false    │
│  model_vendor: ollama     # Works with json_mode: true/false    │
│  model_vendor: gemini     # Works with json_mode: true/false    │
│                                                                  │
│  All share same:                                                │
│  - Retry logic                                                  │
│  - DLQ                                                          │
│  - Manifests                                                    │
│  - Validation                                                   │
│  - output_field                                                 │
│  - Observe fields                                               │
│  - Lineage tracking                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Testing Strategy

Add to test suite:

```python
@pytest.mark.parametrize("provider", [
    OpenAIBatchProvider(),
    AnthropicBatchProvider(),
    OllamaLocalBatchProvider(),
    GeminiBatchProvider()
])
def test_json_mode_false(provider):
    """All providers must respect json_mode: false"""
    agent_config = {
        "json_mode": False,
        "compiled_schema": {"type": "object", "properties": {...}}
    }

    tasks = provider.prepare_tasks([{"content": "test"}], agent_config)

    # Verify no schema enforcement in task format
    assert not has_schema_enforcement(tasks[0], provider)


@pytest.mark.parametrize("provider", [
    OpenAIBatchProvider(),
    AnthropicBatchProvider(),
    OllamaLocalBatchProvider(),
    GeminiBatchProvider()
])
def test_none_values_omitted(provider):
    """None values should not appear in requests"""
    batch_task = BatchTask(
        custom_id="test",
        prompt="test",
        user_content="test",
        model_config={"max_tokens": None, "temperature": None}
    )

    task = provider.format_task_for_provider(batch_task, None)

    # Serialize and check for null
    task_json = json.dumps(task)
    assert "null" not in task_json
```

---

## Summary

**Current State**:
- ✅ Post-processing: 100% identical (perfect abstraction)
- ⚠️ Pre-processing: 95% identical (minor fixes needed)

**Fix Required**:
- 2 small changes to Anthropic provider (~15 lines of code)
- Add test suite to prevent drift (~50 lines of code)

**Result After Fix**:
- TRUE drop-in replacement ✅
- Change one line in config, everything works identically
- Clean code principle achieved 🎯

**Effort**: ~30 minutes to implement + 20 minutes to test = 50 minutes total
