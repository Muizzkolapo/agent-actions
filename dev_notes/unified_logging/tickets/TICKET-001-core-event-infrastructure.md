# TICKET-001: Create Core Event Infrastructure

**Status:** ✅ COMPLETED
**Priority:** Critical
**Completed:** January 2026
**Estimate:** 4-6 hours
**Actual:** ~4 hours
**Labels:** logging, infrastructure, foundation

## Description

Create the foundational event infrastructure that all logging will flow through. This is the reusable core that has zero dependencies on agent-actions domain code.

## Deliverables

- [x] `BaseEvent` dataclass with level, category, message, meta, data
- [x] `EventLevel` enum (DEBUG, INFO, WARN, ERROR)
- [x] `EventMeta` dataclass for timestamp, correlation_id, invocation_id
- [x] `EventManager` singleton for event dispatch
- [x] `fire_event()` convenience function
- [x] `EventHandler` protocol for handler implementations
- [x] `EventFilter` protocol for filtering
- [x] `LevelFilter` and `CategoryFilter` implementations

## Files Created

```
agent_actions/logging/core/
├── __init__.py           # Public API exports
├── events.py             # BaseEvent, EventLevel, EventMeta, level mixins
├── protocols.py          # EventHandler protocol, filters
└── manager.py            # EventManager singleton, fire_event()
```

## Key Design Decisions

1. **Dataclasses over Protobuf** - Simpler than dbt's approach, no compilation step
2. **Protocol-based handlers** - Duck typing, no inheritance required
3. **String categories** - Allows extension without modifying enums
4. **Event codes** - dbt-style codes (W001, A002) for easy reference

## Testing

```python
from agent_actions.logging.core import EventManager, BaseEvent, fire_event

manager = EventManager.get()
assert manager is EventManager.get()  # Singleton

event = BaseEvent(message="test")
assert event.event_type == "BaseEvent"
assert event.code.startswith("S")  # System category
```

## Notes

- Core has ZERO imports from agent_actions domain code
- Can be extracted to separate package in future
- Follows dbt's `fire_event()` pattern
