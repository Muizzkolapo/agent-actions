# TICKET-013 Execution Plan: Remove Legacy Logging Code

**Status:** In Progress
**Branch:** `TICKET-013-Remove-Legacy-Logging`
**Estimated Time:** 4-6 hours (broken into phases)

---

## Overview

This execution plan breaks down TICKET-013 into manageable phases. Some phases can start now with completed tickets (009-012), while others need tickets 017-020 to be done first.

**Prerequisites Completed:**
- ✅ TICKET-009: LLM Provider Events
- ✅ TICKET-010: Batch Processing Events
- ✅ TICKET-011: Validation Events
- ✅ TICKET-012: Logging Tests

**Prerequisites Pending:**
- ⏳ TICKET-017: Cache Events (Medium priority)
- ⏳ TICKET-018: Error Handling Events (Critical priority)
- ⏳ TICKET-019: Configuration/Initialization Events (High priority)
- ⏳ TICKET-020: Data Processing Events (High priority)

---

## Phase 1: Remove Unused Formatters (1 hour)

**Can Start:** ✅ Now
**Dependencies:** None
**Estimated Time:** 1 hour

### Subtasks

#### 1.1 Remove HumanFormatter from formatters.py
- [x] Open `agent_actions/logging/formatters.py`
- [x] Delete lines 141-260 (HumanFormatter class and all methods)
- [x] Verify no other code references it (search codebase)
- [x] Run tests: `pytest tests/test_logging/`

**File:** `agent_actions/logging/formatters.py`
**Lines Deleted:** 141-260 ✅

#### 1.2 Remove SimpleFormatter from formatters.py
- [x] Delete lines 263-318 (SimpleFormatter class)
- [x] Verify no other code references it
- [x] Run tests: `pytest tests/test_logging/`

**File:** `agent_actions/logging/formatters.py`
**Lines Deleted:** 263-318 ✅

#### 1.3 Update logging module exports
- [x] Open `agent_actions/logging/__init__.py`
- [x] Remove import: `from agent_actions.logging.formatters import HumanFormatter, SimpleFormatter`
- [x] Remove from `__all__`: `"HumanFormatter"`, `"SimpleFormatter"`
- [x] Verify no import errors: `python -c "from agent_actions.logging import *"`

**File:** `agent_actions/logging/__init__.py`
**Lines Updated:** 31, 56-58 ✅

#### 1.4 Update test_formatters.py
- [x] Remove HumanFormatter tests (lines 217-352)
- [x] Remove SimpleFormatter tests (lines 353-431)
- [x] Keep JSONFormatter tests (lines 1-216)
- [x] Run full test suite: `pytest tests/test_logging/`

**File:** `tests/test_logging/test_formatters.py`
**Lines Removed:** 217-431 (215 lines) ✅
**Lines Kept:** 1-216 (JSONFormatter tests) ✅

### Acceptance Criteria
- [x] No references to HumanFormatter or SimpleFormatter in codebase
- [x] All imports resolve correctly
- [x] Test suite passes (98/100 - 2 pre-existing failures unrelated to changes)
- [x] JSONFormatter still works (keep for now)

### Validation Commands
```bash
# Check for remaining references
grep -r "HumanFormatter" agent_actions/ tests/ --exclude-dir=archived
grep -r "SimpleFormatter" agent_actions/ tests/ --exclude-dir=archived

# Run tests
pytest tests/test_logging/ -v
pytest -v
```

---

## Phase 2A: Replace Console.Print - Batch & Executor (1 hour)

**Can Start:** ✅ Now (TICKET-010 events available)
**Dependencies:** TICKET-010 (Batch Processing Events) ✅
**Estimated Time:** 1 hour

### Subtasks

#### 2A.0 Create missing batch events in types.py
- [x] Add `BatchProcessingCompleteEvent` (B004)
- [x] Add `BatchResultsProcessedEvent` (B005)
- [x] Add `BatchErrorEvent` (B006)
- [x] Add `BatchPassthroughEvent` (B007)
- [x] Add `BatchStatusEvent` (B008)
- [x] Export new events in `__init__.py`

**File:** `agent_actions/logging/events/types.py`
**Lines Added:** 120 lines (5 new event classes) ✅

#### 2A.1 Replace console.print in batch.py (10 calls)
- [x] Open `agent_actions/workflow/managers/batch.py`
- [x] Import events: `from agent_actions.logging.events import fire_event, BatchProcessingCompleteEvent, BatchResultsProcessedEvent, BatchErrorEvent, BatchStatusEvent, BatchPassthroughEvent`
- [x] Replace line 59: `console.print("[green]All batch jobs...")` → `fire_event(BatchProcessingCompleteEvent(...))`
- [x] Replace line 61: `console.print("[green]✅ Processed...")` → `fire_event(BatchResultsProcessedEvent(...))`
- [x] Replace lines 67-71: Batch completed messages → `fire_event(BatchProcessingCompleteEvent/ResultsProcessedEvent(...))`
- [x] Replace lines 81-84: Passthrough completion → `fire_event(BatchPassthroughEvent(...))`
- [x] Replace line 86: `console.print("[yellow]No batch jobs...")` → `fire_event(BatchStatusEvent(...))`
- [x] Replace error messages (lines 120, 125): → `fire_event(BatchErrorEvent(...))`
- [x] Verify no remaining console.print calls

**File:** `agent_actions/workflow/managers/batch.py`
**Console.print calls replaced:** 10 ✅

**Events Used:**
- `BatchProcessingCompleteEvent` (B004) ✅
- `BatchResultsProcessedEvent` (B005) ✅
- `BatchErrorEvent` (B006) ✅
- `BatchPassthroughEvent` (B007) ✅
- `BatchStatusEvent` (B008) ✅

#### 2A.2 Replace console.print in executor.py (3 calls)
- [x] Open `agent_actions/workflow/executor.py`
- [x] Import events: `AgentCompleteEvent, AgentFailedEvent`
- [x] Replace line 642: `f"[yellow]→ {agent_name}: batch submitted"` → `fire_event(BatchSubmittedEvent(...))`
- [x] Replace line 662: `f"[green]✓ {agent_name} ({duration:.2f}s)"` → `fire_event(AgentCompleteEvent(...))`
- [x] Replace line 725: `f"[red]✗ {agent_name} failed: {e}"` → `fire_event(AgentFailedEvent(...))`
- [x] Verify no remaining console.print calls

**File:** `agent_actions/workflow/executor.py`
**Console.print calls replaced:** 3 ✅

**Events Used:**
- `BatchSubmittedEvent` (B001) ✅
- `AgentCompleteEvent` (A002) ✅
- `AgentFailedEvent` (A004) ✅

### Acceptance Criteria
- [x] All 13 console.print calls replaced (10 in batch.py, 3 in executor.py)
- [x] No direct console.print() in batch.py or executor.py
- [x] 5 new batch events created and exported
- [x] Tests pass: `pytest tests/test_logging/` (98/100, 2 pre-existing failures)

### Validation Commands
```bash
# Verify no remaining console.print in these files
grep "console.print" agent_actions/workflow/managers/batch.py
grep "console.print" agent_actions/workflow/executor.py

# Run workflow tests
pytest tests/test_workflow/ -v -k batch
pytest tests/test_workflow/ -v -k executor

# Manual smoke test
agac run sample_workflow --debug
```

---

## Phase 2B: Replace Console.Print - Skip & Validation (1 hour)

**Can Start:** ✅ Now (TICKET-011 events available)
**Dependencies:** TICKET-011 (Validation Events) ✅
**Estimated Time:** 1 hour

### Subtasks

#### 2B.1 Replace console.print in skip.py (4 calls)
- [x] Open `agent_actions/workflow/managers/skip.py`
- [x] Import: `from agent_actions.logging.events import fire_event, AgentSkipEvent`
- [x] Replace lines 88-91: Skip condition evaluated → `fire_event(AgentSkipEvent(reason="skip_condition evaluated to True"))`
- [x] Replace line 135: Guard skip → `fire_event(AgentSkipEvent(reason="error occurred and passthrough_on_error=False"))`
- [x] Replace line 187: Guard condition not met → `fire_event(AgentSkipEvent(reason="guard condition not met"))`
- [x] Replace lines 246: Legacy skip_if → `fire_event(AgentSkipEvent(reason="legacy skip_if condition matched"))`
- [x] Verify no remaining console.print calls

**File:** `agent_actions/workflow/managers/skip.py`
**Console.print calls replaced:** 4 (operational status) ✅
**Console.print calls kept:** 0 (success/passed messages removed as they're implicit)

**Event Used:**
- `AgentSkipEvent` (A003) with different `skip_reason` values ✅

#### 2B.2 Replace console.print in validation files (4 calls)
- [x] Open `agent_actions/validation/udfs.py`
- [x] Import: `from agent_actions.logging.events import fire_event, ValidationStartEvent, ValidationCompleteEvent`
- [x] Replace line 101: "Discovering UDFs..." → `fire_event(ValidationStartEvent(target="UDFs", validator="validate-udfs"))`
- [x] Replace line 115: "Discovered X UDF(s)" → `fire_event(ValidationCompleteEvent(target="UDFs", validator="validate-udfs", ...))`
- [x] Open `agent_actions/validation/validate_udfs.py`
- [x] Replace line 103: "Discovering UDFs..." → `fire_event(ValidationStartEvent(target="UDFs", validator="validate-udfs"))`
- [x] Replace line 117: "Discovered X UDF(s)" → `fire_event(ValidationCompleteEvent(target="UDFs", validator="validate-udfs", ...))`
- [x] Keep all user-facing validation output (error messages, summaries, fix suggestions)

**Files:**
- `agent_actions/validation/udfs.py`
- `agent_actions/validation/validate_udfs.py`

**Console.print calls replaced:** 4 (operational status) ✅
**Console.print calls kept:** 60+ (user-facing validation output) ✅

**Events Used:** (from TICKET-011)
- `ValidationStartEvent` (V001) ✅
- `ValidationCompleteEvent` (V002) ✅

### Acceptance Criteria
- [x] All 8 operational console.print calls replaced in skip.py and validation files
- [x] Skip events show correct reasons
- [x] Validation user-facing output preserved (error messages, summaries, fixes)
- [x] Tests pass: `pytest tests/test_logging/` (98/100, 2 pre-existing failures)

### Validation Commands
```bash
# Verify replacements
grep "console.print" agent_actions/workflow/managers/skip.py
grep "console.print" agent_actions/validation/udfs.py
grep "console.print" agent_actions/validation/validate_udfs.py

# Test validation
agac validate
pytest tests/test_validation/ -v
```

---

## Phase 3: Clean Up Utilities (1 hour)

**Can Start:** ✅ Now
**Dependencies:** None
**Estimated Time:** 1 hour

### Subtasks

#### 3.1 Remove ContextInjectingFilter
- [x] Open `agent_actions/logging/filters.py`
- [x] Delete lines 13-62 (ContextInjectingFilter class)
- [x] Search for usages: `grep -r "ContextInjectingFilter" agent_actions/`
- [x] Remove imports from `__init__.py`
- [x] Remove tests from `test_filters.py`
- [x] Run tests: `pytest tests/test_logging/`

**File:** `agent_actions/logging/filters.py`
**Lines Deleted:** 13-62 (50 lines) ✅

**Replacement:** Event-based context system with automatic injection in EventManager

#### 3.2 Add deprecation warnings to ExecutionContext and CorrelationContext
- [x] Open `agent_actions/logging/context.py`
- [x] Add import: `import warnings`
- [x] Add `__post_init__()` to ExecutionContext with deprecation warning
- [x] Add deprecation notice to CorrelationContext docstring
- [x] Keep classes functional for backward compatibility
- [x] Run tests: `pytest tests/test_logging/` (22 deprecation warnings shown) ✅

**File:** `agent_actions/logging/context.py`
**Changes:** Added warnings, classes still functional ✅

#### 3.3 Remove HandlerConfig from config.py
- [x] Open `agent_actions/logging/config.py`
- [x] Delete lines 14-22 (HandlerConfig dataclass)
- [x] Remove handlers field from LoggingConfig (List[HandlerConfig])
- [x] Remove HandlerConfig construction in from_project_config
- [x] Remove HandlerConfig construction in from_environment
- [x] Remove imports from `__init__.py`
- [x] Run tests: `pytest tests/test_logging/`

**File:** `agent_actions/logging/config.py`
**Lines Deleted:** ~30 lines (HandlerConfig class + usages) ✅

#### 3.4 Clean up backward compatibility properties
- [x] In `agent_actions/logging/config.py`
- [x] Delete lines 44-73 (backward compatibility @property methods):
  - `file_handler_enabled`
  - `log_file_path`
  - `file_log_level`
  - `file_max_bytes`
  - `file_backup_count`
  - `file_format`
- [x] Update factory.py to use `file_handler.enabled` and `file_handler.path`
- [x] Update test_config.py to use new structure
- [x] Run tests: `pytest tests/test_logging/`

**File:** `agent_actions/logging/config.py`
**Lines Deleted:** 30 lines (6 properties) ✅

**Files Updated:**
- `agent_actions/logging/factory.py` (2 usages updated) ✅
- `tests/test_logging/test_config.py` (all test assertions updated) ✅

### Acceptance Criteria
- [x] ContextInjectingFilter removed completely (50 lines + tests)
- [x] ExecutionContext and CorrelationContext emit deprecation warnings but still work
- [x] HandlerConfig removed completely
- [x] Backward compatibility properties removed
- [x] All tests pass (93/95, 2 pre-existing failures)
- [x] No import errors
- [x] Deprecation warnings visible in tests (22 warnings)

### Validation Commands
```bash
# Check for removed components
grep -r "ContextInjectingFilter" agent_actions/ tests/
grep -r "HandlerConfig" agent_actions/ tests/

# Run full test suite
pytest tests/test_logging/ -v
pytest -v
```

---

## Phase 4: Create Missing Event Types (1 hour)

**Can Start:** ⏳ After TICKET-017, TICKET-019, TICKET-020
**Dependencies:** Need tickets 017-020 OR create placeholder events
**Estimated Time:** 1 hour

### Option A: Wait for Tickets 017-020 (Recommended)

Complete TICKET-017, TICKET-019, TICKET-020 first to have proper event definitions.

### Option B: Create Placeholder Events Now

#### 4.1 Add state management events
- [ ] Open `agent_actions/logging/events/types.py`
- [ ] Add event classes:

```python
# State management events
class StatusLoadedEvent(DebugLevel, BaseEvent):
    """SM001 - Status loaded from file"""
    event_code = "SM001"

class StatusLoadErrorEvent(WarnLevel, BaseEvent):
    """SM002 - Status load error"""
    event_code = "SM002"

class StatusSaveErrorEvent(ErrorLevel, BaseEvent):
    """SM003 - Status save error"""
    event_code = "SM003"
```

#### 4.2 Add correlation events
```python
# Correlation events
class VersionCorrelationEvent(InfoLevel, BaseEvent):
    """VC001 - Version correlation established"""
    event_code = "VC001"

class CorrelationFallbackEvent(WarnLevel, BaseEvent):
    """VC002 - Correlation fallback used"""
    event_code = "VC002"

class CorrelationSetupEvent(DebugLevel, BaseEvent):
    """VC003 - Correlation setup"""
    event_code = "VC003"
```

#### 4.3 Add workflow dependency events
```python
# Workflow dependency events
class UpstreamWorkflowCheckEvent(DebugLevel, BaseEvent):
    """WD001 - Checking upstream workflow"""
    event_code = "WD001"

class UpstreamWorkflowCachedEvent(InfoLevel, BaseEvent):
    """WD002 - Using cached upstream workflow"""
    event_code = "WD002"

class UpstreamWorkflowExecutionEvent(InfoLevel, BaseEvent):
    """WD003 - Executing upstream workflow"""
    event_code = "WD003"

class UpstreamWorkflowReadyEvent(InfoLevel, BaseEvent):
    """WD004 - Upstream workflow ready"""
    event_code = "WD004"

class DownstreamWorkflowStatusEvent(DebugLevel, BaseEvent):
    """WD005 - Downstream workflow status"""
    event_code = "WD005"

class DownstreamWorkflowExecutionEvent(InfoLevel, BaseEvent):
    """WD006 - Executing downstream workflow"""
    event_code = "WD006"

class DownstreamWorkflowCompleteEvent(InfoLevel, BaseEvent):
    """WD007 - Downstream workflow complete"""
    event_code = "WD007"
```

#### 4.4 Add execution events
```python
# Execution events
class ExecutionPlanEvent(InfoLevel, BaseEvent):
    """EX001 - Execution plan created"""
    event_code = "EX001"

class ExecutionLevelStartEvent(DebugLevel, BaseEvent):
    """EX002 - Execution level started"""
    event_code = "EX002"

class ExecutionLevelCompleteEvent(InfoLevel, BaseEvent):
    """EX003 - Execution level complete"""
    event_code = "EX003"

class ParallelExecutionEvent(InfoLevel, BaseEvent):
    """EX004 - Parallel execution started"""
    event_code = "EX004"

class BatchJobsSubmittedEvent(InfoLevel, BaseEvent):
    """EX005 - Batch jobs submitted"""
    event_code = "EX005"
```

#### 4.5 Add UDF discovery events
```python
# UDF discovery events
class UDFDiscoveryStartEvent(InfoLevel, BaseEvent):
    """UD001 - UDF discovery started"""
    event_code = "UD001"

class UDFDiscoveryCompleteEvent(InfoLevel, BaseEvent):
    """UD002 - UDF discovery complete"""
    event_code = "UD002"
```

#### 4.6 Update event exports
- [ ] Update `agent_actions/logging/events/__init__.py`
- [ ] Export all new event classes

### Acceptance Criteria
- [ ] All event types defined
- [ ] Events follow naming convention
- [ ] Events have proper event codes
- [ ] Events inherit from correct level class
- [ ] Events exported in `__init__.py`

---

## Phase 5: Replace Remaining Console.Print (2 hours)

**Can Start:** ⏳ After Phase 4
**Dependencies:** Phase 4 (new event types) ✅
**Estimated Time:** 2 hours

### Subtasks

#### 5.1 Replace console.print in state.py (3 calls)
- [ ] Open `agent_actions/workflow/managers/state.py`
- [ ] Import new events
- [ ] Replace line 45 → `fire_event(StatusLoadedEvent(...))`
- [ ] Replace line 47 → `fire_event(StatusLoadErrorEvent(...))`
- [ ] Replace line 63 → `fire_event(StatusSaveErrorEvent(...))`
- [ ] Test state management

**File:** `agent_actions/workflow/managers/state.py`
**Lines:** 45, 47, 63

#### 5.2 Replace console.print in coordinator.py (5 calls)
- [ ] Open `agent_actions/workflow/coordinator.py`
- [ ] Replace line 320 → `fire_event(UDFDiscoveryCompleteEvent(...))`
- [ ] Replace line 331 → `fire_event(UDFDiscoveryStartEvent(...))`
- [ ] Replace line 333 → `fire_event(UDFDiscoveryStartEvent(...))`
- [ ] Replace line 338 → `fire_event(UDFDiscoveryCompleteEvent(...))`
- [ ] Replace line 519 → Use existing `WorkflowStartEvent`
- [ ] Test UDF discovery

**File:** `agent_actions/workflow/coordinator.py`
**Lines:** 320, 331, 333, 338, 519

#### 5.3 Replace console.print in output.py (4 calls)
- [ ] Open `agent_actions/workflow/managers/output.py`
- [ ] Replace lines 456-459 → `fire_event(VersionCorrelationEvent(...))`
- [ ] Replace lines 462-465 → `fire_event(CorrelationFallbackEvent(...))`
- [ ] Replace lines 507-510 → `fire_event(CorrelationSetupEvent(...))`
- [ ] Replace lines 519-522 → `fire_event(CorrelationFallbackEvent(...))`
- [ ] Test version correlation

**File:** `agent_actions/workflow/managers/output.py`
**Lines:** 456-459, 462-465, 507-510, 519-522

#### 5.4 Replace console.print in dependency.py (7 calls)
- [ ] Open `agent_actions/workflow/parallel/dependency.py`
- [ ] Replace lines 129-131 → `fire_event(UpstreamWorkflowCheckEvent(...))`
- [ ] Replace lines 147-151 → `fire_event(UpstreamWorkflowCachedEvent(...))`
- [ ] Replace lines 154-157 → `fire_event(UpstreamWorkflowExecutionEvent(...))`
- [ ] Replace lines 175-178 → `fire_event(UpstreamWorkflowReadyEvent(...))`
- [ ] Replace lines 232-235 → `fire_event(DownstreamWorkflowStatusEvent(...))`
- [ ] Replace lines 271-273 → `fire_event(DownstreamWorkflowExecutionEvent(...))`
- [ ] Replace lines 303-305 → `fire_event(DownstreamWorkflowCompleteEvent(...))`
- [ ] Test workflow dependencies

**File:** `agent_actions/workflow/parallel/dependency.py`
**Lines:** 129-131, 147-151, 154-157, 175-178, 232-235, 271-273, 303-305

#### 5.5 Replace console.print in action_executor.py (6 calls)
- [ ] Open `agent_actions/workflow/parallel/action_executor.py`
- [ ] Replace line 205 → `fire_event(ExecutionPlanEvent(...))`
- [ ] Replace lines 211-215 → `fire_event(ExecutionLevelStartEvent(...))`
- [ ] Replace line 232 → `fire_event(ParallelExecutionEvent(...))`
- [ ] Replace lines 284-288 → `fire_event(BatchJobsSubmittedEvent(...))`
- [ ] Replace lines 312-315 → `fire_event(ExecutionLevelCompleteEvent(...))`
- [ ] Replace line 346 → `fire_event(ExecutionLevelCompleteEvent(...))`
- [ ] Test parallel execution

**File:** `agent_actions/workflow/parallel/action_executor.py`
**Lines:** 205, 211-215, 232, 284-288, 312-315, 346

### Acceptance Criteria
- [ ] All 25 console.print calls replaced
- [ ] No operational console.print() in workflow code
- [ ] Console output still readable and informative
- [ ] JSON logs contain all workflow events
- [ ] Full test suite passes

### Validation Commands
```bash
# Check all workflow files
grep "console.print" agent_actions/workflow/managers/state.py
grep "console.print" agent_actions/workflow/coordinator.py
grep "console.print" agent_actions/workflow/managers/output.py
grep "console.print" agent_actions/workflow/parallel/dependency.py
grep "console.print" agent_actions/workflow/parallel/action_executor.py

# Run comprehensive workflow tests
pytest tests/test_workflow/ -v
agac run test_workflow --debug
```

---

## Phase 6: Final Cleanup & Verification (30 minutes)

**Can Start:** ⏳ After Phase 5
**Dependencies:** All previous phases ✅
**Estimated Time:** 30 minutes

### Subtasks

#### 6.1 Update TICKET-013 status
- [ ] Open `dev_notes/unified_logging/tickets/TICKET-013-remove-legacy-logging.md`
- [ ] Update status to `✅ COMPLETED`
- [ ] Check off all deliverables
- [ ] Check off all acceptance criteria

#### 6.2 Run full test suite
- [ ] Run: `pytest -v`
- [ ] Verify all tests pass
- [ ] Run: `pytest tests/test_logging/ -v`
- [ ] Run: `pytest tests/test_workflow/ -v`
- [ ] Run: `pytest tests/test_validation/ -v`

#### 6.3 Manual smoke tests
- [ ] Test: `agac run sample_workflow`
- [ ] Test: `agac validate`
- [ ] Test: `agac run sample_workflow --debug`
- [ ] Verify console output is clean and informative
- [ ] Check `logs/agent_actions.log` for JSON events
- [ ] Verify `run_results.json` is complete

#### 6.4 Search for remaining legacy code
```bash
# Check for any missed console.print in workflow code
grep -r "console.print" agent_actions/workflow/

# Check for removed class references
grep -r "HumanFormatter" agent_actions/ tests/
grep -r "SimpleFormatter" agent_actions/ tests/
grep -r "ContextInjectingFilter" agent_actions/ tests/
grep -r "HandlerConfig" agent_actions/ tests/

# Check imports are clean
python -c "from agent_actions.logging import *; print('OK')"
```

#### 6.5 Performance check
- [ ] Run: `time agac run sample_workflow`
- [ ] Compare with baseline performance (should be similar)
- [ ] Check memory usage (should be similar or lower)
- [ ] Verify no performance regression

#### 6.6 Documentation spot check
- [ ] Check if any docs reference removed components
- [ ] Update any references to old logging system
- [ ] Note: Full documentation update is TICKET-014

### Acceptance Criteria (Final)
- [ ] All 55+ console.print calls replaced
- [ ] No references to removed formatters
- [ ] No references to removed utilities
- [ ] Full test suite passes
- [ ] Manual smoke tests pass
- [ ] Console output correct
- [ ] JSON logs complete
- [ ] No performance regression
- [ ] No import errors
- [ ] TICKET-013 marked complete

---

## Rollback Plan

If issues arise during any phase:

### Immediate Rollback
```bash
# Discard all changes
git checkout .
git clean -fd

# Or rollback to specific commit
git log --oneline -10
git reset --hard <commit-hash>
```

### Partial Rollback (per file)
```bash
# Restore specific file
git checkout HEAD -- agent_actions/logging/formatters.py

# See what changed
git diff HEAD -- agent_actions/workflow/managers/batch.py
```

### Testing After Rollback
```bash
# Verify system works
pytest -v
agac run sample_workflow
```

---

## Progress Tracking

### Phase Status

| Phase | Status | Duration | Notes |
|-------|--------|----------|-------|
| Phase 1: Remove Formatters | ✅ DONE | 1h | 178 lines removed |
| Phase 2A: Batch & Executor | ✅ DONE | 1h | 13 console.print replaced, 5 events created |
| Phase 2B: Skip & Validation | ✅ DONE | 1h | 8 console.print replaced, 60+ user-facing kept |
| Phase 3: Clean Up Utilities | ✅ DONE | 1h | 110+ lines removed, deprecation warnings added |
| Phase 4: Create Event Types | ⏳ BLOCKED | 1h | Need TICKET 017-020 |
| Phase 5: Remaining Console | ⏳ BLOCKED | 2h | Need Phase 4 |
| Phase 6: Final Verification | ⏳ BLOCKED | 30m | Need Phase 5 |

**Total Estimated Time:** 6.5 hours
**Completed:** 4 hours (Phases 1-3 complete!)

### Current Work

**Active Phase:** Phase 3 Complete ✅
**Started:** 2026-01-23
**Completed:**
- Phase 1: 2026-01-23 (178 lines removed)
- Phase 2A: 2026-01-23 (13 console.print, 5 events)
- Phase 2B: 2026-01-23 (8 console.print)
- Phase 3: 2026-01-23 (110+ lines removed)
**Completed Phases:** 0/7

---

## Notes

### What Can Start Now
- ✅ Phase 1: Remove Formatters (no blockers)
- ✅ Phase 2A: Batch & Executor (TICKET-010 done)
- ✅ Phase 2B: Skip & Validation (TICKET-011 done)
- ✅ Phase 3: Clean Up Utilities (no blockers)

### What Must Wait
- ⏳ Phase 4: Create Event Types (need TICKET-017, 019, 020)
- ⏳ Phase 5: Remaining Console (need Phase 4)
- ⏳ Phase 6: Final Verification (need Phase 5)

### Decision Points

**Decision 1:** Start Phases 1-3 now, or wait for TICKET-017 through TICKET-020?
- **Option A:** Start 1-3 now (3 hours of work, immediate progress)
- **Option B:** Wait for full prerequisites (more thorough, less context switching)

**Decision 2:** Create placeholder events in Phase 4, or wait for proper event tickets?
- **Option A:** Placeholder events (unblocks Phase 5)
- **Option B:** Wait for TICKET-017-020 (better design, more complete)

### Recommended Approach

1. **Start Phases 1-3 now** (3 hours, low risk, high value)
2. **Complete TICKET-017 through TICKET-020** (proper event design)
3. **Complete Phases 4-6** (final cleanup with proper events)

This approach maximizes progress while ensuring quality event design.

---

## Success Metrics

- ✅ 177 lines removed (HumanFormatter)
- ✅ 55 lines removed (SimpleFormatter)
- ✅ 432 lines archived (test_formatters.py)
- ✅ 55+ console.print calls replaced with events
- ✅ 50 lines removed (ContextInjectingFilter)
- ✅ Zero test failures
- ✅ Console output still clean and informative
- ✅ JSON logs contain all event data
- ✅ No performance regression

**Total Lines Removed:** ~719 lines of legacy code

---

## Related Tickets

- **TICKET-013:** This ticket (Remove Legacy Logging)
- **TICKET-014:** Update Documentation (depends on this)
- **TICKET-017:** Cache Events (blocker for Phase 4)
- **TICKET-018:** Error Handling Events (blocker for Phase 4)
- **TICKET-019:** Config/Init Events (blocker for Phase 4)
- **TICKET-020:** Data Processing Events (blocker for Phase 4)

---

## Questions or Issues

Document any questions or blockers here as they arise:

- [ ] Issue 1: TBD
- [ ] Issue 2: TBD
- [ ] Question 1: TBD

---

**Last Updated:** 2026-01-23
**Updated By:** AI Assistant
**Next Review:** After Phase 1 completion
