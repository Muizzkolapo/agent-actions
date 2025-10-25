---
description: Analyze a file or directory for dead code with multi-tool validation
---

# Enhanced Dead Code Analysis: {{arg1}}

Perform a comprehensive multi-tool dead code analysis on: **{{arg1}}**

## Overview

This command uses **multiple detection tools** to find dead code while minimizing false positives:

- **Ruff**: Fast, accurate import/variable detection (95% confidence)
- **Vulture**: Comprehensive dead code detection (filtered for false positives)
- **AST Analysis**: Pattern-based import detection
- **Smart Filters**: Filters out dispatch tables, abstract methods, vendor handlers, etc.

## Step 1: Run Enhanced Dead Code Analyzer

```bash
python .claude/helpers/dead_code_analyzer.py {{arg1}}
```

The analyzer will:
1. Run Ruff for accurate import/variable detection
2. Run Vulture for comprehensive scanning
3. Run AST analysis for additional validation
4. Merge results and score confidence levels
5. Filter known false positive patterns

### Confidence Tiers

**🔴 HIGH (90-100%)**: Very safe to remove
- Multiple tools agree, OR
- Ruff confirms (highly accurate)
- Focus on these first

**🟡 MEDIUM (70-89%)**: Review before removing
- Vulture detects but may be used indirectly
- Check for dispatch tables, abstract methods, dynamic usage

**⚪ LOW (<70%)**: Likely false positives
- High risk of being used via polymorphism, dispatch, etc.
- Usually vendor handlers, providers, or base class methods
- Skip these

## Step 2: Analyze the Results

### Focus on HIGH Confidence Items First

These are the safest to remove:
- Unused imports confirmed by Ruff
- Items detected by multiple tools
- Clear, provable unused code

Example output:
```
🎯 HIGH CONFIDENCE ITEMS (90-100%) - Safe to Remove

📄 agent_actions/integrations/providers/gemini/vendor.py
   Line 3: import 'Any' [95% | ruff,ast]
   Line 3: import 'Dict' [95% | ruff,ast]
   Line 3: import 'List' [95% | ruff,ast]
```

### Review MEDIUM Confidence Items

These require verification:
- May be used via dispatch tables
- May be abstract methods
- May be part of public APIs

Example with warning:
```
⚠️  MEDIUM CONFIDENCE ITEMS (70-89%) - Review Before Removing

📄 agent_actions/integrations/providers/anthropic/provider.py
   Line 327: method 'prepare_tasks' [70% | vulture]
   ⚠️  Located in vendor/provider/handler directory (likely used via dispatch)
```

### Skip LOW Confidence Items

These are almost always false positives:
- Vendor handlers (e.g., `ClaudeHandler`, `GeminiHandler`)
- Provider classes ending in `Provider`
- Factory classes ending in `Factory`
- Base class methods

## Step 3: Generate Cleanup Plan

Create a prioritized cleanup plan based on confidence tiers:

```
═══════════════════════════════════════════════════════
🧹 DEAD CODE CLEANUP PLAN
═══════════════════════════════════════════════════════
Target: {{arg1}}
Date: [current date]

📊 ANALYSIS SUMMARY
───────────────────────────────────────────────────────
Tools Used: ruff, vulture, ast
Total Items Found: [X]
High Confidence: [X] items
Medium Confidence: [X] items
Low Confidence: [X] items (skip these)

🎯 PHASE 1: HIGH CONFIDENCE CLEANUP (Safe)
───────────────────────────────────────────────────────
These can be removed immediately:

Unused Imports ([X] items):
1. [file:line] - [import_name] [tools: ruff,ast]
2. [file:line] - [import_name] [tools: ruff,vulture]

Unused Variables ([X] items):
1. [file:line] - [var_name] [tools: ruff]

Estimated Impact: ~[X] lines removed
Risk Level: Very Low ✅

⚠️  PHASE 2: MEDIUM CONFIDENCE REVIEW (Verify First)
───────────────────────────────────────────────────────
Review these before removal:

1. [file:line] - [item_name]
   • Why flagged: [reason]
   • False positive risk: [risk_description]
   • Verification needed: [check dispatch tables/tests/etc]

⛔ PHASE 3: LOW CONFIDENCE ITEMS (Skip)
───────────────────────────────────────────────────────
DO NOT REMOVE: [X] items

These are likely false positives:
- [X] vendor/provider/handler classes
- [X] base class methods
- [X] factory pattern classes

═══════════════════════════════════════════════════════
🛠️ RECOMMENDED ACTIONS
═══════════════════════════════════════════────────────

Immediate Actions (HIGH confidence):
1. Remove [X] unused imports - safest cleanup
2. Remove [X] unused variables
3. Run tests to verify

Manual Review Required (MEDIUM confidence):
1. Check if [item_name] is used in tests
2. Search for dynamic usage: grep -r "[item_name]" .
3. Check git history: git log -S"[item_name]"

Do Not Remove (LOW confidence):
All items ending in Handler, Provider, Factory, or in base classes

═══════════════════════════════════════════════════════
```

## Step 4: Execute Cleanup

### Phase 1: Remove HIGH Confidence Items

```bash
# Start with unused imports (safest)
# The analyzer shows exactly which lines to modify

# Example: Remove unused imports from gemini/vendor.py line 3
# Before: from typing import Any, Dict, List, Optional, Union
# After:  (remove the line or keep only used imports)

# Run tests after each file
pytest tests/
```

### Phase 2: Review MEDIUM Confidence Items

For each medium-confidence item:

1. **Search for usage**:
   ```bash
   grep -r "item_name" agent_actions/
   grep -r "item_name" tests/
   ```

2. **Check git history**:
   ```bash
   git log -S"item_name" --oneline
   ```

3. **Check for indirect usage**:
   - Dispatch tables (VENDOR_HANDLERS, etc.)
   - Abstract methods (base classes)
   - Dynamic imports
   - Reflection/getattr calls

4. **If truly unused**: Remove and run tests

### Phase 3: Document Findings

Create a summary:
```
Dead Code Cleanup Summary
=========================
High Confidence Removed: [X] items, [X] lines
Medium Confidence Reviewed: [X] items
  - Removed: [X] items
  - Kept (in use): [X] items
Low Confidence Skipped: [X] items

Total Lines Removed: [X,XXX]
Tests Status: ✅ All passing
```

## Important Guidelines

### Always Verify Before Removing

Even high-confidence items should be checked:
- Run tests after removal
- Check for indirect usage
- Review git history

### Known False Positive Patterns

The analyzer automatically filters these, but be aware:

1. **Dispatch Tables**: `FooHandler`, `FooProvider`, `FooProcessor`
2. **Abstract Methods**: Methods in base classes
3. **Magic Methods**: `__init__`, `__str__`, etc.
4. **Test Fixtures**: `setUp`, `tearDown`, `pytest_*`
5. **Vendor/Provider Directories**: Code in `vendor/`, `provider/`, `handler/` dirs

### When NOT to Remove

❌ **Abstract methods** in base classes
❌ **Public API methods** (even if unused internally)
❌ **Vendor handler classes** (used via dispatch)
❌ **Plugin/extension points**
❌ **Methods called via reflection**
❌ **Test fixtures** (pytest hooks)

## Understanding the Confidence Scores

### How Confidence is Calculated

**HIGH (90-100%)**:
- Ruff detects it (95% base confidence)
- Multiple tools agree (+5% bonus per tool)
- Clear, provable unused code

**MEDIUM (70-89%)**:
- Vulture detects it (60-80% base)
- Filtered for known false positive patterns
- May be used indirectly

**LOW (<70%)**:
- Vulture only (60% base)
- Matches false positive patterns (-20% penalty)
- High risk of indirect usage

### Which Tools Detected It

Check the `[tools]` indicator:
- `[ruff]` - Very reliable for imports/variables
- `[ruff,vulture]` - Both agree, very confident
- `[vulture]` - Check carefully, may be false positive
- `[ast,ruff]` - Both static analysis tools agree

## Example Workflow

### 1. Run Analysis

```bash
/find-dead-code agent_actions/llm_invocation
```

### 2. Review HIGH Confidence Items

Output shows:
```
🎯 HIGH CONFIDENCE ITEMS (90-100%) - 11 items

📄 gemini/vendor.py
   Line 3: import 'Any' [95% | ruff,ast]
   Line 3: import 'Dict' [95% | ruff,ast]
   ...
```

### 3. Remove HIGH Confidence Items

Remove the 11 unused imports shown.

### 4. Run Tests

```bash
pytest tests/integrations/providers/
```

### 5. Review MEDIUM Confidence Items

Output shows:
```
⚠️  MEDIUM CONFIDENCE ITEMS (70-89%) - 3 items

📄 base.py
   Line 188: method 'compile_schema' [70% | vulture]
   ⚠️  Method in base class (may be abstract or overridden)
```

Check if `compile_schema` is actually used:
```bash
grep -r "compile_schema" agent_actions/
# Found: It's deprecated but documented - keep for now
```

### 6. Skip LOW Confidence Items

Output shows:
```
⚪ LOW CONFIDENCE ITEMS (<70%) - 47 items

These are likely false positives (vendor handlers, etc.)
```

Don't waste time reviewing these.

## Command Options

```bash
# Full analysis with details
python .claude/helpers/dead_code_analyzer.py agent_actions/orchestration

# Summary only
python .claude/helpers/dead_code_analyzer.py agent_actions/configuration --brief

# Show all items including low-confidence
python .claude/helpers/dead_code_analyzer.py agent_actions/utilities --show-all
```

## Tool Installation

For best results, install all tools:

```bash
# Required
pip install vulture  # Comprehensive detection

# Highly recommended
pip install ruff     # Fast, accurate import detection

# Note: AST analysis is built-in (no installation needed)
```

## After Analysis

Summarize your findings:

**Cleanup Summary**:
- HIGH confidence items removed: [X]
- MEDIUM confidence reviewed: [X] (removed [X], kept [X])
- LOW confidence skipped: [X]
- Total lines removed: [X,XXX]
- Tests: ✅ All passing

**Next Steps**:
1. Commit high-confidence cleanups
2. Document any kept medium-confidence items (why they're in use)
3. Run analysis on next module

## Ask for Next Actions

"Based on the analysis:

**HIGH confidence items** ([X] items):
- Would you like me to remove these now?

**MEDIUM confidence items** ([X] items):
- Should I investigate specific items?
- Do you want a detailed review of any file?

**Next steps**:
1. Remove high-confidence items?
2. Create cleanup branch?
3. Analyze different module?"
