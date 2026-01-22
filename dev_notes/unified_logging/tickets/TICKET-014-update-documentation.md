# TICKET-014: Update Logging Documentation

**Status:** 🔲 TODO
**Priority:** Medium
**Estimate:** 2-3 hours
**Labels:** logging, documentation

## Description

Update all documentation to reflect the new event-based logging system.

## Deliverables

- [ ] Update README logging section
- [ ] Update developer guide
- [ ] Add logging architecture doc
- [ ] Update API documentation

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

- [ ] All docs reference new system
- [ ] No references to old logging
- [ ] Examples are accurate
- [ ] API reference complete
