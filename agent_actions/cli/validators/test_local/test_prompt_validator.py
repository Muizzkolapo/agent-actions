from pathlib import Path
from  agent_actions.cli.validators.prompt_validator import PromptValidator  # Adjust import path as needed

# Initialize the validator
validator = PromptValidator()

# Setup: Create a temporary directory with sample prompt files
prompt_dir = Path("/tmp/my_prompts")
prompt_dir.mkdir(parents=True, exist_ok=True)

# File with valid and duplicate prompts across files
(prompt_dir / "file1.md").write_text("""
# Section 1
```prompt:GREETING```
Hello there!
prompt:FAREWELL
Goodbye!
""")

(prompt_dir / "file2.md").write_text("""
# Section 2
```prompt:GREETING``` 
Hi again!
prompt:QUESTION
How are you?
""")  # GREETING is a duplicate across files

# File with duplicate prompts within the same file
(prompt_dir / "file_with_internal_dup.md").write_text("""
# Section 3
```prompt:ACTION```
Do something.
prompt:ACTION
Do something else.
""")  # ACTION is duplicated within the same file

# Run validation
if validator.validate(prompt_dir):
    print(f"✅ Prompt validation passed for: {prompt_dir}")
else:
    print(f"❌ Prompt validation failed for: {prompt_dir}")
    for error in validator.get_errors():
        print(f"  ERROR: {error}")
    for warning in validator.get_warnings():
        print(f"  WARNING: {warning}")

# Optional cleanup
# import shutil
# shutil.rmtree(prompt_dir)
