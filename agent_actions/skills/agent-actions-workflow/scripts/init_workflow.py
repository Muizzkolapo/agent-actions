#!/usr/bin/env python3
"""
Initialize a new agent-actions workflow with proper directory structure.

Usage:
    python init_workflow.py <workflow-name> --path <output-dir>

Example:
    python init_workflow.py my_quiz_gen --path /path/to/agent_workflow
"""

import argparse
import sys
from pathlib import Path


WORKFLOW_YAML_TEMPLATE = """######################################################################
# {title}
######################################################################
name: {name}
description: "{description}"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  is_operational: false
  prompt_debug: false

actions:
  # ============================================================================
  # STEP 1: FIRST ACTION
  # ============================================================================
  - name: first_action
    intent: "Process the input data"
    schema: {{
      output_field: string
    }}
    prompt: ${name}.First_Prompt
    prompt_debug: true

  # ============================================================================
  # STEP 2: TOOL ACTION EXAMPLE
  # ============================================================================
  - name: process_with_tool
    dependencies: [first_action]
    kind: tool
    impl: my_tool_function
    intent: "Process data with custom tool"
    granularity: Record
"""

PROMPT_STORE_TEMPLATE = """# {title} Prompts

{{prompt First_Prompt}}
You are an expert assistant.

## INPUT
Use 'source.' prefix for input data fields:
- Field 1: {{{{source.field_1}}}}
- Field 2: {{{{source.field_2}}}}

## TASK
Process the data and extract the required information.

## OUTPUT SCHEMA:
```json
{{
  "output_field": "The processed result"
}}
```

## IMPORTANT
- Be accurate and thorough
- Follow the schema exactly
{{end_prompt}}


{{prompt Second_Prompt}}
## INPUT
Use 'source.' for original input data:
- Original Field: {{{{source.field_1}}}}

Use '<action_name>.' for previous action outputs:
- Previous Result: {{{{first_action.output_field}}}}

## TASK
Build on the previous action's output.

## OUTPUT SCHEMA:
```json
{{
  "final_result": "The final processed result"
}}
```
{{end_prompt}}
"""

TOOL_TEMPLATE = '''from typing import List, TypedDict
from agent_actions import udf_tool


class MyToolInput(TypedDict, total=False):
    """Input schema for my_tool_function.

    Source: node_0_first_action output
    Destination: node_1_process_with_tool output
    """
    output_field: str


@udf_tool(input_type=MyToolInput)
def my_tool_function(data: dict) -> dict:
    """Process data and return modified dict.

    Args:
        data: Input data from previous action

    Returns:
        Modified data dict
    """
    # Your processing logic here
    result = data.copy()

    # Example: Add a new field
    result["processed"] = True

    return result
'''


def init_workflow(name: str, output_dir: Path) -> None:
    """Initialize a new workflow with proper structure.

    Creates the workflow directory structure:
      <workflow>/
        agent_config/<name>.yml    - Workflow definition
        agent_io/staging/          - Base input data (target/ created by agac)
        seed_data/                 - Reference data (syllabus, lookups, etc.)

    Note: Prompts and schemas go in central project directories:
      - prompt_store/<name>.md     - Prompt definitions
      - schema/<schema_name>.yml   - Schema definitions
    """
    workflow_dir = output_dir / name
    title = name.replace("_", " ").title()

    # Create directories (target/ is created by agac at runtime)
    (workflow_dir / "agent_config").mkdir(parents=True, exist_ok=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True, exist_ok=True)
    (workflow_dir / "seed_data").mkdir(parents=True, exist_ok=True)

    # Create workflow YAML
    yaml_content = WORKFLOW_YAML_TEMPLATE.format(
        name=name, title=title, description=f"{title} workflow"
    )
    (workflow_dir / "agent_config" / f"{name}.yml").write_text(yaml_content, encoding="utf-8")

    # Create example staging file
    # Note: Data structure is workflow-specific - define fields based on your needs
    staging_example = """[
    {
        "field_1": "value_1",
        "field_2": "value_2",
        "nested_field": {
            "key": "value"
        }
    }
]"""
    (workflow_dir / "agent_io" / "staging" / "example_staging.json").write_text(
        staging_example, encoding="utf-8"
    )

    # Create prompt store template (for user to move to central location)
    prompt_content = PROMPT_STORE_TEMPLATE.format(title=title)
    prompt_file = workflow_dir / f"__{name}_prompts.md"
    prompt_file.write_text(prompt_content, encoding="utf-8")

    print(f"✅ Created workflow: {workflow_dir}")
    print(f"   ├── agent_config/{name}.yml")
    print("   ├── agent_io/staging/example_staging.json")
    print("   ├── seed_data/                    (for reference data)")
    print(f"   └── __{name}_prompts.md          (move to prompt_store/)")
    print()
    print("Next steps:")
    print(f"  1. Edit agent_config/{name}.yml to define your actions")
    print(f"  2. Move __{name}_prompts.md to your project's prompt_store/")
    print("  3. Create schema files in your project's schema/ directory")
    print("  4. Create tool files in your project's tools/ directory")
    print("  5. Add base data to agent_io/staging/")
    print("  6. Add reference data to seed_data/ (if needed)")


def main():
    """CLI entry point for workflow initialization."""
    parser = argparse.ArgumentParser(description="Initialize a new agent-actions workflow")
    parser.add_argument("name", help="Workflow name (snake_case)")
    parser.add_argument("--path", "-p", required=True, help="Output directory for the workflow")

    args = parser.parse_args()

    # Validate name
    if not args.name.replace("_", "").isalnum():
        print("Error: Workflow name must be alphanumeric with underscores", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.path)
    if not output_path.exists():
        output_path.mkdir(parents=True)

    init_workflow(args.name, output_path)


if __name__ == "__main__":
    main()
