"""
Workflow YAML parser for documentation generation.
"""
import yaml
from pathlib import Path
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

        # Parse actions (flat structure from rendered workflows)
        actions = data.get('actions', [])
        for action_data in actions:
            action_name = action_data.get('name', 'unnamed')

            action = {
                'name': action_name,
                'intent': action_data.get('intent', ''),
                'dependencies': []
            }

            # Determine action type (llm or tool) from flat structure
            if action_data.get('kind') == 'tool':
                action['type'] = 'tool'
                action['provider'] = 'tool'
                action['implementation'] = action_data.get('impl', 'unknown')
            else:
                # Default to LLM action
                action['type'] = 'llm'
                action['provider'] = action_data.get('model_vendor', 'unknown')
                action['model'] = action_data.get('model_name', 'unknown')

            # Extract schema (for field-level lineage)
            if 'schema' in action_data:
                action['schema'] = action_data['schema']

            # Extract context_scope (for input fields)
            if 'context_scope' in action_data:
                action['context_scope'] = action_data['context_scope']

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

    @staticmethod
    def load_schema(schema_name: str, schema_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Load and parse a schema YAML file.

        Args:
            schema_name: Name of the schema (e.g., 'candidate_facts_list')
            schema_dir: Path to schema directory

        Returns:
            Dictionary with schema definition including field names and types
        """
        schema_file = schema_dir / f"{schema_name}.yml"

        if not schema_file.exists():
            return None

        try:
            with open(schema_file, 'r') as f:
                schema_data = yaml.safe_load(f)
        except Exception:
            return None

        # Extract field information from schema
        fields = []
        if schema_data.get('type') == 'array' and 'items' in schema_data:
            # Array schema - fields are in items.properties
            properties = schema_data.get('items', {}).get('properties', {})
            for field_name, field_info in properties.items():
                fields.append({
                    'name': field_name,
                    'type': field_info.get('type', 'unknown'),
                    'description': field_info.get('description', '')
                })
        elif schema_data.get('type') == 'object' and 'properties' in schema_data:
            # Object schema - fields are in properties
            properties = schema_data.get('properties', {})
            for field_name, field_info in properties.items():
                fields.append({
                    'name': field_name,
                    'type': field_info.get('type', 'unknown'),
                    'description': field_info.get('description', '')
                })

        return {
            'name': schema_data.get('name', schema_name),
            'type': schema_data.get('type', 'unknown'),
            'fields': fields
        }

    @staticmethod
    def extract_input_fields(context_scope: Dict[str, Any]) -> List[str]:
        """
        Extract input field names from context_scope.

        Args:
            context_scope: The context_scope dict from action definition

        Returns:
            List of input field names (e.g., ['source.page_content', 'seed.exam_syllabus'])
        """
        inputs = []

        # Extract from 'observe' - fields that are read as inputs
        if 'observe' in context_scope and isinstance(context_scope['observe'], list):
            inputs.extend(context_scope['observe'])

        # Extract from 'passthrough' - fields that flow through (both input and output)
        if 'passthrough' in context_scope and isinstance(context_scope['passthrough'], list):
            inputs.extend(context_scope['passthrough'])

        # Extract from 'keep' (legacy/alternative pattern)
        if 'keep' in context_scope and isinstance(context_scope['keep'], list):
            inputs.extend(context_scope['keep'])

        # Remove duplicates while preserving order
        seen = set()
        unique_inputs = []
        for field in inputs:
            if field not in seen:
                seen.add(field)
                unique_inputs.append(field)

        return unique_inputs
