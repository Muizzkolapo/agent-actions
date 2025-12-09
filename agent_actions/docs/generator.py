"""
Catalog and runs data generator.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from .parser import WorkflowParser
from .scanner import ProjectScanner


class CatalogGenerator:
    """Generate catalog.json from workflows."""

    def __init__(self, workflows_data: Dict[str, Dict]):
        self.workflows_data = workflows_data
        self.parser = WorkflowParser()

    def generate(self) -> Dict[str, Any]:
        """Generate the complete catalog structure."""
        catalog = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_workflows': len(self.workflows_data),
                'generator_version': '1.0.0'
            },
            'workflows': {},
            'stats': {
                'total_workflows': 0,
                'total_actions': 0,
                'llm_actions': 0,
                'tool_actions': 0,
                'total_prompts': 0,
                'total_schemas': 0
            }
        }

        for workflow_name, paths in self.workflows_data.items():
            # Use rendered workflow if available, otherwise use original
            yaml_path = paths['rendered'] or paths['original']
            workflow = self.parser.parse_workflow(yaml_path)

            # Skip if workflow parsing failed
            if workflow is None:
                continue

            # Extract dependencies from original workflow's plan section
            dep_map = {}
            if paths['original']:
                try:
                    original_workflow = self.parser.parse_workflow(paths['original'])
                    if original_workflow and original_workflow.get('plan'):
                        _, dep_map = self.parser.parse_plan(original_workflow['plan'])
                except Exception:
                    pass  # Silently skip dependency extraction if it fails

            # Merge dependencies into actions
            for action_name, action in workflow['actions'].items():
                action['dependencies'] = dep_map.get(action_name, [])

            # Create workflow entry
            workflow_id = workflow_name
            catalog['workflows'][workflow_id] = {
                'id': workflow_id,
                'name': workflow['name'],
                'description': workflow['description'],
                'path': workflow['path'],
                'version': workflow['version'],
                'actions': workflow['actions'],
                'action_count': len(workflow['actions'])
            }

            # Update stats
            catalog['stats']['total_workflows'] += 1
            catalog['stats']['total_actions'] += len(workflow['actions'])

            # Count action types
            for action in workflow['actions'].values():
                if action.get('type') == 'llm':
                    catalog['stats']['llm_actions'] += 1
                elif action.get('type') == 'tool':
                    catalog['stats']['tool_actions'] += 1

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

    # Step 2: Generate catalog
    catalog_gen = CatalogGenerator(workflows_data)
    catalog = catalog_gen.generate()

    # Step 3: Initialize empty runs structure
    runs = RunsGenerator.initialize_empty()

    # Step 4: Write data files
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write catalog.json
    catalog_path = output_dir / 'catalog.json'
    with open(catalog_path, 'w') as f:
        json.dump(catalog, f, indent=2)

    # Write runs.json
    runs_path = output_dir / 'runs.json'
    with open(runs_path, 'w') as f:
        json.dump(runs, f, indent=2)

    # Print summary
    total_workflows = catalog['stats']['total_workflows']
    total_actions = catalog['stats']['total_actions']

    print(f"\nBuilding catalog")
    print(f"  Found {total_workflows} workflow{'s' if total_workflows != 1 else ''}")
    print(f"  Compiled {total_actions} action{'s' if total_actions != 1 else ''}")
    print(f"\nDone. Documentation compiled to artefact/")

    return True
