---
description: Review a module for clean code principles using AST analysis, lineage tracking, and Feynman-style explanations
---

# Clean Code Review: {{arg1}}

Perform a comprehensive clean code review of the module: **{{arg1}}**

## Step 1: Gather Information

Read the following files:
1. **Source code**: `agent_actions/{{arg1}}.py` (replace dots with slashes in path)
2. **Documentation**: `pdocs/{{arg1}}.md` (replace dots with slashes in path)

## Step 2: Run Comprehensive Analysis

Run the code analyzer with mature tools (radon, prospector, vulture):

```bash
python .claude/helpers/code_analyzer.py agent_actions/{{arg1}}.py
```

This automatically runs:
- **Radon**: Cyclomatic complexity, maintainability index, LOC metrics
- **Prospector**: Code quality issues (combines pylint, pyflakes, pydocstyle, etc.)
- **Vulture**: Dead code detection
- **AST Analysis**: Imports, classes, functions, inheritance
- **ASCII Diagrams**: Dependencies and lineage visualization

The output includes:
- Module lineage & dependencies (ASCII diagram)
- Complexity metrics per function
- Maintainability index score
- Lines of code statistics
- All code quality violations grouped by severity
- Dead/unused code findings

## Step 3: Feynman-Style Explanation First

Before analyzing clean code violations, explain the module simply:

**Format:**
```
🎓 FEYNMAN EXPLANATION
═══════════════════════════════════════

1. WHAT DOES IT DO? (In one sentence, explain to a 10-year-old)
   →

2. WHY DOES IT EXIST? (What problem does it solve?)
   →

3. HOW DOES IT WORK? (High-level flow, 3-5 steps)
   → 1.
   → 2.
   → 3.

4. WHAT DOES IT TOUCH? (Key dependencies and why)
   →
```

Use ASCII diagrams to visualize the flow if helpful.

## Step 4: Clean Code Analysis

Now analyze against these principles:

### 🔍 SOLID Principles
- **S** - Single Responsibility: Does each class/function do ONE thing?
- **O** - Open/Closed: Is it open for extension, closed for modification?
- **L** - Liskov Substitution: Can subclasses replace parents safely?
- **I** - Interface Segregation: Are interfaces minimal and focused?
- **D** - Dependency Inversion: Does it depend on abstractions?

### 📏 Code Quality Metrics
- **Complexity**: Is cyclomatic complexity < 10 per function?
- **Length**: Are functions < 50 lines, classes < 300 lines?
- **Nesting**: Is nesting depth < 4 levels?
- **Coupling**: Does it depend on too many modules (> 7)?

### ✅ Best Practices
- **Naming**: Clear, descriptive names (no abbreviations)?
- **Type Hints**: All parameters and returns typed?
- **Docstrings**: All public methods documented?
- **Error Handling**: Specific exceptions, proper cleanup?
- **DRY**: No repeated code blocks?
- **Magic Values**: No hardcoded numbers/strings?

## Step 5: Generate Report

Create a structured report:

```
═══════════════════════════════════════════════════════
📋 CLEAN CODE REVIEW REPORT
═══════════════════════════════════════════════════════
Module: {{arg1}}
Date: [current date]

[Include ASCII lineage diagram here]

🎓 SIMPLE EXPLANATION (Feynman Style):
[Your explanation from Step 3]

═══════════════════════════════════════════════════════
🔴 CRITICAL VIOLATIONS (Fix Immediately)
═══════════════════════════════════════════════════════

[List critical issues with line numbers]
Example:
❌ Line 45-67: Function `process_data` violates SRP
   - Does 3 things: validation, transformation, and storage
   - Complexity: 15 (too high)

   💡 Refactoring:
   Split into:
   - `validate_data()`
   - `transform_data()`
   - `store_data()`

═══════════════════════════════════════════════════════
🟡 MAJOR ISSUES (Should Fix Soon)
═══════════════════════════════════════════════════════

[List major issues]

═══════════════════════════════════════════════════════
🟢 MINOR IMPROVEMENTS (Nice to Have)
═══════════════════════════════════════════════════════

[List minor issues]

═══════════════════════════════════════════════════════
✨ GOOD PRACTICES OBSERVED
═══════════════════════════════════════════════════════

[List what's done well]

═══════════════════════════════════════════════════════
📊 METRICS SUMMARY
═══════════════════════════════════════════════════════

Complexity Score: [X] ([Low/Medium/High])
Total Classes: [X]
Total Functions: [X]
Dependencies: [X]
Violations: [Critical: X, Major: X, Minor: X]

Clean Code Score: [X]/100

═══════════════════════════════════════════════════════
🛠️ RECOMMENDED ACTIONS (Priority Order)
═══════════════════════════════════════════════════════

1. [Most important fix]
2. [Second priority]
3. [Third priority]
...

═══════════════════════════════════════════════════════
```

## Important Guidelines

- **Always start with ASCII diagrams** - visualize before analyzing
- **Always explain simply first** (Feynman style) - understand before critiquing
- **Be specific** - cite exact line numbers and code examples
- **Be constructive** - always provide refactoring suggestions
- **Prioritize** - use severity levels (Critical/Major/Minor)
- **Focus on impact** - explain WHY each violation matters
- **Keep ASCII simple** - use box drawing characters (┌─┐│└┘├┤┬┴┼)

## After Review

Ask the user:
"Would you like me to:
1. Apply the highest priority fixes?
2. Review another related module?
3. Generate a refactoring plan?"
