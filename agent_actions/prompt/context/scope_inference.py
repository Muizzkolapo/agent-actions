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
    "expand_version_base_names",
    "infer_dependencies",
]


def expand_version_base_names(action_list: list[str], workflow_actions: list[str]) -> list[str]:
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


def infer_dependencies(
    action_config: dict,
    workflow_actions: list[str],
    action_name: str = "unknown",
    *,
    validate: bool = True,
) -> tuple[list[str], list[str]]:
    """
    Infer input sources and context sources from action configuration.

    - every action in `dependencies` is an input source: a run reads each one's records
      and merges them by source record, so their order changes nothing;
    - an action named in `context_scope` or the prompt but not in `dependencies` is a
      context source.

    Args:
        action_config: Action configuration dict containing dependencies and context_scope
        workflow_actions: List of all action names in the workflow (for validation)
        action_name: Name of current action (for error messages)

    Returns:
        Tuple of (input_sources, context_sources):
        - input_sources: List of actions that provide input files
        - context_sources: List of actions that provide context only (loaded from record namespaces)

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
    # 1. Explicit dependencies are the input sources
    deps = action_config.get("dependencies", [])
    if deps is None:
        input_sources = []
    elif isinstance(deps, str):
        input_sources = [deps]
    else:
        input_sources = list(deps)

    # 2. Parse context_scope to find all referenced actions. Coerced here rather than at
    # each caller: seven of them pass an action config, and the docs parser and inspect
    # read it straight from YAML, where `context_scope:` null or a scalar survives (#1193).
    context_scope = action_config.get("context_scope")
    if not isinstance(context_scope, dict):
        context_scope = {}
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
    # sorted(): this is a set, so iterating it leaks hash randomisation into catalog.json.
    # Declaration order is available for the refs that came from context_scope, but not for
    # the ones inferred from the prompt template, so one rule for the whole tail beats a
    # hybrid. Nothing is lost either way: the order here was hash-random before.
    context_sources = sorted(referenced_actions - set(input_sources))

    # 4. Expand version base names to their variants (e.g., extract_raw_qa -> [extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3])
    # This handles version_consumption where context_scope references the base name
    # Expand both input_sources and context_sources
    input_sources_expanded = expand_version_base_names(input_sources, workflow_actions)
    context_sources_expanded = expand_version_base_names(context_sources, workflow_actions)
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
