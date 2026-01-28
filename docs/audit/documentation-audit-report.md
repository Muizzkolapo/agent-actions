# Documentation Audit Report

**Date:** 2026-01-28
**Scope:** `docs.agent-actions/` documentation vs actual implementation
**Status:** Comprehensive audit complete

---

## Executive Summary

This audit identified **32 documentation issues** across the `docs.agent-actions` directory:
- **8 Critical issues** - Will cause errors for users following docs
- **12 High-priority issues** - Significant inaccuracies or missing features
- **12 Medium/Low issues** - Minor inconsistencies or enhancements needed

---

## Critical Issues (Fix Immediately)

### 1. UDF Decorator: `input_type` Parameter Does Not Exist

**Location:** `docs/reference/tools/udf-decorator.md` (lines 42-46)

**Documentation claims:**
```python
@udf_tool(input_type=MyInput, output_type=MyOutput)
def my_function(data, **kwargs):
```

**Reality:** The `@udf_tool` decorator does NOT accept `input_type`. Users will get:
```
TypeError: udf_tool() got an unexpected keyword argument 'input_type'
```

**Actual signature:**
```python
def udf_tool(
    func: Optional[Callable] = None,
    *,
    output_type: Optional[type] = None,
    output_schema: Optional[str] = None,
    granularity: Granularity = Granularity.RECORD,
)
```

**Fix:** Remove all `input_type` references; clarify input schema comes from workflow YAML `context_scope`.

---

### 2. UDF Decorator: Wrong Import Paths

**Location:** `docs/reference/tools/udf-decorator.md` (lines 176, 311-312)

**Documentation shows:**
```python
from agent_actions.configuration.new_format_schema import Granularity
from agent_actions.utilities.udf_management.udf_registry import FileUDFResult
```

**Correct imports:**
```python
from agent_actions.config.schema import Granularity
from agent_actions import FileUDFResult
# OR
from agent_actions.utils.udf_management.registry import FileUDFResult
```

**Fix:** Update all import paths throughout UDF documentation.

---

### 3. Guard Configuration: Wrong Field Names

**Location:** `docs/reference/execution/guards.md`

**Documentation shows:**
```yaml
guard:
  condition: "expression"
  on_false: "skip"
```

**Actual implementation uses:**
```yaml
guard:
  clause: "expression"
  behavior: "skip"
```

**Fix:** Update all guard examples to use `clause` and `behavior`.

---

### 4. Batch CLI: Commands Documented But Not Implemented

**Location:** `docs/cli-reference/batch.md` (lines 35-149)

**Documented but NOT implemented:**
- `batch retry` command
- `batch chain-status` command

**Actually implemented:**
- `batch status` ✓
- `batch retrieve` ✓

**Fix:** Either implement the missing commands or remove them from documentation.

---

### 5. Run Command: Wrong Flag Names

**Location:** `docs/cli-reference/run.md` (lines 48-52)

**Documentation shows:**
```bash
agent-actions run --parallel
agent-actions run --no-parallel
```

**Actual implementation:**
```bash
agent-actions run --execution-mode parallel
agent-actions run --execution-mode sequential
agent-actions run --execution-mode auto
```

**Fix:** Update run command documentation to use `--execution-mode` with choices.

---

### 6. Status Command: Missing Required Parameter

**Location:** `docs/cli-reference/utilities.md` (lines 115-127)

**Documentation suggests:** Simple command with no required args

**Actual implementation:** Requires `-a/--agent` parameter

**Fix:** Document the required `-a/--agent` parameter.

---

### 7. Init Command: Missing Options

**Location:** `docs/cli-reference/utilities.md` (lines 48-73)

**Documentation missing:**
- `-o, --output-dir` option
- `-t, --template` option
- `-f, --force` flag

**Fix:** Document all init command options.

---

### 8. Inspect Command Group: Not Documented At All

**Location:** Missing from `docs/cli-reference/`

**Fully implemented but undocumented:**
- `inspect dependencies [-a] [--action] [--json]`
- `inspect graph [-a] [--json]`
- `inspect action [-a] <action_name> [--json]`

**Fix:** Create new `inspect.md` documentation file.

---

## High-Priority Issues

### 9. Clean Command: Not Documented

**Location:** Missing from `docs/cli-reference/utilities.md`

**Implemented in:** `agent_actions/cli/test.py`

**Options:**
- `-a, --agent` (required)
- `-f, --force` (flag)
- `--all` (removes all directories)

---

### 10. Configuration: RepromptConfig Default Value Mismatch

**Location:** `docs/reference/validation/reprompting.md`

**Documentation says:** `max_attempts` defaults to `3`
**Schema says:** `max_attempts: int = Field(default=2)`

---

### 11. Configuration: Undocumented Fields in ActionConfig

**Location:** `docs/reference/configuration/index.md`

**Not documented:**
- `policy` - Execution policy
- `idempotency_key` - Idempotency key template
- `versions` - Version configuration
- `version_consumption` - Version output consumption
- `retry` - Retry configuration object
- `drops` - Fields to exclude (only in context-scope.md)
- `observe` - Passthrough fields (only in context-scope.md)

---

### 12. Configuration: DefaultsConfig Fields Mismatch

**Location:** `docs/reference/configuration/defaults.md`

**Documented but NOT in DefaultsConfig schema:**
- `api_key`
- `is_operational`
- `prompt_debug`
- `few_shot`
- `context_scope`

**In schema but NOT in defaults.md table:**
- `drops`
- `observe`

---

### 13. Granularity: Case Sensitivity

**Location:** `docs/reference/execution/granularity.md` (line 25-26)

**Documentation shows:** `granularity: Record` (capitalized)
**Implementation uses:** `granularity: record` (lowercase)

---

### 14. UDF: `output_schema` Parameter Undocumented

**Location:** `docs/reference/tools/udf-decorator.md`

**Not documented but fully implemented:**
```python
@udf_tool(output_schema="ValidationResult")  # Load schema from file
```

---

### 15. Docs Command: Subcommands Not Documented

**Location:** `docs/cli-reference/utilities.md` (lines 97-110)

**Implemented subcommands not documented:**
- `docs generate [--output]`
- `docs serve [--port] [--artefact]`
- `docs test [--test] [--port]`
- `docs dev`

---

### 16. Global Flag: `--quiet` Not Documented

**Location:** `docs/cli-reference/index.md`

**Implemented:** `-q, --quiet` flag
**Status:** Not in documentation

---

### 17. Context: Reserved Namespaces Incomplete

**Location:** `docs/reference/context/seed-data.md`

**Implementation defines 8 reserved namespaces:**
- `source`, `loop`, `workflow`, `seed`, `prompt`, `schema`, `context_scope`, `action`

**Documentation only partially lists these.**

---

### 18. Output Format: `chunk_info` Field Not Documented

**Location:** `docs/reference/data-io/output-format.md`

**Implementation excludes `chunk_info` from content extraction but documentation doesn't mention this field.**

---

### 19. UDF: Programmatic API Undocumented

**Location:** `docs/reference/tools/`

**Public functions not documented:**
- `get_udf(func_name: str) -> Callable`
- `get_udf_metadata(func_name: str) -> Dict[str, Any]`
- `list_udfs() -> List[Dict[str, Any]]`
- `clear_registry() -> None`

---

### 20. Guard: Undocumented Fields

**Location:** `docs/reference/execution/guards.md`

**Not documented:**
- `passthrough_on_error` field
- `scope` field

---

## Medium/Low Priority Issues

### 21. UDF CLI: `--verbose` Option Not in Table

**Location:** `docs/cli-reference/udfs.md` (lines 88-93)

### 22. Reprompt Description Inaccurate

**Location:** `docs/reference/configuration/index.md`

**Says:** "Retry mode: basic, smart, thorough"
**Reality:** RepromptConfig is an object with `validation`, `max_attempts`, `on_exhausted`

### 23. Configuration Fields Missing from Index

**Location:** `docs/reference/configuration/index.md`

Not in ActionConfig Fields table but in examples:
- `json_mode`
- `run_mode`
- `temperature`
- `max_tokens`

### 24. Context Scope: static_data vs seed_data Confusion

**Location:** `docs/reference/context/context-scope.md`

Docstring mentions `static_data` but YAML config key is `seed_data`.

### 25. Run Command: `--static-typing` Not Documented

**Location:** `docs/cli-reference/run.md`

**Implemented:** `--static-typing/--no-static-typing`

### 26-32. Minor Wording/Clarity Issues

- Various minor inconsistencies in examples
- Some deprecated terminology still present
- Missing cross-references between related docs

---

## Summary by File

| File | Critical | High | Medium |
|------|----------|------|--------|
| `cli-reference/run.md` | 1 | 1 | 1 |
| `cli-reference/batch.md` | 1 | 0 | 0 |
| `cli-reference/utilities.md` | 2 | 1 | 0 |
| `cli-reference/index.md` | 0 | 1 | 0 |
| `cli-reference/udfs.md` | 0 | 0 | 1 |
| `reference/tools/udf-decorator.md` | 2 | 2 | 0 |
| `reference/execution/guards.md` | 1 | 1 | 0 |
| `reference/execution/granularity.md` | 0 | 1 | 0 |
| `reference/configuration/index.md` | 0 | 1 | 2 |
| `reference/configuration/defaults.md` | 0 | 1 | 0 |
| `reference/validation/reprompting.md` | 0 | 1 | 0 |
| `reference/context/seed-data.md` | 0 | 1 | 0 |
| `reference/data-io/output-format.md` | 0 | 1 | 0 |
| **NEW: cli-reference/inspect.md** | 1 | 0 | 0 |

---

## Recommended Priority Order

1. **Week 1:** Fix all Critical issues (8 items)
   - UDF decorator documentation complete rewrite
   - Guard field names correction
   - CLI command fixes (batch, run, status, init)
   - Add inspect command documentation

2. **Week 2:** Fix High-priority issues (12 items)
   - Configuration documentation alignment
   - Add missing command options
   - Document new features

3. **Week 3:** Address Medium/Low issues (12 items)
   - Minor corrections and clarifications
   - Cross-reference improvements

---

## Files to Create

1. `docs/cli-reference/inspect.md` - New file for inspect command group

## Files to Significantly Revise

1. `docs/reference/tools/udf-decorator.md` - Remove input_type, fix imports
2. `docs/cli-reference/run.md` - Fix --execution-mode
3. `docs/cli-reference/batch.md` - Remove non-existent commands
4. `docs/reference/execution/guards.md` - Fix field names
5. `docs/reference/configuration/index.md` - Add missing fields
6. `docs/reference/configuration/defaults.md` - Align with schema
