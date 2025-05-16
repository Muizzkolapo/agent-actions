from pathlib import Path
from validators.directory_validator import DirectoryValidator # Adjust import as needed

validator = DirectoryValidator()

# Example 1: Check required directories
data_req_dirs = {
    "operation": "check_required",
    "paths_to_check": [Path("/tmp/existing_dir"), Path("/tmp/another_dir_to_create_later")]
}
# Assuming /tmp/existing_dir exists and /tmp/another_dir_to_create_later does not
# os.makedirs("/tmp/existing_dir", exist_ok=True)

if validator.validate(data_req_dirs):
    print("Required directories check passed (or no errors added).")
else:
    print("Required directories check failed:")
    for err in validator.get_errors():
        print(f"- {err}")

# Example 2: Ensure directories exist (and create them)
data_ensure_dirs = {
    "operation": "ensure_exists",
    "paths_to_check": [Path("/tmp/newly_created_dir_1"), Path("/tmp/newly_created_dir_2")],
    "create_if_missing": True
}
if validator.validate(data_ensure_dirs):
    print("Ensure directories operation completed (check logs for creation, no errors added for this process).")
else:
    print("Ensure directories operation failed:")
    for err in validator.get_errors():
        print(f"- {err}") # Errors would appear if creation failed or a path was not a dir

# Example 3: Check directory structure
# First, create a dummy structure for testing
base = Path("/tmp/test_proj_structure")
if not base.exists(): base.mkdir()
(base / "src").mkdir(exist_ok=True)
(base / "data").mkdir(exist_ok=True)
(base / "src" / "main.py").touch(exist_ok=True)
(base / "data" / "input.csv").touch(exist_ok=True)


data_structure = {
    "operation": "check_structure",
    "base_dir": base,
    "required_structure": {
        "src": {"main.py", "utils.py"}, # utils.py will be missing
        "data": {"input.csv"}
    }
}
if validator.validate(data_structure):
    print("Directory structure check passed.")
else:
    print("Directory structure check failed:")
    for err in validator.get_errors():
        print(f"- {err}")