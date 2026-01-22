# TICKET-008: CLI Logging Integration

**Status:** ✅ COMPLETED
**Priority:** High
**Completed:** January 2026
**Estimate:** 1-2 hours
**Actual:** ~1 hour
**Labels:** logging, cli, integration

## Description

Update CLI commands to use the unified logging initialization with proper workflow context.

## Deliverables

- [x] Update `run` command to initialize with workflow context
- [x] Update `main.py` to use unified initialization
- [x] Pass workflow name and invocation ID

## Files Modified

```
agent_actions/cli/run.py
agent_actions/cli/main.py
```

## Changes in run.py

```python
from agent_actions.logging import LoggerFactory

# In execute() method
LoggerFactory.initialize(
    output_dir=agent_folder,
    workflow_name=self.agent_name,
    invocation_id=run_id,
    force=True,
)
```

## Changes in main.py

Updated `_configure_logging()` to use unified initialization:

```python
def _configure_logging(verbose: bool, quiet: bool) -> None:
    LoggerFactory.initialize(
        verbose=verbose,
        quiet=quiet,
    )
```

## Invocation ID

Each CLI run generates a unique invocation ID:

```python
import uuid
run_id = str(uuid.uuid4())[:8]  # e.g., "abc12345"
```

This ID appears in:
- All log events
- Console output
- JSON log files
- run_results.json

## Notes

- `force=True` allows reinitializing if already initialized
- Workflow name comes from agent/workflow being executed
- Output directory determines where artifacts go
