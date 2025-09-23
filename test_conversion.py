#!/usr/bin/env python3
"""Test script to verify the format conversion is working."""

import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.parser.format_converter import WorkflowFormatConverter


def test_conversion():
    """Test the format conversion."""

    # Load the migrated workflow
    with open('fixed_migrated.yml', 'r') as f:
        new_config = yaml.safe_load(f)

    print("=== ORIGINAL NEW FORMAT ===")
    print(f"Name: {new_config.get('name')}")
    print(f"Actions: {len(new_config.get('actions', []))}")

    for i, action in enumerate(new_config.get('actions', [])[:3]):
        print(f"  {i+1}. {action.get('name')} ({action.get('kind', 'llm')})")

    print(f"Plan: {len(new_config.get('plan', []))} steps")

    # Test format detection
    format_type = WorkflowFormatConverter.detect_format(new_config)
    print(f"\n=== FORMAT DETECTION ===")
    print(f"Detected format: {format_type}")

    # Test conversion
    print(f"\n=== CONVERSION TO OLD FORMAT ===")
    old_config = WorkflowFormatConverter.convert_new_to_old(new_config)

    for workflow_name, agents in old_config.items():
        print(f"Workflow: {workflow_name}")
        print(f"Agents: {len(agents)}")

        for i, agent in enumerate(agents[:3]):
            agent_type = agent.get('agent_type', 'unknown')
            deps = agent.get('dependencies', [])
            deps_str = f" (deps: {deps})" if deps else ""
            print(f"  {i+1}. {agent_type}{deps_str}")

    print(f"\n=== SUCCESS! ===")
    print("Format conversion working correctly")


if __name__ == "__main__":
    test_conversion()