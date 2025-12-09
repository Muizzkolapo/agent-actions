"""
Project scanner for finding workflow files.
"""
from pathlib import Path
from typing import Dict, Any


class ProjectScanner:
    """Scan project directory for agent workflows."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.workflows_found = []

    def scan(self) -> Dict[str, Dict[str, Any]]:
        """
        Scan project directory for workflow files.

        Looks for:
        1. artefact/rendered_workflows/*.yml (rendered workflows)
        2. */agent_config/*.yml (original workflows for plan section)

        The artefact/ directory contains all generated files including
        rendered workflows, catalog, and runs data.

        Returns:
            Dict mapping workflow names to paths:
            {
                'workflow_name': {
                    'rendered': '/path/to/rendered.yml',
                    'original': '/path/to/original.yml'
                }
            }
        """
        workflows = {}
        artefact_dir = self.project_root / 'artefact'

        # First, scan for rendered workflows inside artefact/
        rendered_dir = artefact_dir / 'rendered_workflows'
        if rendered_dir.exists():
            for yaml_file in rendered_dir.glob('*.yml'):
                workflow_name = yaml_file.stem
                workflows[workflow_name] = {
                    'rendered': str(yaml_file),
                    'original': None
                }

        # Then, scan for original workflows with plan sections
        # Skip the artefact directory to avoid scanning generated docs
        for agent_config_dir in self.project_root.rglob('agent_config'):
            # Skip if inside artefact directory
            if artefact_dir in agent_config_dir.parents or agent_config_dir == artefact_dir:
                continue

            for yaml_file in agent_config_dir.glob('*.yml'):
                workflow_name = yaml_file.stem
                if workflow_name in workflows:
                    workflows[workflow_name]['original'] = str(yaml_file)
                else:
                    workflows[workflow_name] = {
                        'rendered': None,
                        'original': str(yaml_file)
                    }

        return workflows
