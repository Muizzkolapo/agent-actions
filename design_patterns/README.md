# Agent Actions Design Patterns

This directory contains standardized design patterns for the Agent Actions codebase. These patterns ensure consistency, maintainability, and ease of development across the project.

## Purpose

Design patterns in this directory serve as:
- **Reference implementations** for common problems
- **Copy-paste templates** for engineers
- **Code review standards** for maintaining consistency
- **Onboarding documentation** for new team members

## Available Patterns

### 1. [Error Handling Pattern](./error_handling_pattern.md)
**Problem:** Users see Python stack traces instead of helpful configuration errors

**Solution:** Context-aware error handling using decorators and standardized handlers

**When to use:**
- Any function that can raise exceptions
- All CLI commands
- API integrations
- File operations

**Key Components:**
- `@with_error_context()` decorator for automatic context capture
- `StandardErrorHandler` for consistent error formatting
- User-friendly error messages that hide Python internals

---

## How to Use These Patterns

### For New Development

1. **Identify the pattern** that matches your use case
2. **Copy the template** from the pattern documentation
3. **Adapt to your module** while maintaining the core structure
4. **Follow the examples** provided in each pattern

### For Code Reviews

Use the checklists in each pattern to ensure:
- Pattern is correctly implemented
- Anti-patterns are avoided
- Consistency is maintained

### For Refactoring

1. **Identify code** that doesn't follow patterns
2. **Use migration guides** in each pattern
3. **Test thoroughly** after refactoring
4. **Update in phases** as outlined

---

## Contributing New Patterns

When adding a new design pattern:

1. **Create a new markdown file** with the pattern name
2. **Follow this structure:**
   - Problem Statement
   - Solution Overview
   - Core Components (with code)
   - Implementation Patterns
   - Usage Examples
   - Migration Guide
   - Benefits
   - Code Review Checklist
   - Anti-Patterns to Avoid

3. **Include:**
   - Real code examples from the codebase
   - Step-by-step implementation guide
   - Clear benefits and trade-offs
   - Migration path for existing code

4. **Update this README** with the new pattern

---

## Pattern Standards

All patterns should be:

- **Consistent**: Work the same way across the codebase
- **Reusable**: Easy to copy and adapt
- **Testable**: Include testing strategies
- **Documented**: Clear examples and anti-patterns
- **Incremental**: Support gradual adoption

---

## Review Process

Before adopting a new pattern:

1. **Prototype** in a small module first
2. **Document** in this directory
3. **Review** with the team
4. **Pilot** in one area
5. **Roll out** systematically

---

## Questions?

For questions about these patterns:
- Check the pattern documentation first
- Review examples in the codebase
- Ask in team discussions
- Propose improvements via pull requests