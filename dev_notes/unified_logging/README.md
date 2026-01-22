# Unified Logging System

This folder contains all documentation and tickets for the dbt-style centralized logging system.

## Overview

We implemented an event-based logging system inspired by dbt. Key features:

- **Single entry point**: All logging flows through `EventManager`
- **Typed events**: `WorkflowStartEvent`, `AgentCompleteEvent`, etc.
- **dbt-style output**: Clean console output with timestamps and status
- **Artifacts**: `run_results.json` for CI/CD integration
- **Backwards compatible**: Existing `logger.info()` calls auto-bridged to events

## Contents

| Document | Description |
|----------|-------------|
| [001_unified_logging_system.md](./001_unified_logging_system.md) | Technical architecture overview |
| [002_migration_tickets.md](./002_migration_tickets.md) | Migration summary |
| [003_developer_quick_reference.md](./003_developer_quick_reference.md) | Quick reference for developers |
| [tickets/](./tickets/) | Individual ticket files |

## Tickets Summary

| Status | Count |
|--------|-------|
| ✅ Completed | 8 |
| 🔲 TODO | 12 |
| **Total** | **20** |

### Completed

| Ticket | Title |
|--------|-------|
| [TICKET-001](./tickets/TICKET-001-core-event-infrastructure.md) | Core Event Infrastructure |
| [TICKET-002](./tickets/TICKET-002-core-event-handlers.md) | Core Event Handlers |
| [TICKET-003](./tickets/TICKET-003-agent-actions-event-types.md) | Agent-Actions Event Types |
| [TICKET-004](./tickets/TICKET-004-run-results-collector.md) | Run Results Collector |
| [TICKET-005](./tickets/TICKET-005-unified-logger-factory.md) | Unified Logger Factory |
| [TICKET-006](./tickets/TICKET-006-instrument-workflow-coordinator.md) | Instrument Workflow Coordinator |
| [TICKET-007](./tickets/TICKET-007-instrument-agent-executor.md) | Instrument Agent Executor |
| [TICKET-008](./tickets/TICKET-008-cli-logging-integration.md) | CLI Logging Integration |

### Pending (Original Migration)

| Ticket | Title | Priority |
|--------|-------|----------|
| [TICKET-009](./tickets/TICKET-009-llm-provider-events.md) | LLM Provider Events | High |
| [TICKET-010](./tickets/TICKET-010-batch-processing-events.md) | Batch Processing Events | Medium |
| [TICKET-011](./tickets/TICKET-011-validation-events.md) | Validation Events | Medium |
| [TICKET-012](./tickets/TICKET-012-logging-tests.md) | Logging System Tests | High |
| [TICKET-013](./tickets/TICKET-013-remove-legacy-logging.md) | Remove Legacy Logging Code | Low |
| [TICKET-014](./tickets/TICKET-014-update-documentation.md) | Update Logging Documentation | Medium |
| [TICKET-015](./tickets/TICKET-015-cli-log-level-flags.md) | CLI Log Level Flags | Medium |
| [TICKET-016](./tickets/TICKET-016-logging-performance.md) | Logging Performance Optimization | Low |

### Pending (Additional Analysis)

| Ticket | Title | Priority |
|--------|-------|----------|
| [TICKET-017](./tickets/TICKET-017-cache-events.md) | Cache Events (6 cache systems) | Medium |
| [TICKET-018](./tickets/TICKET-018-error-handling-events.md) | Error Handling Events | **Critical** |
| [TICKET-019](./tickets/TICKET-019-config-init-events.md) | Config & Init Events | High |
| [TICKET-020](./tickets/TICKET-020-data-processing-events.md) | Data Processing Events | High |

## Quick Start

```python
from agent_actions.logging import fire_event
from agent_actions.logging.events import WorkflowStartEvent

fire_event(WorkflowStartEvent(workflow_name="test", agent_count=5))
```

## Architecture

```
                    Application Code
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    logger.info()    fire_event()     console.print()
          │                │           (deprecated)
          │                │
          ▼                │
  LoggingBridgeHandler     │
          │                │
          └───────►  EventManager  ◄───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Console       JSON File    run_results.json
```
