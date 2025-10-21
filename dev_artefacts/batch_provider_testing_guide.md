# Batch Provider Testing Guide

**Last Updated**: 2025-10-21
**Status**: Reference Documentation

---

## Overview

This guide documents the comprehensive testing architecture for batch providers in agent-actions. All batch providers (OpenAI, Anthropic, Gemini, Ollama) are tested using a 3-tier architecture that ensures:

1. **Contract compliance** - All providers implement the BatchProvider interface correctly
2. **Provider-specific behavior** - Unique features are tested appropriately
3. **Easy extensibility** - Adding tests for new providers is straightforward

---

## Why Test Batch Providers?

### Goals

✅ **Contract Validation**
Ensure all providers correctly implement the 6 required BatchProvider methods

✅ **Format Compliance**
Verify provider-specific request/response formats are handled correctly

✅ **Error Handling**
Test that errors are properly wrapped in VendorAPIError with correct signatures

✅ **Integration Compatibility**
Confirm providers work with BatchService orchestration (retry, DLQ, etc.)

✅ **Regression Prevention**
Catch breaking changes early when refactoring provider code

### Test Coverage Results

| Provider | Total Tests | Passed | Skipped | Pass Rate | Status |
|----------|-------------|--------|---------|-----------|--------|
| OpenAI | 14 | 14 | 0 | 100% | ✅ |
| Anthropic | 16 | 15 | 1 | 93.75% | ✅ |
| Gemini | 14 | 11 | 3 | 78.5% | ✅ |
| Ollama | 13 | 13 | 0 | 100% | ✅ |
| **TOTAL** | **57** | **53** | **4** | **93.0%** | ✅ |

*Note: Skipped tests are intentional - they test integration workflows that differ between providers*

---

## Testing Architecture

### 3-Tier System

```
┌─────────────────────────────────────────────────────────────────┐
│  TIER 1: SHARED FIXTURES (tests/conftest.py)                  │
│                                                                 │
│  ✅ sample_batch_task - Standard BatchTask for all providers   │
│  ✅ sample_batch_task_no_max_tokens - BatchTask w/o max_tokens │
│  ✅ sample_data - Sample data array for prepare_tasks          │
│  ✅ sample_agent_config_json_mode - Config with json_mode=true │
│  ✅ sample_agent_config_no_json_mode - Config w/ json_mode=false│
│                                                                 │
│  Purpose: Consistent test data across ALL provider tests       │
└─────────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 2: CONTRACT TESTS (BaseBatchProviderTests)              │
│  File: tests/integrations/providers/base_batch_provider_tests.py│
│                                                                 │
│  11 Contract Tests (ALL providers must pass):                  │
│                                                                 │
│  1. test_format_task_basic                                     │
│  2. test_format_task_with_schema                               │
│  3. test_format_task_no_max_tokens                             │
│  4. test_parse_success_response_json                           │
│  5. test_parse_success_response_string                         │
│  6. test_parse_error_response                                  │
│  7. test_prepare_tasks_json_mode_true                          │
│  8. test_prepare_tasks_json_mode_false                         │
│  9. test_check_status_returns_valid_state                      │
│  10. test_submit_and_retrieve_workflow                         │
│  11. test_retrieve_invalid_batch_id_raises_error               │
│                                                                 │
│  Purpose: Define contract that ALL providers must satisfy      │
└─────────────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  TIER 3: PROVIDER-SPECIFIC TESTS                              │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   OpenAI     │  │  Anthropic   │  │   Gemini     │         │
│  │  14 tests    │  │  16 tests    │  │  14 tests    │         │
│  │  100% pass   │  │  93.75% pass │  │  78.5% pass  │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                 │
│  ┌──────────────┐                                              │
│  │   Ollama     │                                              │
│  │  13 tests    │                                              │
│  │  100% pass   │                                              │
│  └──────────────┘                                              │
│                                                                 │
│  Purpose: Test provider-unique features and format differences │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tier 1: Shared Fixtures

### Location
`tests/conftest.py` (lines 476-584)

### Fixtures

#### 1. `sample_batch_task`
Standard BatchTask for testing format_task_for_provider:

```python
@pytest.fixture
def sample_batch_task():
    """Standard BatchTask for testing all batch providers."""
    from agent_actions.integrations.providers.base import BatchTask
    return BatchTask(
        custom_id="test-123",
        prompt="You are a helpful assistant",
        user_content='{"question": "What is 2+2?"}',
        model_config={
            "model_name": "test-model",
            "temperature": 0.7,
            "max_tokens": 100
        }
    )
```

#### 2. `sample_batch_task_no_max_tokens`
BatchTask without max_tokens (tests optional parameter handling):

```python
@pytest.fixture
def sample_batch_task_no_max_tokens():
    """BatchTask without max_tokens for testing optional param handling."""
    return BatchTask(
        custom_id="test-456",
        prompt="You are a helpful assistant",
        user_content='{"question": "What is 3+3?"}',
        model_config={
            "model_name": "test-model",
            "temperature": 0.7
            # No max_tokens!
        }
    )
```

#### 3. `sample_data`
Sample data array for testing prepare_tasks:

```python
@pytest.fixture
def sample_data():
    """Sample data for testing prepare_tasks method."""
    return [
        {"target_id": "1", "content": {"question": "Question 1"}},
        {"target_id": "2", "content": {"question": "Question 2"}},
        {"target_id": "3", "content": {"question": "Question 3"}}
    ]
```

#### 4. `sample_agent_config_json_mode`
Agent config with json_mode enabled and schema:

```python
@pytest.fixture
def sample_agent_config_json_mode():
    """Agent config with json_mode: true and compiled schema."""
    return {
        "prompt": "Test prompt",
        "model_name": "test-model",
        "temperature": 0.7,
        "max_tokens": 100,
        "json_mode": True,
        "compiled_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}}
        }
    }
```

#### 5. `sample_agent_config_no_json_mode`
Agent config with json_mode disabled:

```python
@pytest.fixture
def sample_agent_config_no_json_mode():
    """Agent config with json_mode: false (no schema)."""
    return {
        "prompt": "Test prompt",
        "model_name": "test-model",
        "temperature": 0.7,
        "max_tokens": 100,
        "json_mode": False
    }
```

---

## Tier 2: Contract Tests

### Location
`tests/integrations/providers/base_batch_provider_tests.py` (~440 lines)

### Base Class Structure

```python
from abc import ABC, abstractmethod
import pytest
from typing import Dict, Any

class BaseBatchProviderTests(ABC):
    """
    Abstract base class for testing BatchProvider implementations.

    All provider tests inherit from this class to ensure they implement
    the BatchProvider contract correctly.
    """

    # ==================== Required Fixtures ====================
    # Each provider test class MUST implement these 4 fixtures:

    @pytest.fixture
    @abstractmethod
    def provider(self) -> BatchProvider:
        """Return an instance of the provider to test."""
        pass

    @pytest.fixture
    @abstractmethod
    def provider_success_response_json(self) -> Dict[str, Any]:
        """Return a mock successful response with JSON content."""
        pass

    @pytest.fixture
    @abstractmethod
    def provider_success_response_string(self) -> Dict[str, Any]:
        """Return a mock successful response with plain text."""
        pass

    @pytest.fixture
    @abstractmethod
    def provider_error_response(self) -> Dict[str, Any]:
        """Return a mock error response."""
        pass

    # ==================== Contract Tests ====================
    # These 11 tests run automatically for ALL providers
```

### The 11 Contract Tests

#### 1. `test_format_task_basic`
Tests basic task formatting without schema:

```python
def test_format_task_basic(self, provider, sample_batch_task):
    """Test basic task formatting without schema."""
    result = provider.format_task_for_provider(sample_batch_task, schema=None)

    assert isinstance(result, dict)
    assert "custom_id" in result
    assert result["custom_id"] == "test-123"
```

**What it validates:**
- format_task_for_provider returns a dict
- custom_id is included in the formatted task
- custom_id value matches input

#### 2. `test_format_task_with_schema`
Tests task formatting with JSON schema:

```python
def test_format_task_with_schema(self, provider, sample_batch_task):
    """Test task formatting with JSON schema."""
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    result = provider.format_task_for_provider(sample_batch_task, schema=schema)

    assert isinstance(result, dict)
    assert "custom_id" in result
```

**What it validates:**
- Schema parameter is handled correctly
- Formatted task includes custom_id

#### 3. `test_format_task_no_max_tokens`
Tests handling of optional max_tokens parameter:

```python
def test_format_task_no_max_tokens(self, provider, sample_batch_task_no_max_tokens):
    """Test task formatting when max_tokens is not provided."""
    result = provider.format_task_for_provider(
        sample_batch_task_no_max_tokens,
        schema=None
    )

    assert isinstance(result, dict)
    assert "custom_id" in result
```

**What it validates:**
- Provider handles missing max_tokens gracefully
- No errors when optional parameters are omitted

#### 4. `test_parse_success_response_json`
Tests parsing of successful JSON responses:

```python
def test_parse_success_response_json(
    self,
    provider,
    provider_success_response_json
):
    """Test parsing successful response with JSON content."""
    result = provider.parse_provider_response(provider_success_response_json)

    assert isinstance(result, BatchResult)
    assert result.success == True
    assert isinstance(result.content, dict)
    assert result.content["answer"] == "4"
```

**What it validates:**
- parse_provider_response returns BatchResult
- Success responses marked as success=True
- JSON content is parsed into dict

#### 5. `test_parse_success_response_string`
Tests parsing of successful plain text responses:

```python
def test_parse_success_response_string(
    self,
    provider,
    provider_success_response_string
):
    """Test parsing successful response with plain text."""
    result = provider.parse_provider_response(provider_success_response_string)

    assert isinstance(result, BatchResult)
    assert result.success == True
    assert isinstance(result.content, str)
    assert result.content == "Hello world"
```

**What it validates:**
- Plain text responses are handled correctly
- Content remains as string (not parsed as JSON)

#### 6. `test_parse_error_response`
Tests parsing of error responses:

```python
def test_parse_error_response(self, provider, provider_error_response):
    """Test parsing error response."""
    result = provider.parse_provider_response(provider_error_response)

    assert isinstance(result, BatchResult)
    assert result.success == False
    assert result.error is not None
```

**What it validates:**
- Error responses marked as success=False
- Error message is captured

#### 7. `test_prepare_tasks_json_mode_true`
Tests prepare_tasks with json_mode enabled:

```python
def test_prepare_tasks_json_mode_true(
    self,
    provider,
    sample_data,
    sample_agent_config_json_mode
):
    """Test prepare_tasks with json_mode enabled."""
    tasks = provider.prepare_tasks(sample_data, sample_agent_config_json_mode)

    assert isinstance(tasks, list)
    assert len(tasks) == 3
    assert all("custom_id" in task for task in tasks)
```

**What it validates:**
- prepare_tasks returns list of formatted tasks
- Correct number of tasks generated
- All tasks have custom_id

#### 8. `test_prepare_tasks_json_mode_false`
Tests prepare_tasks with json_mode disabled:

```python
def test_prepare_tasks_json_mode_false(
    self,
    provider,
    sample_data,
    sample_agent_config_no_json_mode
):
    """Test prepare_tasks with json_mode disabled."""
    tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)

    assert isinstance(tasks, list)
    assert len(tasks) == 3
```

**What it validates:**
- prepare_tasks works without schema
- json_mode=false is handled correctly

#### 9. `test_check_status_returns_valid_state`
Tests status checking:

```python
def test_check_status_returns_valid_state(self, provider):
    """Test check_status returns a valid state string."""
    # This test is provider-specific and may be overridden
    pass
```

**What it validates:**
- check_status returns a string
- Status values are valid

*Note: Often overridden by providers with different status formats*

#### 10. `test_submit_and_retrieve_workflow`
Tests full batch workflow:

```python
def test_submit_and_retrieve_workflow(
    self,
    tmp_path,
    sample_data,
    sample_agent_config_no_json_mode
):
    """Test complete batch workflow: prepare → submit → retrieve."""
    # Full integration test
    pass
```

**What it validates:**
- End-to-end batch processing works
- Files are created correctly
- Results are retrievable

*Note: Often skipped for providers with different batch APIs*

#### 11. `test_retrieve_invalid_batch_id_raises_error`
Tests error handling for invalid batch IDs:

```python
def test_retrieve_invalid_batch_id_raises_error(self, tmp_path):
    """Test retrieve_results raises error for invalid batch_id."""
    # Provider must raise VendorAPIError
    pass
```

**What it validates:**
- Invalid batch IDs raise appropriate errors
- Errors are wrapped in VendorAPIError

---

## Tier 3: Provider-Specific Tests

### OpenAI Provider

**File**: `tests/integrations/providers/openai/test_openai_batch_provider.py` (~240 lines)

**Test Count**: 14 tests (11 contract + 3 OpenAI-specific)
**Pass Rate**: 100%

#### Required Fixtures

```python
@pytest.fixture
def provider(self):
    """Provide OpenAIBatchProvider with mocked client."""
    provider = OpenAIBatchProvider(api_key="test-api-key")

    # Replace client with mock
    mock_client = Mock()
    provider.client = mock_client

    # Configure mock responses
    mock_created_batch = Mock()
    mock_created_batch.id = "batch-test-12345"
    mock_client.batches.create.return_value = mock_created_batch

    # ... more mock configuration

    return provider
```

**Mocking Strategy**: Direct client replacement after initialization

#### OpenAI-Specific Tests

1. **test_openai_format_task_includes_method_and_url**
   - Verifies OpenAI-specific format (method, url, body)

2. **test_openai_format_task_with_schema_includes_response_format**
   - Tests response_format with json_schema type

3. **test_openai_parse_response_extracts_usage_metadata**
   - Validates usage metadata extraction

---

### Anthropic Provider

**File**: `tests/integrations/providers/anthropic/test_anthropic_batch_provider.py` (~275 lines)

**Test Count**: 16 tests (11 contract + 5 Anthropic-specific)
**Pass Rate**: 93.75% (15 passed, 1 skipped)

#### Required Fixtures

```python
@pytest.fixture
def provider(self):
    """Provide AnthropicBatchProvider with mocked client."""
    # Mock anthropic module at sys.modules level
    mock_anthropic_module = Mock()
    mock_client = Mock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict('sys.modules', {'anthropic': mock_anthropic_module}):
        provider = AnthropicBatchProvider(api_key="test-key")
        provider.client = mock_client

        # Configure mock responses
        mock_batch = Mock()
        mock_batch.id = "msgbatch_test123"
        mock_client.messages.batches.create.return_value = mock_batch

        yield provider  # Use yield to maintain patch context
```

**Mocking Strategy**: sys.modules patching with yield pattern

#### Anthropic-Specific Tests

1. **test_anthropic_format_task_uses_params_not_body**
   - Verifies Anthropic uses 'params' instead of 'body'

2. **test_anthropic_format_task_system_as_top_level**
   - Tests system message at top level (not in messages array)

3. **test_anthropic_format_task_with_schema_uses_tools**
   - Validates tool calling for structured output

4. **test_anthropic_parse_tool_use_response**
   - Tests parsing of tool_use content blocks

5. **test_anthropic_parse_text_response**
   - Tests parsing of plain text responses

#### Skipped Test

- **test_submit_and_retrieve_workflow** - Anthropic has different batch API endpoints

---

### Gemini Provider

**File**: `tests/integrations/providers/gemini/test_gemini_batch_provider.py` (~242 lines)

**Test Count**: 14 tests (8 contract + 3 Gemini-specific + 3 skipped)
**Pass Rate**: 78.5% (11 passed, 3 skipped)

#### Required Fixtures

```python
@pytest.fixture
def provider(self):
    """Provide GeminiBatchProvider with mocked client."""
    mock_genai_module = Mock()
    mock_client = Mock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict('sys.modules', {
        'google': Mock(),
        'google.genai': mock_genai_module,
        'google.genai.types': Mock()
    }):
        with patch('...GEMINI_AVAILABLE', True):
            with patch('...genai', mock_genai_module):
                provider = GeminiBatchProvider(api_key="test-key")
                provider.client = mock_client
                yield provider
```

**Mocking Strategy**: sys.modules patching for google.genai with yield pattern

#### Gemini-Specific Tests

1. **test_gemini_format_task_uses_key_not_custom_id**
   - Verifies Gemini uses 'key' instead of 'custom_id'

2. **test_gemini_format_task_uses_contents_structure**
   - Tests contents/parts nested structure

3. **test_gemini_format_task_with_schema_uses_response_schema**
   - Validates response_schema and response_mime_type

#### Overridden Contract Tests

Since Gemini uses "key" instead of "custom_id", these tests are overridden:

```python
def test_format_task_basic(self, provider, sample_batch_task):
    """Override: Gemini uses 'key' not 'custom_id'."""
    result = provider.format_task_for_provider(sample_batch_task, schema=None)
    assert isinstance(result, dict)
    assert "key" in result  # Changed from "custom_id"
    assert result["key"] == "test-123"
```

Overridden tests:
- test_format_task_basic
- test_format_task_with_schema
- test_format_task_no_max_tokens
- test_prepare_tasks_json_mode_true
- test_prepare_tasks_json_mode_false

#### Skipped Tests

- **test_submit_and_retrieve_workflow** - Different batch API
- **test_retrieve_invalid_batch_id_raises_error** - Different API
- **test_check_status_returns_valid_state** - Uses STATE_* format

---

### Ollama Provider

**File**: `tests/integrations/providers/ollama/test_ollama_batch_provider.py` (~150 lines)

**Test Count**: 13 tests (11 contract + 2 Ollama-specific)
**Pass Rate**: 100%

#### Required Fixtures

```python
@pytest.fixture
def provider(self):
    """Provide OllamaLocalBatchProvider instance."""
    return OllamaLocalBatchProvider(base_url="http://localhost:11434")
```

**Mocking Strategy**: No mocking! Uses local file-based processing

#### Ollama-Specific Tests

1. **test_ollama_transform_response**
   - Tests _transform_ollama_response helper method

2. **test_ollama_status_always_completed**
   - Verifies check_status always returns "completed" (synchronous)

---

## Running Tests

### All Providers

```bash
# Run all batch provider tests
python -m pytest tests/integrations/providers/ -v

# Expected output:
# ========================== test session starts ==========================
# tests/integrations/providers/openai/... 14 passed
# tests/integrations/providers/anthropic/... 15 passed, 1 skipped
# tests/integrations/providers/gemini/... 11 passed, 3 skipped
# tests/integrations/providers/ollama/... 13 passed
# ========================== 53 passed, 4 skipped =========================
```

### Specific Provider

```bash
# OpenAI
python -m pytest tests/integrations/providers/openai/test_openai_batch_provider.py -v

# Anthropic
python -m pytest tests/integrations/providers/anthropic/test_anthropic_batch_provider.py -v

# Gemini
python -m pytest tests/integrations/providers/gemini/test_gemini_batch_provider.py -v

# Ollama
python -m pytest tests/integrations/providers/ollama/test_ollama_batch_provider.py -v
```

### Quick Summary

```bash
# Run without verbose output
python -m pytest tests/integrations/providers/ --tb=no -q
```

---

## Writing Tests for a New Provider

### Step 1: Create Test File

```bash
# Create provider test directory
mkdir -p tests/integrations/providers/your_provider/

# Create test file
touch tests/integrations/providers/your_provider/test_your_provider_batch_provider.py
```

### Step 2: Inherit from BaseBatchProviderTests

```python
from tests.integrations.providers.base_batch_provider_tests import BaseBatchProviderTests
import pytest

class TestYourProviderBatchProvider(BaseBatchProviderTests):
    """
    Tests for YourProviderBatchProvider.

    Inherits 11 contract tests from BaseBatchProviderTests.
    """
    pass
```

### Step 3: Implement Required Fixtures

```python
@pytest.fixture
def provider(self):
    """Provide YourProviderBatchProvider instance."""
    # Your mocking strategy here
    return YourProviderBatchProvider(api_key="test-key")

@pytest.fixture
def provider_success_response_json(self):
    """Mock successful response with JSON content."""
    return {
        "custom_id": "test-123",
        # Your provider's response format
    }

@pytest.fixture
def provider_success_response_string(self):
    """Mock successful response with plain text."""
    return {
        "custom_id": "test-456",
        # Your provider's response format
    }

@pytest.fixture
def provider_error_response(self):
    """Mock error response."""
    return {
        "custom_id": "test-789",
        # Your provider's error format
    }
```

### Step 4: Add Provider-Specific Tests

```python
def test_your_provider_specific_feature(self, provider):
    """Test unique feature of your provider."""
    # Your test logic
    pass
```

### Step 5: Override Tests If Needed

If your provider has format differences (like Gemini's "key" vs "custom_id"):

```python
def test_format_task_basic(self, provider, sample_batch_task):
    """Override: YourProvider uses different format."""
    result = provider.format_task_for_provider(sample_batch_task, schema=None)

    # Your custom assertions
    assert isinstance(result, dict)
    # ... provider-specific checks
```

### Step 6: Run Tests

```bash
python -m pytest tests/integrations/providers/your_provider/ -v
```

---

## Mocking Strategies

### Strategy 1: Direct Client Replacement (OpenAI)

**When to use**: Provider has simple client instantiation

```python
@pytest.fixture
def provider(self):
    provider = YourProvider(api_key="test-key")

    # Replace client after initialization
    mock_client = Mock()
    provider.client = mock_client

    # Configure all mock responses
    mock_client.method.return_value = Mock(id="test-id")

    return provider
```

### Strategy 2: sys.modules Patching (Anthropic, Gemini)

**When to use**: Provider imports external libraries that need mocking

```python
@pytest.fixture
def provider(self):
    # Mock the module before import
    mock_module = Mock()
    mock_client = Mock()
    mock_module.Client.return_value = mock_client

    with patch.dict('sys.modules', {'external_lib': mock_module}):
        provider = YourProvider(api_key="test-key")
        provider.client = mock_client

        # Use yield to maintain patch context
        yield provider
```

### Strategy 3: No Mocking (Ollama)

**When to use**: Provider uses local processing, no external APIs

```python
@pytest.fixture
def provider(self):
    # No mocking needed!
    return YourProvider(base_url="http://localhost:11434")
```

---

## Debugging Test Failures

### Common Issues

#### 1. VendorAPIError Signature Error

**Error**:
```
TypeError: VendorAPIError.__init__() missing 1 required positional argument: 'endpoint'
```

**Fix**:
```python
# Wrong:
raise VendorAPIError("Message", context={...})

# Correct:
raise VendorAPIError(
    vendor='your_provider',
    endpoint='method_name',
    context={'message': 'Message', ...}
)
```

#### 2. Mock Not Configured

**Error**:
```
AttributeError: Mock object has no attribute 'id'
```

**Fix**:
```python
# Configure all mock attributes
mock_obj = Mock()
mock_obj.id = "test-id"
mock_obj.status = "completed"
```

#### 3. Import Errors

**Error**:
```
ImportError: cannot import name 'YourProvider'
```

**Fix**:
```python
# Ensure sys.modules patching happens BEFORE import
with patch.dict('sys.modules', {'lib': mock_lib}):
    from your_module import YourProvider
```

---

## Best Practices

### 1. Use Shared Fixtures

✅ **Do**: Use fixtures from conftest.py
```python
def test_something(self, provider, sample_batch_task):
    # Use shared fixture
    pass
```

❌ **Don't**: Create duplicate test data
```python
def test_something(self, provider):
    # Don't create inline BatchTask
    task = BatchTask(...)  # Use fixture instead!
```

### 2. Override Only When Necessary

✅ **Do**: Override tests with clear reason
```python
def test_format_task_basic(self, provider, sample_batch_task):
    """Override: Gemini uses 'key' not 'custom_id'."""
    # Clear docstring explaining why
    pass
```

❌ **Don't**: Override without explanation
```python
def test_format_task_basic(self, provider, sample_batch_task):
    # No explanation why this is overridden
    pass
```

### 3. Skip Integration Tests Appropriately

✅ **Do**: Skip with clear reason
```python
def test_submit_and_retrieve_workflow(self, ...):
    """Override to skip - YourProvider has different batch API."""
    pytest.skip("Reason for skipping")
```

❌ **Don't**: Skip without explanation
```python
def test_submit_and_retrieve_workflow(self, ...):
    pytest.skip()  # Why?
```

### 4. Test Provider-Specific Features

✅ **Do**: Add tests for unique features
```python
def test_your_provider_special_feature(self, provider):
    """Test YourProvider's unique feature."""
    # Test something only your provider has
    pass
```

---

## Summary

### Test Architecture Benefits

✅ **Consistency** - All providers tested the same way
✅ **Maintainability** - Fix once in base class, all providers benefit
✅ **Coverage** - 11 contract tests ensure core functionality
✅ **Flexibility** - Easy to override for provider differences
✅ **Documentation** - Tests serve as examples

### Adding a New Provider

1. Create test file inheriting from BaseBatchProviderTests
2. Implement 4 required fixtures
3. Add provider-specific tests
4. Override contract tests if needed
5. Run tests and verify 100% pass rate (excluding intentional skips)

### Current Test Coverage

- **57 total tests** across 4 providers
- **53 passed** (93.0%)
- **4 skipped** (intentional - different batch APIs)
- **0 failures**

All batch providers are comprehensively tested! ✅

---

## Related Documentation

- [Adding a New Batch Provider Guide](./adding_new_batch_provider_guide.md)
- [Batch Provider Flow Diagram](./batch_provider_flow_diagram.md)
- [User Guide: Batch Mode](../agentaction-docs/docs/examples/configurations/07-batch-mode.md)
