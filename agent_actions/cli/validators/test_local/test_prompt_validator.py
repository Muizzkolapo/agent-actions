from pathlib import Path
from validators.prompt_validator import PromptValidator  # Adjust import path as needed

# Initialize the validator
validator = PromptValidator()

# Example 1: Validate a directory of prompts
# Assume you have a directory structure like:
# /tmp/prompts/
#   - prompt1.txt
#   - prompt2.json
#   - invalid.yaml  (if you have specific format requirements)
prompt_dir = Path("/tmp/prompts")
# For demonstration, let's create these files
prompt_dir.mkdir(exist_ok=True)
(prompt_dir / "prompt1.txt").write_text("This is a simple text prompt.")
(prompt_dir / "prompt2.json").write_text('{"key": "value", "template": "Hello, {{name}}"}')
(prompt_dir / "invalid.yaml").write_text('key: value\n- item1') # Potentially invalid based on your rules

# Perform validation
if validator.validate(prompt_dir):
    print("All prompts in the directory are valid.")
else:
    print("Prompt validation failed:")
    for error in validator.get_errors():
        print(f"- {error}")

# Example 2: Validate a single prompt file
single_prompt_path = prompt_dir / "prompt2.json"
# Re-initialize validator for a clean slate of errors
validator = PromptValidator()
if validator.validate(single_prompt_path):
    print(f"Prompt at {single_prompt_path} is valid.")
else:
    print(f"Validation for {single_prompt_path} failed:")
    for error in validator.get_errors():
        print(f"- {error}")

# Example 3: Handling a non-existent path
non_existent_path = Path("/tmp/non_existent_prompts")
validator = PromptValidator()
if validator.validate(non_existent_path):
    print("Validation passed (but this shouldn't happen for a non-existent path).")
else:
    print("Validation failed as expected for a non-existent path:")
    for error in validator.get_errors():
        print(f"- {error}")
