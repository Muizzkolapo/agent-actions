#!/usr/bin/env python3
"""
Generate JSON Schema files from Pydantic models for IDE autocomplete support.

This script generates JSON Schema files that can be used by IDEs (VS Code, PyCharm, etc.)
to provide autocomplete and validation for Agent Actions configuration files.

Usage:
    python scripts/generate_json_schemas.py
"""

import json
import sys
from pathlib import Path

# Add parent directory to path to import agent_actions
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_actions.core.parser.config_schema import AgentConfig, DefaultAgentConfig
from agent_actions.core.migration.new_format_schema import (
    WorkflowConfigV2,
    ActionConfig,
    DefaultsConfig,
)


def generate_schema(model_class, output_file: Path, description: str):
    """Generate JSON Schema from a Pydantic model."""
    print(f"Generating schema for {model_class.__name__}...")

    # Generate JSON Schema using Pydantic v2 method
    schema = model_class.model_json_schema(
        by_alias=True,  # Use field aliases (e.g., 'schema' instead of 'output_schema')
        mode='validation'
    )

    # Add description at root level
    if description:
        schema['description'] = description

    # Add $schema field for JSON Schema Draft 7
    schema['$schema'] = 'http://json-schema.org/draft-07/schema#'

    # Write to file with pretty formatting
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(schema, f, indent=2)

    print(f"  ✓ Created: {output_file}")
    print(f"  ✓ Schema contains {len(schema.get('properties', {}))} properties")


def main():
    """Generate all JSON Schema files."""
    # Get the project root directory
    project_root = Path(__file__).parent.parent
    schemas_dir = project_root / 'schemas'

    print("=" * 60)
    print("Agent Actions - JSON Schema Generator")
    print("=" * 60)
    print()

    # Generate schema for workflow configuration
    generate_schema(
        WorkflowConfigV2,
        schemas_dir / 'workflow_schema.json',
        'JSON Schema for Agent Actions workflow configuration files (.yml)'
    )

    print()

    # Generate schema for action configuration
    generate_schema(
        ActionConfig,
        schemas_dir / 'action_schema.json',
        'JSON Schema for Agent Actions action configuration'
    )

    print()

    # Generate schema for workflow defaults
    generate_schema(
        DefaultsConfig,
        schemas_dir / 'defaults_schema.json',
        'JSON Schema for Agent Actions workflow defaults configuration'
    )

    print()

    # Generate schema for agent configuration (project-level)
    generate_schema(
        AgentConfig,
        schemas_dir / 'agent_config_schema.json',
        'JSON Schema for Agent Actions agent configuration (agent_actions.yml)'
    )

    print()

    # Generate schema for default agent configuration
    generate_schema(
        DefaultAgentConfig,
        schemas_dir / 'default_agent_config_schema.json',
        'JSON Schema for Agent Actions default agent configuration'
    )

    print()
    print("=" * 60)
    print("Schema generation complete!")
    print("=" * 60)
    print()
    print("Generated schemas:")
    for schema_file in sorted(schemas_dir.glob('*.json')):
        size_kb = schema_file.stat().st_size / 1024
        print(f"  • {schema_file.name:40} ({size_kb:>6.1f} KB)")

    print()
    print("IDE Setup Instructions:")
    print("=" * 60)
    print()
    print("VS Code:")
    print("  Add to .vscode/settings.json:")
    print('  {')
    print('    "yaml.schemas": {')
    print(f'      "./schemas/workflow_schema.json": "workflows/*.yml"')
    print('    }')
    print('  }')
    print()
    print("PyCharm:")
    print("  1. Go to Preferences → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings")
    print("  2. Click '+' to add a new mapping")
    print("  3. Select the schema file and specify file pattern (e.g., workflows/*.yml)")
    print()
    print("For more details, see: agentaction-docs/docs/guides/ide-setup.md")
    print()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
