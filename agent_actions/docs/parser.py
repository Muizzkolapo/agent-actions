"""
Workflow YAML parser for documentation generation.
"""
import yaml
from typing import Dict, List, Any, Optional, Tuple


class WorkflowParser:
    """Parse and extract information from agent workflow YAML files."""

    @staticmethod
    def parse_workflow(yaml_path: str) -> Optional[Dict[str, Any]]:
        """Parse a workflow YAML file and extract all relevant information."""
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"  ⚠ Warning: YAML parsing error - {e}")
            return None
        except Exception as e:
            print(f"  ⚠ Warning: Error reading file - {e}")
            return None

        workflow = {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'path': yaml_path,
            'version': data.get('version', '1.0.0'),
            'actions': {},
            'plan': data.get('plan', [])
        }

        # Parse actions
        actions = data.get('actions', [])
        for action_data in actions:
            action_name = action_data.get('name', 'unnamed')

            action = {
                'name': action_name,
                'intent': action_data.get('intent', ''),
                'dependencies': []
            }

            # Parse action type (llm or tool)
            if 'llm' in action_data:
                action['type'] = 'llm'
                llm_data = action_data['llm']
                action['provider'] = llm_data.get('provider', 'unknown')
                action['model'] = llm_data.get('model', 'unknown')
                action['inputs'] = [inp.get('name') for inp in llm_data.get('inputs', [])]
                action['outputs'] = [out.get('name') for out in llm_data.get('outputs', [])]
            elif 'tool' in action_data:
                action['type'] = 'tool'
                tool_data = action_data['tool']
                action['provider'] = tool_data.get('provider', 'unknown')
                action['implementation'] = tool_data.get('impl', 'unknown')
                action['inputs'] = [inp.get('name') for inp in tool_data.get('inputs', [])]
                action['outputs'] = [out.get('name') for out in tool_data.get('outputs', [])]

            workflow['actions'][action_name] = action

        return workflow

    @staticmethod
    def parse_plan(plan: List[str]) -> Tuple[List[Dict], Dict[str, List[str]]]:
        """
        Parse the plan section to extract execution order and dependencies.

        Format: "action_name <- dep1, dep2, dep3"

        Returns:
            - execution_plan: List of dicts with action and dependencies
            - dependency_map: Dict mapping action name to list of dependencies
        """
        execution_plan = []
        dependency_map = {}

        for line in plan:
            if not line or line.strip().startswith('#'):
                continue

            line = line.strip()

            if '<-' in line:
                parts = line.split('<-')
                action = parts[0].strip()
                deps = [d.strip() for d in parts[1].split(',')]
                dependency_map[action] = deps
                execution_plan.append({
                    'action': action,
                    'dependencies': deps
                })
            else:
                action = line.strip()
                dependency_map[action] = []
                execution_plan.append({
                    'action': action,
                    'dependencies': []
                })

        return execution_plan, dependency_map
