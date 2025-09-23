#!/usr/bin/env python3
"""Test script to verify the final conversion is working correctly."""

import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.parser.format_converter import WorkflowFormatConverter


def test_tool_conversion():
    """Test that tool actions are converted correctly."""

    # Create a simple test with both LLM and tool actions
    test_config = {
        "name": "test-workflow",
        "defaults": {
            "vendor": "openai",
            "model": "gpt-4"
        },
        "actions": [
            {
                "name": "extract_facts",
                "intent": "Extract facts",
                "schema": "fact_schema",
                "reads": ["content"],
                "writes": ["facts"]
            },
            {
                "name": "cluster_facts",
                "kind": "tool",
                "impl": "my_module.cluster_function",
                "intent": "Cluster facts",
                "reads": ["facts"],
                "writes": ["clusters"]
            }
        ],
        "plan": [
            "extract_facts",
            "cluster_facts <- extract_facts"
        ]
    }

    print("=== TESTING CONVERSION ===")

    # Test format detection
    format_type = WorkflowFormatConverter.detect_format(test_config)
    print(f"Format detected: {format_type}")

    # Convert
    converted = WorkflowFormatConverter.convert_new_to_old(test_config)

    print("\n=== CONVERTED AGENTS ===")
    for workflow_name, agents in converted.items():
        print(f"Workflow: {workflow_name}")

        for i, agent in enumerate(agents, 1):
            agent_type = agent.get('agent_type')
            model_vendor = agent.get('model_vendor')
            model_name = agent.get('model_name')
            schema_name = agent.get('schema_name')
            deps = agent.get('dependencies', [])

            print(f"  {i}. {agent_type}")
            print(f"     vendor: {model_vendor}")
            print(f"     model: {model_name}")
            if schema_name:
                print(f"     schema: {schema_name}")
            if deps:
                print(f"     deps: {deps}")
            print()

    print("=== VALIDATION ===")

    # Check tool action conversion
    tool_agent = None
    for agent in converted['test-workflow']:
        if agent.get('model_vendor') == 'tool':
            tool_agent = agent
            break

    if tool_agent:
        impl_path = tool_agent.get('model_name')
        if '.' in impl_path:
            print(f"✅ Tool action converted correctly: {impl_path}")
        else:
            print(f"❌ Tool action conversion issue: {impl_path}")
    else:
        print("❌ No tool action found after conversion")

    # Check LLM action conversion
    llm_agent = None
    for agent in converted['test-workflow']:
        if agent.get('model_vendor') != 'tool':
            llm_agent = agent
            break

    if llm_agent:
        schema = llm_agent.get('schema_name')
        if schema:
            print(f"✅ LLM action converted correctly with schema: {schema}")
        else:
            print(f"❌ LLM action missing schema: {llm_agent}")
    else:
        print("❌ No LLM action found after conversion")


if __name__ == "__main__":
    test_tool_conversion()