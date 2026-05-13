```markdown
## Prompt Contract: Shared ReactFlow DAG (Docs + VS Code)

### GOAL
Add a ReactFlow-based workflow DAG inside the VS Code extension webview that reuses the existing docs DAG UI code, and refactor the docs DAG transformer so **both Docs and VS Code use one shared DAG→ReactFlow transform function** (single pathway for IDs, edge policy, and layout). The VS Code DAG must preserve current behaviors: workflow selection, `agentActions.dagLayout`, and click-to-open action config.

### FAILURE MODES
1. **CSS missing in VS Code webview**: `@xyflow/react/dist/style.css` isn’t bundled/loaded, causing broken layout/controls/minimap. The design must explicitly produce and load webview CSS assets.
2. **Multiple React copies in the webview bundle**: React hooks break if the docs-imported components pull another React instance. The build must force React/ReactDOM singletons (reuse the existing aliasing approach in `vscode-extension/esbuild.js`).
3. **Node ID mismatch breaks click-to-open**: VS Code must post the exact action name used by `WorkflowModel.getActionByName`. The shared transformer must not sanitize/alter IDs, and the webview must post the exact `node.id`.
4. **Unknown dependencies crash or spam errors**: Some dependency names may not correspond to any action node. The transformer must define a policy: drop invalid edges (default) or materialize placeholder nodes (optional).
5. **Cycles in dependency graph**: Graph may not be a strict DAG. The transformer must not throw; layout should be best-effort, with predictable behavior even if cycles exist.
6. **Layout direction drift between Docs and VS Code**: Docs and VS Code could render different graphs if they each map “vertical/horizontal” differently. The shared transformer must accept an explicit `direction` and both callers must use it.
7. **Theme readability regressions**: Webview must remain legible in light/dark/high-contrast. Node/edge colors must not assume a single theme.
8. **Large graph perf cliff**: Big workflows can freeze the webview (layout + render). Must define a threshold behavior (warn/simplify) rather than unbounded work.
9. **CSP/resource loading failures**: Webview may fail to load scripts/styles due to CSP or `localResourceRoots` misconfiguration. The host must set CSP with nonce and allow only local resources.
10. **Policy drift over time**: Docs and VS Code accidentally reintroduce separate transforms. The code structure must make the shared transformer the obvious/only choice (named export; local wrappers only adapt input types).
11. **Ambiguous action identity across workflows**: If two workflows expose the same `ActionInfo.name`, `getActionByName` may open the wrong config. Payload or lookup must be extended if this is possible in production data.

### CONSTRAINTS
- **Use the existing docs DAG components** (`agent_actions/tooling/docs/frontend/components/workflow-dag.tsx`) where practical, because reimplementing UI would diverge and defeat the “single pathway” intent.
- **Single shared transformer** must live in `agent_actions/tooling/docs/frontend/lib/dag-transformer.ts` and be imported by both Docs and VS Code webview via the existing `@/…` alias, because the extension already resolves `@/` into the docs frontend and this avoids duplicating transformer logic.
- **No remote assets** in webviews, because VS Code webviews must work offline and must not loosen CSP to allow CDNs.
- **Preserve existing commands/config** (`agentActions.showDAG`, `agentActions.openConfig`, `agentActions.dagLayout`), because users already depend on these and Mermaid parity is the baseline.
- **Do not introduce a second layout algorithm** (e.g. ELK) unless Dagre cannot meet requirements, because it increases bundle size and makes the “single pathway” harder to maintain.

### FORMAT
- **End-to-end context & data flows (Docs vs VS Code)**
  - **Docs path**
    - UI entry: `agent_actions/tooling/docs/frontend/components/workflow-dag.tsx`
    - Data acquisition: docs catalog/context provides `Action` records; filter by `workflowId`
    - Transform: `adaptDocsActionsToDAGActions(...)` → `transformActionsToReactFlow(...)`
    - Render: `@xyflow/react` with docs nodeTypes (expandable node UI)
  - **VS Code path**
    - Host entry: `vscode-extension/src/views/dagWebview.ts` creates/reveals a `WebviewPanel`
    - Data source: `WorkflowModel.getWorkflows()` → `WorkflowInfo.actions: ActionInfo[]`
    - Transport: `panel.webview.postMessage({ type: "dag:update", payload })`
    - Webview: `vscode-extension/src/webview/dag.tsx` adapts payload → `DAGAction[]` → shared transformer → ReactFlow render
    - Control return: node click → `{ type: "openAction", actionName }` → host executes `agentActions.openConfig`
  - **Boundary rule**
    - Only the transformer owns node/edge construction + layout policy.
    - Callers own: data acquisition, IPC transport, and node renderer components.

- **Shared transformer API (single pathway)**
  - Update `agent_actions/tooling/docs/frontend/lib/dag-transformer.ts` to export:
    - `type DAGAction` (UI-agnostic action shape)
    - `type DAGNodeData` (node render data; includes label, kind, optional status, and field lists)
    - `function transformActionsToReactFlow(actions: DAGAction[], opts): { nodes, edges }`
  - Transformer policy (must be enforced in one place):
    - **IDs**: `node.id === action.name` (exact string; no sanitization).
    - **Unknown deps policy**: `opts.unknownDeps` with default `"filter"`:
      - `"filter"`: drop edges whose endpoints are missing.
      - `"materialize"`: add placeholder nodes for missing endpoints.
    - **Cycles**: do not throw; layout is best-effort.
    - **Direction**: accept `opts.direction: "LR" | "TB"` and never infer it internally.
    - **Layout defaults**: document and centralize defaults (nodeWidth/Height/nodesep/ranksep) so both surfaces evolve together.
  - **Adapter responsibilities (explicit mapping rules)**
    - Docs adapter must map:
      - `Action.deps` → `DAGAction.deps`
      - `Action.type ("llm" | "tool")` → `DAGAction.kind`
      - `Action.intent` → `DAGAction.intent`
      - `Action.model` / `Action.impl` → `DAGAction.model` / `DAGAction.impl`
      - fields: `inputs/observe/outputs/outputFields/drops` → corresponding `DAGAction` arrays
      - workflow scoping: filter to `workflowId` before transforming
    - VS Code adapter must map (minimum viable):
      - `ActionInfo.name` → `DAGAction.name`
      - `ActionInfo.dependencies` → `DAGAction.deps`
      - `ActionInfo.status` → `DAGAction.status`
      - `ActionInfo.type` → `DAGAction.kind` (initially `"tool"` unless you later enrich with real tool-vs-LLM classification)
      - optional: `ActionInfo.outputFields` → `DAGAction.outputFields` (flatten to string names)
    - **Invariant**: adapters must not normalize/escape `name`; `name` is the stable key for click-to-open.

- **Docs DAG wiring**
  - Update `agent_actions/tooling/docs/frontend/components/workflow-dag.tsx` to:
    - Adapt its existing `Action` records to `DAGAction[]`.
    - Call `transformActionsToReactFlow` with the docs’ desired direction/defaults.
  - Node rendering remains in Docs (expandable nodes, minimap, controls) but uses the shared transformer output.

- **Centralization opportunities (Docs + VS Code shareable pieces)**
  - **DAG adapter utilities**: add a small helper (either alongside the transformer or in a sibling `lib/`) that converts from “caller shapes” → `DAGAction[]`.
    - Docs adapter: `Record<string, Action> + workflowId` → `DAGAction[]`
    - VS Code adapter: `ActionInfo[]` (plus optional enriched fields) → `DAGAction[]`
    - Rationale: keeps mapping rules (what counts as deps, what fields are shown, what’s “kind”) consistent; prevents each surface inventing its own inference logic.
  - **Layout defaults**: keep layout constants (`nodeWidth/nodeHeight/nodesep/ranksep`) in one exported object so both surfaces stay visually consistent as spacing changes.
  - **Status palette + edge styling tokens**: export a small `dagTheme` map (status→colors, edge stroke defaults) consumed by both node renderers so “completed/running/failed” reads the same everywhere.
  - **Unknown-deps policy**: keep the “filter vs materialize” implementation inside the transformer (already required), but also centralize the *default* and document it so callers don’t diverge.
  - **Message contract types (webview IPC)**: define and share TypeScript types for `{type:"ready" | "dag:update" | "openAction"}` payloads.
    - Location options:
      - extension-only: `vscode-extension/src/webview/ipc.ts` (safest if docs never needs it)
      - shared with docs: a lightweight `agent_actions/tooling/docs/frontend/lib/vscode-webview-ipc.ts` imported by the VS Code webview bundle via `@/…`
    - Rationale: prevents silent drift (renamed message types, missing fields) and makes refactors safe.
  - **VS Code theme sync helper**: extract the existing CSS-variable→HSL mapping logic from `vscode-extension/src/webview/main.tsx` into `vscode-extension/src/webview/themeSync.ts`, and reuse in both Query Results and DAG webviews.
    - Rationale: one place to maintain theme edge cases (high contrast, missing variables) and prevents partial copies.
  - **Webview HTML shell builder**: factor out a shared helper in the extension host layer for building webview HTML with CSP+nonce+asset URIs (Query Results + DAG share the pattern).
    - Location: `vscode-extension/src/views/webviewHtml.ts` (extension-only)
    - Rationale: reduces repeated CSP mistakes and makes it easy to add new webviews.
  - **Last-write-wins “ready gate”**: centralize the `ready` handshake and pending payload logic (Query Results already has it; DAG will need it).
    - Location: `vscode-extension/src/views/webviewMessagePump.ts` (extension-only)
    - Rationale: avoids each panel inventing a subtly broken “isReady boolean” flow; encapsulates queued update invariants.
  - **What NOT to centralize (avoid coupling)**:
    - Don’t share VS Code host-side `vscode.*` logic into docs frontend code (keeps docs build independent).
    - Don’t share Next.js/React Router assumptions into the VS Code webview (it must be standalone).
  - **Optional next step (if you want identical node UI)**
    - Reuse docs node components in VS Code by importing `@/components/workflow-dag` into the webview bundle.
    - Caveat: this couples the extension’s webview styling to docs tailwind tokens and xyflow CSS; treat docs frontend as a “design system” dependency if you do this.

- **VS Code DAG webview**
  - Add a new entrypoint `vscode-extension/src/webview/dag.tsx` that:
    - Mounts a ReactFlow renderer (either reuse `WorkflowDAGView` directly or a thin VS Code wrapper).
    - Receives `{ type: "dag:update", payload }` from the host.
    - Adapts extension workflow actions to `DAGAction[]` and calls the shared transformer.
    - Posts `{ type: "openAction", actionName }` on node click where `actionName === node.id`.
    - Implements a `{ type: "ready" }` handshake so the host can defer updates until mounted.
  - Theme handling:
    - Prefer a small shared helper (copied or extracted from `src/webview/main.tsx`) to sync VS Code theme tokens to CSS variables used by the UI.

- **VS Code host panel**
  - Modify `vscode-extension/src/views/dagWebview.ts` to:
    - Render a webview HTML shell that loads `out/dagWebview.js` (and CSS).
    - Set CSP with nonce; load only local assets via `webview.asWebviewUri`.
    - Set `localResourceRoots` to include `out/` and any other required directories.
    - Handle messages:
      - `openAction` → execute `agentActions.openConfig`.
      - `ready` → mark the panel ready and send the latest payload (queue last-write-wins).
    - On model change/theme change/layout setting change, send updates via `postMessage` (do not regenerate HTML each time).

- **Build & packaging**
  - Update `vscode-extension/esbuild.js`:
    - Add a build context for `src/webview/dag.tsx` → `out/dagWebview.js`.
    - Ensure React singleton aliasing applies to this bundle.
    - Ensure CSS is emitted and loaded (choose one):
      - **Preferred**: esbuild bundles CSS imports from `@xyflow/react/dist/style.css` into an output CSS file and the host loads it.
      - **Acceptable**: a dedicated Tailwind-built `src/webview/dag.css` that includes required xyflow base styles (must be documented as a maintenance trade-off).
  - Update `vscode-extension/package.json` to add runtime deps `@xyflow/react` and `dagre` (and types if needed).
  - Update `vscode-extension/.vscodeignore` to include `out/dagWebview.js` and any CSS outputs.

- **Webview IPC contract (explicit schema)**
  - Host → webview:
    - `{ type: "dag:update", payload: { workflowName: string; layout: "vertical"|"horizontal"; actions: Array<{ name: string; deps: string[]; kind: "llm"|"tool"|"unknown"; status?: "pending"|"running"|"completed"|"failed"|"skipped"; model?: string; impl?: string; intent?: string; inputs?: string[]; observe?: string[]; outputs?: string[]; outputFields?: string[]; drops?: string[]; }> } }`
  - Webview → host:
    - `{ type: "ready" }`
    - `{ type: "openAction", actionName: string }`
  - Host must treat messages as untrusted:
    - validate `typeof actionName === "string"` and look it up in the model before executing `agentActions.openConfig`.

- **CSP + resource loading requirements (concrete)**
  - The DAG webview HTML shell must:
    - set CSP with nonce for scripts
    - load scripts/styles only via `webview.asWebviewUri(...)`
    - avoid remote fonts/images/scripts entirely
  - `localResourceRoots` must include the directory that contains:
    - `out/dagWebview.js`
    - the emitted css (if separate)

- **Rollout / fallback strategy (risk control)**
  - Preferred: introduce `agentActions.dagRenderer: "mermaid" | "reactflow"` and keep Mermaid as fallback for one release cycle.
  - If no setting is desired: keep commits separated so reverting the host swap is a one-commit rollback.

- **Large graph behavior**
  - Define a threshold (e.g., nodes > 500) where the VS Code webview:
    - shows a warning banner and disables minimap/animations, and/or
    - uses `unknownDeps:"filter"` forcibly, and/or
    - skips expandable field rendering.
  - Must not silently hang; if layout takes too long, show an actionable message.

- **Host update triggers (when to send `dag:update`)**
  - After `WorkflowModel.onDidChange` while the panel is visible (same as today’s Mermaid `update()`).
  - After `vscode.window.onDidChangeActiveColorTheme` (webview may need theme hint or rely on body class + theme sync).
  - After `vscode.workspace.onDidChangeConfiguration` when `agentActions.dagLayout` or `agentActions.dagRenderer` (if added) changes.
  - After `showWorkflow(workflow)` / workflow pick changes `currentWorkflowName` (keep last-selected workflow stable across refreshes; match existing `DagWebview` behavior).
  - Do **not** replace full `webview.html` on every refresh once the shell is loaded; use `postMessage` only to avoid white flashes and script re-init cost.

- **Layout mapping (single table — no drift)**
  | `agentActions.dagLayout` | Transformer `opts.direction` | Dagre `rankdir` mental model |
  |--------------------------|------------------------------|------------------------------|
  | `vertical`               | `TB`                         | Top → bottom                 |
  | `horizontal`             | `LR`                         | Left → right                 |

- **Sequence (happy path, VS Code)**
  1. User: `agentActions.showDAG` → host picks workflow → creates/reveals panel → sets HTML shell (nonce CSP, script + css URIs).
  2. Webview loads `dagWebview.js` → React mounts → `postMessage({ type: "ready" })`.
  3. Host receives `ready` → flushes latest pending `dag:update` (last-write-wins).
  4. Host (or model listener) sends `dag:update` with actions + layout.
  5. Webview applies adapter → `transformActionsToReactFlow` → `setNodes/setEdges` → `fitView` (debounce if needed).
  6. User clicks node → `postMessage({ type: "openAction", actionName })` → host validates → `executeCommand("agentActions.openConfig", action)`.

- **Multi-workflow & identity**
  - Payload should include `workflowName` for masthead/debug; graph nodes still use global action `name` as `id` (matches `WorkflowModel.getActionByName` which searches all workflows).
  - If two workflows could ever expose the same action name, document whether `openAction` must become `(workflowName, actionName)` — today the model assumes names are unique across the workspace for lookup.

- **Dependency alignment**
  - Pin `@xyflow/react` and `dagre` in `vscode-extension/package.json` to the **same major/minor** as `agent_actions/tooling/docs/frontend/package.json` where possible, to avoid subtle API differences between docs build and extension bundle.

- **File inventory (expected touch list)**
  | Area | Path |
  |------|------|
  | Shared transformer | `agent_actions/tooling/docs/frontend/lib/dag-transformer.ts` |
  | Docs DAG UI | `agent_actions/tooling/docs/frontend/components/workflow-dag.tsx` |
  | VS Code webview entry | `vscode-extension/src/webview/dag.tsx` (new) |
  | VS Code host | `vscode-extension/src/views/dagWebview.ts` |
  | Build | `vscode-extension/esbuild.js` |
  | Deps / package | `vscode-extension/package.json`, `vscode-extension/package-lock.json` |
  | Packaging | `vscode-extension/.vscodeignore` |
  | Optional shared host helpers | `vscode-extension/src/views/webviewHtml.ts`, `vscode-extension/src/views/webviewMessagePump.ts` (new) |
  | Optional theme | `vscode-extension/src/webview/themeSync.ts` (new), refactor `src/webview/main.tsx` to import |
  | Settings (optional) | `vscode-extension/package.json` `contributes.configuration` for `dagRenderer` |
  | Commands | `vscode-extension/src/commands/index.ts` (only if new command or setting wiring) |
  | Changelog | `.changes/unreleased/*.yaml` per repo policy |

- **Manual testing matrix (minimum)**
  | Scenario | Pass criterion |
  |----------|----------------|
  | 0 workflows | Same as today: info message, no crash |
  | 1 workflow | DAG opens; nodes/edges match config; click opens YAML |
  | 2+ workflows | Quick pick; switching workflow updates graph + title |
  | Toggle `dagLayout` | Direction changes without reload loop |
  | Model refresh | Edit manifest/status file; graph updates without losing panel |
  | Theme switch | Light/dark/HC readable; no CSP console errors |
  | Unknown dep | Edge dropped or placeholder per policy; no throw |
  | Large graph | Threshold path triggers; UI remains responsive |

- **Troubleshooting (symptom → likely cause)**
  | Symptom | Likely cause |
  |---------|----------------|
  | Blank panel, CSP error in webview devtools | Wrong `script-src` nonce, or script URI not under `localResourceRoots` |
  | ReactFlow renders but unstyled | `@xyflow/react` CSS not linked or not emitted by build |
  | `useState` / hooks crash | Duplicate React; check `esbuild.js` aliases for DAG bundle |
  | Click does nothing / wrong action | `node.id` ≠ `ActionInfo.name`; adapter mutated name |
  | Graph empty but actions exist | All edges filtered; deps don’t match node ids (versioned names?) |
  | Updates stop after tab switch | `ready` / pending queue bug; or panel disposed |

- **Observability (extension host)**
  - Log at **debug** when: panel created, `ready` received, `dag:update` sent (workflow name + action count only — no record payloads).
  - Log at **warning** when: `openAction` for unknown name, or transform threw (should never throw per contract).

### DELIVERY
- Commit 1: **Docs transformer refactor (low risk, isolated)**
  - Update `agent_actions/tooling/docs/frontend/lib/dag-transformer.ts` to export the shared transformer/types.
  - Update `agent_actions/tooling/docs/frontend/components/workflow-dag.tsx` to use the new API.
  - Verification:
    - `cd agent_actions/tooling/docs/frontend && npm run build`

- Commit 2: **VS Code DAG webview scaffolding (medium risk)**
  - Add `vscode-extension/src/webview/dag.tsx`.
  - Add/adjust CSS strategy for xyflow styles.
  - Update `vscode-extension/esbuild.js` to build `out/dagWebview.js` (+ css).
  - Verification:
    - `cd vscode-extension && npm run build` (or `npm run compile` depending on repo norms)

- Commit 3: **Host panel switch (behavioral change)**
  - Update `vscode-extension/src/views/dagWebview.ts` to host the React webview and message passing.
  - Add deps and packaging updates (`package.json`, `.vscodeignore`).
  - Verification:
    - `cd vscode-extension && npm run typecheck && npm run build`
    - Manual: open VS Code extension dev host, run “Agent Actions: Show Workflow DAG”, click node opens config, toggle `dagLayout`.
  - Optional Commit 4: **Settings + rollback ergonomics**
    - Add `agentActions.dagRenderer` (and wire host to branch Mermaid vs ReactFlow).
    - Verification: toggle setting; both renderers work; default matches product decision.

- **Local dev loop (engineer)**
  1. From repo root: `cd agent-actions/vscode-extension && npm install && npm run compile` (or `watch` if available).
  2. Open `vscode-extension` in VS Code → Run Extension (F5) → test command palette `Agent Actions: Show Workflow DAG`.
  3. Webview debug: Command Palette → “Developer: Open Webview Developer Tools” on the DAG panel.
  4. After docs transformer changes: `cd agent_actions/tooling/docs/frontend && npm install && npm run build`.

- **Ship checklist**
  - Add **Changie** entry under `.changes/unreleased/` per `CLAUDE.local.md` (Enhancement or Under the Hood).
  - Run `vsce package` (or CI equivalent) and confirm the `.vsix` contains `out/dagWebview.js` and emitted CSS (unzip and inspect if unsure).

### FAILURE CONDITIONS
Design anti-patterns:
- A second, duplicate DAG transformer is introduced (Docs and VS Code do not share the same exported transformer function).
- Node IDs are sanitized/hashed in one surface but not the other, breaking click-to-open or diverging edge policy.
- CSS for `@xyflow/react` is “fixed” by loosening CSP or using a remote CDN.
- Concurrency/ready handling drops updates (no last-write-wins queue; updates sent before `ready` are lost without retry).

Output defects:
- VS Code webview fails to load due to CSP errors, missing `localResourceRoots`, or missing packaged assets.
- `npm run build` for docs frontend or VS Code extension fails (type errors, missing deps).
- React hooks error at runtime (“Cannot read properties of null (reading 'useState')”) indicating multiple React copies.
- Wrong action opens on click when multiple workflows define the same action name without disambiguation in the contract.
```

Assumptions I Made:
- The VS Code extension build can be extended to emit/load CSS for `@xyflow/react/dist/style.css` without introducing a new bundler.
- VS Code DAG nodes can be rendered acceptably with the fields available from `WorkflowModel` today; richer fields (inputs/observe/intent/model) can be empty unless we explicitly extend the model later.
- The repo wants prompt contracts stored under `agent-actions/prompt-contracts/` (this directory didn’t exist yet in this clone).
- Action names remain **globally unique** across workflows in a workspace for `getActionByName`; if that is false in the wild, the contract must be revised to pass `workflowName` with `openAction` and resolve actions per-workflow.
- Engineers have access to the full `agent-actions` repo (docs frontend + extension) in one workspace for path resolution and CI.
