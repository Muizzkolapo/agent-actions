# Claude Code Configuration

This directory contains custom commands and helpers for Claude Code.

## Available Commands

### `/organize-code <path>`

**Analyze codebase structure and identify processing stages** in the agent pipeline.

**Usage:**
```bash
# Analyze entire codebase
/organize-code agent_actions/

# Analyze specific module
/organize-code agent_actions/core/

# Export as JSON
python .claude/helpers/code_organizer.py agent_actions/ --json report.json
```

**Identifies 13 Processing Stages:**
1. Input Loading & Extraction
2. Pre-Processing & Data Preparation
3. Pre-LLM Validation
4. Prompt Generation & Context Building
5. LLM Invocation & Provider Integration (real-time)
5B. **Batch Processing & Queue Management** (bulk operations)
6. Response Processing & Transformation
7. Post-Processing & Output Generation
8. Workflow Orchestration & Execution
9. State Management & Context
10. Configuration & Schema Management
11. CLI & User Interface
12. Utilities & Common Functions
13. Testing & Quality Assurance

**Detects:**
- Architectural layers and organization
- Circular dependencies
- Large modules (>500 LOC)
- Missing `__init__.py` files
- Misplaced utility code

**Perfect for:**
- Understanding codebase structure
- Identifying refactoring opportunities
- Tracking processing pipeline stages
- Architecture documentation
- Code organization improvements

---

### `/find-dead-code <file_or_directory>`

**Enhanced multi-tool dead code analysis** with false positive filtering to find unused code safely.

**Usage:**
```bash
# Analyze a single file
/find-dead-code agent_actions/core/parser/parser.py

# Analyze an entire directory
/find-dead-code agent_actions/agents
```

**Multi-Tool Detection:**
- **Ruff**: Fast, accurate import/variable detection (95% confidence)
- **Vulture**: Comprehensive dead code detection
- **AST Analysis**: Additional validation
- **Smart Filters**: Automatically filters dispatch tables, abstract methods, vendor handlers

**Confidence Tiers:**
- 🔴 **HIGH (90-100%)**: Very safe to remove (multiple tools agree OR Ruff confirms)
- 🟡 **MEDIUM (70-89%)**: Review before removing (may be used indirectly)
- ⚪ **LOW (<70%)**: Likely false positives (skip these - polymorphism/dispatch)

**What it detects:**
- Unused functions and methods
- Unused classes
- Unused variables
- Unused imports (Ruff-validated, very accurate)
- Unused properties and attributes

**Report includes:**
- Tool-specific attribution (`[ruff,vulture,ast]`)
- Confidence breakdown by tier
- False positive risk warnings
- High-confidence items shown first
- Low-confidence items hidden by default

**Perfect for:**
- Spring cleaning dead code safely
- Removing unused imports (Ruff-validated)
- Avoiding false positives (dispatch tables, vendors, etc.)
- Reducing codebase size confidently

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

**Enhanced multi-tool dead code analyzer** with smart false positive filtering.

**Usage:**
```bash
# Analyze a single file
python .claude/helpers/dead_code_analyzer.py agent_actions/core/parser.py

# Analyze a directory
python .claude/helpers/dead_code_analyzer.py agent_actions/agents

# Brief summary only (no detailed findings)
python .claude/helpers/dead_code_analyzer.py agent_actions/agents --brief

# Show all items including low-confidence (false positives)
python .claude/helpers/dead_code_analyzer.py agent_actions/agents --show-all
```

**Multi-Tool Detection:**
- **Ruff** (F401, F841): Fast, accurate import/variable detection (95% confidence)
- **Vulture**: Comprehensive dead code detection (60%+ confidence)
- **AST Analysis**: Custom unused import detection
- **Cross-Validation**: Merges results and adjusts confidence scores
- **Smart Filtering**: Automatically downgrades known false positive patterns

**False Positive Filters:**
Automatically detects and lowers confidence for:
- Dispatch tables: `*Handler`, `*Provider`, `*Processor`, `*Factory`, `*Plugin`
- Abstract methods in base classes
- Magic methods: `__init__`, `__str__`, etc.
- Test fixtures: `setUp`, `tearDown`, `pytest_*`
- Code in vendor/provider/handler directories

**Confidence Scoring:**
- **HIGH (90-100%)**: Ruff confirms OR multiple tools agree - very safe to remove
- **MEDIUM (70-89%)**: Vulture detects, filtered for patterns - review carefully
- **LOW (<70%)**: High false positive risk - skip these

**What it finds:**
- Unused functions (never called)
- Unused classes (never instantiated)
- Unused methods (never invoked)
- Unused variables (assigned but never read)
- Unused imports (Ruff-validated for accuracy)
- Unused properties and attributes

**Enhanced Output:**
- Confidence tier breakdown (HIGH/MEDIUM/LOW)
- Tool attribution for each finding (`[ruff,vulture,ast]`)
- False positive risk warnings (`⚠️ Located in vendor directory`)
- High-confidence items shown first
- Low-confidence items hidden by default
- Summary statistics with tool availability
- Estimated safe removal vs. total potential

**Perfect for:**
- Finding truly unused code (not false positives)
- Cleaning up unused imports with confidence
- Avoiding mistakes from dispatch tables/polymorphism
- Safe codebase reduction

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
# Option 1: Quick dead code check (multi-tool analysis)
/find-dead-code agent_actions/core/parser.py

# Option 2: Full directory scan
/find-dead-code agent_actions/agents

# Option 3: Manual run for saving to file
python .claude/helpers/dead_code_analyzer.py agent_actions/agents > dead_code_report.txt

# Focus on high-confidence items only (safest)
# The tool automatically separates HIGH/MEDIUM/LOW confidence
# - HIGH (90-100%): Safe to remove immediately
# - MEDIUM (70-89%): Review before removing
# - LOW (<70%): Skip - likely false positives
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
# Step 1: Find and remove dead code first (focus on HIGH confidence)
/find-dead-code agent_actions
# The tool will separate findings into:
# - HIGH confidence (90-100%): Remove these first ✅
# - MEDIUM confidence (70-89%): Review carefully ⚠️
# - LOW confidence (<70%): Skip - likely false positives ⛔

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

## Tool Installation

For best results with dead code analysis, install the recommended tools:

```bash
# Required for basic dead code detection
pip install vulture

# Highly recommended for accurate import detection (95% confidence)
pip install ruff

# Note: AST analysis is built-in (no installation needed)
```

**Without Ruff:** The analyzer still works but will have lower confidence scores for imports.

**With Ruff:** Import detection is highly accurate (95% confidence), dramatically reducing false positives.

## Tips

- **Dead Code**: Start with HIGH confidence items (90-100%) - very safe to remove
- **Dead Code**: Review MEDIUM items carefully (70-89%) - may be used indirectly
- **Dead Code**: Skip LOW confidence items (<70%) - likely false positives from dispatch tables
- Start with modules that have low complexity for practice
- Review related modules together to see coupling issues
- Use the lineage graphs to identify tight coupling
- Always run the analyzer manually first to see the structure
