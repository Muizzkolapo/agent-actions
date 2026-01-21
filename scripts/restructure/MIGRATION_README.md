# Domain-Driven Restructure Migration

This document describes the migration scripts and manual changes made to restructure the `agent_actions` codebase from a technical-layer organization to a domain-driven structure.

## Migration Scripts

### 1. `migration_map.py`

Defines all mappings for the migration:

- **`DIRECTORY_STRUCTURE`**: List of new directories to create
- **`FILE_MIGRATIONS`**: Dict mapping `old_path` → `new_path` for each file
- **`IMPORT_REWRITES`**: Dict mapping `old_import` → `new_import` for updating imports

### 2. `migrate.py`

Main migration script with 17 phases:

```bash
# Preview changes
python scripts/restructure/migrate.py --dry-run

# Run all phases
python scripts/restructure/migrate.py --all

# Run specific phase
python scripts/restructure/migrate.py --phase N

# Only update imports (after files moved)
python scripts/restructure/migrate.py --update-imports
```

**Phases:**
- Phase 0: Create directory structure
- Phase 1: Move errors module
- Phase 2: Move utils module
- Phase 3: Move logging module
- Phase 4: Move models module
- Phase 5: Move input domain
- Phase 6: Move processing domain
- Phase 7: Move prompt domain
- Phase 8: Move output domain
- Phase 9: Move llm domain
- Phase 10: Move config domain
- Phase 11: Move validation domain
- Phase 12: Move workflow domain
- Phase 13: Move cli domain
- Phase 14: Move tooling
- Phase 15: Update imports
- Phase 16: Cleanup old directories

**Notes:**
- Guard filtering remains in the input preprocessing domain (`input/preprocessing/filtering`). It does **not** move to `processing/guards` in the scripted migration to match current repo usage.

---

## Current Repo Alignment (Jan 21, 2026)

The migration map is aligned to the current repository state:

- **Correlation IDs:** `utilities/correlation/version_id_generator.py` migrates to `utils/correlation/version_id.py`.
- **Version correlator:** `orchestration/version_correlator.py` migrates to `workflow/managers/loop.py`.
- **Chunking:** `preprocessing/chunking/field_chunking.py` and the `preprocessing/chunking/strategies/*` files are explicitly mapped.
- **LLM config:** `llm_invocation/config/vendor_config.py` migrates to `llm/config/vendor.py`.
- **CLI clean command:** `cli/test.py` migrates to `cli/commands/clean.py`.
- **No shims/fallbacks:** The script expects real source files and produces a clean move/update. Missing files are treated as map errors and should be fixed, not bypassed.

---

## Dry-Run Validation Checklist

Before running a real migration:

1. Run a full dry run:
   ```bash
   python scripts/restructure/migrate.py --all --dry-run
   ```
2. Confirm **no** "Source not found" lines appear.
3. Confirm import rewrites are non-zero and plausible.
4. Only then run the real migration.

### Dry-Run on an Already-Migrated Repo

If the repo has already been migrated, a full dry run will report many
`Source not found` lines because the *old* paths no longer exist. That is
expected and not an error by itself.

Use this decision guide:

- **If the repo is pre-migration:** any `Source not found` indicates a missing
  mapping or an incorrect path in `FILE_MIGRATIONS`. Fix the map and re-run.
- **If the repo is post-migration:** focus on *collisions* and any unexpected
  "Would move" operations. Those indicate the map still references live files
  and could cause unintended changes.
- For **import-only verification**, run:
  ```bash
  python scripts/restructure/migrate.py --update-imports --dry-run
  ```
  This keeps the check scoped to import rewrites without trying to move files.

---

## Manual Changes Made

The following changes were made manually after running the migration scripts:

### 1. Renamed `logging/` to `log/`

The Python standard library has a `logging` module, which caused conflicts. Renamed the directory:

```bash
mv agent_actions/logging agent_actions/log

# Updated all imports across the codebase:
# agent_actions.logging → agent_actions.log
```

**Files affected:** All files importing from `agent_actions.logging`

### 2. Fixed `__init__.py` Exports

After migration, some `__init__.py` files referenced old module names. Fixed:

#### `agent_actions/input/preprocessing/context/__init__.py`
```python
from .context_scope_processor import ContextScopeProcessor
from .static_data_loader import StaticDataLoader, StaticDataLoadError
from .llm_context_builder import LLMContextBuilder
from .llm_context_utils import LLMContextUtils
from .historical_node_loader import HistoricalNodeDataLoader, HistoricalDataRequest
```

#### `agent_actions/shared/user_errors/__init__.py`
```python
from .error_translator import ErrorTranslator  # was .translator
```

#### `agent_actions/shared/user_errors/formatters/__init__.py`
```python
from .error_formatter_base import ErrorFormatter  # was .base
from .configuration_formatter import ConfigurationErrorFormatter
from .llm_formatter import LLMErrorFormatter
from .validation_formatter import ValidationErrorFormatter
from .file_formatter import FileErrorFormatter
```

#### `agent_actions/validation/static_analyzer/__init__.py`
```python
from .workflow_static_analyzer import WorkflowStaticAnalyzer, analyze_workflow  # was .analyzer
```

#### `agent_actions/workflow/__init__.py`
```python
from agent_actions.workflow.schema_service import WorkflowSchemaService  # Added
```

#### `agent_actions/input_loading/__init__.py`
```python
from .base_base_loader import *  # was .base
```

### 3. Copied Missing Files

Some files weren't included in `FILE_MIGRATIONS` and were copied manually:

```bash
# Context preprocessing files
cp agent_actions/preprocessing/context/*.py agent_actions/input/preprocessing/context/

# Input loading files
cp agent_actions/input_loading/*.py agent_actions/input/loaders/
```

### 4. Fixed Test Imports

Updated test files to use new import paths:

#### `tests/core/test_udf_loader.py`
```python
# Changed:
from agent_actions.input.loaders.udf_loader import ...
# To:
from agent_actions.input_loading.udf_loader import ...
```

#### `tests/services/test_workflow_schema_service.py`
```python
# Changed:
from agent_actions.workflow.workflow_schema_service import ...
# To:
from agent_actions.workflow.schema_service import ...
```

#### `tests/validation/test_conflict_detector.py`
```python
# Consolidated imports to use package-level imports:
from agent_actions.validation.static_analyzer import (
    ConflictDetector,
    ConflictAnalysisResult,
    ...
)
```

---

## New Directory Structure

```
agent_actions/
├── cli/                    # Command-line interface
│   └── commands/           # CLI subcommands
├── config/                 # Configuration and DI
│   ├── di/                 # Dependency injection
│   └── schema.py           # Config schemas
├── errors/                 # Error types and exceptions
├── input/                  # Input loading domain
│   ├── loaders/            # Data loaders
│   └── preprocessing/      # Data preprocessing
│       └── context/        # Context building
├── input_loading/          # Backward compat (to be removed)
├── llm/                    # LLM invocation domain
│   ├── batch/              # Batch processing
│   └── providers/          # LLM provider clients
├── log/                    # Logging infrastructure
│   └── errors/             # Logging errors
├── models/                 # Data models
├── output/                 # Output handling domain
│   ├── response/           # Response processing
│   └── writers/            # File writers
├── processing/             # Core processing domain
│   ├── guards/             # Processing guards
│   ├── recovery/           # Error recovery
│   └── transform/          # Data transformations
├── prompt/                 # Prompt generation domain
│   ├── context/            # Context for prompts
│   └── templates/          # Prompt templates
├── shared/                 # Shared utilities
│   └── user_errors/        # User-facing errors
├── tooling/                # Developer tools
│   ├── docs/               # Documentation generation
│   └── lsp/                # Language server
├── utils/                  # General utilities
│   ├── expression/         # Expression evaluation
│   └── udf_management/     # UDF utilities
├── validation/             # Validation domain
│   ├── static_analysis/    # Static analysis (compat)
│   └── static_analyzer/    # Static type checking
└── workflow/               # Workflow orchestration
    ├── managers/           # Workflow managers
    └── parallel/           # Parallel execution
```

---

## Test Results

After migration: **1575/1700 tests passing (93%)**

Remaining failures are primarily integration tests that need additional import path updates.
