# Error Handling Pattern - Implementation Plan

## Overview
This document provides a concrete implementation plan for the Context-Aware Error Handling pattern to fix issue #394.

## Implementation Phases

### Phase 0: User-Facing Error Formatting (Priority: CRITICAL)
**Timeline:** Week 1 - Days 1-2

#### 0.1 Create Core Infrastructure
```python
# agent_actions/core/error_context.py
# agent_actions/core/error_handler.py
# agent_actions/core/safe_format.py
```

**Tasks:**
1. Create error_context.py with decorators
2. Create error_handler.py with StandardErrorHandler
3. Create safe_format.py with safe_format_error()
4. Add UserFriendlyError exception class

#### 0.2 Create CLI-Specific Handler
```python
# agent_actions/cli/friendly_errors.py
```

**Tasks:**
1. Create CLIErrorHandler extending StandardErrorHandler
2. Add specific message formatting for each error type
3. Add debug mode support

---

### Phase 1: Fix Critical __str__ Methods (Priority: HIGH)
**Timeline:** Week 1 - Day 3

#### 1.1 Fix Base Exception Class
```python
# agent_actions/core/exceptions.py - Line 70-76
```

**Current Problem:**
```python
def __str__(self) -> str:
    context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())  # CRASHES if context is string!
```

**Fix:**
```python
def __str__(self) -> str:
    try:
        base_msg = super().__str__()
        if self.context:
            if isinstance(self.context, dict):
                context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
                return f"{base_msg} [Context: {context_str}]"
            else:
                return f"{base_msg} [Context: {self.context}]"
        return base_msg
    except:
        return self.message or "Exception occurred"
```

---

### Phase 2: Fix Root Cause Issues (Priority: HIGH)
**Timeline:** Week 1 - Day 4

#### 2.1 Fix ConfigurationError Call
```python
# agent_actions/tasks/services/batch_service.py - Line 243
```

**Current Problem:**
```python
raise ConfigurationError(f"batch_provider_{provider_type}", f"Failed to create provider: {e}", cause=e)
# Second argument is string, but should be dict!
```

**Fix:**
```python
raise ConfigurationError(
    f"Failed to create batch provider: {provider_type}",
    context={'provider': provider_type, 'error': safe_format_error(e)},
    cause=e
)
```

---

### Phase 2.5: Fix CLI Commands (Priority: HIGH)
**Timeline:** Week 1 - Day 5 & Week 2 - Day 1

#### 2.5.1 Update Main CLI Entry Point
```python
# agent_actions/cli/main.py - Line 147-154
```

**Apply pattern to all 8 CLI commands:**
- agent_actions/tasks/run.py (lines 92, 95)
- agent_actions/tasks/batch.py (lines 27, 48)
- agent_actions/tasks/docs.py (lines 94, 113, 116, 143)
- agent_actions/tasks/test.py (line 40)
- agent_actions/tasks/compile.py (lines 84, 89, 120)
- agent_actions/tasks/init.py (lines 114, 117, 147)
- agent_actions/tasks/status.py (lines 64, 79)

**Template for each command:**
```python
from agent_actions.cli.friendly_errors import CLIErrorHandler

error_handler = CLIErrorHandler(__name__)

@click.command()
def command():
    try:
        # command logic
    except Exception as e:
        user_error = error_handler.wrap_for_cli(e)
        click.echo(f"Error: {user_error.user_message}", err=True)

        if '--debug' in sys.argv:
            click.echo("\n--- Debug Information ---", err=True)
            traceback.print_exc()

        raise click.Abort()
```

---

### Phase 3: Systematic str(e) Replacement (Priority: MEDIUM)
**Timeline:** Week 2 - Days 2-3

#### 3.1 High-Priority Files
Replace all `str(e)` with `safe_format_error(e)`:

1. **agent_actions/agents/generators/target_generator.py** (line 141)
2. **agent_actions/core/tooling.py** (line 102)
3. **agent_actions/agents/transformers/string_transformer.py** (5 occurrences)
4. **agent_actions/agents/handlers/*.py** (multiple files)
5. **agent_actions/integrations/providers/*.py** (API providers)

**Search and replace pattern:**
```bash
# Find all str(e) calls
grep -r "str(e)" agent_actions/ --include="*.py"

# Replace with safe_format_error(e)
```

---

### Phase 4: Add Decorators (Priority: MEDIUM)
**Timeline:** Week 2 - Days 4-5

#### 4.1 Decorate Key Functions
Add context decorators to functions that handle:
- Agent operations
- File operations
- API calls
- Configuration loading

**Example:**
```python
@with_error_context(operation="load_agent", resource_type="agent")
def load_agent(agent_name: str):
    # existing code
```

---

### Phase 5: Testing (Priority: HIGH)
**Timeline:** Week 3 - Days 1-2

#### 5.1 Create Test Suite
```python
# tests/core/test_error_handling.py
```

**Test cases:**
1. Broken __str__ methods
2. String context vs dict context
3. Exception chaining
4. Safe formatting fallbacks
5. CLI error display
6. Debug mode output

#### 5.2 Integration Tests
Test actual error paths:
- Invalid model name
- Missing config file
- API authentication failure
- Schema validation error

---

### Phase 6: Documentation (Priority: LOW)
**Timeline:** Week 3 - Day 3

1. Update CONTRIBUTING.md with error handling guidelines
2. Add examples to design_patterns/
3. Create troubleshooting guide for users

---

## Rollout Strategy

### Week 1: Critical Fixes
- Days 1-2: Core infrastructure (Phase 0)
- Day 3: Fix __str__ methods (Phase 1)
- Day 4: Fix root causes (Phase 2)
- Day 5: Start CLI updates (Phase 2.5)

### Week 2: Systematic Updates
- Day 1: Complete CLI updates
- Days 2-3: Replace str(e) calls (Phase 3)
- Days 4-5: Add decorators (Phase 4)

### Week 3: Testing & Documentation
- Days 1-2: Comprehensive testing (Phase 5)
- Day 3: Documentation (Phase 6)

---

## Success Metrics

### Immediate Success (Week 1)
- [ ] No more `'str' object has no attribute 'items'` errors
- [ ] CLI shows user-friendly messages
- [ ] Debug mode available for developers

### Full Success (Week 3)
- [ ] All str(e) calls replaced
- [ ] All CLI commands use pattern
- [ ] Comprehensive test coverage
- [ ] Documentation complete

---

## Risk Mitigation

### Risk 1: Breaking Existing Code
**Mitigation:**
- Make changes backward compatible
- Add try/catch in __str__ methods
- Test each phase before proceeding

### Risk 2: Incomplete Coverage
**Mitigation:**
- Use grep to find all instances
- Code review checklist
- Automated linting rules

### Risk 3: Performance Impact
**Mitigation:**
- Decorators are lightweight
- Context capture is lazy
- Only format errors when needed

---

## Validation Checklist

After each phase, verify:

- [ ] No Python tracebacks shown to users
- [ ] Error messages are actionable
- [ ] Context is preserved through chain
- [ ] Debug mode shows full details
- [ ] Tests pass
- [ ] No new str(e) calls introduced

---

## Quick Start for Engineers

### To fix a module:

1. **Import the tools:**
```python
from agent_actions.core.error_context import with_error_context
from agent_actions.core.error_handler import StandardErrorHandler
from agent_actions.core.safe_format import safe_format_error
```

2. **Create handler:**
```python
error_handler = StandardErrorHandler(__name__)
```

3. **Decorate functions:**
```python
@with_error_context(operation="your_operation", resource_type="your_resource")
def your_function(param: str):
    pass
```

4. **Handle exceptions:**
```python
try:
    result = do_work()
except Exception as e:
    message = error_handler.handle(e)
    # Use message for display
```

That's it! The pattern handles the rest.