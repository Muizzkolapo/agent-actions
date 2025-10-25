# Claude Code Configuration

This directory contains custom commands and helpers for Claude Code.

## Available Commands

### `/find-dead-code <file_or_directory>`

Performs focused dead code analysis to find unused functions, classes, imports, variables, and methods.

**Usage:**
```bash
# Analyze a single file
/find-dead-code agent_actions/core/parser/parser.py

# Analyze an entire directory
/find-dead-code agent_actions/agents
```

**What it detects:**
- Unused functions and methods
- Unused classes
- Unused variables
- Unused imports (high-confidence removals)
- Unused properties and attributes
- Confidence levels (🔴 80%+ high, 🟡 60-79% medium)

**Report includes:**
- Summary statistics by type
- Distribution visualization
- Detailed findings by file with line numbers
- Estimated lines that can be removed
- Prioritized cleanup recommendations

**Perfect for:**
- Spring cleaning dead code
- Reducing codebase size
- Improving import times
- Removing legacy/unused features

### `/review-clean-code <module>`

Performs a comprehensive clean code review of a **single module** using AST analysis, lineage tracking, and Feynman-style explanations.

**Usage:**
```bash
/review-clean-code agent_actions.core.context.context
```

**Process:**
1. **AST Analysis** - Parses the code structure
2. **Lineage Tracking** - Builds dependency graph
3. **ASCII Visualization** - Shows dependencies and flow
4. **Feynman Explanation** - Explains simply first
5. **Clean Code Analysis** - Checks SOLID principles, metrics, and best practices
6. **Detailed Report** - Prioritized violations and refactoring suggestions

**What it checks:**
- SOLID principles
- Cyclomatic complexity
- Function/class length
- Type hints coverage
- Docstring completeness
- DRY violations
- Magic values
- Error handling
- Naming conventions
- Coupling and cohesion

### `/review-batch-report <report_file>`

Analyzes a pre-generated batch analysis report for **multiple modules** and creates a prioritized action plan.

**Workflow:**
```bash
# Step 1: Run batch analyzer (in your terminal)
python .claude/helpers/batch_analyzer.py agent_actions/agents > batch_report.txt

# Step 2: Analyze the report
/review-batch-report batch_report.txt
```

**What it provides:**
- **Executive Summary** - Overall code health metrics
- **Priority Action Plan** - Immediate/Short-term/Long-term tasks
- **Pattern Analysis** - Common issues across files
- **Refactoring Strategies** - How to fix each type of issue
- **Success Metrics** - Target goals and progress tracking
- **Next Steps** - Concrete actions to take

**Perfect for:**
- Reviewing entire directories/packages
- Planning refactoring sprints
- Prioritizing technical debt cleanup
- Team code health assessments

## Helpers

### `dead_code_analyzer.py`

Focused dead code analyzer for **finding unused code** in files or directories.

**Usage:**
```bash
# Analyze a single file
python .claude/helpers/dead_code_analyzer.py agent_actions/core/parser.py

# Analyze a directory
python .claude/helpers/dead_code_analyzer.py agent_actions/agents

# Brief summary only (no detailed findings)
python .claude/helpers/dead_code_analyzer.py agent_actions/agents --brief
```

**Detection Methods:**
- **Vulture**: Industry-standard dead code detector (60%+ confidence threshold)
- **AST Analysis**: Custom unused import detection
- **Line Span Calculation**: Determines actual size of dead code

**What it finds:**
- Unused functions (never called)
- Unused classes (never instantiated)
- Unused methods (never invoked)
- Unused variables (assigned but never read)
- Unused imports (imported but never used)
- Unused properties and attributes

**Output:**
- Summary statistics with breakdown by type
- ASCII bar chart of dead code distribution
- Detailed findings grouped by file
- Confidence indicators (🔴 high, 🟡 medium, ⚪ low)
- Line numbers and size for each dead item
- Estimated total removable lines

**Perfect for:**
- Finding safe-to-remove code
- Cleaning up unused imports
- Reducing codebase bloat
- Pre-refactoring cleanup

### `code_analyzer.py`

Comprehensive code analyzer for **single files** using industry-standard mature tools.

**Usage:**
```bash
python .claude/helpers/code_analyzer.py agent_actions/path/to/module.py
```

**Integrated Tools:**
- **Radon**: Cyclomatic complexity, maintainability index, LOC/LLOC/SLOC metrics
- **Prospector**: Multi-tool analysis (pylint, pyflakes, pydocstyle, pycodestyle, mccabe)
- **Vulture**: Dead code detection
- **AST Analysis**: Custom lineage tracking and dependency visualization

**Features:**
- Extracts imports, classes, functions, inheritance
- Tracks all dependencies
- Calculates complexity metrics per function
- Maintainability index scoring
- Code quality violation detection (errors, warnings, info)
- Dead code identification
- Beautiful ASCII diagrams

### `batch_analyzer.py`

Batch code analyzer for **entire directories** - analyzes multiple files and generates summary reports.

**Usage:**
```bash
# Analyze all files in a directory
python .claude/helpers/batch_analyzer.py agent_actions/agents

# Save report to file for later analysis
python .claude/helpers/batch_analyzer.py agent_actions/agents > batch_report.txt
```

**What it does:**
- Scans all Python files in a directory
- Runs radon, prospector, vulture on each file
- Aggregates results across all files
- Generates prioritized summary report

**Report Sections:**
- **Overall Statistics** - Total LOC, violations, dead code, averages
- **Top 10 Most Complex Files** - Highest complexity scores
- **Top 10 Files with Most Violations** - Violation counts by severity
- **Top 10 Lowest Maintainability** - Files needing refactoring
- **Top 10 Files with Most Dead Code** - Unused code findings
- **🔍 Detailed Analysis** - NEW! Top problem files with:
  - Specific violation messages with line numbers
  - Downstream dependencies (who imports this file)
  - Sample violations from each file
  - Dead code details with confidence levels
- **Priority Recommendations** - Critical files scored by impact

**Perfect for:**
- Assessing code health of entire packages
- Finding worst offenders quickly
- Planning refactoring efforts
- Team code review sessions

## Architecture

```
.claude/
├── commands/
│   ├── find-dead-code.md         # Dead code analysis for cleanup
│   ├── review-clean-code.md      # Single module review (Feynman + clean code)
│   └── review-batch-report.md    # Batch report analysis & action plan
├── helpers/
│   ├── dead_code_analyzer.py     # Focused dead code detection
│   ├── code_analyzer.py          # Single file analysis (radon, prospector, vulture)
│   └── batch_analyzer.py         # Directory batch analysis
└── README.md                      # This file
```

## Typical Workflow

### For Dead Code Cleanup
```bash
# Option 1: Quick dead code check
/find-dead-code agent_actions/core/parser.py

# Option 2: Full directory scan
/find-dead-code agent_actions/agents

# Option 3: Manual run for saving to file
python .claude/helpers/dead_code_analyzer.py agent_actions/agents > dead_code_report.txt
```

### For Single Module Review
```bash
# Option 1: Direct analysis
/review-clean-code agent_actions.core.context.context

# Option 2: Manual analysis first, then review
python .claude/helpers/code_analyzer.py agent_actions/core/context/context.py
# Read output, then run /review-clean-code for deeper analysis
```

### For Batch/Directory Review
```bash
# Step 1: Run batch analyzer (in your terminal - may take a few minutes)
python .claude/helpers/batch_analyzer.py agent_actions/agents > batch_report.txt

# Step 2: Open batch_report.txt to review findings
# You'll see:
#   - Specific violation messages with line numbers
#   - Downstream dependencies (impact analysis)
#   - Dead code details with confidence levels
#   - Priority scores for critical files

# Step 3: Analyze the report with Claude for action plan
/review-batch-report batch_report.txt

# Step 4: Deep dive into priority files
/review-clean-code agent_actions.agents.transformers.data_processor
```

### Complete Codebase Health Check
```bash
# Step 1: Find and remove dead code first
/find-dead-code agent_actions
# Review and remove high-confidence dead code

# Step 2: Run batch analysis after cleanup
python .claude/helpers/batch_analyzer.py agent_actions > batch_report.txt

# Step 3: Get prioritized action plan
/review-batch-report batch_report.txt

# Step 4: Deep dive into critical modules
/review-clean-code [high-priority-module]
```

## Principles

All code reviews follow these principles:

1. **Visualize First** - Use ASCII diagrams to understand structure
2. **Explain Simply** - Feynman-style explanations before analysis
3. **Be Specific** - Cite line numbers and provide examples
4. **Be Constructive** - Always suggest improvements
5. **Prioritize** - Critical → Major → Minor
6. **Focus on Impact** - Explain WHY violations matter

## Examples

### Good Review Output

```
═══════════════════════════════════════════════════════
🎓 FEYNMAN EXPLANATION
═══════════════════════════════════════════════════════

WHAT: This is a "shopping cart" for data - it holds items
      temporarily before processing them.

WHY: We need to collect data from multiple sources before
     validating and saving it all at once.

HOW: 1. Items are added to the cart
     2. When ready, we validate all items
     3. Then we save them as a batch
     4. Finally, we clear the cart

TOUCHES: Uses ValidationService (to check data)
         Uses StorageService (to save data)
         Depends on: typing, dataclasses

═══════════════════════════════════════════════════════
🔴 CRITICAL VIOLATIONS
═══════════════════════════════════════════════════════

❌ Line 45-67: `process_batch` violates SRP
   Complexity: 15 (High)

   💡 Refactoring: Split into 3 functions...
```

## Tips

- Start with modules that have low complexity for practice
- Review related modules together to see coupling issues
- Use the lineage graphs to identify tight coupling
- Always run the analyzer manually first to see the structure
