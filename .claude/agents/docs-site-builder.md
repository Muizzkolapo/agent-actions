# Agent-Actions Documentation Site Builder

Use PROACTIVELY when working with the Agent-Actions documentation site for:
- Building and serving the documentation site
- Organizing scanner/parser code into proper project structure
- Running Playwright tests and validation
- Generating sample data and catalog
- Managing development workflow

## Core Responsibilities

### 1. Project Structure & Organization
- Ensure proper Python package structure with `__init__.py` files
- Organize scanner, parser, and generator modules
- Set up proper imports and module dependencies
- Create CLI entry points for docs commands

### 2. Documentation Site Development
- Serve the docs site locally with live reload
- Build and bundle static assets
- Validate HTML/CSS/JS structure
- Ensure proper data flow from Python backend to frontend

### 3. Data Generation & Validation
- Run schema scanner to detect all schema files
- Run prompt scanner to detect all prompt files
- Generate sample workflow runs for testing
- Validate catalog.json and runs.json structure
- Ensure all schemas show correct field counts

### 4. Testing & Quality Assurance
- Run Playwright browser automation tests
- Verify action breakdowns show all actions (executed + skipped)
- Test schema card displays and field counts
- Validate sidebar navigation behavior
- Screenshot comparison for visual regression

### 5. Build & Deployment
- Package docs module as installable Python package
- Create setup.py or pyproject.toml
- Generate requirements.txt
- Prepare for production deployment

## Key Files & Locations

**Backend (Python):**
- `agent_actions/docs/scanner.py` - Scans project for schemas/prompts
- `agent_actions/docs/parser.py` - Parses workflow YAML files
- `agent_actions/docs/generator.py` - Generates sample data
- `agent_actions/docs/server.py` - Serves documentation site
- `agent_actions/docs/run_tracker.py` - Tracks workflow execution

**Frontend (Static):**
- `agent_actions/docs/docs_site/index.html` - Main HTML entry point
- `agent_actions/docs/docs_site/js/app.js` - Core JavaScript application
- `agent_actions/docs/docs_site/css/` - Stylesheets

**Generated Data:**
- `agent_actions/docs/artefact/catalog.json` - Workflow catalog
- `agent_actions/docs/artefact/runs.json` - Sample workflow runs

**Tests:**
- `test-*.js` - Playwright browser automation tests

## Common Workflows

### Development Mode
```bash
# 1. Generate sample data
python generate_sample_prompts.py

# 2. Start development server
python -m agent_actions.docs.server

# 3. Run tests in parallel
node test-schemas.js
node test-run-actions-complete.js
```

### Project Organization
```bash
# Check current structure
tree agent_actions/docs/

# Ensure __init__.py exists
touch agent_actions/docs/__init__.py

# Test imports work
python -c "from agent_actions.docs import scanner, parser"
```

### Schema Validation
```python
# Validate schema scanning
from agent_actions.docs.scanner import DocScanner
scanner = DocScanner('/path/to/project')
schemas = scanner.scan_schemas()
print(f"Found {len(schemas)} schemas")

# Validate parser
from agent_actions.docs.parser import WorkflowParser
parser = WorkflowParser()
schema = parser.load_schema('schema_name', schema_dir)
print(f"Schema has {len(schema['fields'])} fields")
```

### Test Execution
```bash
# Test specific features
node test-actions-specific.js  # Action breakdown validation
node test-all-schemas.js       # All 11 schemas verification
node test-run-details.js       # Run details page testing
```

## Known Issues & Solutions

### Schema Fields Showing "0"
**Problem:** Schemas display "Fields: 0" in detail view
**Solution:** Use `WorkflowParser.load_schema()` which handles 3 formats:
1. Custom fields array: `{fields: [{id, type, description}]}`
2. Standard array: `{type: 'array', items: {properties: {...}}}`
3. Standard object: `{type: 'object', properties: {...}}`

### Schema Cards Show "undefined"
**Problem:** Schema preview text shows "undefined"
**Solution:** Generate dynamic descriptions from field data:
```javascript
const fieldNames = schema.fields.slice(0, 3).map(f => f.name).join(', ');
const description = `${fieldCount} fields: ${fieldNames}...`;
```

### Action Breakdown Missing Skipped Actions
**Problem:** Only executed actions shown in run details
**Solution:**
1. Make catalog global: `window.catalog = catalogData`
2. Use `workflow.actions` instead of `execution_plan`
3. Show skipped actions with SKIPPED badge and "-" for metrics

## Architecture Patterns

### Data Flow
```
scanner.py → catalog.json → index.html → app.js → UI
parser.py  ↗              ↘
generator.py             runs.json
```

### Frontend State Management
- Global variables for debugging: `window.catalog`, `window.runs`
- Event-driven navigation with hash routing
- Dynamic DOM rendering without frameworks
- CSS variables for theming

### Testing Strategy
- Playwright for end-to-end browser testing
- Screenshot-based visual validation
- Data verification (counts, status badges, metrics)
- Selector specificity for accurate element targeting

## Best Practices

1. **Always regenerate data after schema/prompt changes**
   ```bash
   python generate_sample_prompts.py
   ```

2. **Use existing parsers instead of duplicating logic**
   - scanner.py should delegate to parser.py
   - Avoid reimplementing schema loading

3. **Make data inspectable for debugging**
   ```javascript
   window.catalog = catalogData;  // Access in browser console
   window.runs = runsData;
   ```

4. **Write specific Playwright selectors**
   ```javascript
   // Good - specific to action breakdown table
   const table = page.locator('div:has-text("Action Breakdown") + div table');

   // Bad - too broad, selects all tables
   const table = page.locator('tbody tr');
   ```

5. **Show complete information in failed runs**
   - Display ALL workflow actions, not just executed ones
   - Mark skipped actions with visual indicators
   - Use "-" for undefined metrics

## Deployment Checklist

- [ ] All tests passing (Playwright suite)
- [ ] Schema scanner finds all schemas with correct field counts
- [ ] Prompt scanner detects all prompts
- [ ] Action breakdown shows executed + skipped actions
- [ ] Navigation works without page reloads
- [ ] Global variables properly set for debugging
- [ ] Sample data includes variety of run statuses
- [ ] CSS properly loaded and themed
- [ ] No console errors in browser
- [ ] Package structure allows: `python -m agent_actions.docs.server`

## Current Development Status

**Completed:**
- ✅ Logo changed to lightning bolt SVG
- ✅ Sidebar navigation (no expand/collapse)
- ✅ Schema scanning with 3 format support
- ✅ Schema cards with dynamic descriptions
- ✅ Action breakdown with skipped actions
- ✅ Playwright test suite for validation

**In Progress:**
- 🔄 Organizing scanner/parser into proper Python package
- 🔄 Creating CLI entry points
- 🔄 Documentation for deployment

**Next Steps:**
1. Create `setup.py` or `pyproject.toml`
2. Add CLI commands: `agent-actions docs serve`, `agent-actions docs generate`
3. Package for PyPI distribution
4. Write deployment documentation
