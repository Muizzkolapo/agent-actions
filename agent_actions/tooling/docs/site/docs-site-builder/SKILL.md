---
name: docs-site-builder
description: Agent-Actions documentation site development toolkit. Use PROACTIVELY when working with the Agent-Actions docs site at agent_actions/docs/docs_site for (1) Building and serving the documentation site, (2) Running Playwright tests and validation, (3) Generating sample data and catalog, (4) Troubleshooting schema fields, action breakdowns, or data flow issues, (5) Organizing scanner/parser/generator modules, (6) Managing the development workflow.
---

# Agent-Actions Documentation Site Builder

## Overview

This skill provides tools and knowledge for developing, testing, and maintaining the Agent-Actions documentation site. The docs site is a static HTML/CSS/JS application that displays workflow schemas, prompts, and execution runs, with a Python backend for scanning, parsing, and generating documentation data.

## Quick Start

### Development Workflow

Use the provided helper scripts for common operations:

```bash
# 1. Generate sample data
python scripts/generate_data.py

# 2. Start development server (http://localhost:8000)
python scripts/serve.py

# 3. Run all Playwright tests
python scripts/run_tests.py

# Or run specific tests
python scripts/run_tests.py schemas  # Runs test-schemas.js
```

Alternatively, run commands directly:

```bash
# Generate data
python generate_sample_prompts.py

# Start server
python -m agent_actions.docs.server

# Run individual tests
node test-schemas.js
node test-run-actions-complete.js
```

## Project Structure

### Backend (Python)

- `agent_actions/docs/scanner.py` - Scans project for schemas/prompts
- `agent_actions/docs/parser.py` - Parses workflow YAML files (supports 3 schema formats)
- `agent_actions/docs/generator.py` - Generates sample workflow runs
- `agent_actions/docs/server.py` - Serves documentation site with live reload
- `agent_actions/docs/run_tracker.py` - Tracks workflow execution for live runs

### Frontend (Static)

- `agent_actions/docs/docs_site/index.html` - Main HTML entry point
- `agent_actions/docs/docs_site/js/app.js` - Core JavaScript application (hash routing, dynamic rendering)
- `agent_actions/docs/docs_site/css/` - Stylesheets with CSS variables for theming

### Generated Data

- `agent_actions/docs/artefact/catalog.json` - Workflow catalog with schemas and prompts
- `agent_actions/docs/artefact/runs.json` - Sample workflow execution runs

### Tests

- `test-*.js` - Playwright browser automation tests for validation

## Core Tasks

### 1. Schema Scanning & Field Counting

The parser supports 3 schema formats and correctly counts fields:

**Format 1: Custom fields array**
```json
{
  "fields": [
    {"id": "name", "type": "string", "description": "User name"},
    {"id": "email", "type": "string", "description": "Email address"}
  ]
}
```

**Format 2: Standard array with items.properties**
```json
{
  "type": "array",
  "items": {
    "properties": {
      "name": {"type": "string"},
      "email": {"type": "string"}
    }
  }
}
```

**Format 3: Standard object with properties**
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "email": {"type": "string"}
  }
}
```

**Critical:** Use `SchemaLoader.load_schema()` + `extract_fields_for_docs()` which handles all 3 formats.

```python
from agent_actions.response_processing.schema_loader import SchemaLoader
from agent_actions.docs.parser import extract_fields_for_docs

raw_schema = SchemaLoader.load_schema('schema_name', schema_dir)
fields = extract_fields_for_docs(raw_schema)
field_count = len(fields)  # Correctly normalized
```

### 2. Action Breakdown Display

Run details must show ALL workflow actions (executed + skipped), not just executed ones.

**Implementation pattern:**

```javascript
// 1. Make catalog global for debugging
window.catalog = catalogData;

// 2. Find workflow definition in catalog
const workflow = catalog.workflows.find(w => w.name === run.workflow_name);

// 3. Use workflow.actions (complete list) instead of run.execution_plan
const allActions = workflow.actions;

// 4. For each action, check if executed or skipped
allActions.forEach(action => {
  const executed = run.execution_plan?.find(e => e.action === action.name);
  if (executed) {
    // Show metrics from execution
    showMetrics(executed.duration, executed.tokens, executed.status);
  } else {
    // Show SKIPPED badge with "-" for metrics
    showSkippedAction(action.name, action.description);
  }
});
```

### 3. Testing with Playwright

All tests use Playwright for browser automation. Common patterns:

```javascript
// Specific selector for action breakdown table
const table = page.locator('div:has-text("Action Breakdown") + div table');

// Count rows (should include executed + skipped)
const rowCount = await table.locator('tbody tr').count();

// Check for SKIPPED badge
const skippedBadges = await page.locator('.badge.skipped').count();

// Take screenshot for visual validation
await page.screenshot({ path: 'test-output.png', fullPage: true });
```

**Best practices:**
- Use specific selectors to avoid matching wrong elements
- Verify counts match expected totals (e.g., 11 schemas, all workflow actions)
- Take screenshots for visual regression testing
- Check for specific status badges (SUCCESS, FAILED, SKIPPED)

### 4. Data Flow & Debugging

The data flows: `scanner.py → catalog.json → index.html → app.js → UI`

**Enable debugging:**

```javascript
// In app.js, expose data globally
window.catalog = catalogData;
window.runs = runsData;

// In browser console, inspect data
catalog.schemas.length  // Should be 11
catalog.workflows[0].actions  // Full action list
runs[0].execution_plan  // Executed actions only
```

**Always regenerate data after changes:**

```bash
python generate_sample_prompts.py  # After modifying schemas/prompts
```

## Common Issues & Solutions

### Schema Fields Showing "0" or "undefined"

**Problem:** Schema cards display "Fields: 0" or "undefined" preview text

**Solution:**
1. Use `SchemaLoader.load_schema()` + `extract_fields_for_docs()` which handles all 3 formats
2. Generate dynamic descriptions from field data:

```javascript
const fieldCount = schema.fields.length;
const fieldNames = schema.fields.slice(0, 3).map(f => f.name).join(', ');
const description = `${fieldCount} fields: ${fieldNames}...`;
```

### Action Breakdown Missing Skipped Actions

**Problem:** Only executed actions shown in run details (e.g., 4 shown instead of 12 total)

**Solution:**
1. Make catalog global: `window.catalog = catalogData`
2. Get complete action list from workflow definition: `workflow.actions`
3. Show skipped actions with SKIPPED badge and "-" for undefined metrics
4. Do NOT use `run.execution_plan` alone - it only has executed actions

### Tests Selecting Wrong Elements

**Problem:** Playwright selectors match multiple elements or wrong sections

**Solution:** Use specific selectors that target context:

```javascript
// Good - specific to action breakdown section
const table = page.locator('div:has-text("Action Breakdown") + div table');

// Bad - matches all tables
const table = page.locator('table');
```

## Architecture Patterns

### Frontend State Management

- Global variables for debugging: `window.catalog`, `window.runs`
- Event-driven navigation with hash routing (`#schemas`, `#runs/run-1`)
- Dynamic DOM rendering without frameworks (vanilla JS)
- CSS variables for theming (`:root { --primary-color: ... }`)

### Testing Strategy

- Playwright for end-to-end browser testing
- Screenshot-based visual validation
- Data verification (counts, status badges, metrics)
- Selector specificity for accurate element targeting

### Module Organization

- Scanner delegates to parser for schema loading (avoid duplication)
- Parser normalizes all schema formats to consistent structure
- Generator uses parser to create realistic sample data
- Server serves static files with proper MIME types

## Best Practices

1. **Always regenerate data after schema/prompt changes**
   ```bash
   python generate_sample_prompts.py
   ```

2. **Use existing parsers instead of duplicating logic**
   - scanner.py should delegate to parser.py
   - Never reimplement schema loading

3. **Make data inspectable for debugging**
   ```javascript
   window.catalog = catalogData;  // Access in browser console
   window.runs = runsData;
   ```

4. **Write specific Playwright selectors**
   ```javascript
   // Target specific sections to avoid wrong matches
   const table = page.locator('div:has-text("Action Breakdown") + div table');
   ```

5. **Show complete information in failed runs**
   - Display ALL workflow actions, not just executed ones
   - Mark skipped actions with visual indicators
   - Use "-" for undefined metrics

## Current Development Status

**Completed:**
- ✅ Logo changed to lightning bolt SVG
- ✅ Sidebar navigation (no expand/collapse)
- ✅ Schema scanning with 3 format support
- ✅ Schema cards with dynamic descriptions
- ✅ Action breakdown with skipped actions
- ✅ Playwright test suite for validation

**Known Working Features:**
- Schema detection: Finds all 11 schemas with correct field counts
- Prompt scanning: Detects all prompt files
- Action breakdown: Shows executed + skipped actions
- Navigation: Hash routing works without page reloads
- Testing: Playwright suite validates all features

## Helper Scripts

This skill includes 3 helper scripts in the `scripts/` directory:

1. **serve.py** - Start development server on http://localhost:8000
2. **generate_data.py** - Generate sample catalog.json and runs.json
3. **run_tests.py** - Run Playwright tests (all or by pattern)

All scripts include error handling and informative output. They can be executed directly or via Python interpreter.
