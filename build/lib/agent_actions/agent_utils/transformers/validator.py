# agent_utils/validator.py

def validate_agent_config(agent_config):
    """
    Validate the agent configuration to ensure all required fields are present and correctly formatted.
    """
    required_keys = {'agent_type', 'model_name', 'api_key', 'schema_name', 'prompt'}

    for idx, agent in enumerate(agent_config):
        # Skip validation for top-level UDFs
        if 'udf' in agent:
            continue
        
        missing_keys = required_keys - agent.keys()
        if missing_keys:
            return False, f"Agent {idx + 1} is missing required keys: {', '.join(missing_keys)}"

        # Ensure dependencies is a list if it exists, otherwise set it to an empty list
        if 'dependencies' in agent and not isinstance(agent['dependencies'], list):
            return False, f"Agent {idx + 1}: 'dependencies' should be a list."
        agent.setdefault('dependencies', [])

    return True, "Agent configuration is valid."
