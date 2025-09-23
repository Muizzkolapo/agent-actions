#!/usr/bin/env python3
"""
Quick utility to convert new format back to old format for current system compatibility.
"""

import yaml
import sys
from pathlib import Path


def convert_new_to_old(new_config_path: str, output_path: str):
    """Convert new format back to old format."""

    with open(new_config_path, 'r') as f:
        new_config = yaml.safe_load(f)

    # Extract workflow info
    workflow_name = new_config['name']
    actions = new_config['actions']
    defaults = new_config.get('defaults', {})

    # Convert actions back to agents
    agents = []
    for action in actions:
        agent = {}

        # Map action fields back to agent fields
        if action.get('kind') == 'tool':
            # Tool action - reconstruct template syntax
            agent = {
                'template_type': 'tooling_workflow',
                'agent_type': action['name'],
                'model_name': action.get('impl', action['name']),
                'description': action.get('intent', ''),
                'granularity': action.get('granularity', defaults.get('granularity')),
                'is_operational': True
            }

            # Add dependencies if any (need to extract from plan)
            # For now, skip dependencies - would need plan parsing

        else:
            # LLM agent
            agent = {
                'agent_type': action['name'].replace('_', ''),  # Reverse name mapping
                'model_vendor': action.get('vendor', defaults.get('vendor')),
                'model_name': action.get('model', defaults.get('model')),
                'json_mode': defaults.get('json_mode', True),
                'granularity': action.get('granularity', defaults.get('granularity')),
                'is_operational': True,
                'run_mode': defaults.get('run_mode', 'online'),
                'use_few_shot_samples': action.get('few_shot', 0),
                'side_collection': action.get('observe', []),
                'remove_collection': action.get('drops', []),
                'prompt': action.get('prompt')
            }

            if action.get('output_schema'):
                agent['schema_name'] = action['output_schema']

            if action.get('guard'):
                agent['where_clause'] = {
                    'clause': action['guard'],
                    'scope': 'item'
                }

        agents.append(agent)

    # Create old format structure
    old_config = {
        workflow_name: agents
    }

    # Save
    with open(output_path, 'w') as f:
        yaml.dump(old_config, f, default_flow_style=False, indent=2)

    print(f"✅ Converted back to old format: {output_path}")
    print(f"⚠️  Note: Some advanced features may be lost in conversion")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_back_to_old.py <new_format.yml> <old_format.yml>")
        sys.exit(1)

    convert_new_to_old(sys.argv[1], sys.argv[2])