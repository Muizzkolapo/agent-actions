#!/usr/bin/env python3
"""Debug script to see the full converted config."""

import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.parser.format_converter import WorkflowFormatConverter


def debug_full_conversion():
    """Debug the full conversion process."""

    config_path = "agent_workflow/qanalabs-quiz-gen/qanalabs-quiz-gen.yml"

    # Load the current config
    with open(config_path, 'r') as f:
        raw_config = yaml.safe_load(f)

    print(f"=== NEW FORMAT CONFIG ===")
    print(f"Name: {raw_config.get('name')}")
    print(f"Actions: {len(raw_config.get('actions', []))}")

    # List all actions
    for i, action in enumerate(raw_config.get('actions', []), 1):
        name = action.get('name', 'unknown')
        kind = action.get('kind', 'llm')
        print(f"  {i:2d}. {name} ({kind})")

    # Convert
    converted = WorkflowFormatConverter.convert_new_to_old(raw_config)

    print(f"\n=== CONVERTED OLD FORMAT ===")
    for workflow_name, agents in converted.items():
        print(f"Workflow: {workflow_name}")
        print(f"Agents: {len(agents)}")

        for i, agent in enumerate(agents, 1):
            agent_type = agent.get('agent_type', 'unknown')
            model_vendor = agent.get('model_vendor', 'unknown')
            deps = agent.get('dependencies', [])
            deps_str = f" (deps: {len(deps)})" if deps else ""
            print(f"  {i:2d}. {agent_type} [{model_vendor}]{deps_str}")

    # Check if there are any problematic agents
    print(f"\n=== VALIDATION CHECKS ===")
    workflow_name = list(converted.keys())[0]
    agents = converted[workflow_name]

    problematic = []
    for i, agent in enumerate(agents):
        issues = []
        if not agent.get('agent_type'):
            issues.append("missing agent_type")
        if not agent.get('model_vendor'):
            issues.append("missing model_vendor")
        if issues:
            problematic.append(f"Agent {i+1}: {', '.join(issues)}")

    if problematic:
        print("Issues found:")
        for issue in problematic:
            print(f"  - {issue}")
    else:
        print("All agents look valid!")


if __name__ == "__main__":
    debug_full_conversion()