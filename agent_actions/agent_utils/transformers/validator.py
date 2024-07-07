# agent_utils/validator.py

def validate_agent_config(agent_config):
    """
    Validate the agent configuration to ensure that only the first agent can have no dependencies
    and all subsequent agents have at least one dependency.

    :param agent_config: The list of agent configurations.
    :return: Tuple (is_valid, message). is_valid is True if the configuration is valid, False otherwise.
             message contains the error message if the configuration is invalid.
    """
    for idx, agent in enumerate(agent_config):
        if idx == 0:
            # The first agent can have no dependencies
            if agent['dependencies']:
                return False, f"The first agent '{agent['agent_type']}' should have no dependencies."
        else:
            # All other agents must have at least one dependency
            if not agent['dependencies']:
                return False, f"The agent '{agent['agent_type']}' must have at least one dependency."

    return True, "Agent configuration is valid."
