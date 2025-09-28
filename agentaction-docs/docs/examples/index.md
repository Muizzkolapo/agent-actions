---
title: Examples
description: Real-world examples and sample configurations for Agent Actions
sidebar_position: 4
---

# Examples

Learn by example with real-world workflows and configurations that demonstrate Agent Actions capabilities.

## Configuration Examples

Ready-to-use workflow configurations that showcase best practices and advanced features.

### Educational Quiz Generation

**Configuration File**: [qanalabs-quiz-gen-migrated.yml](./configurations/qanalabs-quiz-gen-migrated.yml)

A comprehensive workflow for generating educational quizzes from content, featuring:

- **Modern YAML format** with `actions` and `plan` structure
- **Additive defaults** for `drops` and `observe` fields - demonstrates the new DRY approach
- **Complex processing pipeline**: fact extraction → clustering → validation → quiz generation
- **Loop actions** for generating multiple choice distractors
- **Advanced field control** for LLM prompt optimization

**Key Features Demonstrated:**
- ✅ **Composable configurations** using additive defaults
- ✅ **Tool workflows** for data transformation
- ✅ **Conditional logic** with guard clauses
- ✅ **Multi-stage validation** and quality checks
- ✅ **Schema-driven outputs** for structured data

This example shows how to build maintainable, DRY configurations by extracting common field patterns to defaults while allowing action-specific customization.

## Coming Soon

- **API Integration Examples**: Connect external services and APIs
- **Multi-Modal Workflows**: Handle text, images, and structured data
- **Performance Optimization**: Large-scale processing patterns
- **Custom Validators**: Build domain-specific validation logic
- **Error Handling**: Robust failure recovery patterns

## Using Examples

All examples are production-ready configurations that you can:

1. **Copy and customize** for your specific use case
2. **Learn from** to understand best practices
3. **Extend** with additional actions and features
4. **Test** in your own environment

Each example includes detailed comments explaining the workflow logic and design decisions.

## Contributing Examples

Have a great workflow to share? We'd love to include community examples that demonstrate:

- Novel use cases and applications
- Best practices and optimization techniques
- Integration patterns with external tools
- Domain-specific workflows (healthcare, finance, education, etc.)

Submit examples via pull request with clear documentation and usage instructions.