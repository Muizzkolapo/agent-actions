from pathlib import Path
from validators.project_validator import ProjectValidator # Adjust import as needed

# Setup a dummy project structure for testing
project_root = Path("/tmp/test_project_root")
project_root.mkdir(exist_ok=True)
(project_root / "agent_actions").mkdir(exist_ok=True)
(project_root / "agent_actions" / "workflows").mkdir(exist_ok=True)
(project_root / "agent_actions" / "configs").mkdir(exist_ok=True)
(project_root / "agent_actions" / "prompts").mkdir(exist_ok=True)
(project_root / "agent_actions" / "outputs").mkdir(exist_ok=True)
(project_root / "agent_actions" / "templates").mkdir(exist_ok=True)

# Create a validator instance
validator = ProjectValidator(project_root)

# --- Test Case 1: Valid Project Structure ---
print("--- Running Test Case 1: Valid Project Structure ---")
is_valid = validator.validate()
if is_valid:
    print("Project structure is valid.")
else:
    print("Project structure validation failed:")
    for error in validator.get_errors():
        print(f"- {error}")
print("-" * 20)


# --- Test Case 2: Missing a Directory ---
print("--- Running Test Case 2: Missing Directory ---")
# Temporarily remove a directory to test failure
import shutil
shutil.rmtree(project_root / "agent_actions" / "prompts")

validator_missing_dir = ProjectValidator(project_root)
is_valid_missing = validator_missing_dir.validate()
if not is_valid_missing:
    print("Project structure validation failed as expected.")
    for error in validator_missing_dir.get_errors():
        print(f"- {error}")
else:
    print("Validation passed, but it should have failed.")
print("-" * 20)

# Restore for next tests if any
(project_root / "agent_actions" / "prompts").mkdir(exist_ok=True)


# --- Test Case 3: Custom Paths (if your validator supports them) ---
# This part depends on your implementation of ProjectValidator.
# If it can take custom paths, you would set them up here.
# For example:
# custom_paths = {
#     "workflows": project_root / "my_custom_workflows",
#     ...
# }
# validator_custom = ProjectValidator(project_root, custom_paths=custom_paths)
# ... and so on.

# Cleanup the dummy project structure
shutil.rmtree(project_root)
print("Cleanup complete.")
