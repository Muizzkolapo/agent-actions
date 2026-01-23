# TICKET-014: Update Logging Documentation

**Status:** ✅ DONE
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, documentation

## Description

Update all documentation to reflect the new event-based logging system.

## Deliverables

- [x] Update README logging section
- [x] Update developer guide
- [x] Add logging architecture doc
- [x] Update API documentation

## Documentation Updates

### README.md

Add section on logging:
- How to configure logging
- Verbose/quiet modes
- Where artifacts are written

### Developer Guide

Document for contributors:
- How to add new event types
- How to create handlers
- Testing guidelines

### Architecture Doc

Create `docs/architecture/logging.md`:
- System overview diagram
- Event flow explanation
- Handler responsibilities

### API Documentation

Document public API:
- `LoggerFactory.initialize()`
- `fire_event()`
- Event types reference

## Content Outline

### For Users

```markdown
## Logging

Agent-actions uses an event-based logging system inspired by dbt.

### Configuration

- `--verbose` / `-v`: Show debug output
- `--quiet` / `-q`: Show only warnings and errors

### Artifacts

After each run:
- `target/run_results.json` - Execution summary
- `target/logs/events.json` - Full event log (NDJSON)
```

### For Developers

```markdown
## Adding New Events

1. Create event class in `logging/events/types.py`
2. Inherit from `BaseEvent` and appropriate level mixin
3. Add to `__all__` exports
4. Add handler support if needed
```

## Acceptance Criteria

- [x] All docs reference new system
- [x] No references to old logging
- [x] Examples are accurate
- [x] API reference complete

## Implementation Summary

### Files Updated

1. **README.md** - Added comprehensive "Logging and Observability" section:
   - Configuration options (--verbose, --quiet)
   - Output artifacts locations (run_results.json, events.json)
   - Event-based system overview

2. **CONTRIBUTING.md** - Added "Event-Based Logging System" section:
   - System architecture diagram
   - How to add new event types
   - How to create event handlers
   - Testing events and handlers
   - Context propagation
   - Event guidelines

3. **docs.agent-actions/docs/reference/architecture/logging.md** (NEW) - Comprehensive architecture documentation:
   - System overview and architecture diagram
   - Core components (EventManager, Event Types, Handlers)
   - Event flow (initialization, emission, enrichment, dispatch, output)
   - Context propagation
   - Testing guidelines
   - Configuration options
   - Best practices
   - Migration guide from legacy logging

4. **docs.agent-actions/docs/reference/api/logging.md** (NEW) - Complete API reference:
   - Public API (fire_event, get_manager, LoggerFactory)
   - EventManager methods
   - All event classes with examples
   - Event handler classes
   - Configuration classes
   - Constants (EventLevel, EventCategory)
   - Usage examples

### Artifact Paths Verified

Confirmed actual artifact paths:
- `{workflow}/agent_io/target/run_results.json` - Execution summary
- `{workflow}/agent_io/target/events.json` - Full event log (NDJSON)
- `logs/agent_actions.log` - Application logs (if configured)

### Note on --quiet Flag

The --quiet flag is supported in LoggerFactory.initialize() but not yet exposed in the CLI. This will be added in TICKET-015.
