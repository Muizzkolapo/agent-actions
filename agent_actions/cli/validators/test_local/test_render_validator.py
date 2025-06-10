from pathlib import Path
from validators.render_validator import RenderValidator # Adjust import as needed
# Assuming FileHandler is set up and agent_actions.handlers.file_handler exists
# For this example, we might need to mock FileHandler or set up a dummy structure

# Setup for a mock FileHandler for the example to run without the actual FileHandler setup
class MockFileHandler:
    @staticmethod
    def get_agent_paths(agent_name):
        if agent_name == "my_agent":
            # Simulate finding agent paths
            mock_agent_dir = Path(f"/tmp/mock_agents/{agent_name}_config_dir")
            mock_agent_dir.mkdir(parents=True, exist_ok=True)
            return (str(mock_agent_dir), "mock_type", "mock_description")
        return (None, None, None)

    @staticmethod
    def find_config_file(directory_str, filename):
        config_path = Path(directory_str) / filename
        if filename == "my_agent.yml" and "my_agent" in directory_str : # Check specific agent
            # Simulate finding the config file
            config_path.touch(exist_ok=True)
            return str(config_path)
        return None

# Replace the actual FileHandler with the mock for the example
# This is a common technique for testing or running examples in isolation.
# In your actual code, you would import the real FileHandler.
import sys
if 'agent_actions.handlers.file_handler' not in sys.modules:
    # Mock the module if it's not available for the example
    from unittest.mock import MagicMock
    sys.modules['agent_actions.handlers.file_handler'] = MagicMock(FileHandler=MockFileHandler)
else: # If it is available, ensure our mock can be used if desired for this specific test
    original_file_handler = sys.modules['agent_actions.handlers.file_handler'].FileHandler
    sys.modules['agent_actions.handlers.file_handler'].FileHandler = MockFileHandler # Override for this example


validator = RenderValidator()

# --- Example 1: Validate agent paths ---
print("\n--- Validating Agent Paths ---")
data_agent = {"agent_name": "my_agent"}
if validator.validate(data_agent):
    print(f"Agent path validation for '{data_agent['agent_name']}' passed.")
else:
    print(f"Agent path validation for '{data_agent['agent_name']}' failed:")
    for err in validator.get_errors(): print(f"  - {err}")

data_bad_agent = {"agent_name": "non_existent_agent"}
if validator.validate(data_bad_agent):
    print(f"Agent path validation for '{data_bad_agent['agent_name']}' passed (unexpectedly).")
else:
    print(f"Agent path validation for '{data_bad_agent['agent_name']}' failed:")
    for err in validator.get_errors(): print(f"  - {err}")


# --- Example 2: Validate template directory ---
print("\n--- Validating Template Directory ---")
valid_template_dir = Path("/tmp/my_template_dir")
valid_template_dir.mkdir(exist_ok=True) # Ensure it exists
data_template = {"template_dir": valid_template_dir}
if validator.validate(data_template):
    print(f"Template directory validation for '{valid_template_dir}' passed.")
else:
    print(f"Template directory validation for '{valid_template_dir}' failed:")
    for err in validator.get_errors(): print(f"  - {err}")

invalid_template_dir = Path("/tmp/non_existent_template_dir")
data_bad_template = {"template_dir": invalid_template_dir}
if validator.validate(data_bad_template):
    print(f"Template directory validation for '{invalid_template_dir}' passed (unexpectedly).")
else:
    print(f"Template directory validation for '{invalid_template_dir}' failed:")
    for err in validator.get_errors(): print(f"  - {err}")

# --- Example 3: Validate output file ---
print("\n--- Validating Output File ---")
output_dir_for_file = Path("/tmp/output_for_render")
output_dir_for_file.mkdir(exist_ok=True)
data_output = {"output_file": str(output_dir_for_file / "render_output.txt")}
if validator.validate(data_output):
    print(f"Output file validation for '{data_output['output_file']}' passed.")
else:
    print(f"Output file validation for '{data_output['output_file']}' failed:")
    for err in validator.get_errors(): print(f"  - {err}")

# --- Example 4: Validate all aspects ---
print("\n--- Validating All Aspects ---")
data_all = {
    "agent_name": "my_agent",
    "template_dir": valid_template_dir,
    "output_file": str(output_dir_for_file / "all_render_output.txt")
}
if validator.validate(data_all):
    print("Combined render validation passed.")
else:
    print("Combined render validation failed:")
    for err in validator.get_errors(): print(f"  - {err}")

# Clean up mock FileHandler if it was injected for the example
if 'original_file_handler' in locals() :
    sys.modules['agent_actions.handlers.file_handler'].FileHandler = original_file_handler

# Clean up created directories for example
import shutil
shutil.rmtree("/tmp/mock_agents", ignore_errors=True)
shutil.rmtree(valid_template_dir, ignore_errors=True)
shutil.rmtree(output_dir_for_file, ignore_errors=True)