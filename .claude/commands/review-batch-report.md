---
description: Analyze a pre-generated batch code analysis report and provide prioritized recommendations
---

# Batch Report Analysis

Analyzing batch code analysis report: **{{arg1}}**

## Step 1: Read the Report

Read the batch analysis report:

```bash
cat {{arg1}}
```

## Step 2: Extract Key Findings

Parse the report and identify:
1. **Overall Statistics** - Total LOC, violations, dead code, averages
2. **Most Complex Files** - Top offenders by complexity score
3. **Most Violations** - Files with highest violation counts
4. **Lowest Maintainability** - Files needing refactoring
5. **Dead Code** - Files with unused code
6. **Priority Recommendations** - Critical files flagged by the report

## Step 3: Generate Action Plan

Create a prioritized action plan in this format:

```
═══════════════════════════════════════════════════════════════════════════════
🎯 BATCH ANALYSIS ACTION PLAN
═══════════════════════════════════════════════════════════════════════════════

📊 EXECUTIVE SUMMARY
───────────────────────────────────────────────────────────────────────────────
Total Files Analyzed: [X]
Total LOC: [X]
Total Issues: [X]

Overall Code Health: [Excellent/Good/Fair/Poor]

Key Metrics:
  • Average Complexity: [X] ([Low/Medium/High])
  • Average Maintainability: [X] (Rank: [A/B/C])
  • Critical Files: [X] files need immediate attention
  • Total Violations: [X]
  • Dead Code Items: [X]

═══════════════════════════════════════════════════════════════════════════════
🔴 IMMEDIATE ACTIONS (Week 1 - Critical)
═══════════════════════════════════════════════════════════════════════════════

Based on the priority recommendations, focus on files with:
  - Complexity > 50
  - Maintainability Index < 10
  - Violations > 20

Priority Files to Fix:
  1. [file_path]
     Issue: [complexity/maintainability/violations]
     Impact: [Why it matters]
     Estimated Effort: [X hours]

  2. [file_path]
     ...

Recommended Approach:
  → Start with file #1
  → Run detailed review: /review-clean-code [module.path]
  → Apply refactorings
  → Run tests
  → Move to next file

═══════════════════════════════════════════════════════════════════════════════
🟡 SHORT-TERM ACTIONS (Week 2-4 - Important)
═══════════════════════════════════════════════════════════════════════════════

Files with moderate issues:
  - Complexity 20-50
  - Maintainability 10-20
  - Violations 10-20

Action Items:
  1. [file_path] - [specific issue]
  2. ...

═══════════════════════════════════════════════════════════════════════════════
🟢 LONG-TERM IMPROVEMENTS (Month 2-3 - Nice to Have)
═══════════════════════════════════════════════════════════════════════════════

Clean up tasks:
  • Dead code removal in [X] files
  • Documentation improvements
  • Minor refactorings

═══════════════════════════════════════════════════════════════════════════════
📈 PATTERNS & TRENDS
═══════════════════════════════════════════════════════════════════════════════

Analyze the report for patterns:

Common Issues Across Files:
  • [Pattern 1]: Found in [X] files
    Example: [specific files]
    Fix: [general solution]

  • [Pattern 2]: ...

Architectural Concerns:
  • [If certain modules/packages have consistent issues]
  • [Suggest architectural improvements]

Code Smells Detected:
  • [List common anti-patterns found]

═══════════════════════════════════════════════════════════════════════════════
🛠️ REFACTORING STRATEGIES
═══════════════════════════════════════════════════════════════════════════════

For High Complexity Files:
  1. Extract Method - Break down long functions
  2. Extract Class - Split responsibilities
  3. Replace Conditional with Polymorphism
  4. Introduce Parameter Object

For Low Maintainability:
  1. Improve naming clarity
  2. Add/improve docstrings
  3. Reduce nesting depth
  4. Remove magic numbers

For High Violations:
  1. Address errors first
  2. Fix warnings
  3. Clean up style issues

For Dead Code:
  1. Verify truly unused (check across project)
  2. Remove carefully
  3. Run full test suite

═══════════════════════════════════════════════════════════════════════════════
📊 SUCCESS METRICS
═══════════════════════════════════════════════════════════════════════════════

Target Goals (After Cleanup):
  ✓ Average Complexity: < 15
  ✓ Average Maintainability: > 20 (Rank A)
  ✓ Critical Files: 0
  ✓ Total Violations: < 50
  ✓ Dead Code: 0

Track Progress:
  • Rerun batch analysis weekly
  • Monitor improvement trends
  • Celebrate wins!

═══════════════════════════════════════════════════════════════════════════════
🚀 NEXT STEPS
═══════════════════════════════════════════════════════════════════════════════

Immediate Next Actions:
  1. Pick the #1 priority file from the critical list
  2. Run detailed review:
     /review-clean-code [module.path.to.file]
  3. Read the Feynman explanation to understand it
  4. Apply suggested refactorings
  5. Run tests to ensure nothing breaks
  6. Commit changes
  7. Move to next file

Week 1 Goal:
  • Fix [X] critical files
  • Reduce violations by [X]%
  • Improve average maintainability to [X]

═══════════════════════════════════════════════════════════════════════════════
```

## Step 4: Provide Detailed Breakdown

For each file in the priority list, provide:
- **File**: Full path
- **Current State**: Complexity, MI, violations, LOC
- **Specific Issues**: What's wrong (be specific with line refs if available)
- **Impact**: Why it matters (technical debt, bugs, maintainability)
- **Refactoring Plan**: Step-by-step approach
- **Estimated Effort**: Time needed
- **Dependencies**: What else might break

## Step 5: Offer to Deep Dive

After presenting the action plan, ask:

```
Would you like me to:
1. Deep dive into the #1 priority file? (/review-clean-code <module>)
2. Explain refactoring strategies for a specific pattern?
3. Help implement fixes for a specific file?
4. Rerun analysis after your changes?
```

## Important Guidelines

- **Be Specific**: Use actual file names and metrics from the report
- **Prioritize Ruthlessly**: Focus on high-impact files first
- **Consider Dependencies**: Some files might be critical infrastructure
- **Be Realistic**: Don't overwhelm - break into manageable chunks
- **Explain Why**: Always explain the business/technical impact
- **Provide Examples**: Show concrete refactoring approaches
- **Track Progress**: Suggest how to measure improvement

## ASCII Art Encouragement

Use ASCII diagrams to visualize:
- Complexity distribution (histogram)
- Priority matrix (urgency vs effort)
- Dependency graphs if patterns emerge
- Progress tracking charts
