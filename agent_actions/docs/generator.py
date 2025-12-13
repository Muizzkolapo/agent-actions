"""
Catalog and runs data generator.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from .parser import WorkflowParser
from .scanner import ProjectScanner


class CatalogGenerator:
    """Generate catalog.json from workflows."""

    def __init__(self, workflows_data: Dict[str, Dict], project_path: Optional[str] = None):
        self.workflows_data = workflows_data
        self.parser = WorkflowParser()
        self.project_path = Path(project_path) if project_path else None
        self.schema_dir = self._find_schema_dir()

    def _find_schema_dir(self) -> Optional[Path]:
        """Find the schema directory in the project."""
        if not self.project_path:
            return None

        # Try common locations
        schema_locations = [
            self.project_path / 'schema',
            self.project_path / 'schemas',
            self.project_path.parent / 'schema',
        ]

        for schema_dir in schema_locations:
            if schema_dir.exists() and schema_dir.is_dir():
                return schema_dir

        return None

    def _enrich_action_with_fields(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich action with input/output field information for lineage.

        Args:
            action: Action dictionary from parser

        Returns:
            Enriched action with 'inputs' and 'outputs' fields
        """
        enriched = action.copy()

        # Extract output fields from schema
        if 'schema' in action:
            schema_value = action['schema']

            # Handle two types of schemas:
            # 1. String reference to schema file (e.g., "candidate_facts_list")
            # 2. Inline schema dict (e.g., {"summary_title": "string", ...})

            if isinstance(schema_value, str) and self.schema_dir:
                # Referenced schema - load from YAML file
                schema = self.parser.load_schema(schema_value, self.schema_dir)
                if schema and schema.get('fields'):
                    # Add output fields (field names only for lineage view)
                    enriched['outputs'] = [field['name'] for field in schema['fields']]
                    # Optionally add field details for tooltips/documentation
                    enriched['output_fields'] = schema['fields']

            elif isinstance(schema_value, dict):
                # Inline schema - extract field names directly
                field_names = list(schema_value.keys())
                enriched['outputs'] = field_names
                # Create field details from inline schema
                enriched['output_fields'] = [
                    {'name': name, 'type': type_val, 'description': ''}
                    for name, type_val in schema_value.items()
                ]

        # Extract input fields from context_scope
        if 'context_scope' in action:
            inputs = self.parser.extract_input_fields(action['context_scope'])
            if inputs:
                enriched['inputs'] = inputs

        # Clean up internal fields not needed in catalog
        enriched.pop('context_scope', None)

        return enriched

    def generate(self, prompts_data: Optional[Dict[str, Any]] = None, schemas_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate the complete catalog structure."""
        catalog = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_workflows': len(self.workflows_data),
                'generator_version': '1.0.0'
            },
            'workflows': {},
            'prompts': prompts_data or {},
            'schemas': schemas_data or {},
            'stats': {
                'total_workflows': 0,
                'total_actions': 0,
                'llm_actions': 0,
                'tool_actions': 0,
                'total_prompts': 0,
                'total_schemas': 0
            }
        }

        # Track unique schemas and prompts across all workflows
        unique_schemas = set()
        actions_with_prompts = 0

        for workflow_name, paths in self.workflows_data.items():
            # Use rendered workflow if available, otherwise use original
            yaml_path = paths['rendered'] or paths['original']
            workflow = self.parser.parse_workflow(yaml_path)

            # Skip if workflow parsing failed
            if workflow is None:
                continue



            # Merge dependencies and enrich actions with field information
            enriched_actions = {}
            for action_name, action in workflow['actions'].items():
                # Dependencies are already in action definition now
                # action['dependencies'] = action.get('dependencies', []) 
                
                # Enrich with input/output fields for lineage
                enriched_actions[action_name] = self._enrich_action_with_fields(action)

            # Create workflow entry
            workflow_id = workflow_name
            catalog['workflows'][workflow_id] = {
                'id': workflow_id,
                'name': workflow['name'],
                'description': workflow['description'],
                'path': workflow['path'],
                'version': workflow['version'],
                'actions': enriched_actions,
                'action_count': len(enriched_actions)
            }

            # Update stats
            catalog['stats']['total_workflows'] += 1
            catalog['stats']['total_actions'] += len(workflow['actions'])

            # Count action types, schemas, and prompts
            for action in workflow['actions'].values():
                if action.get('type') == 'llm':
                    catalog['stats']['llm_actions'] += 1
                elif action.get('type') == 'tool':
                    catalog['stats']['tool_actions'] += 1

                # Count unique schemas (only string references, not inline dicts)
                schema = action.get('schema')
                if schema and isinstance(schema, str):
                    unique_schemas.add(schema)

                # Count actions with prompts (LLM actions typically have prompts)
                if action.get('prompt') or (action.get('type') == 'llm' and action.get('intent')):
                    actions_with_prompts += 1

        # Update global stats for schemas and prompts
        catalog['stats']['total_schemas'] = len(schemas_data) if schemas_data else 0
        catalog['stats']['total_prompts'] = len(prompts_data) if prompts_data else 0

        return catalog


class RunsGenerator:
    """Initialize runs data structure."""

    @staticmethod
    def initialize_empty() -> Dict[str, Any]:
        """
        Initialize empty runs data structure.

        Actual run data will be populated by the workflow execution system
        via the RunTracker when workflows are executed.
        """
        runs = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_runs': 0
            },
            'executions': []
        }

        return runs


def generate_docs(project_path: str, output_dir: Path) -> bool:
    """
    Main entry point for docs generation.

    Args:
        project_path: Path to project root
        output_dir: Target directory for generated files (artefact/)

    Returns:
        True if successful, False otherwise
    """
    # Step 1: Scan project
    scanner = ProjectScanner(project_path)
    workflows_data = scanner.scan()

    if not workflows_data:
        print("❌ No workflows found in project!")
        return False

    # Step 1b: Scan prompts
    prompts_data = scanner.scan_prompts()

    # Step 1c: Scan schemas
    schemas_data = scanner.scan_schemas()

    # Step 2: Generate catalog
    catalog_gen = CatalogGenerator(workflows_data, project_path=project_path)
    catalog = catalog_gen.generate(prompts_data=prompts_data, schemas_data=schemas_data)

    # Step 3: Write data files
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write catalog.json
    catalog_path = output_dir / 'catalog.json'
    with open(catalog_path, 'w') as f:
        json.dump(catalog, f, indent=2)

    # Initialize runs.json only if it doesn't exist
    # (RunTracker manages all updates to this file during workflow execution)
    runs_path = output_dir / 'runs.json'
    if not runs_path.exists():
        runs = RunsGenerator.initialize_empty()
        with open(runs_path, 'w') as f:
            json.dump(runs, f, indent=2)

    # Print summary
    total_workflows = catalog['stats']['total_workflows']
    total_actions = catalog['stats']['total_actions']
    total_prompts = catalog['stats']['total_prompts']
    total_schemas = catalog['stats']['total_schemas']

    print(f"\nBuilding catalog")
    print(f"  Found {total_workflows} workflow{'s' if total_workflows != 1 else ''}")
    print(f"  Compiled {total_actions} action{'s' if total_actions != 1 else ''}")
    print(f"  Discovered {total_prompts} prompt{'s' if total_prompts != 1 else ''}")
    print(f"  Loaded {total_schemas} schema{'s' if total_schemas != 1 else ''}")
    print(f"\nDone. Documentation compiled to artefact/")

    return True
