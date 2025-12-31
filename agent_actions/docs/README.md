# Agent-Actions Documentation System

Interactive documentation site generator for agent workflows. Automatically scans your project for workflows, prompts, and schemas, then generates a beautiful static documentation site.

## Features

- **Workflow Catalog**: Browse all workflows with action breakdowns
- **Run History**: View execution history with detailed action timelines
- **Schema Browser**: Explore data schemas with field definitions
- **Prompt Library**: View all LLM prompts used across workflows
- **Interactive UI**: No build step required, pure HTML/CSS/JS
- **Complete Action Tracking**: Shows both executed and skipped actions

## Quick Start

```bash
# 1. Generate documentation data
agac docs generate

# 2. Serve the documentation site
agac docs serve

# 3. Open browser to http://localhost:8000
```

## CLI Commands

### `agac docs generate`

Scans your project and generates documentation data files.

**What it scans:**
- Workflows in `artefact/rendered_workflows/` and `*/agent_config/`
- Prompts in `prompt_store/*.md` files
- Schemas in `schema/*.yml` files

**Output:**
- `artefact/catalog.json` - Complete workflow catalog
- `artefact/runs.json` - Workflow execution history

**Options:**
- `--output`, `-o` - Output directory (default: `artefact`)

**Example:**
```bash
agac docs generate
agac docs generate --output ./custom-artefact
```

### `agac docs serve`

Starts HTTP server to view the documentation site.

**Requirements:**
- Must run `agac docs generate` first
- `artefact/` directory must exist with `catalog.json` and `runs.json`

**Options:**
- `--port`, `-p` - Port number (default: 8000)

**Example:**
```bash
agac docs serve
agac docs serve --port 3000
```

### `agac docs test`

Runs Playwright browser tests to verify the documentation site.

**Requirements:**
- Node.js installed
- Playwright test files in project root
- Documentation server running

**Test Suites:**
- `schemas` - Verifies all schemas display with correct field counts
- `actions` - Verifies action breakdowns show executed + skipped actions
- `all` - Runs all test suites (default)

**Options:**
- `--test`, `-t` - Which suite to run (schemas, actions, all)
- `--port`, `-p` - Port where server is running (default: 8890)

**Example:**
```bash
# Run all tests
agac docs test

# Run only schema tests
agac docs test --test schemas

# Test against custom port
agac docs test --port 3000
```

## Architecture

### Backend (Python)

```
agent_actions/docs/
├── __init__.py          # Public API exports
├── scanner.py           # Scans project for workflows/prompts/schemas
├── parser.py            # Parses YAML workflow files
├── generator.py         # Generates catalog.json and runs.json
├── server.py            # HTTP server for documentation site
└── run_tracker.py       # Tracks workflow execution (runtime)
```

### Frontend (Static HTML/CSS/JS)

```
agent_actions/docs/docs_site/
├── index.html           # Main HTML entry point
├── js/
│   └── app.js          # Core application logic
└── css/
    └── styles.css      # Styling and theme
```

### Data Flow

```
Project Files → Scanner → Parser → Generator → JSON Data → Static Site
     ↓            ↓         ↓          ↓           ↓             ↓
workflows/   scan()   parse()   generate()   catalog.json   Browser
prompts/     scan_    load_     CatalogGen   runs.json
schemas/     prompts  schema    RunsGen
```

## Schema Support

The parser handles **3 different schema formats** to ensure compatibility:

### Format 1: Custom Fields Array

```yaml
name: example_schema
fields:
  - id: field_name
    type: string
    description: Field description
    required: true
```

### Format 2: Standard Array Schema

```yaml
name: example_schema
type: array
items:
  properties:
    field_name:
      type: string
      description: Field description
  required:
    - field_name
```

### Format 3: Standard Object Schema

```yaml
name: example_schema
type: object
properties:
  field_name:
    type: string
    description: Field description
required:
  - field_name
```

All formats are normalized to a consistent structure with `fields` array containing:
- `name`: Field identifier
- `type`: Data type
- `description`: Field purpose
- `required`: Whether field is mandatory

## Prompt Support

Prompts are extracted from markdown files using this pattern:

```markdown
{prompt prompt_name}
This is the prompt content.
It can span multiple lines.
{end_prompt}
```

Multiple prompts can exist in a single markdown file. Each prompt gets:
- `id`: Prompt identifier
- `name`: Display name
- `content`: Full prompt text
- `source_file`: Path to markdown file
- `line_start` / `line_end`: Location in file

## Action Breakdown

The documentation system shows **complete action breakdowns** including both executed and skipped actions.

**For each action:**
- ✅ **Executed**: Shows status (success/failed), duration, and token usage
- ⏭️ **Skipped**: Shows SKIPPED status with "-" for duration/tokens
- Lower opacity for skipped actions
- Full action context from workflow definition

This ensures you see the complete picture of what ran and what didn't run in each workflow execution.

## Development Workflow

### Making Changes

```bash
# 1. Modify scanner, parser, or generator
vim agent_actions/docs/scanner.py

# 2. Regenerate documentation
agac docs generate

# 3. Restart server (Ctrl+C and rerun)
agac docs serve --port 8890

# 4. Run tests to verify
agac docs test
```

### Frontend Development

```bash
# 1. Start documentation server
agac docs serve --port 8890

# 2. Edit frontend files
vim agent_actions/docs/docs_site/js/app.js

# 3. Refresh browser (no build step required!)

# 4. Test changes
agac docs test
```

### Creating Tests

Playwright tests go in project root:

```javascript
// test-my-feature.js
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();

  await page.goto('http://localhost:8890');
  await page.waitForLoadState('networkidle');

  // Your test logic here

  await browser.close();
})();
```

Run with: `node test-my-feature.js` or `agac docs test`

## Debugging

### Browser Console Access

The documentation site exposes global variables for debugging:

```javascript
// In browser console:
console.log(window.catalog);  // View entire catalog
console.log(window.runs);     // View all runs

// Inspect specific workflow
const workflow = window.catalog.workflows['my_workflow'];
console.log(workflow.actions);

// Check run details
const run = window.runs.executions[0];
console.log(run.actions);
```

### Common Issues

**Schemas showing 0 fields:**
- Ensure `agac docs generate` was run after schema changes
- Check that schema files are in `schema/` directory
- Verify YAML format matches one of the 3 supported formats

**Action breakdown empty:**
- Check that `window.catalog` is populated (browser console)
- Verify workflow exists in catalog
- Ensure `workflow.actions` contains action definitions

**Server can't find artefact/:**
- Run `agac docs generate` first
- Check current directory has `artefact/` folder
- Verify `catalog.json` and `runs.json` exist

## Design Decisions

### Why Static Site?

- **Zero dependencies**: No npm install, no build process
- **Fast**: Pure HTML/CSS/JS loads instantly
- **Portable**: Copy `docs_site/` anywhere and it works
- **Debuggable**: View source, use browser DevTools directly

### Why Python Backend?

- **Integration**: Already part of agent-actions codebase
- **YAML parsing**: Leverages existing workflow parser
- **CLI integration**: Natural fit with `agac` command structure

### Why JSON Data Files?

- **Separation**: Backend generates once, frontend consumes many times
- **Testable**: Inspect data files directly
- **Portable**: Move data files to different environments easily

## Testing Strategy

### Unit Tests (Python)

```bash
pytest agent_actions/docs/
```

Tests scanner, parser, and generator in isolation.

### Integration Tests (Playwright)

```bash
agac docs test
```

Tests end-to-end flow: data generation → serving → browser rendering.

### Manual Testing

```bash
# 1. Generate with real project
agac docs generate

# 2. Inspect data files
cat artefact/catalog.json | jq '.stats'

# 3. Serve and browse
agac docs serve
```

## Best Practices

1. **Always regenerate after changes**: Run `agac docs generate` after modifying workflows, prompts, or schemas

2. **Use existing parsers**: Don't duplicate schema/prompt parsing logic - use `SchemaLoader.load_schema()` + `extract_fields_for_docs()` and `ProjectScanner.scan_prompts()`

3. **Make data inspectable**: Expose data via `window.catalog` and `window.runs` for debugging

4. **Write specific selectors**: Target exact elements in Playwright tests (e.g., `div:has-text("Action Breakdown") + div table` instead of `tbody tr`)

5. **Show complete information**: Display all workflow actions, not just executed ones - mark skipped actions clearly

6. **Test with real data**: Use actual workflow definitions and schemas, not mocked data

## Future Enhancements

- [ ] Live reload during development
- [ ] Watch mode for automatic regeneration
- [ ] Export to static HTML (no server required)
- [ ] Search and filtering in UI
- [ ] Diff view for workflow changes
- [ ] Performance metrics dashboard
- [ ] Custom themes and branding

## Contributing

When adding features:

1. Update scanner/parser if changing data collection
2. Update generator if changing catalog structure
3. Update frontend (app.js) if changing UI
4. Add Playwright tests for verification
5. Update this README with new functionality
6. Run full test suite: `agac docs test`

## License

Part of the agent-actions project. See root LICENSE file.
