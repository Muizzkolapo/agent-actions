# TICKET-016: Logging Performance Optimization

**Status:** 🔲 TODO
**Priority:** Low
**Estimate:** 2-4 hours
**Labels:** logging, performance

## Description

Optimize logging performance for high-volume scenarios (many agents, large batches).

## Deliverables

- [ ] Benchmark current performance
- [ ] Optimize hot paths
- [ ] Add async file writing option
- [ ] Document performance characteristics

## Benchmarks to Run

```python
import time
from agent_actions.logging import fire_event
from agent_actions.logging.events import AgentCompleteEvent

start = time.perf_counter()
for i in range(10000):
    fire_event(AgentCompleteEvent(
        agent_name=f"agent_{i}",
        agent_index=i,
        total_agents=10000,
        execution_time=0.1,
    ))
elapsed = time.perf_counter() - start
print(f"10000 events in {elapsed:.2f}s ({10000/elapsed:.0f} events/sec)")
```

## Optimization Areas

### Event Creation

- Pre-compute event codes
- Avoid unnecessary copies
- Use `__slots__` on event classes

### Handler Dispatch

- Filter early to avoid handler calls
- Batch handler updates
- Consider async handlers

### File I/O

- Buffer writes (already implemented)
- Async file handler option
- Compression for old logs

## Target Performance

- Event creation: <0.1ms
- Handler dispatch: <0.5ms total
- File write (buffered): <0.01ms per event

## Acceptance Criteria

- [ ] Benchmark baseline documented
- [ ] No regression from optimizations
- [ ] High-volume scenario tested (>1000 agents)
- [ ] Memory usage reasonable
