# TICKET-015: Implement CLI Log Level Flags

**Status:** ✅ DONE
**Priority:** Medium
**Estimate:** 1-2 hours
**Labels:** logging, cli

## Description

Ensure `--verbose` and `--quiet` flags work correctly with the new event system.

## Deliverables

- [x] `--verbose` shows DEBUG level events
- [x] `--quiet` shows only WARN and ERROR
- [x] Default shows INFO level
- [x] Flags work for all commands

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

- [x] `-v` shows debug output
- [x] `-q` suppresses info/debug
- [x] Flags documented in help
- [x] Works with all CLI commands

## Implementation Summary

### Changes Made

1. **agent_actions/cli/main.py**:
   - Added `-q/--quiet` flag to global CLI options (line 60)
   - Updated `_configure_logging()` to detect quiet mode (line 117)
   - Pass `quiet=quiet_mode` to `LoggerFactory.initialize()` (line 131)

### How It Works

**Flag Detection** (main.py:115-117):
```python
debug_mode = "--debug" in argv
verbose_mode = "--verbose" in argv or "-v" in argv
quiet_mode = "--quiet" in argv or "-q" in argv
```

**Level Configuration** (main.py:121-128):
```python
if debug_mode:
    config.default_level = "DEBUG"
elif verbose_mode:
    config.default_level = "INFO"
elif quiet_mode:
    config.default_level = "WARN"
```

**LoggerFactory Integration** (main.py:127-132):
```python
LoggerFactory.initialize(
    config=config,
    verbose=debug_mode or verbose_mode,
    quiet=quiet_mode,
    force=True,
)
```

### Level Mapping

| Mode | Flag | Console Level | Categories Shown |
|------|------|---------------|------------------|
| Default | (none) | INFO | workflow, agent, batch |
| Verbose | `-v` or `--verbose` | DEBUG | all categories |
| Debug | `--debug` | DEBUG | all categories + source refs |
| Quiet | `-q` or `--quiet` | WARN | all categories (WARN+ only) |

### Testing

Verified that:
- ✅ Default mode sets EventLevel.INFO
- ✅ Verbose mode sets EventLevel.DEBUG
- ✅ Quiet mode sets EventLevel.WARN
- ✅ Flags appear in `--help` output
- ✅ Flags are global and work with all commands

### CLI Help Output

```
Options:
  --version      Show the version and exit.
  --debug        Enable debug mode with verbose logging and source file/line
                 references
  -v, --verbose  Enable verbose output
  -q, --quiet    Show only warnings and errors
  --help         Show this message and exit.
```

### Notes

- The `--verbose` flag was already implemented, only `--quiet` was added
- LoggerFactory.initialize() already had support for the quiet parameter
- All flags are global options available to all subcommands
- More verbose flags take precedence when multiple are provided (debug > verbose > default > quiet)
