# TICKET-015: Implement CLI Log Level Flags

**Status:** 🔲 TODO
**Priority:** Medium
**Estimate:** 1-2 hours
**Labels:** logging, cli

## Description

Ensure `--verbose` and `--quiet` flags work correctly with the new event system.

## Deliverables

- [ ] `--verbose` shows DEBUG level events
- [ ] `--quiet` shows only WARN and ERROR
- [ ] Default shows INFO level
- [ ] Flags work for all commands

## Current State

Flags are passed to `LoggerFactory.initialize()` but need verification.

## Expected Behavior

### Default (no flags)

```
10:30:45 | Running workflow my_workflow (5 agents)
10:30:46 | 1/5 START extract_data
10:30:58 | 1/5 OK extract_data in 12.34s (1700 tokens)
```

### Verbose (`-v`)

```
10:30:45 | [DEBUG] Loading config from /path/to/config.yaml
10:30:45 | [DEBUG] Validating agent schema
10:30:45 | Running workflow my_workflow (5 agents)
10:30:46 | [DEBUG] LLM request to gpt-4 (500 tokens)
10:30:46 | 1/5 START extract_data
...
```

### Quiet (`-q`)

```
10:30:58 | [WARN] Rate limit hit, retrying in 60s
10:31:45 | [ERROR] Agent transform_data failed: ValidationError
```

## Implementation

Verify in `ConsoleEventHandler`:

```python
if self.min_level == EventLevel.DEBUG:
    # Show all categories
elif self.min_level == EventLevel.WARN:
    # Only show warnings and errors
else:
    # Default: workflow, agent, batch categories only
```

## Acceptance Criteria

- [ ] `-v` shows debug output
- [ ] `-q` suppresses info/debug
- [ ] Flags documented in help
- [ ] Works with all CLI commands
