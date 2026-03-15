"""Guard reference validation functions extracted from ActionExpander."""

from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.field_resolution import ReferenceParser, ReferenceValidator


def build_schema_registry(agents: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build schema registry from agent configs.

    Args:
        agents: List of agent configurations

    Returns:
        Dictionary mapping agent names to their JSON output schemas
    """
    action_schemas: dict[str, Any] = {}
    for agent in agents:
        agent_name = agent.get("agent_type") or agent.get("name", "unknown")

        # Add schema if present (both LLM and UDF actions can have schemas)
        if agent.get("json_output_schema"):
            action_schemas[agent_name] = agent["json_output_schema"]

    return action_schemas


def validate_agent_guards(
    agent: dict[str, Any],
    validator: ReferenceValidator,
    agent_indices: dict[str, int],
    action_schemas: dict[str, Any],
) -> list[str]:
    """
    Validate guard references for a single agent.

    Args:
        agent: Agent configuration
        validator: Reference validator instance
        agent_indices: Mapping of agent names to indices
        action_schemas: Mapping of agent names to schemas

    Returns:
        List of error messages
    """
    errors = []
    agent_name = agent.get("agent_type") or agent.get("name", "unknown")

    # Check guard conditions
    guard = agent.get("guard")
    if guard and isinstance(guard, dict):
        clause = guard.get("clause", "")
        if clause:
            parser = ReferenceParser()
            references = parser.parse_batch(clause)

            guard_errors = validator.validate_with_schemas(
                references=list(references),
                validation_context={
                    "agent_config": agent,
                    "agent_indices": agent_indices,
                    "action_schemas": action_schemas,
                    "current_agent_name": agent_name,
                },
            )
            errors.extend(guard_errors)

    # Check conditional_clause (UDF guards)
    conditional_clause = agent.get("conditional_clause")
    if conditional_clause and isinstance(conditional_clause, str):
        parser = ReferenceParser()
        references = parser.parse_batch(conditional_clause)

        guard_errors = validator.validate_with_schemas(
            references=list(references),
            validation_context={
                "agent_config": agent,
                "agent_indices": agent_indices,
                "action_schemas": action_schemas,
                "current_agent_name": agent_name,
            },
        )
        errors.extend(guard_errors)

    return errors


def validate_guard_references(agents: list[dict[str, Any]], strict: bool = True) -> list[str]:
    """
    Validate that guard conditions only reference valid upstream actions.

    This should be called after expand_actions_to_agents() to ensure all
    guard field references (e.g., "extract_facts.count > 5") reference
    actions that exist and are upstream in the dependency graph.

    Args:
        agents: List of agent configurations from expand_actions_to_agents()
        strict: If True, raise exception on validation errors. If False,
               return list of error messages.

    Returns:
        List of error messages (empty if all valid)

    Raises:
        ConfigValidationError: If strict=True and validation fails

    Example:
        config = {'name': 'my_workflow', 'actions': [...]}
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result['my_workflow']

        # Validate guard references
        errors = ActionExpander.validate_guard_references(agents, strict=False)
        if errors:
            for error in errors:
                logger.warning(error)
    """
    errors = []
    validator = ReferenceValidator(strict_dependencies=True)

    # Build agent_indices from the list
    agent_indices: dict[str, int] = {}
    for idx, agent in enumerate(agents):
        agent_name: str = agent.get("agent_type") or agent.get("name") or f"unknown_{idx}"
        agent_indices[agent_name] = idx

    # Build schema registry from agent configs
    action_schemas = build_schema_registry(agents)

    # Validate each agent's guard references with schemas
    for agent in agents:
        agent_errors = validate_agent_guards(agent, validator, agent_indices, action_schemas)
        errors.extend(agent_errors)

    # Handle strict mode
    if strict and errors:
        raise ConfigValidationError(
            config_key="guard",
            reason="Guard references invalid actions",
            context={
                "errors": errors,
                "hint": (
                    "Ensure guard conditions only reference actions that are "
                    "declared in the dependencies list and exist in the workflow."
                ),
            },
        )

    return errors
