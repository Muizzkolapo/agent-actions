# Batch Provider Abstraction Opportunities

**Principle**: "Abstract what we own, not what we control"

We should extract **common batch workflow code** (our code) into reusable base implementations, while keeping **vendor-specific API calls** (their code) in each provider.

---

## Current Duplication Analysis

### 1. Batch Directory Setup (Duplicated in ALL providers)

#### OpenAI:
```python
# Create batch directory
if output_directory:
    batch_dir = Path(output_directory) / "batch"
else:
    batch_dir = Path.cwd() / "batch"

ensure_directory_exists(batch_dir)
```

#### Anthropic:
```python
# Create batch directory for saving reference files
if output_directory:
    batch_dir = Path(output_directory) / "batch"
else:
    batch_dir = Path.cwd() / "batch"

ensure_directory_exists(batch_dir)
```

#### Ollama:
```python
# Setup directories
if output_directory:
    batch_dir = Path(output_directory) / "batch"
else:
    batch_dir = Path.cwd() / "batch"

ensure_directory_exists(batch_dir)
```

**Lines duplicated**: ~6 lines × 4 providers = **24 lines**

---

### 2. JSONL File Writing (Duplicated in OpenAI, Ollama)

#### OpenAI:
```python
# Write tasks to JSONL file
file_name = f"{Path(batch_name).stem}_batch_input.jsonl"
file_path = batch_dir / file_name

with open(file_path, 'w') as file:
    for task in tasks:
        file.write(json.dumps(task) + '\n')

print(f"OpenAI batch file created at: {file_path}")
```

#### Ollama:
```python
# Write input JSONL file
input_file_name = f"{Path(batch_name).stem}_ollama_batch_input.jsonl"
input_file_path = batch_dir / input_file_name

with open(input_file_path, 'w') as f:
    for task in tasks:
        f.write(json.dumps(task) + '\n')

print(f"Ollama batch input file: {input_file_path}")
```

**Lines duplicated**: ~8 lines × 2 providers = **16 lines**

---

### 3. JSONL File Reading (Duplicated in OpenAI, Ollama)

#### OpenAI:
```python
# Parse JSONL results
batch_results = []
for line in result_content.decode('utf-8').split('\n'):
    if line.strip():
        try:
            raw_result = json.loads(line)
            batch_result = self.parse_provider_response(raw_result)
            batch_results.append(batch_result)
        except json.JSONDecodeError as e:
            print(f"Error parsing result line: {e}")
            continue

return batch_results
```

#### Ollama:
```python
# Parse results
batch_results = []
with open(output_file_path, 'r') as f:
    for line_num, line in enumerate(f, 1):
        if line.strip():
            try:
                raw_result = json.loads(line)
                batch_result = self.parse_provider_response(raw_result)
                batch_results.append(batch_result)
            except json.JSONDecodeError as e:
                print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                batch_results.append(BatchResult(
                    custom_id=f"error_line_{line_num}",
                    content=None,
                    success=False,
                    error=f"JSON parsing error: {e}",
                    metadata={"line_number": line_num}
                ))

return batch_results
```

**Lines duplicated**: ~15 lines × 2 providers = **30 lines**

---

### 4. Batch ID Generation (Only Ollama, but should be standardized)

#### Ollama:
```python
# Generate batch ID
batch_id = f"batch_{uuid.uuid4().hex}"
```

This should be standardized if needed, or rely on vendor-provided IDs.

---

### 5. Optional Parameter Handling (Varies by provider)

#### OpenAI:
```python
if "temperature" in batch_task.model_config:
    temp_value = batch_task.model_config["temperature"]
    if model_name not in default_temp_only_models or temp_value == 1:
        if model_name not in default_temp_only_models:
            body["temperature"] = temp_value

if "max_tokens" in batch_task.model_config and batch_task.model_config["max_tokens"] is not None:
    body["max_tokens"] = batch_task.model_config["max_tokens"]
```

#### Ollama:
```python
max_tokens = batch_task.model_config.get("max_tokens")
if max_tokens is not None:
    body["max_tokens"] = max_tokens
```

#### Anthropic:
```python
if "temperature" in batch_task.model_config:
    params["temperature"] = batch_task.model_config["temperature"]
```

**Note**: This varies by vendor requirements, but pattern could be abstracted.

---

## Proposed Abstraction: Base Helper Methods

Create helper methods in the `BatchProvider` base class:

### File: `agent_actions/integrations/providers/base.py`

```python
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from agent_actions.core.utils.path_utils import ensure_directory_exists


class BatchProvider(ABC):
    """Abstract base class for batch providers."""

    # ============================================================================
    # ABSTRACT METHODS (Must be implemented by each provider)
    # ============================================================================

    @abstractmethod
    def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Prepare tasks from data. Provider-specific."""
        pass

    @abstractmethod
    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Format single task for vendor API. Provider-specific."""
        pass

    @abstractmethod
    def submit_batch(self, tasks: List[Dict[str, Any]], batch_name: str, output_directory: Optional[str] = None) -> str:
        """Submit batch to vendor. Provider-specific."""
        pass

    @abstractmethod
    def check_status(self, batch_id: str) -> str:
        """Check batch status from vendor. Provider-specific."""
        pass

    @abstractmethod
    def retrieve_results(self, batch_id: str, output_directory: Optional[str] = None) -> List[BatchResult]:
        """Retrieve results from vendor. Provider-specific."""
        pass

    @abstractmethod
    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """Parse vendor response to BatchResult. Provider-specific."""
        pass

    # ============================================================================
    # CONCRETE HELPER METHODS (Reusable across all providers)
    # ============================================================================

    def _get_batch_directory(self, output_directory: Optional[str] = None) -> Path:
        """
        Get or create the batch directory.

        This is OUR code - same for all providers.

        Args:
            output_directory: Optional output directory

        Returns:
            Path to batch directory
        """
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"

        ensure_directory_exists(batch_dir)
        return batch_dir

    def _write_jsonl_file(
        self,
        tasks: List[Dict[str, Any]],
        batch_dir: Path,
        batch_name: str,
        provider_name: str
    ) -> Path:
        """
        Write tasks to JSONL file.

        This is OUR code - same for all providers that use JSONL.

        Args:
            tasks: List of task dictionaries
            batch_dir: Directory to write to
            batch_name: Base name for the file
            provider_name: Provider name for file suffix (e.g., "openai", "ollama")

        Returns:
            Path to created file
        """
        file_name = f"{Path(batch_name).stem}_{provider_name}_batch_input.jsonl"
        file_path = batch_dir / file_name

        with open(file_path, 'w') as file:
            for task in tasks:
                file.write(json.dumps(task) + '\n')

        print(f"{provider_name.title()} batch input file: {file_path}")
        return file_path

    def _read_jsonl_file(self, file_path: Path) -> List[BatchResult]:
        """
        Read JSONL file and parse to BatchResults.

        This is OUR code - same for all providers that use JSONL.

        Args:
            file_path: Path to JSONL file

        Returns:
            List of BatchResult objects
        """
        batch_results = []

        if not file_path.exists():
            from agent_actions.core.exceptions import VendorAPIError
            raise VendorAPIError(
                "Batch output file not found",
                context={
                    'expected_path': str(file_path),
                    'vendor': self.__class__.__name__
                }
            )

        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                        # Create error result for unparseable lines
                        batch_results.append(BatchResult(
                            custom_id=f"error_line_{line_num}",
                            content=None,
                            success=False,
                            error=f"JSON parsing error: {e}",
                            metadata={"line_number": line_num, "raw_line": line[:100]}
                        ))

        return batch_results

    def _add_optional_param(
        self,
        target: Dict[str, Any],
        key: str,
        value: Any,
        default: Any = None
    ) -> None:
        """
        Add parameter to target dict only if value is not None.

        This is OUR code - standardizes optional parameter handling.

        Args:
            target: Dict to add parameter to
            key: Parameter key
            value: Parameter value (only added if not None)
            default: Default value to use if value is None and this is provided
        """
        if value is not None:
            target[key] = value
        elif default is not None:
            target[key] = default
```

---

## Updated Provider Implementations

### OpenAI Provider (After Abstraction)

```python
class OpenAIBatchProvider(BatchProvider):
    """OpenAI batch provider using base abstractions."""

    def submit_batch(self, tasks, batch_name, output_directory=None) -> str:
        # ✅ Use base method for directory setup
        batch_dir = self._get_batch_directory(output_directory)

        # ✅ Use base method for JSONL writing
        file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "openai")

        # ❌ Vendor-specific: Upload to OpenAI (THEIR code, we don't own)
        batch_file = self.client.files.create(
            file=open(file_path, "rb"),
            purpose="batch"
        )

        # ❌ Vendor-specific: Create batch job (THEIR code)
        batch_job = self.client.batches.create(
            input_file_id=batch_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )

        return batch_job.id

    def retrieve_results(self, batch_id, output_directory=None) -> List[BatchResult]:
        # ❌ Vendor-specific: Retrieve from OpenAI API (THEIR code)
        batch_job = self.client.batches.retrieve(batch_id)
        result_content = self.client.files.content(batch_job.output_file_id).content

        # ✅ Use base method for JSONL parsing
        # But wait - we need to parse from bytes content, not file...
        # So we still need custom logic here

        batch_results = []
        for line in result_content.decode('utf-8').split('\n'):
            if line.strip():
                try:
                    raw_result = json.loads(line)
                    batch_result = self.parse_provider_response(raw_result)
                    batch_results.append(batch_result)
                except json.JSONDecodeError as e:
                    print(f"Error parsing result line: {e}")
                    continue

        return batch_results
```

### Ollama Provider (After Abstraction)

```python
class OllamaLocalBatchProvider(BatchProvider):
    """Ollama local provider using base abstractions."""

    def submit_batch(self, tasks, batch_name, output_directory=None) -> str:
        # ✅ Use base method for directory setup
        batch_dir = self._get_batch_directory(output_directory)

        # Generate batch ID (local, not from vendor)
        batch_id = f"batch_{uuid.uuid4().hex}"

        # ✅ Use base method for JSONL writing
        input_file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "ollama")

        # ❌ Provider-specific: Process with Ollama (OUR choice to use Ollama)
        results = []
        for task in tasks:
            # ... process with Ollama ...

        # Write output JSONL
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"
        with open(output_file_path, 'w') as f:
            for result in results:
                f.write(json.dumps(result) + '\n')

        return batch_id

    def retrieve_results(self, batch_id, output_directory=None) -> List[BatchResult]:
        # ✅ Use base method for directory
        batch_dir = self._get_batch_directory(output_directory)

        # Find output file
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        # ✅ Use base method for JSONL reading
        return self._read_jsonl_file(output_file_path)
```

### Anthropic Provider (After Abstraction)

```python
class AnthropicBatchProvider(BatchProvider):
    """Anthropic provider using base abstractions."""

    def submit_batch(self, tasks, batch_name, output_directory=None) -> str:
        # ✅ Use base method for directory setup
        batch_dir = self._get_batch_directory(output_directory)

        # Save tasks as JSON (Anthropic uses JSON, not JSONL)
        file_name = f"{Path(batch_name).stem}_anthropic_batch_input.json"
        file_path = batch_dir / file_name
        with open(file_path, 'w') as file:
            json.dump({"requests": tasks}, file, indent=2)

        print(f"Anthropic batch input saved at: {file_path}")

        # ❌ Vendor-specific: Submit to Anthropic API (THEIR code)
        batch_response = self.client.messages.batches.create(requests=tasks)

        return batch_response.id
```

---

## Code Reduction Summary

| Component | Before | After | Saved |
|-----------|--------|-------|-------|
| Directory setup | 6 lines × 4 = 24 | 1 line × 4 = 4 | **20 lines** |
| JSONL writing | 8 lines × 2 = 16 | 1 line × 2 = 2 | **14 lines** |
| JSONL reading | 15 lines × 2 = 30 | 1 line × 1 = 1 | **29 lines** |
| Optional params | ~10 lines × 3 = 30 | 1-2 lines × 3 = 6 | **24 lines** |
| **Total** | **~100 lines** | **~15 lines** | **~85 lines (85%)** |

Plus: **Consistent behavior** across all providers!

---

## Implementation Plan

### Step 1: Add Helper Methods to Base Class
**File**: `agent_actions/integrations/providers/base.py`
- Add `_get_batch_directory()`
- Add `_write_jsonl_file()`
- Add `_read_jsonl_file()`
- Add `_add_optional_param()`

**Estimated time**: 20 minutes

### Step 2: Update OpenAI Provider
**File**: `agent_actions/integrations/providers/openai/provider.py`
- Replace directory setup with `self._get_batch_directory()`
- Replace JSONL writing with `self._write_jsonl_file()`
- Keep vendor API calls (file upload, batch create)

**Estimated time**: 10 minutes

### Step 3: Update Anthropic Provider
**File**: `agent_actions/integrations/providers/anthropic/provider.py`
- Replace directory setup with `self._get_batch_directory()`
- Keep JSON writing (Anthropic uses JSON, not JSONL)
- Keep vendor API calls

**Estimated time**: 5 minutes

### Step 4: Update Ollama Provider
**File**: `agent_actions/integrations/providers/ollama/provider.py`
- Replace directory setup with `self._get_batch_directory()`
- Replace JSONL writing with `self._write_jsonl_file()`
- Replace JSONL reading with `self._read_jsonl_file()`
- Remove `_update_registry()` method (not provider's responsibility)

**Estimated time**: 15 minutes

### Step 5: Update Gemini Provider (if needed)
**File**: `agent_actions/integrations/providers/gemini/provider.py`
- Apply same refactoring

**Estimated time**: 10 minutes

### Step 6: Test All Providers
- Run with each provider
- Verify batch workflows work identically

**Estimated time**: 20 minutes

**Total**: ~80 minutes

---

## Benefits

1. **DRY (Don't Repeat Yourself)**: 85% code reduction in common logic
2. **Consistency**: All providers handle files the same way
3. **Maintainability**: Fix once in base, applies to all providers
4. **Testing**: Test helpers once, reuse everywhere
5. **Clarity**: Providers focus on vendor-specific logic only

---

## Principle Validation

**"Abstract what we own, not what we control"** ✅

### We Own (Abstract):
- ✅ Directory structure (`batch/` directory)
- ✅ JSONL file format (our choice)
- ✅ File naming conventions
- ✅ Error handling patterns
- ✅ Optional parameter handling

### We Don't Control (Keep Provider-Specific):
- ❌ OpenAI API calls (`client.files.create`, `client.batches.create`)
- ❌ Anthropic API calls (`client.messages.batches.create`)
- ❌ Ollama API calls (`client.chat`)
- ❌ Response formats (each vendor returns different structure)
- ❌ Status values (each vendor has different status strings)

**Result**: Clean separation between our workflow code and vendor API code!
