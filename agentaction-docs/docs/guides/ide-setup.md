---
title: IDE Setup for Configuration Validation
description: Configure your IDE for autocomplete and validation of Agent Actions configuration files
sidebar_position: 1
---

# IDE Setup Guide

This guide shows you how to configure your IDE to provide autocomplete, validation, and inline documentation for Agent Actions configuration files.

## Overview

Agent Actions provides JSON Schema files that enable IDEs to:

- **Autocomplete** field names and values while you type
- **Validate** configuration syntax in real-time
- **Show documentation** for fields via hover tooltips
- **Catch errors** before running workflows

## Generating JSON Schemas

First, generate the JSON Schema files:

```bash
# From the project root
python scripts/generate_json_schemas.py
```

This creates schema files in the `schemas/` directory:

```
schemas/
├── action_schema.json                    # Action configuration
├── agent_config_schema.json              # Project-level agent config
├── default_agent_config_schema.json      # Default agent settings
├── defaults_schema.json                  # Workflow defaults
└── workflow_schema.json                  # Complete workflow structure
```

## VS Code Setup

### Method 1: Workspace Settings (Recommended)

Create or edit `.vscode/settings.json` in your project root:

```json
{
  "yaml.schemas": {
    "./schemas/workflow_schema.json": "workflows/*.yml",
    "./schemas/agent_config_schema.json": "agent_actions.yml"
  },
  "yaml.customTags": [
    "!Ref",
    "!Join sequence",
    "!Sub"
  ],
  "yaml.format.enable": true,
  "yaml.validate": true,
  "editor.quickSuggestions": {
    "strings": true
  }
}
```

### Method 2: User Settings

1. Open VS Code Settings (Cmd+, on Mac, Ctrl+, on Windows/Linux)
2. Search for "yaml schemas"
3. Click "Edit in settings.json"
4. Add the schema mappings:

```json
{
  "yaml.schemas": {
    "/absolute/path/to/schemas/workflow_schema.json": "workflows/*.yml"
  }
}
```

### Method 3: Inline Schema Reference

Add to the top of your YAML file:

```yaml
# yaml-language-server: $schema=../schemas/workflow_schema.json

name: my_workflow
description: Example workflow
version: "1.0"
```

### Required Extension

Install the YAML extension:

1. Open Extensions (Cmd+Shift+X / Ctrl+Shift+X)
2. Search for "YAML" by Red Hat
3. Click Install

**Extension ID**: `redhat.vscode-yaml`

### Features You'll Get

- ✅ Autocomplete for field names
- ✅ Enum value suggestions (e.g., `kind: llm` vs `kind: tool`)
- ✅ Validation errors highlighted in red
- ✅ Hover tooltips with field descriptions
- ✅ Required field warnings

### Example: Autocomplete in Action

When typing in a workflow file:

```yaml
actions:
  - name: extract
    # Type "in" and you'll see suggestions:
    # - intent
    # - impl
    # - idempotency_key
    intent: Extract entities
    # Type "ki" and you'll see:
    # - kind: [llm, tool]
    kind: llm
    # Hovering over "kind" shows: "Type of action - LLM-based or tool/function execution"
```

## PyCharm / IntelliJ IDEA Setup

### Step 1: Configure JSON Schema Mappings

1. Open **Preferences/Settings** (Cmd+, / Ctrl+Alt+S)
2. Navigate to: **Languages & Frameworks** → **Schemas and DTDs** → **JSON Schema Mappings**
3. Click the **+** button to add a new mapping

### Step 2: Add Workflow Schema

1. **Name**: Agent Actions Workflow
2. **Schema file or URL**: Click folder icon and select `schemas/workflow_schema.json`
3. **Schema version**: JSON Schema version 7
4. **File path pattern**: Click **+** and add:
   - Pattern: `workflows/*.yml`
   - Match pattern: `*.yml` in `workflows` directory

### Step 3: Add Agent Config Schema

1. Click **+** to add another mapping
2. **Name**: Agent Actions Config
3. **Schema file or URL**: Select `schemas/agent_config_schema.json`
4. **File path pattern**: Add `agent_actions.yml`

### Step 4: Enable YAML Support

1. Ensure YAML plugin is enabled: **Preferences** → **Plugins** → search "YAML"
2. Enable: **Editor** → **Code Completion** → **Autopopup code completion**

### Features You'll Get

- ✅ Smart autocomplete with Ctrl+Space
- ✅ Real-time validation
- ✅ Quick documentation (Ctrl+Q / F1)
- ✅ Error highlighting
- ✅ Structure view (Cmd+7 / Alt+7)

## Sublime Text Setup

### Install LSP and LSP-yaml

1. Install Package Control (if not installed)
2. Install packages:
   - `LSP`
   - `LSP-yaml`

### Configure LSP-yaml

1. Open: **Preferences** → **Package Settings** → **LSP** → **Servers** → **LSP-yaml**
2. Add configuration:

```json
{
  "settings": {
    "yaml.schemas": {
      "/absolute/path/to/schemas/workflow_schema.json": "workflows/*.yml",
      "/absolute/path/to/schemas/agent_config_schema.json": "agent_actions.yml"
    },
    "yaml.validate": true,
    "yaml.hover": true,
    "yaml.completion": true
  }
}
```

## Neovim Setup

### Using nvim-lspconfig

1. Install `yaml-language-server`:

```bash
npm install -g yaml-language-server
```

2. Configure in your `init.lua`:

```lua
require('lspconfig').yamlls.setup {
  settings = {
    yaml = {
      schemas = {
        ["/absolute/path/to/schemas/workflow_schema.json"] = "workflows/*.yml",
        ["/absolute/path/to/schemas/agent_config_schema.json"] = "agent_actions.yml",
      },
      validate = true,
      hover = true,
      completion = true,
    },
  },
}
```

### Using coc.nvim

Add to `:CocConfig`:

```json
{
  "yaml.schemas": {
    "/absolute/path/to/schemas/workflow_schema.json": "workflows/*.yml",
    "/absolute/path/to/schemas/agent_config_schema.json": "agent_actions.yml"
  }
}
```

## Emacs Setup

### Using lsp-mode

1. Install `yaml-language-server`:

```bash
npm install -g yaml-language-server
```

2. Configure in `.emacs` or `init.el`:

```elisp
(use-package lsp-mode
  :hook (yaml-mode . lsp)
  :config
  (setq lsp-yaml-schemas
        '(("/absolute/path/to/schemas/workflow_schema.json" . ["workflows/*.yml"])
          ("/absolute/path/to/schemas/agent_config_schema.json" . ["agent_actions.yml"]))))
```

## Verifying Setup

### Test Autocomplete

1. Open a workflow file
2. Start typing a new action:

```yaml
actions:
  - name: test
    # Press Ctrl+Space (or your IDE's autocomplete shortcut)
    # You should see suggestions for: intent, kind, impl, model_vendor, etc.
```

### Test Validation

1. Add an invalid field:

```yaml
actions:
  - name: test
    intent: Test action
    kind: invalid_type  # Should show error: must be 'llm' or 'tool'
```

2. You should see a red underline or error marker

### Test Documentation

1. Hover over a field name (e.g., `kind`)
2. You should see a tooltip with:
   ```
   Type of action
   Enum: llm, tool
   Default: llm
   ```

## Troubleshooting

### Autocomplete Not Working

**VS Code:**
- Ensure YAML extension is installed and enabled
- Check `.vscode/settings.json` has correct schema paths
- Try reloading window: Cmd+Shift+P → "Reload Window"

**PyCharm:**
- Check schema file path is absolute or relative to project root
- Verify YAML plugin is enabled
- Invalidate caches: File → Invalidate Caches / Restart

### Schema Not Found

- Ensure you've run `python scripts/generate_json_schemas.py`
- Check schema file paths are correct (absolute or relative to workspace)
- Verify schema files exist: `ls -la schemas/`

### Validation Not Working

**VS Code:**
```json
{
  "yaml.validate": true,
  "yaml.schemaStore.enable": true
}
```

**PyCharm:**
- Preferences → Editor → Inspections → YAML → check "YAML schema validation"

### Wrong Schema Applied

- Check file path patterns don't overlap
- More specific patterns take precedence
- Try inline schema reference at top of file

## Advanced Configuration

### Multiple Schema Versions

Support different schema versions:

```json
{
  "yaml.schemas": {
    "./schemas/workflow_schema.json": "workflows/*.yml",
    "./schemas/workflow_v2_schema.json": "workflows/v2/*.yml"
  }
}
```

### Custom Schema Extensions

Extend schemas for custom fields:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "allOf": [
    { "$ref": "./schemas/workflow_schema.json" },
    {
      "properties": {
        "custom_field": {
          "type": "string",
          "description": "Your custom field"
        }
      }
    }
  ]
}
```

### Workspace Recommendations

Add to `.vscode/extensions.json`:

```json
{
  "recommendations": [
    "redhat.vscode-yaml"
  ]
}
```

Team members opening the project will be prompted to install recommended extensions.

## Benefits of IDE Integration

### 1. Faster Development

- No need to remember field names
- Autocomplete reduces typos
- Quick access to documentation

### 2. Early Error Detection

- Catch configuration errors before running
- Validation happens as you type
- Clear error messages with context

### 3. Better Documentation

- Inline field descriptions
- Type information visible
- Enum values suggested

### 4. Consistency

- Same schema across team
- Standardized configuration format
- Reduced configuration drift

## Next Steps

- Read [Configuration Schema Reference](../reference/configuration-schema.md) to understand the schema structure
- See [Configuration Fields Reference](../reference/configuration-fields.md) for complete field documentation
- Check [Configuration Examples](../examples/configurations/index.md) for real-world usage
- Review [Configuration Hierarchy](../core-concepts/configuration-hierarchy.md) to understand how settings are merged

## Resources

- [VS Code YAML Extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)
- [JSON Schema Documentation](https://json-schema.org/)
- [YAML Language Server](https://github.com/redhat-developer/yaml-language-server)
