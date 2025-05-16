from pathlib import Path
# Assuming ProjectValidator is in validators.project_validator
from agent_actions.cli.validators.project_validator import ProjectValidator

# Example usage:
validator = ProjectValidator()
project_data = {
    "project_name": "My-Project_123",
    "output_dir": Path("/mnt/data/projects"),
    "project_dir": Path("/mnt/data/projects/My-Project_123"),
    "template": "basic_web_app",
    "available_templates": ["basic_web_app", "data_science_proj", "cli_tool"],
    "force": False
}

if validator.validate(project_data):
    print("Project parameters are valid!")
    # Proceed with project creation
else:
    print("Project validation failed:")
    for error in validator.get_errors():
        print(f"- {error}")
    # Handle errors appropriately