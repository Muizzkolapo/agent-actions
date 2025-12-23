"""
Field Resolution Module - Centralized field reference parsing and resolution.

This module provides a unified API for field reference operations across
guards, prompts, filters, and context_scope directives.

Key Components:
- FieldReferenceResolver: Main entry point for parsing and resolving references
- EvaluationContextProvider: Builds rich context for guard/filter evaluation
- ReferenceValidator: Validates references against dependency graph
- ParsedReference: Structured representation of a parsed reference
- EvaluationContext: Rich context with upstream action data

Example - Resolving field references:
    from agent_actions.utilities.field_resolution import FieldReferenceResolver

    resolver = FieldReferenceResolver()

    # Parse a reference
    ref = resolver.parse("extract_facts.count")

    # Resolve to value
    result = resolver.resolve(ref, field_context)
    print(result.value)  # 5

Example - Building guard evaluation context:
    from agent_actions.utilities.field_resolution import EvaluationContextProvider

    provider = EvaluationContextProvider()

    # Build context with upstream data
    context = provider.build_context(
        current_item=item,
        agent_config=config,
        agent_name='my_action',
        agent_indices=indices,
        file_path=path
    )

    # Now guards can access upstream fields!
    eval_data = context.to_flat_dict()
    # WHERE clause "extract_facts.count > 5" will work

Example - Validating guard references:
    from agent_actions.utilities.field_resolution import ReferenceValidator

    validator = ReferenceValidator()

    errors = validator.extract_and_validate(
        guard_condition="extract.count > 5 AND source.type == 'doc'",
        agent_config=config,
        agent_indices=indices
    )

    if errors:
        raise WorkflowValidationError("\\n".join(errors))
"""

# Core resolver
from .field_reference_resolver import (
    FieldReferenceResolver,
    ResolvedReference,
)

# Parser and data classes
from .reference_parser import (
    ReferenceParser,
    ParsedReference,
    ReferenceFormat,
)

# Context provider
from .evaluation_context_provider import (
    EvaluationContextProvider,
    EvaluationContext,
)

# Validator
from .reference_validator import (
    ReferenceValidator,
    SPECIAL_NAMESPACES,
)

# Exceptions
from .exceptions import (
    FieldResolutionError,
    InvalidReferenceError,
    ReferenceNotFoundError,
    DependencyValidationError,
    SchemaFieldValidationError,
)


__all__ = [
    # Core resolver
    'FieldReferenceResolver',
    'ResolvedReference',

    # Parser
    'ReferenceParser',
    'ParsedReference',
    'ReferenceFormat',

    # Context
    'EvaluationContextProvider',
    'EvaluationContext',

    # Validation
    'ReferenceValidator',
    'SPECIAL_NAMESPACES',

    # Exceptions
    'FieldResolutionError',
    'InvalidReferenceError',
    'ReferenceNotFoundError',
    'DependencyValidationError',
    'SchemaFieldValidationError',
]
