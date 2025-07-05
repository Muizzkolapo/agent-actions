from pathlib import Path
from validators.render_validator import RenderValidator # Adjust import as needed

# Setup a dummy environment for testing
template_dir = Path("/tmp/test_templates")
template_dir.mkdir(exist_ok=True)
rendered_dir = Path("/tmp/test_rendered_workflows")
rendered_dir.mkdir(exist_ok=True)

# Create a sample template file
template_content = """
agent: {{ agent_name }}
details:
  model: {{ model | default('gpt-3.5-turbo') }}
  temperature: {{ temperature | default(0.7) }}
"""
(template_dir / "my_agent_template.j2").write_text(template_content)

# --- Test Case 1: Successful Render ---
print("--- Running Test Case 1: Successful Render ---")
validator_success = RenderValidator()
data_success = {
    "operation": "validate_render",
    "agent_name": "MyTestAgent",
    "template_dir": template_dir,
    "rendered_workflows_dir": rendered_dir,
    "context": {"agent_name": "MyTestAgentFromContext", "temperature": 0.9}
}
if validator_success.validate(data_success):
    print("Render validation passed.")
    # You can also check the content of the rendered file
    rendered_file = rendered_dir / "MyTestAgent.yml"
    if rendered_file.exists():
        print(f"Rendered file content:\n{rendered_file.read_text()}")
    else:
        print("Rendered file was not created.")
else:
    print("Render validation failed:")
    for error in validator_success.get_errors():
        print(f"- {error}")
print("-" * 20)


# --- Test Case 2: Missing Template ---
print("--- Running Test Case 2: Missing Template ---")
validator_missing = RenderValidator()
data_missing = {
    "operation": "validate_render",
    "agent_name": "NonExistentAgent",
    "template_dir": template_dir,
    "rendered_workflows_dir": rendered_dir,
    "context": {}
}
if not validator_missing.validate(data_missing):
    print("Render validation failed as expected for a missing template.")
    for error in validator_missing.get_errors():
        print(f"- {error}")
else:
    print("Validation passed, but it should have failed.")
print("-" * 20)


# --- Test Case 3: Jinja2 Rendering Error ---
print("--- Running Test Case 3: Jinja2 Rendering Error ---")
# Create a template with a syntax error
bad_template_content = "agent: {{ agent_name" # Missing closing brace
(template_dir / "bad_template.j2").write_text(bad_template_content)

validator_error = RenderValidator()
data_error = {
    "operation": "validate_render",
    "agent_name": "bad_template",
    "template_dir": template_dir,
    "rendered_workflows_dir": rendered_dir,
    "context": {"agent_name": "Test"}
}
if not validator_error.validate(data_error):
    print("Render validation failed as expected due to Jinja2 error.")
    for error in validator_error.get_errors():
        print(f"- {error}")
else:
    print("Validation passed, but it should have failed.")
print("-" * 20)


# Cleanup
import shutil
shutil.rmtree(template_dir)
shutil.rmtree(rendered_dir)
print("Cleanup complete.")
