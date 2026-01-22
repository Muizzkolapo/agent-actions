# TICKET-013: Remove Legacy Logging Code

**Status:** 🔲 TODO
**Priority:** Low
**Estimate:** 4-6 hours
**Labels:** logging, cleanup, tech-debt

## Description

After all events are instrumented and tested, remove the legacy logging infrastructure that's no longer needed. This ticket documents all code identified for removal through comprehensive codebase analysis.

## Prerequisites

Complete these tickets before starting cleanup:
- [ ] TICKET-009 through TICKET-012 (core event instrumentation)
- [ ] TICKET-017 through TICKET-020 (additional events)
- [ ] All tests pass with new event system
- [ ] No runtime errors in production workflows

## Deliverables

- [ ] Remove unused formatter classes
- [ ] Replace console.print with events (55 calls)
- [ ] Remove deprecated logging utilities
- [ ] Clean up legacy configuration code
- [ ] Update imports and exports
- [ ] Remove or update test files

---

## 1. FORMATTER CLASSES TO REMOVE

### File: `agent_actions/logging/formatters.py`

**Remove entirely (lines 141-318):**

#### A. HumanFormatter (lines 141-260)
- Old human-readable formatter with ANSI colors
- Only used in test file
- **Replacement:** `AgentActionsFormatter` in `events/formatters.py`

#### B. SimpleFormatter (lines 263-318)
- Simple text formatter for file output
- Only used in test file
- **Replacement:** Event-based console output via `ConsoleEventHandler`

**Keep for now:**
- **JSONFormatter (lines 12-138)** - May still be used by `StructuredLogHandler`

### File: `agent_actions/logging/__init__.py`

**Update exports (lines 31, 56-58):**
```python
# REMOVE these exports:
from agent_actions.logging.formatters import HumanFormatter, SimpleFormatter

# REMOVE from __all__:
"HumanFormatter",
"SimpleFormatter",
```

### File: `tests/test_logging/test_formatters.py`

**Remove or archive entire file (lines 1-432):**
- 217 lines testing HumanFormatter
- 138 lines testing SimpleFormatter
- 205 lines testing JSONFormatter

---

## 2. CONSOLE.PRINT CALLS TO REPLACE WITH EVENTS

### Summary
- **Total found:** 131 calls
- **To replace:** 55 calls (operational/status)
- **Keep:** 72 calls (user-facing CLI)
- **Maybe:** 4 calls (judgment required)

### A. Batch Processing Status (batch.py) - 8 calls

**File:** `agent_actions/workflow/managers/batch.py`

| Line | Current Output | Replacement Event |
|------|---------------|-------------------|
| 59 | `"[green]All batch jobs are completed..."` | `BatchProcessingCompleteEvent` |
| 61 | `"[green]✅ Processed all batch results..."` | `BatchResultsProcessedEvent` |
| 67-71 | Error messages | `BatchErrorEvent` |
| 81-84 | Passthrough completion | `BatchPassthroughEvent` |
| 86 | `"[yellow]No batch jobs found..."` | `BatchStatusEvent` |

### B. Agent Execution Status (executor.py) - 2 calls

**File:** `agent_actions/workflow/executor.py`

| Line | Current Output | Replacement Event |
|------|---------------|-------------------|
| 622 | `f"[yellow]→ {agent_name}: batch submitted[/yellow]"` | Use existing `BatchSubmittedEvent` |
| 642 | `f"[green]✓ {agent_name} ({duration:.2f}s)[/green]"` | Use existing `AgentCompleteEvent` |

### C. State Management (state.py) - 3 calls

**File:** `agent_actions/workflow/managers/state.py`

| Line | Current Output | Replacement Event |
|------|---------------|-------------------|
| 45 | `f"[dim]Loaded status for {len(self.agent_status)} agents[/dim]"` | `StatusLoadedEvent` |
| 47 | `f"[yellow]Warning: Could not load status file: {e}[/yellow]"` | `StatusLoadErrorEvent` |
| 63 | `f"[red]Error saving status: {e}[/red]"` | `StatusSaveErrorEvent` |

### D. Skip Evaluation (skip.py) - 7 calls

**File:** `agent_actions/workflow/managers/skip.py`

Replace all with `AgentSkipEvent` with appropriate reason:
- Lines 88-91: Skip condition evaluated to True
- Lines 93-95: Passed skip condition check
- Lines 135-137: Guard skip message
- Lines 187-189: Guard condition not met
- Lines 203-206: Guard passed message
- Lines 246-248: Legacy skip_if message

### E. UDF Discovery (coordinator.py) - 5 calls

**File:** `agent_actions/workflow/coordinator.py`

| Line | Current Output | Replacement Event |
|------|---------------|-------------------|
| 320 | `f"[green]✅ Discovered {total_udfs} UDF(s)[/green]"` | `UDFDiscoveryCompleteEvent` |
| 331 | `f"[cyan]🔍 Discovering UDFs in {abs_path}...[/cyan]"` | `UDFDiscoveryStartEvent` |
| 333 | `"[cyan]🔍 Discovering UDFs...[/cyan]"` | `UDFDiscoveryStartEvent` |
| 338 | `f"[green]✅ Discovered {len(registry)} UDF(s)[/green]"` | `UDFDiscoveryCompleteEvent` |
| 519 | `f"Found {total_agents} agents to run."` | Use existing `WorkflowStartEvent` |

### F. Version Correlation (output.py) - 4 calls

**File:** `agent_actions/workflow/managers/output.py`

| Lines | Current Output | Replacement Event |
|-------|---------------|-------------------|
| 456-459 | Using correlated input message | `VersionCorrelationEvent` |
| 462-465 | Fallback message | `CorrelationFallbackEvent` |
| 507-510 | Correlation setup | `CorrelationSetupEvent` |
| 519-522 | Fallback during setup | `CorrelationFallbackEvent` |

### G. Workflow Dependencies (dependency.py) - 7 calls

**File:** `agent_actions/workflow/parallel/dependency.py`

| Lines | Current Output | Replacement Event |
|-------|---------------|-------------------|
| 129-131 | Upstream workflow check | `UpstreamWorkflowCheckEvent` |
| 147-151 | Upstream already completed | `UpstreamWorkflowCachedEvent` |
| 154-157 | Executing upstream | `UpstreamWorkflowExecutionEvent` |
| 175-178 | Ready to use upstream | `UpstreamWorkflowReadyEvent` |
| 232-235 | No downstream found | `DownstreamWorkflowStatusEvent` |
| 271-273 | Downstream execution | `DownstreamWorkflowExecutionEvent` |
| 303-305 | Downstream completion | `DownstreamWorkflowCompleteEvent` |

### H. Action Executor (action_executor.py) - 6 calls

**File:** `agent_actions/workflow/parallel/action_executor.py`

| Lines | Current Output | Replacement Event |
|-------|---------------|-------------------|
| 205 | Execution plan | `ExecutionPlanEvent` |
| 211-215 | Level execution info | `ExecutionLevelStartEvent` |
| 232 | Parallel agents | `ParallelExecutionEvent` |
| 284-288 | Batch jobs submitted | `BatchJobsSubmittedEvent` |
| 312-315 | All agents complete | `ExecutionLevelCompleteEvent` |
| 346 | Action complete | `ExecutionLevelCompleteEvent` |

### I. UDF Validation Files (13+ calls)

**Files:** `agent_actions/validation/udfs.py` and `validation/validate_udfs.py`

Replace discovery/validation status messages (lines 101, 115-127)

---

## 3. DEPRECATED LOGGING UTILITIES TO REMOVE

### A. Legacy Context Injection Filter

**File:** `agent_actions/logging/filters.py`

**Remove class (lines 13-62):**
```python
class ContextInjectingFilter(logging.Filter):
    """Injects execution context into log records."""
```
**Replacement:** Event-based context system with automatic injection in `EventManager`

### B. Correlation Context (Partial Deprecation)

**File:** `agent_actions/logging/context.py`

**Mark as deprecated (lines 31-150):**
- `ExecutionContext` class
- `CorrelationContext` class

**Replacement:**
- Event metadata system (`EventMeta`)
- `EventManager.set_context()`

**Note:** Keep for backward compatibility initially, add deprecation warnings

### C. Service Logger Helpers (Gradual Migration)

**File:** `agent_actions/cli/utils/service_logger.py`

**Status:** Transitional - migrate over time to domain-specific events

Methods to eventually replace (lines 15-135):
- `log_operation_start()` → OperationStartEvent
- `log_operation_success()` → OperationCompleteEvent
- `log_operation_error()` → OperationErrorEvent
- `log_validation_start/success/error()` → ValidationEvents
- `log_file_operation()` → FileOperationEvent
- `log_config_operation()` → ConfigOperationEvent

---

## 4. LEGACY CONFIGURATION CODE

### File: `agent_actions/logging/config.py`

#### A. Remove HandlerConfig (lines 14-22)
```python
@dataclass
class HandlerConfig:
    """Handler configuration"""
    handler_type: Literal["stream", "file", "rotating"] = "stream"
    # ... rest of class
```
**Reason:** Not used by new event system

#### B. Simplify FileHandlerSettings (lines 26-34)
Remove unused properties, keep only:
- `enabled`
- `path`

#### C. Remove backward compatibility properties (lines 57-86)
```python
@property
def file_handler_enabled(self) -> bool:
def log_file_path(self) -> Optional[str]:
def file_log_level(self) -> LogLevel:
def file_max_bytes(self) -> int:
def file_backup_count(self) -> int:
def file_format(self) -> Literal["human", "json"]:
```
**Reason:** Only for backward compatibility, no longer needed

---

## 5. DEPRECATED SERVICE METHODS

### File: `agent_actions/llm/realtime/services/prompt_service.py`

**Already marked DEPRECATED (lines 10-42):**
```python
@staticmethod
def prepare_prompt(...):
    warnings.warn(
        "PromptService.prepare_prompt() is deprecated...",
        DeprecationWarning,
    )
```
**Action:** Remove after deprecation period

### File: `agent_actions/llm/realtime/services/context.py`

**Already marked DEPRECATED (lines 19-93):**
```python
@staticmethod
def build_field_context(...):
    warnings.warn(
        "ContextService.build_field_context() is deprecated...",
        DeprecationWarning,
    )
```
**Action:** Remove after deprecation period

---

## 6. MIGRATION CHECKLIST

### Phase 1: Verify Prerequisites
- [ ] All event instrumentation tickets complete (009-020)
- [ ] Run full test suite - all tests pass
- [ ] Manual smoke test of critical workflows
- [ ] Console output looks correct with new events
- [ ] JSON logs contain all expected data
- [ ] run_results.json is complete and accurate

### Phase 2: Remove Formatters (1 hour)
- [ ] Remove `HumanFormatter` from formatters.py
- [ ] Remove `SimpleFormatter` from formatters.py
- [ ] Update `__init__.py` exports
- [ ] Remove or archive `test_formatters.py`
- [ ] Run tests - verify no breakage

### Phase 3: Replace Console.Print Calls (2-3 hours)
- [ ] Replace batch.py console calls (8 calls)
- [ ] Replace executor.py console calls (2 calls)
- [ ] Replace state.py console calls (3 calls)
- [ ] Replace skip.py console calls (7 calls)
- [ ] Replace coordinator.py UDF discovery (5 calls)
- [ ] Replace output.py correlation (4 calls)
- [ ] Replace dependency.py workflow deps (7 calls)
- [ ] Replace action_executor.py levels (6 calls)
- [ ] Replace validation files (13 calls)
- [ ] Run tests after each file

### Phase 4: Clean Up Utilities (1 hour)
- [ ] Add deprecation warnings to CorrelationContext
- [ ] Remove ContextInjectingFilter
- [ ] Clean up config.py backward compat properties
- [ ] Remove HandlerConfig class
- [ ] Run tests

### Phase 5: Documentation (1 hour)
- [ ] Update API documentation
- [ ] Update migration guides
- [ ] Update examples in README
- [ ] Document breaking changes

### Phase 6: Final Verification (30 min)
- [ ] Full test suite passes
- [ ] No import errors
- [ ] Console output verified
- [ ] JSON logs verified
- [ ] Performance benchmarks acceptable

---

## 7. NEW EVENT TYPES NEEDED

Add these to `agent_actions/logging/events/types.py`:

```python
# Batch processing events
class BatchProcessingCompleteEvent(InfoLevel, BaseEvent):
    """BP004 - All batch jobs completed"""

class BatchResultsProcessedEvent(InfoLevel, BaseEvent):
    """BP005 - Batch results processed"""

class BatchErrorEvent(ErrorLevel, BaseEvent):
    """BP006 - Batch processing error"""

# State management events
class StatusLoadedEvent(DebugLevel, BaseEvent):
    """SM001 - Status loaded"""

class StatusLoadErrorEvent(WarnLevel, BaseEvent):
    """SM002 - Status load error"""

class StatusSaveErrorEvent(ErrorLevel, BaseEvent):
    """SM003 - Status save error"""

# Correlation events
class VersionCorrelationEvent(InfoLevel, BaseEvent):
    """VC001 - Version correlation"""

class CorrelationFallbackEvent(WarnLevel, BaseEvent):
    """VC002 - Correlation fallback"""

# Workflow dependency events
class UpstreamWorkflowCheckEvent(DebugLevel, BaseEvent):
    """WD001 - Upstream workflow check"""

class UpstreamWorkflowCachedEvent(InfoLevel, BaseEvent):
    """WD002 - Upstream workflow cached"""

class DownstreamWorkflowStatusEvent(DebugLevel, BaseEvent):
    """WD003 - Downstream workflow status"""

# Execution events
class ExecutionPlanEvent(InfoLevel, BaseEvent):
    """EX001 - Execution plan"""

class ExecutionLevelStartEvent(DebugLevel, BaseEvent):
    """EX002 - Execution level started"""

class ExecutionLevelCompleteEvent(InfoLevel, BaseEvent):
    """EX003 - Execution level complete"""
```

---

## Acceptance Criteria

- [ ] No references to removed formatters
- [ ] All console.print calls replaced or documented as "KEEP"
- [ ] All imports resolve correctly
- [ ] Tests pass
- [ ] Documentation updated
- [ ] Console output still correct
- [ ] JSON logs contain all data
- [ ] No performance regression

---

## Files Modified Summary

| File | Action | Count |
|------|--------|-------|
| `logging/formatters.py` | Remove classes | Lines 141-318 |
| `logging/__init__.py` | Update exports | 2 exports |
| `tests/test_logging/test_formatters.py` | Remove/archive | Entire file |
| `logging/filters.py` | Remove class | Lines 13-62 |
| `logging/config.py` | Clean up | 3 sections |
| `workflow/managers/batch.py` | Replace console.print | 8 calls |
| `workflow/executor.py` | Replace console.print | 2 calls |
| `workflow/managers/state.py` | Replace console.print | 3 calls |
| `workflow/managers/skip.py` | Replace console.print | 7 calls |
| `workflow/coordinator.py` | Replace console.print | 5 calls |
| `workflow/managers/output.py` | Replace console.print | 4 calls |
| `workflow/parallel/dependency.py` | Replace console.print | 7 calls |
| `workflow/parallel/action_executor.py` | Replace console.print | 6 calls |
| `validation/udfs.py` | Replace console.print | 13+ calls |

**Total:** 14 files, 55+ console.print replacements
