# Adding a New Batch Provider - Complete Guide

**Last Updated**: 2025-10-20
**Status**: Reference Documentation

---

## Quick Summary

Adding a new batch provider takes **~2-3 hours** for a competent developer. You only need to implement 6 methods and the rest of the system works automatically.

**Proven**: We added Ollama provider in 2.75 hours (including bug fixes).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  USER CHANGES ONE LINE IN CONFIG:                                       │
│                                                                          │
│  model_vendor: openai  →  model_vendor: gemini                         │
│                                                                          │
│  Everything else works identically ✅                                   │
└─────────────────────────────────────────────────────────────────────────┘

                                    ▼

┌─────────────────────────────────────────────────────────────────────────┐
│                        BATCH WORKFLOW SYSTEM                             │
│                                                                          │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌────────────┐ │
│  │   OpenAI    │   │  Anthropic  │   │   Ollama    │   │   Gemini   │ │
│  │  Provider   │   │  Provider   │   │  Provider   │   │  Provider  │ │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬─────┘ │
│         │                 │                 │                 │        │
│         └─────────────────┴─────────────────┴─────────────────┘        │
│                                    │                                    │
│                   ALL IMPLEMENT BatchProvider INTERFACE                 │
│                                    │                                    │
│         ┌──────────────────────────┴──────────────────────────┐        │
│         │                                                      │        │
│         │  6 Required Methods (YOU IMPLEMENT THESE):          │        │
│         │  1. prepare_tasks(data, config) → tasks            │        │
│         │  2. format_task_for_provider(task, schema) → dict  │        │
│         │  3. submit_batch(tasks, name, dir) → batch_id      │        │
│         │  4. check_status(batch_id) → status_string          │        │
│         │  5. retrieve_results(batch_id, dir) → BatchResults  │        │
│         │  6. parse_provider_response(raw) → BatchResult      │        │
│         │                                                      │        │
│         │  + 4 Helper Methods (WE PROVIDE THESE):             │        │
│         │  - _get_batch_directory(dir) → Path                 │        │
│         │  - _write_jsonl_file(tasks, dir, name, vendor)      │        │
│         │  - _read_jsonl_file(path) → BatchResults            │        │
│         │  - _add_optional_param(dict, key, val, default)     │        │
│         │                                                      │        │
│         └──────────────────────────────────────────────────────┘        │
│                                    │                                    │
│                   RETURNS List[BatchResult] (STANDARDIZED)              │
│                                    │                                    │
│                                    ▼                                    │
│         ┌──────────────────────────────────────────────────────┐       │
│         │         BATCH SERVICE (100% SHARED CODE)             │       │
│         │                                                       │       │
│         │  ✅ Registry Management (.batch_registry.json)       │       │
│         │  ✅ Retry Logic (failed items → retry batch)         │       │
│         │  ✅ DLQ (dead_letter_queue.jsonl)                    │       │
│         │  ✅ Manifests (workflow tracking)                    │       │
│         │  ✅ Validation (schema, config)                      │       │
│         │  ✅ output_field handling                            │       │
│         │  ✅ Observe fields (lineage tracking)                │       │
│         │  ✅ WHERE clause filtering                           │       │
│         │  ✅ Passthrough data                                 │       │
│         │  ✅ Context mapping                                  │       │
│         │                                                       │       │
│         │  YOU GET ALL OF THIS FOR FREE! 🎁                    │       │
│         └───────────────────────────────────────────────────────┘      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step: Adding a New Provider

Let's say you want to add **Gemini** as a batch provider.

### Step 1: Create Provider File Structure

```bash
agent_actions/
└── integrations/
    └── providers/
        └── gemini/
            ├── __init__.py
            └── provider.py
```

**File: `agent_actions/integrations/providers/gemini/__init__.py`**
```python
"""Gemini batch provider."""
from .provider import GeminiBatchProvider

__all__ = ['GeminiBatchProvider']
```

---

### Step 2: Implement the Provider Class

**File: `agent_actions/integrations/providers/gemini/provider.py`**

```python
"""
Gemini Batch API provider implementation.

This module implements the BatchProvider interface for Google's Gemini API.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..base import BatchProvider, BatchTask, BatchResult


class GeminiBatchProvider(BatchProvider):
    """
    Gemini Batch API implementation of the BatchProvider interface.

    Handles format transformations:
    - Input: BatchTask → Gemini batch request format
    - Output: Gemini batch response → BatchResult
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Gemini client."""
        # Import vendor SDK
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.genai = genai
        except ImportError as e:
            from agent_actions.core.exceptions import ConfigurationError
            raise ConfigurationError(
                "Required package not installed",
                context={'package': 'google-generativeai',
                        'install_command': 'pip install google-generativeai'},
                cause=e
            )

    # ================================================================
    # REQUIRED METHOD #1: prepare_tasks
    # ================================================================
    def prepare_tasks(self,
                     data: List[Dict[str, Any]],
                     agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data to Gemini batch format.

        IMPORTANT: Check json_mode setting!
        """
        tasks = []

        # ✅ CRITICAL: Respect json_mode setting (consistent with other providers)
        json_mode = agent_config.get("json_mode", True)
        schema = agent_config.get("compiled_schema") if json_mode else None

        for row in data:
            # Create standardized BatchTask
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=row.get("prompt", agent_config.get("prompt", "")),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", "gemini-1.5-flash"),
                    "temperature": agent_config.get("temperature", 1.0),
                    "max_tokens": agent_config.get("max_tokens")
                },
                metadata=row
            )

            # Transform to Gemini format
            gemini_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(gemini_task)

        return tasks

    # ================================================================
    # REQUIRED METHOD #2: format_task_for_provider
    # ================================================================
    def format_task_for_provider(self,
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Transform BatchTask to Gemini's expected format.

        This is YOUR CODE - vendor-specific transformation.
        """
        # Build Gemini request format
        # (This is example - adjust to actual Gemini API format)
        request = {
            "model": batch_task.model_config.get("model_name", "gemini-1.5-flash"),
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{batch_task.prompt}\n\n{batch_task.user_content}"}]
                }
            ]
        }

        # Use base helper for optional parameters (consistent!)
        generation_config = {}
        self._add_optional_param(generation_config, "temperature",
                                batch_task.model_config.get("temperature"))
        self._add_optional_param(generation_config, "maxOutputTokens",
                                batch_task.model_config.get("max_tokens"))

        if generation_config:
            request["generationConfig"] = generation_config

        # Add schema if provided
        if schema:
            # Gemini uses response_schema or response_mime_type
            request["generationConfig"]["response_mime_type"] = "application/json"
            request["generationConfig"]["response_schema"] = schema

        return {
            "custom_id": batch_task.custom_id,
            "request": request
        }

    # ================================================================
    # REQUIRED METHOD #3: submit_batch
    # ================================================================
    def submit_batch(self,
                    tasks: List[Dict[str, Any]],
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """
        Submit batch job to Gemini.

        PATTERN: Use base helpers for OUR CODE, vendor SDK for VENDOR CODE.
        """
        # ✅ OUR CODE: Use base helper for directory setup
        batch_dir = self._get_batch_directory(output_directory)

        # ✅ OUR CODE: Use base helper to write JSONL (for audit trail)
        file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "gemini")

        # ❌ VENDOR CODE: Call Gemini API (vendor-specific!)
        # (Adjust this to actual Gemini batch API)
        batch_job = self.genai.batch_create(
            requests=tasks,
            name=batch_name
        )

        batch_id = batch_job.id
        print(f"Gemini batch job created with ID: {batch_id}")
        return batch_id

    # ================================================================
    # REQUIRED METHOD #4: check_status
    # ================================================================
    def check_status(self, batch_id: str) -> str:
        """
        Check Gemini batch job status.

        IMPORTANT: Return standardized status strings!
        """
        try:
            # ❌ VENDOR CODE: Call Gemini API
            batch_info = self.genai.batch_get(batch_id)

            # ✅ OUR CODE: Map vendor statuses to standard format
            status_mapping = {
                'PENDING': 'validating',
                'RUNNING': 'in_progress',
                'COMPLETED': 'completed',
                'FAILED': 'failed',
                'CANCELLED': 'cancelled'
            }

            gemini_status = batch_info.state  # Adjust to actual field name
            return status_mapping.get(gemini_status, gemini_status.lower())

        except Exception as e:
            from agent_actions.core.exceptions import VendorAPIError
            raise VendorAPIError(
                "Failed to check Gemini batch status",
                context={'batch_id': batch_id, 'vendor': 'gemini'},
                cause=e
            )

    # ================================================================
    # REQUIRED METHOD #5: retrieve_results
    # ================================================================
    def retrieve_results(self,
                        batch_id: str,
                        output_directory: Optional[str] = None) -> List[BatchResult]:
        """
        Retrieve and transform Gemini batch results.

        PATTERN: Download from vendor, save locally, parse to BatchResult.
        """
        try:
            # Check if batch is completed
            status = self.check_status(batch_id)
            if status != 'completed':
                print(f"Batch {batch_id} is not completed. Status: {status}")
                return []

            # ❌ VENDOR CODE: Retrieve results from Gemini API
            results_data = self.genai.batch_get_results(batch_id)

            # ✅ OUR CODE: Save raw results for debugging (optional but recommended)
            if output_directory:
                batch_dir = self._get_batch_directory(output_directory)
                raw_results_file = batch_dir / f"{batch_id}_gemini_raw_results.jsonl"
                with open(raw_results_file, 'w') as f:
                    for entry in results_data:
                        f.write(json.dumps(entry) + '\n')

            # ✅ OUR CODE: Transform to BatchResult format
            batch_results = []
            for raw_result in results_data:
                batch_result = self.parse_provider_response(raw_result)
                batch_results.append(batch_result)

            return batch_results

        except Exception as e:
            from agent_actions.core.exceptions import VendorAPIError
            raise VendorAPIError(
                "Failed to retrieve Gemini batch results",
                context={'batch_id': batch_id, 'vendor': 'gemini'},
                cause=e
            )

    # ================================================================
    # REQUIRED METHOD #6: parse_provider_response
    # ================================================================
    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """
        Transform Gemini response to standardized BatchResult.

        THIS IS THE MAGIC: Convert vendor format → our format.
        """
        custom_id = raw_response.get("custom_id", "unknown")

        # Check for errors
        if raw_response.get("error"):
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=str(raw_response["error"]),
                metadata={"raw_error": raw_response["error"]}
            )

        # Extract content from Gemini response
        # (Adjust to actual Gemini response structure)
        response_data = raw_response.get("response", {})
        candidates = response_data.get("candidates", [])

        content = None
        if candidates:
            candidate = candidates[0]
            content_parts = candidate.get("content", {}).get("parts", [])
            if content_parts:
                content_text = content_parts[0].get("text", "")

                # Try to parse as JSON
                try:
                    content = json.loads(content_text)
                except json.JSONDecodeError:
                    content = content_text

        # Build metadata
        metadata = {
            "model": response_data.get("model"),
            "finish_reason": candidates[0].get("finishReason") if candidates else None,
            "safety_ratings": candidates[0].get("safetyRatings") if candidates else None
        }

        # Extract usage
        usage = response_data.get("usageMetadata", {})

        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=True,
            error=None,
            metadata=metadata,
            usage=usage
        )
```

---

### Step 3: Register Provider in Factory

**File: `agent_actions/integrations/providers/factory.py`**

```python
# Add import at top
from .gemini.provider import GeminiBatchProvider

# Add to create_batch_provider() function
def create_batch_provider(provider_type: str, **kwargs) -> BatchProvider:
    """Factory function to create batch provider instances."""

    if provider_type == 'openai':
        return OpenAIBatchProvider(**kwargs)

    elif provider_type == 'anthropic':
        return AnthropicBatchProvider(**kwargs)

    elif provider_type == 'ollama':
        return OllamaLocalBatchProvider(**kwargs)

    elif provider_type == 'gemini':  # ✅ ADD THIS
        return GeminiBatchProvider(**kwargs)

    else:
        from agent_actions.core.exceptions import ConfigurationError
        raise ConfigurationError(
            f"Unsupported batch provider type: {provider_type}",
            context={
                'provider_type': provider_type,
                'supported_providers': ['openai', 'anthropic', 'ollama', 'gemini']
            }
        )

# Add to get_supported_providers() function
def get_supported_providers() -> list[str]:
    """Get list of supported batch provider types."""
    return ['openai', 'anthropic', 'ollama', 'gemini']  # ✅ ADD 'gemini'
```

---

### Step 4: Test Your Provider

Create a test workflow config:

**File: `sample/test_gemini_batch.yaml`**

```yaml
workflow_id: test_gemini
version: "1.0"

agents:
  fact_extractor:
    model_vendor: gemini  # ✅ Use your new provider
    model_name: gemini-1.5-flash
    prompt: "Extract key facts from the following text"
    schema_name: FactExtraction
    json_mode: true
    temperature: 1.0
    max_tokens: 1024

input_source:
  type: batch_file
  path: test_data.json

output:
  path: output/
```

Run it:

```bash
python -m agent_actions.cli.main workflow run sample/test_gemini_batch.yaml
```

---

## What You DON'T Need to Implement

The following are handled automatically by BatchService:

### ✅ Registry Management
```python
# BatchService creates .batch_registry.json automatically
# Tracks: batch_id, status, timestamp, provider, retry attempts
# YOU DON'T WRITE THIS CODE!
```

### ✅ Retry Logic
```python
# BatchService automatically:
# - Extracts failed items from your BatchResults
# - Creates retry batch with suffix _retry_1, _retry_2, etc.
# - Resubmits using same provider
# YOU DON'T WRITE THIS CODE!
```

### ✅ DLQ (Dead Letter Queue)
```python
# BatchService automatically:
# - Moves items that fail max_retries to dead_letter_queue.jsonl
# - Logs errors with full context
# YOU DON'T WRITE THIS CODE!
```

### ✅ Validation
```python
# BatchService validates:
# - Schema exists when json_mode: true
# - Required config fields present
# - Model name format (if applicable)
# YOU DON'T WRITE THIS CODE!
```

### ✅ Manifests
```python
# BatchService creates manifest.json tracking:
# - Workflow metadata
# - Agent batch IDs
# - Lineage (observe fields)
# - Timestamps
# YOU DON'T WRITE THIS CODE!
```

### ✅ output_field Handling
```python
# BatchService automatically:
# - Wraps non-JSON content in output_field when json_mode: false
# - Handles both dict and string content
# YOU DON'T WRITE THIS CODE!
```

---

## Code Separation: "OUR CODE" vs "VENDOR CODE"

### ✅ OUR CODE (Use Base Helpers)

```python
# Directory setup
batch_dir = self._get_batch_directory(output_directory)

# JSONL file operations
file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "gemini")
batch_results = self._read_jsonl_file(file_path)

# Optional parameters
self._add_optional_param(config, "temperature", value)
self._add_optional_param(config, "max_tokens", value, default=4096)
```

### ❌ VENDOR CODE (Implement Yourself)

```python
# Calling vendor API
batch_job = self.gemini.batch_create(requests=tasks)

# Checking vendor status
batch_info = self.gemini.batch_get(batch_id)

# Retrieving vendor results
results = self.gemini.batch_get_results(batch_id)

# Parsing vendor response format
content = raw_response["response"]["candidates"][0]["content"]["parts"][0]["text"]
```

---

## The 6-Method Contract

### Input/Output Expectations

```python
# 1. prepare_tasks
Input:  data: List[Dict], agent_config: Dict
Output: List[Dict] (vendor-specific task format)

# 2. format_task_for_provider
Input:  batch_task: BatchTask, schema: Optional[Dict]
Output: Dict (single vendor-specific task)

# 3. submit_batch
Input:  tasks: List[Dict], batch_name: str, output_directory: Optional[str]
Output: str (batch_id from vendor)

# 4. check_status
Input:  batch_id: str
Output: str (one of: 'validating', 'in_progress', 'finalizing', 'completed', 'failed', 'cancelled')

# 5. retrieve_results
Input:  batch_id: str, output_directory: Optional[str]
Output: List[BatchResult]

# 6. parse_provider_response
Input:  raw_response: Any (vendor-specific format)
Output: BatchResult (standardized)
```

---

## Common Patterns by Provider Type

### Pattern A: Cloud Async (OpenAI, Anthropic, Gemini)

```python
def submit_batch(self, tasks, batch_name, output_directory):
    # 1. Write local file for audit
    batch_dir = self._get_batch_directory(output_directory)
    file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "vendor")

    # 2. Submit to cloud API
    batch_job = self.client.batch_create(...)

    # 3. Return batch_id (processing happens async)
    return batch_job.id

def check_status(self, batch_id):
    # Poll vendor API for status
    batch_info = self.client.batch_get(batch_id)
    return self._map_status(batch_info.status)

def retrieve_results(self, batch_id, output_directory):
    # Download from vendor
    results = self.client.batch_get_results(batch_id)

    # Save locally (optional)
    if output_directory:
        batch_dir = self._get_batch_directory(output_directory)
        # Save raw results...

    # Parse and return
    return [self.parse_provider_response(r) for r in results]
```

### Pattern B: Local Sync (Ollama, Local Models)

```python
def submit_batch(self, tasks, batch_name, output_directory):
    # 1. Write input file
    batch_dir = self._get_batch_directory(output_directory)
    file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "vendor")

    # 2. Generate batch_id
    batch_id = f"batch_{uuid.uuid4().hex}"

    # 3. Process ALL tasks immediately (sync)
    results = []
    for task in tasks:
        response = self.client.generate(...)
        results.append(self._format_response(response, task['custom_id']))

    # 4. Write output file
    output_path = batch_dir / f"{batch_id}_results.jsonl"
    with open(output_path, 'w') as f:
        for result in results:
            f.write(json.dumps(result) + '\n')

    # 5. Return batch_id (already completed!)
    return batch_id

def check_status(self, batch_id):
    # Always completed since we process synchronously
    return "completed"

def retrieve_results(self, batch_id, output_directory):
    # Read from local file
    batch_dir = self._get_batch_directory(output_directory)
    file_path = batch_dir / f"{batch_id}_results.jsonl"
    return self._read_jsonl_file(file_path)
```

---

## Testing Checklist

Before considering your provider "done", test these scenarios:

### ✅ Basic Functionality
- [ ] Submit batch with 10 items
- [ ] Check status returns correct state
- [ ] Retrieve results when completed
- [ ] All 10 items processed successfully

### ✅ json_mode Support
- [ ] `json_mode: true` enforces schema
- [ ] `json_mode: false` allows free text
- [ ] Schema validation works correctly

### ✅ Error Handling
- [ ] Invalid API key raises proper exception
- [ ] Network errors are caught and wrapped
- [ ] Malformed responses don't crash

### ✅ Optional Parameters
- [ ] `temperature` is applied (or omitted if None)
- [ ] `max_tokens` is applied (or uses default if required)
- [ ] Other model-specific params work

### ✅ Integration with BatchService
- [ ] Registry entry created correctly
- [ ] Retry logic works (force a failure)
- [ ] DLQ receives max-retry failures
- [ ] Manifest tracks batch_id correctly
- [ ] output_field wrapping works in non-JSON mode

---

## Time Estimates

Based on Ollama implementation (actual: 2.75 hours):

| Task | Estimated Time |
|------|----------------|
| Setup file structure | 5 min |
| Implement 6 required methods | 60-90 min |
| Register in factory | 5 min |
| Write basic tests | 30 min |
| Debug integration issues | 30-60 min |
| **TOTAL** | **2-3 hours** |

**Factors that affect time:**
- ✅ Vendor SDK quality (good docs = faster)
- ✅ Batch API maturity (well-designed = faster)
- ✅ Your familiarity with vendor API
- ❌ Unusual response formats (nested objects, streams)
- ❌ Non-standard status codes
- ❌ Special authentication requirements

---

## Summary: What Makes This Easy

### You Only Write 6 Methods
Everything else (registry, retry, DLQ, manifests, validation) is provided.

### Base Class Helpers
Use `_get_batch_directory()`, `_write_jsonl_file()`, etc. - no boilerplate!

### Standardized Format
Input: `BatchTask` → Output: `BatchResult` - consistent across all providers.

### Factory Pattern
Register once in `factory.py`, works everywhere.

### Proven Pattern
3 providers already working (OpenAI, Anthropic, Ollama) - copy their structure!

---

## Example: Minimal Working Provider

Here's the absolute minimum (no error handling, no options):

```python
from ..base import BatchProvider, BatchTask, BatchResult
from typing import List, Dict, Any, Optional

class MinimalProvider(BatchProvider):
    def __init__(self, api_key: str):
        self.client = SomeVendorClient(api_key)

    def prepare_tasks(self, data, agent_config):
        return [self.format_task_for_provider(
            BatchTask(
                custom_id=row["target_id"],
                prompt=agent_config["prompt"],
                user_content=json.dumps(row["content"]),
                model_config={"model_name": agent_config["model_name"]}
            ),
            agent_config.get("compiled_schema")
        ) for row in data]

    def format_task_for_provider(self, task, schema):
        return {"custom_id": task.custom_id, "request": {"prompt": task.prompt}}

    def submit_batch(self, tasks, batch_name, output_directory):
        return self.client.submit(tasks).id

    def check_status(self, batch_id):
        return self.client.get_status(batch_id).status.lower()

    def retrieve_results(self, batch_id, output_directory):
        return [self.parse_provider_response(r)
                for r in self.client.get_results(batch_id)]

    def parse_provider_response(self, raw):
        return BatchResult(
            custom_id=raw["id"],
            content=raw["response"]["text"],
            success=True
        )
```

**That's it!** 36 lines of code and you have a working provider. 🎉

---

## Questions to Ask When Adding a Provider

1. **Does the vendor have a batch API?**
   - Yes → Implement async pattern (OpenAI/Anthropic style)
   - No → Implement sync pattern (Ollama style)

2. **Does the vendor support JSON schema enforcement?**
   - Native support → Add to `format_task_for_provider()`
   - Tool calling → Use tool pattern (like Anthropic)
   - No support → Skip schema handling

3. **What status values does the vendor return?**
   - Map them to: `validating`, `in_progress`, `finalizing`, `completed`, `failed`, `cancelled`

4. **Does the vendor require specific parameters?**
   - Required → Use `default` in `_add_optional_param()`
   - Optional → Omit `default`

5. **How are results retrieved?**
   - Download file → Save locally, parse with `_read_jsonl_file()`
   - Stream API → Iterate and parse inline
   - Paginated → Loop until all pages retrieved

---

## Final Checklist

Before submitting PR:

- [ ] All 6 methods implemented
- [ ] Registered in `factory.py`
- [ ] `json_mode: true/false` both work
- [ ] Errors wrapped in appropriate exceptions
- [ ] Files saved to `batch/` directory
- [ ] Returns `List[BatchResult]` from `retrieve_results()`
- [ ] Status mapping to standard values
- [ ] Tested end-to-end with sample workflow
- [ ] Updated this guide with any new patterns discovered

---

**Remember**: You're not building a batch system. You're just translating between our format and the vendor's format. The batch system already exists! 🚀
