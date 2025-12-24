"""
Workflow YAML parser for documentation generation.
"""
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml


class WorkflowParser:
    """Parse and extract information from agent workflow YAML files."""

    @staticmethod
    def parse_workflow(yaml_path: str) -> Optional[Dict[str, Any]]:
        """Parse a workflow YAML file and extract all relevant information."""
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"  ⚠ Warning: YAML parsing error - {e}")
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"  ⚠ Warning: Error reading file - {e}")
            return None

        workflow = {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'path': yaml_path,
            'version': data.get('version', '1.0.0'),
            'actions': {}
        }

        # Parse actions (flat structure from rendered workflows)
        actions = data.get('actions', [])
        for action_data in actions:
            action_name = action_data.get('name', 'unnamed')

            action = {
                'name': action_name,
                'intent': action_data.get('intent', ''),
                'dependencies': action_data.get('dependencies', [])
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

            # Extract additional action configuration fields
            action['granularity'] = action_data.get('granularity')  # RECORD or FILE
            action['guard'] = action_data.get('guard')              # Conditional execution
            action['drops'] = action_data.get('drops', [])          # Fields excluded from prompt
            action['observe'] = action_data.get('observe', [])      # Pass-through fields
            action['policy'] = action_data.get('policy')            # Execution policy
            action['few_shot'] = action_data.get('few_shot')        # Few-shot example count
            action['prompt'] = action_data.get('prompt')            # Prompt reference
            action['idempotency_key'] = action_data.get('idempotency_key')

            # Loop configuration
            if 'loop' in action_data:
                action['loop'] = action_data['loop']  # {param, range, mode}
            if 'loop_consumption' in action_data:
                action['loop_consumption'] = action_data['loop_consumption']

            workflow['actions'][action_name] = action

        return workflow



    @staticmethod
    def load_schema(schema_name: str, schema_dir: Path) -> Optional[Dict[str, Any]]:  # pylint: disable=too-many-locals
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
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_data = yaml.safe_load(f)
        except Exception:  # pylint: disable=broad-exception-caught
            return None

        # Extract field information from schema
        fields = []
        schema_type = schema_data.get('type', 'object')

        # Format 1: Custom 'fields' array at root
        if 'fields' in schema_data and isinstance(schema_data['fields'], list):
            for field_def in schema_data['fields']:
                # Nested format: {id, type: array, items: {properties: {...}}}
                is_nested_array = (
                    field_def.get('type') == 'array'
                    and 'items' in field_def
                    and 'properties' in field_def['items']
                )
                if is_nested_array:
                    items = field_def['items']
                    required_fields = items.get('required', [])
                    for prop_name, prop_def in items['properties'].items():
                        fields.append({
                            'name': prop_name,
                            'type': prop_def.get('type', 'unknown'),
                            'description': prop_def.get('description', ''),
                            'required': prop_name in required_fields
                        })
                    schema_type = 'array'
                # Simple format: {id, type, description}
                elif 'id' in field_def:
                    fields.append({
                        'name': field_def['id'],
                        'type': field_def.get('type', 'unknown'),
                        'description': field_def.get('description', ''),
                        'required': field_def.get('required', False)
                    })

        # Format 2: Standard array schema with type at root
        elif schema_data.get('type') == 'array' and 'items' in schema_data:
            properties = schema_data.get('items', {}).get('properties', {})
            required_fields = schema_data.get('items', {}).get('required', [])
            for field_name, field_info in properties.items():
                fields.append({
                    'name': field_name,
                    'type': field_info.get('type', 'unknown'),
                    'description': field_info.get('description', ''),
                    'required': field_name in required_fields
                })

        # Format 3: Standard object schema
        elif schema_data.get('type') == 'object' and 'properties' in schema_data:
            properties = schema_data.get('properties', {})
            required_fields = schema_data.get('required', [])
            for field_name, field_info in properties.items():
                fields.append({
                    'name': field_name,
                    'type': field_info.get('type', 'unknown'),
                    'description': field_info.get('description', ''),
                    'required': field_name in required_fields
                })

        return {
            'name': schema_data.get('name', schema_name),
            'type': schema_type,
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
