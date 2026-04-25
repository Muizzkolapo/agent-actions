"""Dependency inference for context scope resolution."""

import logging

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import (
    ContextDependencyInferredEvent,
    ContextFieldSkippedEvent,
)
from agent_actions.prompt.context.scope_parsing import (
    extract_action_names_from_context_scope,
    extract_action_names_from_template,
    parse_field_reference,
)
from agent_actions.utils.constants import SPECIAL_NAMESPACES

logger = logging.getLogger(__name__)

__all__ = [
    "infer_dependencies",
]


def _get_base_name(action_name: str) -> str:
    """
    Strip trailing _N suffix to get base action name.

    Examples:
        'classify_1' -> 'classify'
        'research_10' -> 'research'
        'extract_raw_qa_2' -> 'extract_raw_qa'
        'validate' -> 'validate' (no suffix)
    """
    parts = action_name.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return action_name


def _is_parallel_branches(dependencies: list[str]) -> bool:
    """
    Detect if dependencies are parallel branches of the same action.

    Parallel branches have the same base name with numeric suffixes:
    - ['classify_1', 'classify_2', 'classify_3'] -> True (all 'classify')
    - ['extract', 'enrich', 'validate'] -> False (different actions)
    - ['classify'] -> True (single = trivially parallel)

    Note: Different base names with same suffix are NOT parallel:
    - ['classify_text_1', 'classify_image_1'] -> False (different base names)

    Args:
        dependencies: List of dependency action names

    Returns:
        True if all dependencies are branches of same action, False if fan-in
    """
    if len(dependencies) <= 1:
        return True  # Single or empty is trivially "parallel"

    base_names = {_get_base_name(dep) for dep in dependencies}
    return len(base_names) == 1


def _get_version_branches(base_name: str, dependencies: list[str]) -> list[str]:
    """
    Find all dependencies that are version branches of a base name.

    Examples:
        _get_version_branches('research', ['research_1', 'research_2', 'summarize'])
        -> ['research_1', 'research_2']

        _get_version_branches('classify', ['classify_text_1', 'classify_image_1'])
        -> []  (these have different base names)

    Args:
        base_name: The base action name to match
        dependencies: List of dependency action names

    Returns:
        List of dependencies that are versions of base_name
    """
    return [
        d
        for d in dependencies
        if d.startswith(f"{base_name}_") and d[len(base_name) + 1 :].isdigit()
    ]


def _resolve_input_sources_for_fan_in(
    dependencies: list[str],
    primary_dependency: str | None = None,
) -> tuple[list[str], list[str]]:
    """
    Resolve which dependencies are input sources vs context sources for fan-in pattern.

    Used by infer_dependencies() for prompt context classification.

    Args:
        dependencies: List of all dependency action names
        primary_dependency: Optional explicit primary override

    Returns:
        Tuple of (input_sources, context_sources)

    Raises:
        ValueError: If primary_dependency is invalid (not found in deps or as base name)
    """
    if primary_dependency is None:
        # No explicit primary - use first dependency
        # But if first dep is a version branch, include ALL sibling branches
        first_dep = dependencies[0]
        base_name = _get_base_name(first_dep)
        sibling_branches = _get_version_branches(base_name, dependencies)

        if sibling_branches and first_dep in sibling_branches:
            # First dep is a version branch - include all siblings as input
            input_sources = sibling_branches
        else:
            # First dep is not versioned - just use it
            input_sources = [first_dep]
    elif primary_dependency in dependencies:
        # Explicit primary exists in deps - check if it's versioned
        base_name = _get_base_name(primary_dependency)
        sibling_branches = _get_version_branches(base_name, dependencies)

        if sibling_branches and primary_dependency in sibling_branches:
            # Primary is a version branch - include all siblings
            input_sources = sibling_branches
        else:
            # Primary is not versioned - just use it
            input_sources = [primary_dependency]
    else:
        # Primary is a base name - expand to all version branches
        version_branches = _get_version_branches(primary_dependency, dependencies)
        if version_branches:
            input_sources = version_branches
        else:
            raise ValueError(
                f"primary_dependency '{primary_dependency}' not found in "
                f"dependencies list {dependencies} (also checked as base name)"
            )

    context_sources = [d for d in dependencies if d not in input_sources]
    return input_sources, context_sources


def infer_dependencies(
    action_config: dict,
    workflow_actions: list[str],
    action_name: str = "unknown",
    *,
    validate: bool = True,
) -> tuple[list[str], list[str]]:
    """
    Infer input sources and context sources from action configuration.

    This method implements the simplified dependency model where:
    - `dependencies` field = input sources (determines execution count)
    - Actions in `context_scope` but NOT in `dependencies` = context sources (auto-inferred)

    Args:
        action_config: Action configuration dict containing dependencies and context_scope
        workflow_actions: List of all action names in the workflow (for validation)
        action_name: Name of current action (for error messages)

    Returns:
        Tuple of (input_sources, context_sources):
        - input_sources: List of actions that provide input files
        - context_sources: List of actions that provide context only (loaded via historical loader)

    Raises:
        ConfigurationError: If a referenced action doesn't exist in workflow

    Example:
        action_config = {
            "dependencies": "add_answer_text",
            "context_scope": {
                "observe": [
                    "add_answer_text.*",
                    "suggest_distractor_counts.*",
                    "write_scenario_question.question"
                ]
            }
        }
        workflow_actions = ["extract", "flatten", "add_answer_text", "suggest_distractor_counts", "write_scenario_question"]

        Returns:
            (["add_answer_text"], ["suggest_distractor_counts", "write_scenario_question"])
    """
    # 1. Get explicit dependencies (input sources)
    # Support both 'dependencies' and 'depends_on' for backward compatibility
    deps = action_config.get("dependencies") or action_config.get("depends_on", [])
    if deps is None:
        all_deps = []
    elif isinstance(deps, str):
        all_deps = [deps]
    else:
        all_deps = list(deps)

    # 1b. Handle fan-in pattern: multiple DIFFERENT dependencies
    # For fan-in, only the primary dependency is an input source
    # The rest become context sources (loaded via historical loader with lineage matching)
    #
    # Exception: If reduce_key is set, it's an aggregation pattern - all are input sources
    #
    # Versioned primary handling: If primary_dependency is a base name (e.g., "research")
    # that matches version branches (research_1, research_2), ALL matching branches
    # become input sources.
    fan_in_context_sources: list[str] = []
    has_reduce_key = action_config.get("reduce_key") is not None
    is_parallel = _is_parallel_branches(all_deps)

    if len(all_deps) > 1 and not is_parallel and not has_reduce_key:
        # Fan-in detected - use shared helper
        primary_dep = action_config.get("primary_dependency")
        try:
            input_sources, fan_in_context_sources = _resolve_input_sources_for_fan_in(
                all_deps, primary_dep
            )
        except ValueError as e:
            raise ConfigurationError(
                f"Action '{action_name}': {e}",
                context={"action": action_name, "operation": "resolve_fan_in_sources"},
                cause=e,
            ) from e

        logger.debug(
            "Action '%s': Fan-in detected with dependencies %s. "
            "Input sources: %s. "
            "Context sources (lineage-matched): %s",
            action_name,
            all_deps,
            input_sources,
            fan_in_context_sources,
        )
    else:
        # Single dependency, parallel branches, or aggregation (reduce_key) - all are input sources
        input_sources = all_deps

    # 2. Parse context_scope to find all referenced actions
    context_scope = action_config.get("context_scope", {})
    referenced_actions = extract_action_names_from_context_scope(context_scope)

    # 2a. Auto-infer from prompt template (if no context_scope configured)
    # This enables {{ upstream_action.field }} references to work without explicit context_scope
    from agent_actions.prompt.formatter import PromptFormatter

    try:
        raw_prompt = PromptFormatter.get_raw_prompt(action_config)
        if raw_prompt:
            template_actions = extract_action_names_from_template(raw_prompt)
            # Only add template-referenced actions that are valid workflow actions
            valid_template_actions = template_actions & set(workflow_actions)
            if valid_template_actions - referenced_actions:
                logger.debug(
                    f"[TEMPLATE-INFER] Action '{action_name}': Auto-inferred context sources "
                    f"from template: {valid_template_actions - referenced_actions}"
                )
            referenced_actions = referenced_actions | valid_template_actions
    except Exception as e:
        logger.debug(
            "Prompt retrieval failed for template inference on '%s': %s",
            action_name,
            e,
            exc_info=True,
        )

    # 2b. Identify wildcard actions from context_scope
    wildcard_actions = set()
    all_field_refs = []
    all_field_refs.extend(context_scope.get("observe", []))
    all_field_refs.extend(context_scope.get("passthrough", []))
    for field_ref in all_field_refs:
        try:
            ref_action, ref_field = parse_field_reference(field_ref)
            if ref_field == "*":
                wildcard_actions.add(ref_action)
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=field_ref,
                    reason=str(e),
                    directive="infer_dependencies",
                )
            )
            continue

    # 3. Auto-infer context sources (in context_scope but NOT in dependencies)
    # Also include fan-in context sources (non-primary dependencies from fan-in pattern)
    potential_context_sources = (
        referenced_actions - set(input_sources) - set(fan_in_context_sources)
    )
    context_sources = list(fan_in_context_sources)  # Start with fan-in context sources
    for action in potential_context_sources:
        context_sources.append(action)

    # 4. Expand version base names to their variants (e.g., extract_raw_qa -> [extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3])
    # This handles version_consumption where context_scope references the base name
    def expand_version_base_names(
        action_list: list[str],
    ) -> list[str]:
        """Expand version base names to their actual variants in the workflow."""
        expanded = []
        for action in action_list:
            if action in workflow_actions:
                # Action exists as-is
                expanded.append(action)
            else:
                # Check if this is a version base name
                version_variants = [
                    wf_action
                    for wf_action in workflow_actions
                    if wf_action.startswith(f"{action}_") and wf_action[len(action) + 1 :].isdigit()
                ]
                if version_variants:
                    # Expand to all variants. For context sources with wildcards, we still
                    # expand to concrete version names so they can be loaded via agent_indices.
                    expanded.extend(version_variants)
                    logger.debug(
                        f"[VERSION_EXPAND] Expanded version base name '{action}' to {version_variants}"
                    )
                else:
                    # Not a version base name - keep as-is (will error in validation)
                    expanded.append(action)
        return expanded

    # Expand both input_sources and context_sources
    input_sources_expanded = expand_version_base_names(input_sources)
    context_sources_expanded = expand_version_base_names(context_sources)
    # Avoid loading context sources already provided via input sources.
    if input_sources_expanded:
        input_sources_set = set(input_sources_expanded)
        context_sources_expanded = [
            dep for dep in context_sources_expanded if dep not in input_sources_set
        ]

    # 5. Validate all referenced actions exist in workflow
    # Skipped at runtime (validate=False) because the static validator
    # already caught invalid references during preflight.
    if validate:
        all_referenced = set(input_sources_expanded) | set(context_sources_expanded)
        for dep_action in all_referenced:
            if dep_action in SPECIAL_NAMESPACES:
                continue

            if dep_action not in workflow_actions:
                raise ConfigurationError(
                    f"Action '{action_name}': References '{dep_action}' in dependencies/context_scope "
                    f"but '{dep_action}' not found in workflow.\n\n"
                    f"Available actions: {workflow_actions}",
                    context={
                        "action": action_name,
                        "missing_action": dep_action,
                        "workflow_actions": workflow_actions,
                        "input_sources": input_sources_expanded,
                        "context_sources": context_sources_expanded,
                    },
                )

    logger.debug(
        f"[INFER_DEPS] Action '{action_name}': "
        f"input_sources={input_sources_expanded}, context_sources={context_sources_expanded}"
    )

    # Fire event for successful inference
    fire_event(
        ContextDependencyInferredEvent(
            action_name=action_name,
            input_sources=input_sources_expanded,
            context_sources=context_sources_expanded,
        )
    )

    return input_sources_expanded, context_sources_expanded
