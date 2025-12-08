# agent_actions/ Structure Cleanup Tasks

**Branch:** `refactor-agent-actions-structure`
**Created:** 2025-12-08
**Purpose:** Reorganize agent_actions/ folder structure to improve maintainability

---

## Overview

Based on comprehensive analysis of the codebase:
- **Total files in agent_actions/**: 276
- **Files needing attention**: ~15-20 files (5-7%)
- **Estimated effort**: 1-2 days with testing

**Main Issues:**
1. Prompt logic in wrong module (preprocessing → prompt_generation)
2. Duplicate files (pp_* versions)
3. Name conflicts (same class names in different modules)
4. Redundant prefixes (pp_, utils_)
5. Misplaced utilities

---

## Priority 1: High Priority (Immediate)

### Task 1.1: Remove Duplicate Files ✅ COMPLETED

**What:** Delete 1 duplicate file that's not being used

**Why:**
- `pp_sample_enricher.py` is 100% identical to `sample_enricher.py`
- Having duplicates causes confusion about which file is "correct"
- Wastes developer time when searching code
- Risk of updating one but not the other

**How:**
```bash
git rm agent_actions/preprocessing/pp_sample_enricher.py
```

**Verification:**
- ✅ Confirmed identical to sample_enricher.py (diff shows no changes)
- ✅ Confirmed not imported anywhere (grep found no imports)

**Impact:** Zero risk - true duplicate not in use

**Status:** ✅ Completed in commit dca801e

**Note:** `utilities/logging.py` was removed from this task as it's actively used by `di_configurator.py`.
It contains `LoggerFactory` which differs from `logging/factory.py`. Migration deferred to Task 2.5.

---

### Task 1.2: Move Prompt Files to prompt_generation/

**What:** Move 3 prompt-related files from preprocessing/ to prompt_generation/

**Why:**
- These files handle **prompt preparation**, not data preprocessing
- Current location violates Single Responsibility Principle
- Developers expect prompt logic in the `prompt_generation/` module
- `preprocessing/` module is too large (20 files) - needs focus
- Improves code discoverability and maintainability

**Files misplaced:**
- `prompt_formatter.py` - Loads and formats prompts with field references
- `prompt_utils.py` - Processes field references and dispatch_task() calls
- `sample_enricher.py` - Enriches prompts with few-shot examples

**How:**
```bash
git mv agent_actions/preprocessing/prompt_formatter.py agent_actions/prompt_generation/
git mv agent_actions/preprocessing/prompt_utils.py agent_actions/prompt_generation/
git mv agent_actions/preprocessing/sample_enricher.py agent_actions/prompt_generation/
```

**Import updates needed:**
- [ ] Search for `from agent_actions.preprocessing.prompt_formatter import`
- [ ] Search for `from agent_actions.preprocessing.prompt_utils import`
- [ ] Search for `from agent_actions.preprocessing.sample_enricher import`
- [ ] Update all imports to `agent_actions.prompt_generation.*`

**Impact:** Medium risk - requires import updates across codebase

---

### Task 1.3: Rename Files to Avoid Conflicts

**What:** Rename 2 files that have confusing name conflicts

---

#### **Problem 1: Two Different FileHandler Classes**

**Why this is bad:**
- Two different files, both defining a class called `FileHandler`
- Causes confusion: "Which FileHandler should I import?"
- Can lead to bugs when wrong one is imported
- Makes code reviews harder
- Violates naming uniqueness principle

**Current state:**
```bash
agent_actions/utilities/file_handler.py           → class FileHandler (general file ops)
agent_actions/prompt_generation/file_handler.py  → class FileHandler (JSON-specific)
```

**How to fix:**
```bash
# Rename the JSON-specific one to be descriptive
git mv agent_actions/prompt_generation/file_handler.py \
       agent_actions/prompt_generation/json_file_handler.py
```

**Import updates needed:**
- [ ] Search for `from agent_actions.prompt_generation.file_handler import`
- [ ] Update to `from agent_actions.prompt_generation.json_file_handler import`
- [ ] Update class usage if needed

---

#### **Problem 2: Two Confusingly Similar LoopCorrelator Names**

**Why this is bad:**
- Two files with almost identical names but different responsibilities
- `loop_correlator.py` appears twice in codebase
- Developer confusion: "Which loop correlator do I need?"
- Easy to import the wrong one
- Names don't clearly indicate different purposes

**Current state:**
```bash
agent_actions/orchestration/loop_correlator.py           → LoopOutputCorrelator (handles parallel loop outputs)
agent_actions/utilities/correlation/loop_correlator.py  → LoopCorrelator (generates correlation IDs)
```

**How to fix:**
```bash
# Rename utilities one to be more descriptive of its actual purpose
git mv agent_actions/utilities/correlation/loop_correlator.py \
       agent_actions/utilities/correlation/loop_id_generator.py
```

**Import updates needed:**
- [ ] Search for `from agent_actions.utilities.correlation.loop_correlator import`
- [ ] Update to `from agent_actions.utilities.correlation.loop_id_generator import`
- [ ] Rename class inside file: `LoopCorrelator` → `LoopIdGenerator`
- [ ] Update all class instantiations and usage

**Impact:** Medium risk - requires import and class name updates

---

## Priority 2: Medium Priority (Short-term)

### Task 2.1: Clean Up Redundant Prefixes in utilities/

**Files to rename:**
```bash
agent_actions/utilities/utils_path_utils.py         → agent_actions/utilities/path_utils.py
agent_actions/utilities/utils_processor_helpers.py  → agent_actions/utilities/processor_helpers.py
```

**Action:**
```bash
git mv agent_actions/utilities/utils_path_utils.py agent_actions/utilities/path_utils.py
git mv agent_actions/utilities/utils_processor_helpers.py agent_actions/utilities/processor_helpers.py
```

**Import updates needed:**
- [ ] Search for `from agent_actions.utilities.utils_path_utils import`
- [ ] Search for `from agent_actions.utilities.utils_processor_helpers import`
- [ ] Update all imports

**Impact:** Low risk - simple renames

---

### Task 2.2: Move Response Transformation to response_processing/

**Files to move:**
```bash
agent_actions/preprocessing/response_transformer.py     → agent_actions/response_processing/
agent_actions/preprocessing/pp_response_transformer.py  → agent_actions/response_processing/ (or DELETE if duplicate)
```

**Action:**
```bash
# First check if pp_response_transformer is different
diff agent_actions/preprocessing/response_transformer.py \
     agent_actions/preprocessing/pp_response_transformer.py

# If identical, delete the pp_ version
git rm agent_actions/preprocessing/pp_response_transformer.py

# Move the main one
git mv agent_actions/preprocessing/response_transformer.py \
       agent_actions/response_processing/
```

**Import updates needed:**
- [ ] Search for `from agent_actions.preprocessing.response_transformer import`
- [ ] Search for `from agent_actions.preprocessing.pp_response_transformer import`
- [ ] Update all imports to `agent_actions.response_processing.*`

**Impact:** Medium risk - requires import updates

---

### Task 2.3: Clean Up Redundant Prefixes in preprocessing/

**Files to check and rename/merge:**
```bash
agent_actions/preprocessing/pp_context_preprocessor.py
```

**Action:**
```bash
# Check if it's different from context_preprocessor.py
diff agent_actions/preprocessing/context_preprocessor.py \
     agent_actions/preprocessing/pp_context_preprocessor.py

# Option 1: If identical, delete pp_ version
git rm agent_actions/preprocessing/pp_context_preprocessor.py

# Option 2: If different, rename to something meaningful
git mv agent_actions/preprocessing/pp_context_preprocessor.py \
       agent_actions/preprocessing/context_preprocessor_v2.py
```

**Import updates needed:**
- [ ] Search for `from agent_actions.preprocessing.pp_context_preprocessor import`
- [ ] Update imports based on action taken

**Impact:** Low-Medium risk - depends on whether file is in use

---

### Task 2.4: Fix Misplaced Validation Utility

**File to move:**
```bash
agent_actions/validation/llm_context_utils.py  → agent_actions/utilities/
```

**Action:**
```bash
git mv agent_actions/validation/llm_context_utils.py agent_actions/utilities/
```

**Import updates needed:**
- [ ] Search for `from agent_actions.validation.llm_context_utils import`
- [ ] Update to `from agent_actions.utilities.llm_context_utils import`

**Impact:** Low risk - simple move

---

### Task 2.5: Consolidate Logging Utilities

**Problem:** `utilities/logging.py` contains `LoggerFactory` that's actively used by `di_configurator.py`

**Files involved:**
```bash
agent_actions/utilities/logging.py       # Contains LoggerFactory used by DI
agent_actions/logging/factory.py         # Contains more complete LoggerFactory
```

**Options:**

**Option A: Migrate DI to use logging/factory.py**
```bash
# Update di_configurator.py import
from agent_actions.logging.factory import LoggerFactory

# Then delete utilities/logging.py
git rm agent_actions/utilities/logging.py
```

**Option B: Keep utilities/logging.py as a compatibility wrapper**
```python
# In utilities/logging.py - make it a re-export
from agent_actions.logging.factory import LoggerFactory
from agent_actions.logging.context import LoggingContext

__all__ = ['LoggerFactory', 'LoggingContext']
```

**Recommended:** Option A (cleaner, removes duplication)

**Import updates needed:**
- [ ] Update `agent_actions/configuration/di_configurator.py`
- [ ] Search for any other imports of `utilities.logging`

**Impact:** Low risk - single import to update

---

## Priority 3: Low Priority (Long-term)

### Task 3.1: Create io/ Module for File Operations

**Purpose:** Consolidate file I/O operations

**Files to move:**
```bash
agent_actions/utilities/file_handler.py  → agent_actions/io/file_handler.py
agent_actions/utilities/file_writer.py   → agent_actions/io/file_writer.py
agent_actions/input_loading/*_loader.py  → agent_actions/io/readers/*_loader.py (optional)
```

**Action:**
```bash
# Create io module
mkdir -p agent_actions/io/readers
touch agent_actions/io/__init__.py
touch agent_actions/io/readers/__init__.py

# Move files
git mv agent_actions/utilities/file_handler.py agent_actions/io/
git mv agent_actions/utilities/file_writer.py agent_actions/io/
```

**Import updates needed:**
- [ ] Extensive - search all file_handler and file_writer imports
- [ ] Update to new io module paths

**Impact:** High risk - many imports to update

---

### Task 3.2: Reorganize preprocessing/ into Submodules

**Purpose:** Split large preprocessing module (20 files)

**Proposed structure:**
```
preprocessing/
├── data/           # Data transformation
├── context/        # Context building
├── parsing/        # AST and expression parsing
├── chunking/       # Field chunking
└── staging/        # Staging content
```

**Action:** This is a major refactoring - defer to separate task

**Impact:** Very high risk - major structural change

---

### Task 3.3: Slim Down utilities/ Module

**Purpose:** Move domain-specific utilities to proper modules

**Files to move:**
```bash
agent_actions/utilities/context_scope_processor.py  → agent_actions/preprocessing/context/
agent_actions/utilities/llm_context_builder.py      → agent_actions/preprocessing/context/
```

**Action:** Defer to separate task after preprocessing reorganization

**Impact:** High risk - depends on other refactoring

---

## Testing Checklist

After each priority level:

### Unit Tests
- [ ] Run all tests: `pytest`
- [ ] Run specific module tests after changes
- [ ] Check for import errors

### Integration Tests
- [ ] Run integration tests: `pytest tests/integration/`
- [ ] Verify workflow execution still works

### Import Verification
- [ ] Search for old import paths: `grep -r "from agent_actions.preprocessing.prompt_formatter"`
- [ ] Verify no broken imports remain

### Linting
- [ ] Run linter: `pylint agent_actions/`
- [ ] Fix any new issues introduced

---

## Rollback Plan

If issues arise:

```bash
# Rollback entire branch
git checkout main
git branch -D refactor-agent-actions-structure

# Rollback specific file
git checkout main -- path/to/file.py

# Rollback last commit
git reset --hard HEAD~1
```

---

## Completion Checklist

- [ ] Priority 1 tasks completed
- [ ] All imports updated and verified
- [ ] Tests passing
- [ ] Code review completed
- [ ] Documentation updated
- [ ] Pull request created
- [ ] Priority 2 tasks completed (if approved)
- [ ] Priority 3 tasks deferred or completed

---

## Notes

- Keep commits atomic (one logical change per commit)
- Update this file as tasks are completed
- Mark tasks with `[DONE]` when completed
- Add notes about challenges or decisions made

---

## Commit Strategy

Each priority level should be a separate commit:

1. **Commit 1:** Remove duplicate files
2. **Commit 2:** Move prompt files to prompt_generation + imports
3. **Commit 3:** Rename files to avoid conflicts + imports
4. **Commit 4:** Clean up redundant prefixes + imports
5. **Commit 5:** Move response files + imports
6. **Commit 6:** Fix misplaced files + imports

Each commit message should follow:
```
refactor(module): brief description

- Detailed change 1
- Detailed change 2

Refs: #issue-number (if applicable)
```
