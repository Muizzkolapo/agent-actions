# Issue: Version Template Variables Not Injected in Prompt Store References

## Summary

Version iteration variables (`{{ i }}`, `{{ idx }}`, `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}`) are not available when using prompt store references (`prompt: $workflow.Prompt_Name`). They only work partially with inline prompts using `${i}` syntax.

## Environment

- **Framework**: agent-actions
- **Affected Components**:
  - `agent_actions/output/response/expander.py`
  - `agent_actions/workflow/pipeline.py`
  - `agent_actions/prompt/context/scope.py`

---

## Root Cause Analysis

### Current Architecture: Lazy Rendering

The current system renders prompts lazily at execution time:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CURRENT FLOW (Lazy Rendering)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. YAML Load                                                               │
│     └─ _resolve_prompt_fields() → Loads prompt text from store              │
│                                   (Templates NOT rendered)                  │
│                                                                              │
│  2. Action Expansion                                                        │
│     └─ Stores version metadata in agent_config                              │
│        (But version context not available to prompts)                       │
│                                                                              │
│  3. Execution (per record, per agent)                                       │
│     └─ _render_prompt_template() → Jinja2 render with runtime context       │
│        ❌ Version variables not in context → UNDEFINED ERROR                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Problems with lazy rendering:**
1. Version context not available during prompt rendering
2. No way to inspect fully rendered configs before execution
3. Harder to debug template issues
4. Documentation can't show compiled prompts

---

## Proposed Solution: Compile-First Architecture (Like dbt)

### Design Principle

Like dbt's `dbt compile` command, we should have a **compile phase** that produces fully rendered configurations before the execution engine sees them.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PROPOSED FLOW (Compile-First)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: COMPILE (New)                                                     │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  1. Load YAML + Resolve Prompt Store References                             │
│     └─ $workflow.Prompt_Name → raw template text                            │
│                                                                              │
│  2. Expand Versioned Actions                                                │
│     └─ action_1, action_2, action_3 each with version context               │
│                                                                              │
│  3. Compile Version Context Into Each Agent                                 │
│     └─ agent["_version_context"] = {i, idx, length, first, last, ...}       │
│                                                                              │
│  4. Pre-Render Static Template Variables                                    │
│     └─ Render {{ i }}, {{ version.length }}, {{ version.first }}            │
│        into prompts (these are known at compile time)                       │
│                                                                              │
│  5. Output: Compiled Config                                                 │
│     └─ Fully expanded agents with pre-rendered prompts                      │
│        (Only runtime variables like {{ source.* }} remain)                  │
│                                                                              │
│  ───────────────────────────────────────────────────────────────────────   │
│                                                                              │
│  PHASE 2: EXECUTE (Existing, simplified)                                    │
│  ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│  1. Load Compiled Config                                                    │
│     └─ Agents already have version variables baked in                       │
│                                                                              │
│  2. Execute (per record)                                                    │
│     └─ Only render runtime variables ({{ source.* }}, {{ dep.* }})          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Benefits of Compile-First

1. **Inspectable**: Can view fully compiled configs before execution
2. **Debuggable**: Template errors surface at compile time, not runtime
3. **Documentable**: Docs can show actual prompts with version variables rendered
4. **Cacheable**: Compiled configs can be cached
5. **Testable**: Can unit test compiled output without running full workflow

---

## Implementation Plan

### Phase 1: Immediate Fix (Completed)

Add version context to the existing lazy rendering flow:

1. ✅ **expander.py**: Compile `_version_context` during action expansion
2. ✅ **pipeline.py**: Extract version context into `loop_context` for ProcessingContext
3. ✅ **scope.py**: Add `version` namespace to field_context (renamed from `loop`)

### Phase 2: Compile-First Architecture (Future)

Create a proper compile step that pre-renders version variables:

#### Step 1: Create WorkflowCompiler Class

```python
# agent_actions/compile/compiler.py

class WorkflowCompiler:
    """Compiles workflow configs like dbt compile."""

    def compile(self, workflow_path: str) -> CompiledWorkflow:
        """
        Compile a workflow YAML into fully rendered agent configs.

        Returns:
            CompiledWorkflow with all version variables pre-rendered
        """
        # 1. Load and parse YAML
        raw_config = self._load_yaml(workflow_path)

        # 2. Resolve prompt store references
        config = self._resolve_prompt_references(raw_config)

        # 3. Expand versioned actions
        expanded = ActionExpander.expand_actions_to_agents(config)

        # 4. Pre-render version variables in prompts
        compiled_agents = self._render_version_variables(expanded)

        # 5. Return compiled workflow
        return CompiledWorkflow(
            name=config["name"],
            agents=compiled_agents,
            compile_time=datetime.now(),
            source_path=workflow_path,
        )

    def _render_version_variables(self, agents: Dict) -> Dict:
        """Pre-render version variables in prompts."""
        for agent_name, agent_config in agents.items():
            version_ctx = agent_config.get("_version_context")
            if version_ctx and agent_config.get("prompt"):
                # Render version variables
                prompt = agent_config["prompt"]
                env = Environment()
                template = env.from_string(prompt)
                agent_config["prompt"] = template.render(
                    i=version_ctx["i"],
                    idx=version_ctx["idx"],
                    version=version_ctx,
                    **{k: v for k, v in version_ctx.items()
                       if k not in ("i", "idx", "length", "first", "last")}
                )
        return agents
```

#### Step 2: Create Compiled Artifact Format

```python
# agent_actions/compile/artifact.py

@dataclass
class CompiledWorkflow:
    """Compiled workflow artifact."""
    name: str
    agents: Dict[str, AgentConfig]
    compile_time: datetime
    source_path: str

    def to_yaml(self) -> str:
        """Export as YAML for inspection."""
        return yaml.dump(self.to_dict(), default_flow_style=False)

    def to_json(self) -> str:
        """Export as JSON for inspection."""
        return json.dumps(self.to_dict(), indent=2)
```

#### Step 3: Add CLI Command

```bash
# Compile and output to target/compiled/
agac compile workflow_name

# Compile and inspect
agac compile workflow_name --inspect

# Compile with debug output
agac compile workflow_name --debug
```

#### Step 4: Update Execution to Use Compiled Configs

```python
# agent_actions/workflow/coordinator.py

class AgentWorkflow:
    def __init__(self, ...):
        # Check for pre-compiled config
        compiled_path = self._get_compiled_path(workflow_path)
        if compiled_path.exists():
            self.config = CompiledWorkflow.load(compiled_path)
        else:
            # Compile on-the-fly
            compiler = WorkflowCompiler()
            self.config = compiler.compile(workflow_path)
```

---

## Variable Categories

### Compile-Time Variables (Pre-rendered)

These are known at compile time and should be rendered during compilation:

| Variable | Source | Compile-Time? |
|----------|--------|---------------|
| `{{ i }}` | Version iteration | ✅ Yes |
| `{{ idx }}` | Version index | ✅ Yes |
| `{{ version.length }}` | Total versions | ✅ Yes |
| `{{ version.first }}` | Is first | ✅ Yes |
| `{{ version.last }}` | Is last | ✅ Yes |
| `{{ custom_param }}` | Custom param | ✅ Yes |
| `{{ workflow.name }}` | Workflow metadata | ✅ Yes |

### Runtime Variables (Rendered at execution)

These depend on input data and must be rendered at execution time:

| Variable | Source | Compile-Time? |
|----------|--------|---------------|
| `{{ source.* }}` | Input record | ❌ No |
| `{{ dep_name.* }}` | Upstream output | ❌ No |
| `{{ seed.* }}` | Seed data (could be) | ⚠️ Maybe |

---

## Output Structure

### Compiled Workflow Directory

```
target/
└── compiled/
    └── incident_triage/
        ├── manifest.json           # Compilation metadata
        ├── compiled_config.yaml    # Full compiled config
        └── agents/
            ├── extract_incident_details.yaml
            ├── classify_severity_1.yaml   # Version variable pre-rendered
            ├── classify_severity_2.yaml   # Version variable pre-rendered
            ├── classify_severity_3.yaml   # Version variable pre-rendered
            └── aggregate_severity.yaml
```

### Example Compiled Agent

**Before compilation:**
```yaml
name: classify_severity_1
prompt: |
  You are classifier {{ i }} of {{ version.length }}.
  {% if version.first %}Be conservative.{% endif %}
  Analyze: {{ source.incident_report }}
```

**After compilation:**
```yaml
name: classify_severity_1
prompt: |
  You are classifier 1 of 3.
  Be conservative.
  Analyze: {{ source.incident_report }}
_compiled: true
_version_context:
  i: 1
  idx: 0
  length: 3
  first: true
  last: false
```

---

## Testing Plan

### Unit Tests

```python
def test_compiler_renders_version_variables():
    """Verify compiler pre-renders version variables in prompts."""
    compiler = WorkflowCompiler()
    compiled = compiler.compile("test_workflow.yaml")

    agent = compiled.agents["classify_severity_1"]
    assert "{{ i }}" not in agent["prompt"]
    assert "classifier 1 of 3" in agent["prompt"]

def test_compiler_preserves_runtime_variables():
    """Verify compiler does NOT render runtime variables."""
    compiler = WorkflowCompiler()
    compiled = compiler.compile("test_workflow.yaml")

    agent = compiled.agents["classify_severity_1"]
    assert "{{ source.incident_report }}" in agent["prompt"]
```

### Integration Tests

```python
def test_compiled_workflow_executes_correctly():
    """Verify compiled workflows execute the same as non-compiled."""
    # Compile
    compiler = WorkflowCompiler()
    compiled = compiler.compile("incident_triage.yaml")
    compiled.save("target/compiled/incident_triage")

    # Execute from compiled
    workflow = AgentWorkflow("target/compiled/incident_triage")
    result = workflow.run(input_data)

    # Verify
    assert result["classify_severity_1"]["prompt"].startswith("You are classifier 1")
```

---

## Migration Path

1. **v1 (Current Fix)**: Version context injected at runtime (backward compatible)
2. **v2 (Compile-First)**: Optional compile step, execution auto-compiles if not pre-compiled
3. **v3 (Compile-Required)**: All workflows must be compiled before execution

---

## Files to Modify

### Phase 1 (Completed)

| File | Change |
|------|--------|
| `agent_actions/output/response/expander.py` | ✅ Add `_version_context` compilation |
| `agent_actions/workflow/pipeline.py` | ✅ Extract version context into `loop_context` |
| `agent_actions/prompt/context/scope.py` | ✅ Add `version` namespace to field_context |
| `docs.agent-actions/docs/reference/execution/versions.md` | ✅ Update documentation |
| `tests/core/parser/test_version_context_injection.py` | ✅ Add unit tests |

### Phase 2 (Completed)

| File | Change |
|------|--------|
| `agent_actions/compile/__init__.py` | ✅ New: Module exports |
| `agent_actions/compile/compiler.py` | ✅ New: WorkflowCompiler class |
| `agent_actions/compile/artifact.py` | ✅ New: CompiledWorkflow, CompiledAgent, CompilationMetadata |
| `tests/core/compile/test_compiler.py` | ✅ New: Unit tests (24 tests) |
| `tests/core/compile/test_compiler_integration.py` | ✅ New: Integration tests (6 tests) |

Note: CLI command removed - the engine handles rendering internally. The compile module
provides the infrastructure for pre-rendering version variables before execution.

---

## Acceptance Criteria

### Phase 1 (Completed)
- [x] `{{ i }}`, `{{ idx }}` work in prompt store templates
- [x] `{{ version.length }}`, `{{ version.first }}`, `{{ version.last }}` work
- [x] Custom param names work in prompt store templates
- [x] Jinja2 conditionals work in prompt store templates
- [x] Documentation updated with `version` namespace (not `loop`)
- [x] Unit tests pass

### Phase 2 (Internal Compiler - Completed)
- [x] WorkflowCompiler class for pre-rendering version variables
- [x] Compiled configs inspectable via module API
- [x] Version variables pre-rendered at compile time
- [x] Runtime variables preserved for execution
- [x] Engine uses expanded/rendered configs internally
