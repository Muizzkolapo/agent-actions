---
description: Analyze a file or directory for dead code (unused functions, classes, imports, variables)
---

# Dead Code Analysis: {{arg1}}

Perform a comprehensive dead code analysis on: **{{arg1}}**

## Step 1: Run Dead Code Analyzer

Run the specialized dead code analyzer that uses vulture + AST analysis:

```bash
python .claude/helpers/dead_code_analyzer.py {{arg1}}
```

This will detect:
- **Unused Functions**: Functions that are defined but never called
- **Unused Classes**: Classes that are defined but never instantiated
- **Unused Methods**: Methods that are never invoked
- **Unused Variables**: Variables that are assigned but never read
- **Unused Imports**: Import statements for modules/objects that are never used
- **Unused Properties**: Properties that are never accessed
- **Unused Attributes**: Class attributes that are never referenced

The output includes:
- Summary statistics of dead code by type
- Distribution visualization (ASCII bar chart)
- Detailed findings organized by file
- Line numbers and confidence levels for each finding
- Estimated lines that could be removed

## Step 2: Analyze the Results

Review the output and categorize the findings:

### High Confidence (🔴 80%+)
These items are very likely dead code and can be safely removed after a quick verification:
- List the most impactful high-confidence items
- Note which files have the most dead code

### Medium Confidence (🟡 60-79%)
These items require more careful review:
- May be used indirectly (reflection, dynamic imports, etc.)
- May be part of a public API
- May be test fixtures or utilities

### Files with Most Dead Code
Identify files that need the most cleanup:
- Which files have the highest number of dead items?
- Which files have the most dead lines?

## Step 3: Generate Cleanup Report

Create a prioritized cleanup report:

```
═══════════════════════════════════════════════════════
🧹 DEAD CODE CLEANUP REPORT
═══════════════════════════════════════════════════════
Target: {{arg1}}
Date: [current date]

📊 EXECUTIVE SUMMARY
───────────────────────────────────────────────────────
Total Dead Items: [X]
Estimated Dead Lines: [X,XXX]
Potential Impact: [X]% reduction in codebase size

🎯 PRIORITY 1 - QUICK WINS (High Confidence)
───────────────────────────────────────────────────────
These can be safely removed now:

1. [file_path:line]
   • Type: [function/class/import]
   • Name: '[name]'
   • Impact: [X] lines removed
   • Reason: [why it's dead]

2. ...

🟡 PRIORITY 2 - VERIFY BEFORE REMOVING (Medium Confidence)
───────────────────────────────────────────────────────
Review these carefully before removal:

1. [file_path:line]
   • Type: [function/class]
   • Name: '[name]'
   • Why verify: [might be used via reflection/API/etc]

📁 PRIORITY 3 - FILES NEEDING CLEANUP
───────────────────────────────────────────────────────
Files with the most dead code:

1. [file_path]
   • Dead items: [X]
   • Dead lines: [X]
   • Main issues: [summary]

🔍 DETAILED ANALYSIS
───────────────────────────────────────────────────────

For each major file with dead code:

📄 [file_path]

UNUSED IMPORTS (Easy Cleanup):
• Line [X]: [import name] - never referenced
• Line [Y]: [import name] - never used
→ Impact: Faster import times, cleaner dependencies

UNUSED FUNCTIONS:
• Line [X]: '[function_name]' ([Z] lines)
  - Was it replaced by something else?
  - Is it legacy code?
  - Should it be deprecated instead of removed?

UNUSED CLASSES:
• Line [X]: '[class_name]' ([Z] lines)
  - Check for subclasses
  - Check for serialization dependencies
  - Document reason for removal

═══════════════════════════════════════════════════════
🛠️ RECOMMENDED ACTIONS
═══════════════════════════════════════════════════════

Immediate Actions (High Confidence):
1. Remove unused imports in [file1, file2, file3]
2. Delete dead utility functions in [file4]
3. Remove unused helper classes in [file5]

Careful Review Required:
1. Verify [function_name] in [file] - may be API endpoint
2. Check [class_name] in [file] - may be used in tests
3. Investigate [method_name] - may be callback/hook

Not Recommended to Remove:
1. [name] - Part of public API (deprecate instead)
2. [name] - Used via reflection/dynamic import
3. [name] - Test fixture

═══════════════════════════════════════════════════════
📈 EXPECTED BENEFITS
═══════════════════════════════════════════════════════

After cleanup:
• ✅ Reduced codebase size: ~[X,XXX] lines
• ✅ Faster imports: [X] unused imports removed
• ✅ Lower maintenance: Fewer dead code paths
• ✅ Better clarity: Remove confusing unused code
• ✅ Improved metrics: Better code coverage visibility

═══════════════════════════════════════════════════════
```

## Step 4: Ask for Next Actions

After presenting the report, ask the user:

"Would you like me to:
1. Start removing high-confidence dead code items?
2. Generate a detailed cleanup plan for a specific file?
3. Create a git branch for systematic dead code removal?
4. Run dead code analysis on a different module/directory?"

## Important Guidelines

- **Always verify before removing**: Even high-confidence findings should be checked
- **Check for indirect usage**: Look for reflection, `getattr()`, dynamic imports, serialization
- **Consider public APIs**: Don't remove public methods even if unused internally
- **Check tests**: Look in test files for usage
- **Be conservative with methods**: Methods might be hooks, callbacks, or overrides
- **Group deletions logically**: Remove related dead code together
- **Update documentation**: Remove references to deleted code
- **Run tests after removal**: Ensure nothing breaks

## Special Cases to Watch For

1. **Test fixtures**: May look unused but are required by test framework
2. **Abstract methods**: Must exist even if not called directly
3. **API endpoints**: May be called externally even if not in codebase
4. **CLI commands**: May be invoked via command line
5. **Configuration handlers**: May be used via config files
6. **Serialization**: Classes used for JSON/pickle may look unused
7. **Plugins/Extensions**: May be loaded dynamically
8. **Deprecated code**: Should be marked deprecated, not immediately removed

## For Directory Analysis

If {{arg1}} is a directory, provide:
1. **Cross-file analysis**: Show which files are never imported
2. **Dependency graph**: Identify isolated modules
3. **Cleanup order**: Suggest order of removal (bottom-up)
4. **Impact assessment**: Which removals have the most impact

## After Analysis

Summarize:
- Total dead code found
- Estimated lines that can be removed
- Top files needing cleanup
- Recommended next steps
