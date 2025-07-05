# Example: Validate agent entries
from agent_actions.cli.validators.config_validator import ConfigValidator

config_val = ConfigValidator()
my_agent_config_data = [
    {"agent_type": "llm", "name": "MyAgent", "model": "gpt-4"},
    {"agent_type": "function", "name": "MyHelper", "code_path": "src/helpers.py"}
]
project_root = "/path/to/my/project"

data_for_entries = {
    "operation": "validate_agent_entries",
    "agent_config_data": my_agent_config_data,
    "agent_name": "MyAgentConfig", # Contextual name for this config block
    "project_dir": project_root
}

if config_val.validate(data_for_entries):
    print("Agent entries are valid.")
else:
    print("Agent entry validation failed:")
    for error in config_val.get_errors():
        print(f" - {error}")

# Example: Check if an agent name is unique
data_for_name_check = {
    "operation": "check_agent_name_unique",
    "agent_name": "MyAgent",
    "project_dir": project_root,
    "current_file_path": "/path/to/my/project/agent_config/MyAgent.yaml" # Optional context
}
if config_val.validate(data_for_name_check):
    print("Agent name is unique (or no conflicts found with others).")
else:
    print("Agent name uniqueness check failed:")
    for error in config_val.get_errors():
        print(f" - {error}")