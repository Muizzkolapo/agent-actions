# RFC-001: VS Code Workflow Navigator Extension

**Status:** Draft
**Author:** Engineering Team
**Created:** 2026-01-27
**Last Updated:** 2026-01-27

---

## Summary

Build a first-class VS Code extension that provides intelligent navigation and visualization for Agent Actions workflows. Engineers can view actions in execution order, click to navigate to folders, and see real-time status—without modifying the underlying folder structure.

---

## Problem Statement

### Current Pain Points

1. **Action folders are sorted alphabetically**, not by execution order
   ```
   target/
     ├── add_answer_text/           # Actually runs 5th
     ├── aggregate_votes/           # Actually runs 4th
     ├── canonicalize_qa/           # Actually runs 7th
     ├── extract_raw_qa_1/          # Actually runs 2nd
     └── summarize_page_content/    # Actually runs 1st
   ```

2. **Engineers cannot quickly identify:**
   - Which action runs first/last
   - Which actions run in parallel (same level)
   - Which action another engineer is working on
   - The dependency relationships between actions

3. **Workaround attempts have significant downsides:**
   - Numbered folder prefixes (`01_action`) would break 8+ internal files
   - README files get out of sync
   - CLI commands require context switching

### Impact

- Engineers waste time navigating to find the right action folder
- Onboarding is slower as new team members learn the workflow structure
- Collaboration friction when discussing "the third action" vs "canonicalize_qa"

---

## Goals

1. **Zero breaking changes** - Folder structure remains unchanged
2. **First-class IDE experience** - Native VS Code look and feel
3. **Real-time awareness** - See execution status, not just structure
4. **Click-to-navigate** - One click to open any action's folder or files
5. **Minimal setup** - Works automatically when opening an Agent Actions project

## Non-Goals

- Modifying the underlying folder naming convention
- Replacing the CLI inspect commands
- Building a full workflow execution UI (just navigation)
- Supporting IDEs other than VS Code (initially)

---

## Prior Art

### GitLens (40M+ installs)
**Approach:** Overlays Git metadata on top of existing files without changing structure.

**Key patterns we adopt:**
- Inline annotations (blame → execution order)
- Custom tree views in sidebar
- Status bar integration
- CodeLens decorations above code blocks

**Reference:** [GitLens Marketplace](https://marketplace.visualstudio.com/items?itemName=eamodio.gitlens)

### ZenML Studio Extension
**Approach:** DAG visualization directly in VS Code using webviews.

**Key patterns we adopt:**
- Webview for visual DAG rendering
- Tree view for pipeline/step navigation
- Integration with manifest files

**Reference:** [ZenML DAG Visualization Blog](https://www.zenml.io/blog/dag-visualization-vscode-extension)

### Airflow Extension (by Necati Arslan)
**Approach:** Browse DAGs in tree view with status indicators.

**Key patterns we adopt:**
- Tree view with status icons (✓ completed, ⟳ running, ○ pending)
- Filter by tags/status
- Favorite actions for quick access

**Reference:** [Airflow Extension](https://marketplace.visualstudio.com/items?itemName=NecatiARSLAN.airflow-vscode-extension)

### Pipeline Visualizer
**Approach:** Interactive Mermaid.js diagrams for Azure DevOps/GitHub Actions.

**Key patterns we adopt:**
- Auto-detection of workflow files
- Clickable nodes to jump to definitions
- Color-coded stages

**Reference:** [Pipeline Visualizer](https://marketplace.visualstudio.com/items?itemName=DannydeHaan.pipeline-visualizer)

---

## Proposed Solution

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     VS Code Extension                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Tree View   │  │   Webview    │  │  Editor Decorations  │  │
│  │  Provider    │  │   DAG Panel  │  │  (CodeLens/Inline)   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         └─────────────────┼──────────────────────┘              │
│                           │                                      │
│                    ┌──────▼───────┐                             │
│                    │   Workflow   │                             │
│                    │    Model     │                             │
│                    └──────┬───────┘                             │
│                           │                                      │
│         ┌─────────────────┼─────────────────┐                   │
│         │                 │                 │                    │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌─────▼────────┐          │
│  │ YAML Parser  │  │   Manifest   │  │ File Watcher │          │
│  │ (Config)     │  │   Reader     │  │ (Status)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Actions Project                        │
├─────────────────────────────────────────────────────────────────┤
│  agent_config/              agent_io/                           │
│    └── workflow.yml           ├── source/                       │
│                               ├── staging/                      │
│                               └── target/                       │
│                                   ├── .manifest.json            │
│                                   ├── action_1/                 │
│                                   └── action_2/                 │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. Workflow Tree View (Primary Navigation)

A custom tree view in the VS Code sidebar showing actions in execution order.

```
AGENT ACTIONS                                    [↻] [⚙]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▼ qanalabs_quiz_gen
  │
  ├── [1] 📥 summarize_page_content              ✓
  │       └── 📁 target/summarize_page_content/
  │
  ├── [2] 📥 flatten_raw_questions               ✓
  │       └── 📁 target/flatten_raw_questions/
  │
  ├── [3] ⚡ extract_raw_qa                      ⟳ 2/3
  │       ├── 📁 extract_raw_qa_1/               ✓
  │       ├── 📁 extract_raw_qa_2/               ✓
  │       └── 📁 extract_raw_qa_3/               ⟳
  │
  ├── [4] 🔀 aggregate_votes                     ○
  │       └── 📁 target/aggregate_votes/
  │
  └── [5] 📤 canonicalize_qa                     ○
          └── 📁 target/canonicalize_qa/

Legend: 📥 Source  ⚡ Parallel  🔀 Merge  📤 Output
        ✓ Done  ⟳ Running  ○ Pending  ✗ Failed
```

**Interactions:**
- **Click folder icon** → Opens folder in Explorer
- **Click action name** → Opens action config in YAML
- **Right-click** → Context menu (Open Folder, View Schema, View Prompt, Run Action)
- **Hover** → Tooltip with dependencies, output fields, model info

**Implementation:**
```typescript
class WorkflowTreeProvider implements vscode.TreeDataProvider<ActionNode> {
  private _onDidChangeTreeData = new vscode.EventEmitter<ActionNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private workflowModel: WorkflowModel) {
    // Watch manifest for status changes
    this.workflowModel.onDidChange(() => this._onDidChangeTreeData.fire(undefined));
  }

  getTreeItem(element: ActionNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      `[${element.index}] ${element.name}`,
      element.hasVersions ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
    );

    item.iconPath = this.getStatusIcon(element.status);
    item.contextValue = element.type; // For context menu filtering
    item.command = {
      command: 'agentActions.openFolder',
      arguments: [element.folderPath]
    };

    return item;
  }
}
```

#### 2. DAG Webview Panel (Visual Overview)

An interactive dependency graph rendered with D3.js or Mermaid.js.

```
┌─────────────────────────────────────────────────────────────┐
│  Workflow: qanalabs_quiz_gen                    [Fit] [PNG] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│     ┌─────────────┐                                         │
│     │ summarize   │                                         │
│     │ page_content│ ✓                                       │
│     └──────┬──────┘                                         │
│            │                                                │
│            ▼                                                │
│     ┌─────────────┐                                         │
│     │   flatten   │                                         │
│     │raw_questions│ ✓                                       │
│     └──────┬──────┘                                         │
│            │                                                │
│     ┌──────┴──────┬──────────────┐                         │
│     ▼             ▼              ▼                          │
│  ┌──────┐    ┌──────┐      ┌──────┐                        │
│  │ext_1 │ ✓  │ext_2 │ ✓    │ext_3 │ ⟳                      │
│  └──┬───┘    └──┬───┘      └──┬───┘                        │
│     └───────────┼─────────────┘                            │
│                 ▼                                           │
│          ┌───────────┐                                      │
│          │ aggregate │                                      │
│          │   votes   │ ○                                    │
│          └─────┬─────┘                                      │
│                ▼                                            │
│         ┌────────────┐                                      │
│         │canonicalize│                                      │
│         │    _qa     │ ○                                    │
│         └────────────┘                                      │
│                                                             │
│  Click any node to navigate                                 │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:** Use VS Code's Webview API with:
- **Mermaid.js** for simple rendering (lower effort)
- **D3.js/Dagre** for interactive features (pan, zoom, click)
- **Message passing** between webview and extension for navigation

#### 3. CodeLens Integration (In-Editor Navigation)

Add clickable links above action definitions in YAML files.

```yaml
# ▶ Run Action | 📁 Open Folder | 👁 View Output (23 records)
- name: extract_raw_qa
  dependencies: [flatten_raw_questions]
  model_name: gpt-4
  prompt: |
    Extract Q&A pairs from the content.
```

**Implementation:**
```typescript
class WorkflowCodeLensProvider implements vscode.CodeLensProvider {
  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    const lenses: vscode.CodeLens[] = [];

    // Find all "- name: action_name" patterns
    const actionPattern = /^(\s*)-\s*name:\s*(\w+)/gm;
    let match;

    while ((match = actionPattern.exec(document.getText())) !== null) {
      const line = document.positionAt(match.index).line;
      const range = new vscode.Range(line, 0, line, 0);
      const actionName = match[2];

      lenses.push(
        new vscode.CodeLens(range, {
          title: '📁 Open Folder',
          command: 'agentActions.openFolder',
          arguments: [actionName]
        }),
        new vscode.CodeLens(range, {
          title: '👁 View Output',
          command: 'agentActions.viewOutput',
          arguments: [actionName]
        })
      );
    }

    return lenses;
  }
}
```

#### 4. Status Bar Integration

Show current workflow context in the status bar.

```
┌────────────────────────────────────────────────────────────────┐
│ ... │ 🔄 qanalabs_quiz_gen: 3/7 actions │ [3] extract_raw_qa ⟳ │
└────────────────────────────────────────────────────────────────┘
```

Click to:
- Open workflow tree view
- Jump to currently running action
- Quick-switch between workflows

#### 5. File Decorations

Add visual indicators to the file explorer without renaming folders.

```
target/
  ├── [1] summarize_page_content/     ✓
  ├── [2] flatten_raw_questions/      ✓
  ├── [3] extract_raw_qa_1/           ✓
  ├── [3] extract_raw_qa_2/           ✓
  ├── [3] extract_raw_qa_3/           ⟳
  ├── [4] aggregate_votes/            ○
  └── [5] canonicalize_qa/            ○
```

**Implementation:** Use `FileDecorationProvider`:
```typescript
class ActionDecorationProvider implements vscode.FileDecorationProvider {
  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    const actionInfo = this.workflowModel.getActionByPath(uri.fsPath);
    if (!actionInfo) return undefined;

    return {
      badge: `${actionInfo.index}`,
      tooltip: `Action #${actionInfo.index}: ${actionInfo.name}\nStatus: ${actionInfo.status}`,
      color: this.getStatusColor(actionInfo.status)
    };
  }
}
```

---

## Technical Design

### Data Sources

| Source | Purpose | Watch Strategy |
|--------|---------|----------------|
| `agent_config/*.yml` | Action definitions, dependencies, execution order | `vscode.workspace.onDidChangeTextDocument` |
| `agent_io/target/.manifest.json` | Runtime status, output directories | `vscode.workspace.createFileSystemWatcher` |
| `agent_io/target/*/` | Output existence, record counts | Directory watcher |

### Workflow Model

Central data structure that all UI components consume:

```typescript
interface WorkflowModel {
  name: string;
  actions: ActionInfo[];
  executionLevels: Map<number, ActionInfo[]>;  // For parallel grouping

  // Events
  onDidChange: vscode.Event<void>;

  // Queries
  getActionByName(name: string): ActionInfo | undefined;
  getActionByPath(path: string): ActionInfo | undefined;
  getActionsByLevel(level: number): ActionInfo[];
}

interface ActionInfo {
  name: string;
  index: number;           // Execution order (1-based)
  level: number;           // Parallel level (for grouping)
  status: 'pending' | 'running' | 'completed' | 'failed';
  type: 'source' | 'transform' | 'merge' | 'parallel';
  folderPath: string;
  configLocation: vscode.Location;  // Line in YAML
  dependencies: string[];
  outputFields: string[];
  versions?: string[];     // For parallel actions
}
```

### Extension Activation

```json
{
  "activationEvents": [
    "workspaceContains:**/agent_config/*.yml",
    "workspaceContains:**/.manifest.json"
  ]
}
```

### Commands

| Command | Description | Keybinding |
|---------|-------------|------------|
| `agentActions.openFolder` | Open action's target folder | - |
| `agentActions.openConfig` | Jump to action in YAML | - |
| `agentActions.showDAG` | Open DAG webview | `Cmd+Shift+D` |
| `agentActions.refresh` | Refresh workflow model | `Cmd+Shift+R` |
| `agentActions.goToAction` | Quick pick to jump to action | `Cmd+Shift+A` |

### Settings

```json
{
  "agentActions.showStatusBar": true,
  "agentActions.showCodeLens": true,
  "agentActions.showFileDecorations": true,
  "agentActions.dagLayout": "vertical",  // or "horizontal"
  "agentActions.refreshInterval": 2000   // ms, for status polling
}
```

---

## Implementation Plan

### Phase 1: Core Navigation (MVP)
**Goal:** Basic tree view with click-to-navigate

- [ ] Project scaffolding (TypeScript, esbuild, tests)
- [ ] YAML parser for workflow config
- [ ] Manifest reader for status
- [ ] Tree view provider with execution order
- [ ] Click to open folder command
- [ ] Basic status icons (✓ ○)

**Deliverable:** Engineers can see actions in order and click to navigate.

### Phase 2: Enhanced UX
**Goal:** Rich interactions and real-time updates

- [ ] File watcher for manifest changes
- [ ] File decorations in Explorer
- [ ] CodeLens in YAML files
- [ ] Status bar indicator
- [ ] Hover tooltips with dependencies
- [ ] Right-click context menu

**Deliverable:** Real-time status updates and in-editor navigation.

### Phase 3: Visual DAG
**Goal:** Interactive dependency graph

- [ ] Webview panel infrastructure
- [ ] DAG rendering (Mermaid or D3)
- [ ] Click-to-navigate from nodes
- [ ] Pan/zoom controls
- [ ] Export to PNG/SVG

**Deliverable:** Visual overview of workflow structure.

### Phase 4: Polish & Publish
**Goal:** Production-ready extension

- [ ] Settings UI
- [ ] Welcome/onboarding view
- [ ] Documentation
- [ ] Telemetry (opt-in)
- [ ] VS Code Marketplace publishing
- [ ] CI/CD for releases

---

## Alternatives Considered

### 1. Numbered Folder Prefixes
**Approach:** Rename folders from `action_name` to `01_action_name`.

**Why rejected:**
- Breaks 8+ internal files with path dependencies
- Renumbering on workflow changes is error-prone
- Merge conflicts when multiple engineers modify order

### 2. Symlink Layer
**Approach:** Keep original folders, create `_ordered/` with numbered symlinks.

**Why not chosen as primary:**
- Symlinks not universally supported (Windows, some file systems)
- Two locations to navigate is confusing
- Still doesn't provide status or interactivity

**Verdict:** Could be added as optional feature for terminal users.

### 3. CLI-Only Solution
**Approach:** Enhance `agac inspect` commands with better output.

**Why not sufficient:**
- Requires context switching to terminal
- No click-to-navigate
- No real-time updates
- Engineers primarily work in IDE

### 4. Auto-generated INDEX.md
**Approach:** Generate markdown file listing actions in order.

**Why not sufficient:**
- Gets stale if not auto-updated
- No interactivity
- Requires opening separate file

**Verdict:** Could complement the extension for non-VS Code users.

---

## Open Questions

1. **Multi-root workspaces:** How to handle multiple Agent Actions projects in one workspace?
   - Proposal: Separate tree view sections per project

2. **Remote development:** Does this work with VS Code Remote (SSH, Containers)?
   - Needs testing; likely works since we use standard VS Code APIs

3. **Performance:** Large workflows (50+ actions) - need virtualization?
   - Proposal: Lazy loading for large workflows

4. **Integration with `agac` CLI:** Should extension be able to trigger workflow runs?
   - Proposal: Phase 5 feature, not MVP

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Time to navigate to action folder | < 2 clicks (down from 5+) |
| Onboarding comprehension | New engineers understand flow in < 5 min |
| Adoption | 80% of team using extension within 1 month |
| Marketplace rating | 4.5+ stars |

---

## References

- [VS Code Tree View API](https://code.visualstudio.com/api/extension-guides/tree-view)
- [VS Code UX Guidelines for Views](https://code.visualstudio.com/api/ux-guidelines/views)
- [VS Code Extension Samples](https://github.com/Microsoft/vscode-extension-samples)
- [GitLens Extension](https://marketplace.visualstudio.com/items?itemName=eamodio.gitlens)
- [ZenML DAG Visualization](https://www.zenml.io/blog/dag-visualization-vscode-extension)
- [Airflow VS Code Extension](https://marketplace.visualstudio.com/items?itemName=NecatiARSLAN.airflow-vscode-extension)
- [Pipeline Visualizer](https://marketplace.visualstudio.com/items?itemName=DannydeHaan.pipeline-visualizer)
- [VS Code FileDecorationProvider](https://code.visualstudio.com/api/references/vscode-api#FileDecorationProvider)

---

## Appendix A: File Structure

```
vscode-agent-actions/
├── package.json
├── tsconfig.json
├── src/
│   ├── extension.ts              # Entry point
│   ├── model/
│   │   ├── workflowModel.ts      # Central data model
│   │   ├── yamlParser.ts         # Parse workflow YAML
│   │   └── manifestReader.ts     # Read .manifest.json
│   ├── providers/
│   │   ├── treeViewProvider.ts   # Sidebar tree
│   │   ├── codeLensProvider.ts   # YAML CodeLens
│   │   ├── decorationProvider.ts # File explorer badges
│   │   └── statusBarProvider.ts  # Status bar item
│   ├── views/
│   │   └── dagWebview.ts         # DAG panel
│   ├── commands/
│   │   ├── openFolder.ts
│   │   ├── openConfig.ts
│   │   └── goToAction.ts
│   └── test/
│       └── suite/
├── media/
│   ├── icons/
│   └── dag/
│       └── dag.html              # Webview template
└── README.md
```

## Appendix B: Package.json Contribution Points

```json
{
  "contributes": {
    "views": {
      "explorer": [
        {
          "id": "agentActionsWorkflow",
          "name": "Agent Actions",
          "icon": "media/icons/agent-actions.svg",
          "contextualTitle": "Workflow Navigator"
        }
      ]
    },
    "commands": [
      {
        "command": "agentActions.openFolder",
        "title": "Open Action Folder",
        "category": "Agent Actions"
      },
      {
        "command": "agentActions.showDAG",
        "title": "Show Workflow DAG",
        "category": "Agent Actions"
      },
      {
        "command": "agentActions.goToAction",
        "title": "Go to Action...",
        "category": "Agent Actions"
      }
    ],
    "menus": {
      "view/item/context": [
        {
          "command": "agentActions.openFolder",
          "when": "view == agentActionsWorkflow",
          "group": "navigation"
        }
      ]
    },
    "keybindings": [
      {
        "command": "agentActions.showDAG",
        "key": "cmd+shift+d",
        "when": "agentActions.isAgentProject"
      },
      {
        "command": "agentActions.goToAction",
        "key": "cmd+shift+a",
        "when": "agentActions.isAgentProject"
      }
    ]
  }
}
```
