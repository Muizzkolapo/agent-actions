#!/usr/bin/env python3
"""
Initialize a new agent-actions workflow with proper directory structure.
"""

import argparse
import sys
from pathlib import Path


WORKFLOW_YAML_TEMPLATE = """################################################################################
# {title}
################################################################################
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
The user will provide data to process.

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
    """Initialize a new workflow with proper structure."""

    workflow_dir = output_dir / name
    title = name.replace("_", " ").title()

    # Create directories
    (workflow_dir / "agent_config").mkdir(parents=True, exist_ok=True)
    (workflow_dir / "agent_io" / "source").mkdir(parents=True, exist_ok=True)
    (workflow_dir / "agent_io" / "target").mkdir(parents=True, exist_ok=True)
    (workflow_dir / "prompt_store").mkdir(parents=True, exist_ok=True)

    # Create workflow YAML
    yaml_content = WORKFLOW_YAML_TEMPLATE.format(
        name=name, title=title, description=f"{title} workflow"
    )
    (workflow_dir / "agent_config" / f"{name}.yml").write_text(yaml_content)

    # Create prompt store
    prompt_content = PROMPT_STORE_TEMPLATE.format(title=title)
    (workflow_dir / "prompt_store" / f"{name}.md").write_text(prompt_content)

    # Create example source file
    source_example = """[
    {
        "source_guid": "example-001",
        "content": {
            "input_data": "Your input data here"
        }
    }
]"""
    (workflow_dir / "agent_io" / "source" / "example_source.json").write_text(source_example)

    print(f"✅ Created workflow: {workflow_dir}")
    print(f"   ├── agent_config/{name}.yml")
    print(f"   ├── agent_io/source/example_source.json")
    print(f"   └── prompt_store/{name}.md")
    print()
    print("Next steps:")
    print(f"  1. Edit agent_config/{name}.yml to define your actions")
    print(f"  2. Edit prompt_store/{name}.md to add your prompts")
    print("  3. Create tool files in your tools directory")
    print("  4. Add source data to agent_io/source/")


def main():
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
