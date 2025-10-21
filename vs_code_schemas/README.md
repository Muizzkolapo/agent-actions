# JSON Schema Files for IDE Integration

This directory contains JSON Schema files generated from Agent Actions' Pydantic models. These schemas enable IDE autocomplete, validation, and documentation for configuration files.

## Available Schemas

| Schema File | Purpose | Use For |
|------------|---------|---------|
| `workflow_schema.json` | Complete workflow structure | `workflows/*.yml` files |
| `action_schema.json` | Individual action configuration | Action definitions within workflows |
| `defaults_schema.json` | Workflow defaults section | `defaults:` section in workflows |
| `agent_config_schema.json` | Project-level agent configuration | `agent_actions.yml` |
| `default_agent_config_schema.json` | Default agent settings | `default_agent_config:` section |

## Generating Schemas

To regenerate these schemas after Pydantic model changes:

```bash
python scripts/generate_json_schemas.py
```

## IDE Setup

### VS Code

Add to `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "./schemas/workflow_schema.json": "workflows/*.yml",
    "./schemas/agent_config_schema.json": "agent_actions.yml"
  }
}
```

### PyCharm

1. Go to: Preferences → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings
2. Add new mapping for `workflow_schema.json` with pattern `workflows/*.yml`
3. Add new mapping for `agent_config_schema.json` with pattern `agent_actions.yml`

## Documentation

See [IDE Setup Guide](../agentaction-docs/docs/guides/ide-setup.md) for detailed instructions.

## Schema Source

These schemas are automatically generated from:

- `agent_actions/core/parser/config_schema.py` - Project-level schemas
- `agent_actions/core/migration/new_format_schema.py` - Workflow schemas
- `agent_actions/core/parser/vendor_config.py` - Vendor-specific schemas

## Version

Schemas follow JSON Schema Draft 7 specification.

Last generated: Run `python scripts/generate_json_schemas.py` to update
