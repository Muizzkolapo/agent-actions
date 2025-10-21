# API Documentation Generation

This repository uses [pdoc](https://pdoc.dev/) to automatically generate comprehensive API documentation from Python docstrings.

## Quick Start

### Generate Documentation

You can generate the documentation in two ways:

#### Option 1: Using the Shell Script (Unix/Mac)
```bash
./docs_scripts/generate_docs.sh
```

#### Option 2: Using the Python Script (Cross-platform)
```bash
python docs_scripts/generate_docs.py
```

**Note:** Both scripts automatically change to the repository root directory before generating documentation, so `pdoc_docs/` will always be created in the repository root, regardless of where you run the script from.

### View Documentation

After generation, open the documentation in your browser:
```bash
open pdoc_docs/index.html
```

Or navigate to `pdoc_docs/index.html` manually.

## What Gets Documented

The documentation generator covers all major modules:
- `agent_actions` - Core package
- `agent_actions.agents` - Agent implementations
- `agent_actions.core` - Core utilities and functionality
- `agent_actions.integrations` - External service integrations
- `agent_actions.tasks` - Task processing and management
- `agent_actions.cli` - Command-line interface

## Using Documentation with LLMs

The generated HTML documentation can be used with LLMs to:

1. **Code Analysis**: Extract structure and relationships
2. **Refactoring Suggestions**: Compare against industry standards
3. **Documentation Improvements**: Identify missing or unclear docstrings
4. **Architecture Review**: Understand module dependencies

### Example Workflow

1. Generate the documentation:
   ```bash
   python docs_scripts/generate_docs.py
   ```

2. The documentation will be in `pdoc_docs/` with 178+ HTML files covering the entire codebase

3. Use the documentation with your LLM workflow for:
   - Codebase understanding
   - Refactoring analysis
   - Architecture review
   - Industry standard compliance checks

## Installation

If pdoc is not installed, install it with:
```bash
pip install pdoc
```

## Output

- **Format**: HTML
- **Location**: `pdoc_docs/`
- **Files**: ~178 HTML files
- **Features**:
  - Searchable documentation
  - Source code viewing
  - Inheritance diagrams
  - Cross-referenced links

## Notes

- The `pdoc_docs/` directory is gitignored (not committed to version control)
- Documentation is generated from code docstrings
- Warnings about type annotations are normal and don't affect functionality
- Regenerate documentation after significant code changes

## Advanced Usage

### Serve Documentation Locally

You can serve the documentation with a live-reloading server:
```bash
pdoc agent_actions agent_actions.agents agent_actions.core agent_actions.integrations agent_actions.tasks agent_actions.cli
```

This will start a local server (usually at http://localhost:8080) and auto-regenerate docs when code changes.

### Custom Output Format

To generate documentation in a different directory:
```bash
pdoc agent_actions -o custom_docs_dir
```

## Troubleshooting

**Issue**: "pdoc: command not found"
**Solution**: Install pdoc with `pip install pdoc`

**Issue**: No modules documented
**Solution**: Ensure you're running from the repository root directory

**Issue**: Type annotation warnings
**Solution**: These are informational only and don't affect the generated documentation
