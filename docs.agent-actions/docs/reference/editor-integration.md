---
title: Editor Integration
description: LSP support for VS Code, Neovim, and other editors
sidebar_position: 10
---

# Editor Integration

What happens when you Ctrl+Click on `$prompts.Extract_Facts` in your workflow YAML? Without editor integration, nothing. You'd manually search for the prompt file, scroll to find the right `{prompt}` block, and lose your train of thought. With the Agent Actions LSP, you jump directly to the definition—just like navigating code.

The Language Server Protocol (LSP) brings IDE-quality navigation to your agentic workflows. It's bundled with agent-actions, so you get it automatically with `pip install agent-actions`.

## What You Get

```mermaid
flowchart LR
    subgraph "Your Workflow"
        WF["prompt: $prompts.Fact_Extraction"]
    end

    subgraph "LSP Features"
        GTD[Go to Definition]
        HOV[Hover Preview]
        AC[Autocomplete]
        OUT[Outline/Symbols]
    end

    subgraph "Result"
        JUMP["→ prompt_store/prompts.md:42"]
    end

    WF -->|Ctrl+Click| GTD
    GTD --> JUMP
```

| Feature | What It Does | Example |
|---------|--------------|---------|
| **Go to Definition** | Ctrl+Click to jump to source | `$prompts.Extract` → prompt file, line 42 |
| **Hover** | Preview content without leaving current file | Hover on `impl: flatten_questions` → see function signature |
| **Autocomplete** | Suggestions as you type | Type `$prompts.` → list of available prompts |
| **Outline** | Document symbols in sidebar | See all actions in a workflow, all prompts in a file |
| **Syntax Highlighting** | Colored `{prompt}` tags and Jinja2 | Visual distinction for template syntax |

## Navigation Reference

The LSP understands agent-actions references and resolves them to file locations:

| Pattern | Example | Jumps To |
|---------|---------|----------|
| **Prompt** | `prompt: $quiz_gen.Extract_Raw_QA` | `prompt_store/quiz_gen.md` → `{prompt Extract_Raw_QA}` |
| **Tool/UDF** | `impl: flatten_questions` | `tools/**/flatten_questions.py` → `@udf_tool def` |
| **Schema** | `schema: question_schema` | `schema/question_schema.yml` |
| **Action** | `dependencies: extract_qa` or `dependencies: [a, b]` | Same file → `- name: extract_qa` |
| **Workflow** | `workflow: other_workflow` | `agent_workflow/other_workflow/agent_config/*.yml` |
| **Seed File** | `$file:exam_syllabus.json` | `seed_data/exam_syllabus.json` |

## Installation

The LSP comes bundled with agent-actions. Install the package and you get `agac-lsp`:

```bash
pip install agent-actions

# Verify it's available
agac-lsp --help
```

## VS Code Setup

### Option A: Install from VSIX (Recommended)

Build and install the VS Code extension:

```bash
# From the agent-actions repository
cd editors/vscode

# Install dependencies and build
npm install
npm run compile

# Package the extension
npx vsce package --allow-missing-repository

# Install to VS Code
code --install-extension agent-actions-lsp-0.2.0.vsix
```

After installation, reload VS Code (`Cmd+Shift+P` → "Developer: Reload Window").

### Option B: Development Mode

For extension development or testing:

1. Open the extension folder:
   ```bash
   code editors/vscode
   ```

2. Install dependencies:
   ```bash
   npm install && npm run compile
   ```

3. Press **F5** to launch Extension Development Host

4. Open your agent-actions project and test Ctrl+Click

### Requirements

The extension needs `agac-lsp` in your PATH. If you installed agent-actions in a virtual environment:

```bash
# Option 1: Activate the environment before opening VS Code
source .venv/bin/activate
code .

# Option 2: Add the venv bin to PATH in your shell config
export PATH="$HOME/projects/my-project/.venv/bin:$PATH"
```

## Neovim Setup

Using nvim-lspconfig:

```lua
local lspconfig = require('lspconfig')
local configs = require('lspconfig.configs')

-- Register the agent-actions language server
configs.agent_actions = {
  default_config = {
    cmd = { 'agac-lsp', '--stdio' },
    filetypes = { 'yaml', 'markdown' },
    root_dir = lspconfig.util.root_pattern('agent_actions.yml'),
    settings = {},
  },
}

-- Configure with your preferences
lspconfig.agent_actions.setup({
  on_attach = function(client, bufnr)
    -- Go to definition
    vim.keymap.set('n', 'gd', vim.lsp.buf.definition, { buffer = bufnr })
    -- Hover
    vim.keymap.set('n', 'K', vim.lsp.buf.hover, { buffer = bufnr })
    -- Autocomplete (if using nvim-cmp, it picks this up automatically)
  end,
})
```

## Cursor Setup

Cursor uses VS Code extensions. Follow the VS Code VSIX installation, then:

1. Open Cursor
2. Go to Extensions → Install from VSIX
3. Select `agent-actions-lsp-0.2.0.vsix`
4. Reload the window

## Syntax Highlighting

The extension provides syntax highlighting for prompt files (Markdown with agent-actions syntax):

| Element | Highlighting | Example |
|---------|--------------|---------|
| `{prompt Name}` | Keyword (purple) | Block delimiter |
| `{end_prompt}` | Keyword (purple) | Block delimiter |
| `{{ variable }}` | Variable (orange) | Jinja2 expression |
| `{% for/if/else %}` | Control (blue) | Jinja2 control flow |
| `{# comment #}` | Comment (dimmed) | Jinja2 comment |
| `CRITICAL` / `WARNING` | Warning markers | Red/yellow emphasis |

### Outline Navigation

Open the Outline panel (`Cmd+Shift+O` in VS Code) to see document symbols:

**In YAML workflow files:**
- All action names listed as symbols
- Quick jump to any action

**In Markdown prompt files:**
- All `{prompt}` blocks listed
- Quick navigation between prompts

## How It Works

```mermaid
flowchart TB
    subgraph "Editor"
        ED[VS Code / Neovim / Cursor]
    end

    subgraph "LSP Server"
        SRV[agac-lsp]
        IDX[indexer.py]
        RES[resolver.py]
    end

    subgraph "Your Project"
        CFG[agent_actions.yml]
        WF[agent_workflow/]
        PS[prompt_store/]
        TOOLS[tools/]
        SCH[schema/]
    end

    ED <-->|LSP Protocol| SRV
    SRV --> IDX
    SRV --> RES
    IDX -->|indexes| WF
    IDX -->|indexes| PS
    IDX -->|indexes| TOOLS
    IDX -->|indexes| SCH
    RES -->|resolves| WF
```

### Project Detection

The LSP finds your project by walking up from the opened file until it finds `agent_actions.yml`. It then indexes:

| Directory | What's Indexed |
|-----------|----------------|
| `agent_workflow/*/agent_config/*.yml` | Actions (`- name: X`) |
| `prompt_store/*.md` | Prompts (`{prompt X}`) |
| `tools/**/*.py` | UDF tools (`@udf_tool def`) |
| `schema/*.yml` | Schema files |
| `seed_data/` | Seed files (`$file:X`) |

### Re-indexing

The LSP re-indexes automatically when you save files. If you add new files while the LSP is running:

- Save any file to trigger re-index
- Or reload the editor window

## Troubleshooting

### "agac-lsp: command not found"

The LSP command isn't in your PATH:

```bash
# Check if agent-actions is installed
pip show agent-actions

# Find where agac-lsp is
pip show agent-actions | grep Location
# Then check: <location>/agent_actions/lsp/

# Reinstall if needed
pip install --force-reinstall agent-actions
```

### Extension Not Activating

1. Check Output panel → "Agent Actions LSP" for errors
2. Ensure your workspace contains `agent_actions.yml`
3. Verify `agac-lsp --help` works in terminal

### References Not Resolving

If Ctrl+Click doesn't work on a reference:

1. **File not indexed yet** - Save any file to trigger re-index
2. **Reference typo** - The referenced item doesn't exist
3. **Outside project** - The file isn't under the `agent_actions.yml` directory

### Hover Shows Nothing

The LSP may not have finished indexing. Wait a moment after opening a project, or reload the window.

## See Also

- [Skills Command](../cli-reference/skills) - Install AI coding assistant skills
- [Troubleshooting](./troubleshooting) - Common issues and solutions
