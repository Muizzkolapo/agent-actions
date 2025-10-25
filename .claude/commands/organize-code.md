# Analyze and Organize Code Structure

Analyze the codebase structure, identify processing stages, and detect organizational issues.

## Overview

This command uses the enhanced Code Organizer tool to:
1. **Analyze directory structure** and module organization
2. **Identify processing stages** in the agent pipeline (Input → Pre-processing → LLM → Output)
3. **Detect architectural layers** using the 13-stage architecture
4. **Find organizational issues** (circular dependencies, large modules, missing `__init__.py` files)
5. **Generate recommendations** for improving code organization

## Usage

```bash
python .claude/helpers/code_organizer.py {{arg1}}
```

**Arguments:**
- `{{arg1}}` - Path to analyze (default: `agent_actions/`)

**Options:**
- `--json FILE` - Export report as JSON
- `--exclude PATTERN` - Exclude additional patterns

## Processing Stages

The tool identifies 13 processing stages in the agent pipeline:

### 1️⃣ Input Loading & Extraction
**Purpose:** Load and extract data from various sources
**Modules:** `input_loading/`, `file_reader`, loaders
**Keywords:** loader, extractor, reader, load, extract, read

### 2️⃣ Pre-Processing & Data Preparation
**Purpose:** Transform, filter, chunk data before LLM
**Modules:** `preprocessing/`, `staging`, `filters`, `field_chunking`
**Keywords:** staging, filter, chunk, transform, prepare

### 3️⃣ Validation
**Purpose:** Validate inputs, prompts, configs, and outputs
**Modules:** `validation/`, validation logic
**Keywords:** validator, validate, validation, check

### 4️⃣ Prompt Generation & Context Building
**Purpose:** Build prompts, manage context, apply templates
**Modules:** `prompt_generation/`, `render_workflow`
**Keywords:** generator, prompt, template, render, context

### 5️⃣ LLM Invocation & Provider Integration
**Purpose:** Call LLM providers for real-time and batch processing
**Modules:** `llm_invocation/`, `llm_invocation/batch/`, vendor handlers
**Keywords:** provider, vendor, handler, llm, model, batch

### 6️⃣ Response Processing & Transformation
**Purpose:** Process LLM responses, parse JSON, transform outputs
**Modules:** `response_processing/`, response transformers, interceptors
**Keywords:** transformer, response, interceptor, strategy, parse

### 7️⃣ Post-Processing & Output Generation
**Purpose:** Generate final outputs, apply post-processing
**Modules:** `postprocessing/`, `target_generator`, `output_handler`
**Keywords:** target, output, writer, write, generate

### 8️⃣ Workflow Orchestration & Execution
**Purpose:** Manage workflow execution, dependencies
**Modules:** `orchestration/`, `agent_workflow`, `agent_runner`
**Keywords:** workflow, runtime, runner, orchestrate, execute

### 9️⃣ State Management & Context
**Purpose:** Manage application state, context, artifacts
**Modules:** `state_management/`, `artifacts`, `manifest`, `path_manager`
**Keywords:** context, artifact, state, manifest, path_manager

### 🔟 Configuration & Schema Management
**Purpose:** Parse and manage configuration, schemas, DI
**Modules:** `configuration/`, DI configurator, bootstrap
**Keywords:** config, schema, bootstrap, di_configurator, container

### 1️⃣1️⃣ CLI & User Interface
**Purpose:** Command-line interface and user interactions
**Modules:** `cli/`, command handlers
**Keywords:** cli, command, interface

### 1️⃣2️⃣ Utilities & Common Functions
**Purpose:** Shared utilities, helpers, common functions
**Modules:** `utilities/`, helpers
**Keywords:** utils, helper, utility

### 1️⃣3️⃣ Shared Components
**Purpose:** Shared types, exceptions, and base classes
**Modules:** `shared/`, exceptions
**Keywords:** exception, error, base, shared

### 1️⃣3️⃣ Testing & Quality Assurance
**Purpose:** Test suites, fixtures, mocks, and quality checks
**Modules:** `tests/`, test utilities
**Keywords:** test, fixture, mock, assert, pytest

## Example Output

```
================================================================================
📋 CODE ORGANIZATION REPORT
================================================================================

📁 Root Path: /path/to/agent_actions
📦 Total Modules: 222
📂 Total Directories: 94
📝 Total Lines of Code: 35,575

🔄 PROCESSING STAGES BREAKDOWN:
   (Modules classified by their role in the agent pipeline)

   Configuration & Schema Management
   Parse and manage configuration, schemas, and contracts
   📦 35 modules
      • _internal/bootstrap/__init__.py
      • core/parser/config_parser.py
      ... and 33 more

   Input Loading & Extraction
   Load and extract data from various sources (JSON, CSV, XML, text)
   📦 19 modules
      • agents/extractors/json_loader.py
      • agents/extractors/text_loader.py
      ... and 17 more

   [... continues for all 12 stages ...]

🏗️  Architectural Layers:
  • _internal/ - Internal Implementation
    Files: 25, Lines: 2,400
  • core/ - Core Infrastructure
    Files: 70, Lines: 8,500
  • agents/ - Agent Layer
    Files: 62, Lines: 12,000
  [... etc ...]

⚠️  Organizational Issues (31):

  Circular dependencies (18):
    • _internal/staging/staging_loader.py -> agent_actions.core.constants
    • _internal/staging/staging_content.py -> agent_actions.core.constants
    ... and 16 more

  Large modules (13):
    • Large module (2285 LOC): tasks/services/batch_service.py
    • Large module (613 LOC): _internal/filters/secure_parser.py
    ... and 11 more

💡 Recommendations:
  1. 📏 Consider splitting 13 large modules (>500 LOC) into smaller, more focused modules
  2. 🔄 Refactor 18 potential circular dependencies by introducing interfaces
  3. 📚 Large codebase (200+ modules): Consider creating architecture documentation
  4. 🛠️  Multiple utils modules (20): Consider consolidating utility code
```

## Use Cases

### 1. Understand Codebase Structure
```bash
# Analyze the entire codebase
python .claude/helpers/code_organizer.py agent_actions/

# Analyze a specific module
python .claude/helpers/code_organizer.py agent_actions/core/
```

### 2. Identify Processing Stages
View which modules belong to each stage of the agent pipeline:
- See what happens during pre-processing
- Understand the LLM invocation flow
- Track post-processing and output generation

### 3. Detect Architectural Issues
- Find circular dependencies
- Identify large modules that should be split
- Locate missing `__init__.py` files
- Discover misplaced utility code

### 4. Export for Documentation
```bash
# Export as JSON for documentation tools
python .claude/helpers/code_organizer.py agent_actions/ --json org_report.json
```

### 5. Track Refactoring Progress
Run before and after refactoring to measure improvements:
- Number of circular dependencies reduced
- Large modules split
- Better organization of utilities

## Interpreting Results

### Processing Stages
- **High module count** in a stage indicates complexity
- **Few modules** may indicate missing functionality or over-consolidation
- **Modules in multiple stages** may indicate mixed responsibilities

### Architectural Layers
- **_internal/** - Low-level implementation details
- **core/** - Shared infrastructure and utilities
- **agents/** - Agent-specific logic
- **integrations/** - External service connections
- **tasks/** - High-level task orchestration
- **cli/** - User interface

### Issues to Address

**Circular Dependencies:**
- Introduce interfaces/protocols
- Move shared code to a common location
- Use dependency injection

**Large Modules (>500 LOC):**
- Split into multiple focused modules
- Extract classes to separate files
- Create subpackages for related functionality

**Missing `__init__.py`:**
- Add to make directories proper Python packages
- Include `__all__` for public API

**Utils Proliferation:**
- Consolidate related utilities
- Create focused utility modules
- Document utility organization

## Advanced Usage

### Exclude Patterns
```bash
# Exclude test files and temp directories
python .claude/helpers/code_organizer.py agent_actions/ --exclude "test_*" "*.bak" "temp_*"
```

### Integration with CI/CD
```bash
# Generate report and check for issues
python .claude/helpers/code_organizer.py agent_actions/ --json report.json

# Parse JSON and fail if too many issues
python -c "
import json
with open('report.json') as f:
    report = json.load(f)
    if len(report['organizational_issues']) > 50:
        print('Too many organizational issues!')
        exit(1)
"
```

### Compare Before/After Refactoring
```bash
# Before refactoring
python .claude/helpers/code_organizer.py agent_actions/ --json before.json

# After refactoring
python .claude/helpers/code_organizer.py agent_actions/ --json after.json

# Compare
python -c "
import json
with open('before.json') as f: before = json.load(f)
with open('after.json') as f: after = json.load(f)

print(f'Issues before: {len(before[\"organizational_issues\"])}')
print(f'Issues after: {len(after[\"organizational_issues\"])}')
print(f'Improvement: {len(before[\"organizational_issues\"]) - len(after[\"organizational_issues\"])} issues fixed')
"
```

## Tips

1. **Run regularly** during development to catch organizational drift
2. **Use JSON export** to track metrics over time
3. **Focus on high-priority issues** first (circular dependencies, large modules)
4. **Document stage assignments** for new team members
5. **Integrate into code review** process

## Related Commands

- `/find-dead-code` - Find unused code
- `/review-clean-code` - Review code quality
- `/review-batch-report` - Batch code analysis

---

This tool helps maintain clean, organized, and understandable code architecture by providing visibility into structure and identifying improvement opportunities.
