# Design Spec: `contract` Block for ActionConfig

**Status**: Draft
**Author**: Engineering
**Date**: 2026-03-29

---

## 1. Problem Statement

In agent-actions, the semantic intent behind an LLM action is fragmented across three surfaces:

| Concern | Current Location | Issue |
|---------|-----------------|-------|
| What the action should accomplish | `intent` (1-line in YAML) + `## TASK` section in prompt markdown | Goal described at two fidelity levels in two files |
| Behavioral rules | `context_scope` (YAML) + `## GUIDELINES` prose (prompt markdown) + `guard` (YAML) | Constraints split between config and prompt prose |
| Output structure | `schema/*.yml` + `## OUTPUT FORMAT` block duplicated in prompt markdown | Schema defined twice |
| What makes output wrong | `guard` (YAML, pre-execution) + `reprompt` (YAML) + negative instructions scattered in prompt prose | No single place to express "this output is unacceptable" |

There is no mechanism to define **machine-evaluable semantic rules** that are checked against LLM output. The schema validates shape (field names, types). Guards run pre-execution. But rules like "cannot recommend reject unless risk_level is high" or "reasoning must be substantive, not generic" have no home — they exist only as prompt prose the LLM may ignore.

---

## 2. Solution Overview

Add an optional `contract` block to each action in the workflow YAML. It bundles three concerns into a single, structured, machine-readable surface:

```yaml
- name: analyze_clause
  contract:
    goal: "Analyze a single contract clause for risk level, obligations, and deadlines"
    constraints:
      - "Cite at least one risk_indicator from the clause text"
      - "Identify obligated party for every obligation"
    failure_conditions:
      - id: empty_indicators
        rule: "len(risk_indicators) == 0"
        message: "Every clause must have at least one risk indicator"
        severity: error
      - id: orphan_reject
        rule: 'recommended_action == "reject" and risk_level != "high"'
        message: "Cannot recommend reject unless risk_level is high"
        severity: error
      - id: generic_reasoning
        rule: "len(reasoning) < 20"
        message: "Reasoning is too brief to be useful"
        severity: warning
```

**Design principles**:
- **Additive, not replacing** — `intent`, `schema`, `prompt`, `guard`, `reprompt` all continue to work unchanged
- **Optional** — actions without `contract` behave exactly as today
- **Machine-evaluable** — failure_conditions are expressions evaluated against LLM output, not just prose
- **Integrated with reprompt** — error-severity violations trigger targeted reprompts with specific feedback
- **Observable** — every evaluation emits structured events for tracking

---

## 3. YAML Surface

### 3.1 ContractConfig Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goal` | `string` | No | Rich description of what the action accomplishes. Richer than `intent`. Injected into prompt. |
| `constraints` | `list[string]` | No | Behavioral rules injected into the prompt as a structured section. Soft enforcement — the LLM sees them but they are not machine-evaluated. |
| `failure_conditions` | `list[FailureCondition]` | No | Machine-evaluable rules checked against LLM output post-response. Hard enforcement for error severity. |

### 3.2 FailureCondition Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `string` | Yes | — | Unique identifier within the action. Used in events, reprompt feedback, and tracking. Must be a valid identifier (alphanumeric + underscore). |
| `rule` | `string` | Yes | — | Python expression evaluated against the LLM response dict. If it evaluates to `True`, the condition is **violated**. |
| `message` | `string` | Yes | — | Human-readable explanation of the violation. Shown to the LLM during reprompt and emitted in events. |
| `severity` | `enum` | No | `error` | One of: `error`, `warning`, `info`. Controls enforcement behavior. |

### 3.3 Severity Behavior

| Severity | Injected into prompt | Triggers reprompt | Blocks output | Tracked in events |
|----------|---------------------|-------------------|---------------|-------------------|
| `error` | Yes | Yes | Yes (until resolved or attempts exhausted) | Yes |
| `warning` | Yes | No | No | Yes |
| `info` | No | No | No | Yes |

### 3.4 Full Example

```yaml
- name: analyze_clause
  dependencies: [split_into_clauses]
  contract:
    goal: "Analyze a single contract clause for risk level, obligations, and deadlines"
    constraints:
      - "Compare clause language against each risk level's indicators"
      - "Identify obligated party; categorize as: payment, delivery, reporting, compliance, notification, cooperation"
      - "Consider industry benchmarks (30-day payment terms, mutual termination rights)"
    failure_conditions:
      - id: empty_indicators
        rule: "len(risk_indicators) == 0"
        message: "Every clause must have at least one risk indicator"
        severity: error
      - id: orphan_reject
        rule: 'recommended_action == "reject" and risk_level != "high"'
        message: "Cannot recommend reject unless risk_level is high"
        severity: error
      - id: generic_reasoning
        rule: "len(reasoning) < 20"
        message: "Reasoning is too brief to be useful"
        severity: warning
      - id: score_outlier
        rule: "risk_score > 0.9 and risk_level == 'low'"
        message: "High risk_score with low risk_level may indicate inconsistency"
        severity: info
  schema: contract_reviewer/analyze_clause
  prompt: $contract_reviewer.Analyze_Clause
  model_vendor: anthropic
  model_name: claude-sonnet-4-20250514
  api_key: ANTHROPIC_API_KEY
  reprompt:
    max_attempts: 2
    on_exhausted: return_last
  context_scope:
    observe:
      - split_into_clauses.clause_number
      - split_into_clauses.clause_text
      - seed_data.risk_criteria
    passthrough:
      - split_into_clauses.clause_number
      - source.contract_id
```

---

## 4. Rule Expression Language

### 4.1 Evaluation Model

`failure_conditions[].rule` expressions are evaluated against the LLM response dict. Field names in the expression resolve to top-level keys in the response. The expression evaluates to `True` when the condition is **violated** (i.e., the output is unacceptable).

```
Response: {"risk_level": "low", "risk_indicators": [], "recommended_action": "reject", "reasoning": "Bad"}

Rule: "len(risk_indicators) == 0"    → True  (violation: indicators empty)
Rule: 'recommended_action == "reject" and risk_level != "high"'  → True  (violation: reject without high risk)
Rule: "len(reasoning) < 20"          → True  (violation: reasoning too brief)
```

### 4.2 Supported Syntax

| Category | Supported | Examples |
|----------|-----------|---------|
| Comparisons | `==`, `!=`, `<`, `>`, `<=`, `>=` | `risk_score > 0.9` |
| Boolean ops | `and`, `or`, `not` | `a == "x" and b != "y"` |
| Built-in functions | `len`, `any`, `all`, `min`, `max`, `sum`, `abs`, `str`, `int`, `float`, `bool` | `len(items) == 0` |
| Membership | `in`, `not in` | `"admin" not in roles` |
| Subscript | `response[0]`, `response["key"]` | `items[0] == "bad"` |
| Literals | strings, numbers, booleans, None, lists, tuples | `risk_level == "high"` |
| Ternary | `x if cond else y` | `len(a) if a else 0` |

### 4.3 Blocked Syntax (Security)

| Blocked | Reason |
|---------|--------|
| `import`, `__import__` | No module imports |
| `exec`, `eval`, `compile` | No dynamic code execution |
| `__` dunder access | No internal attribute access |
| `os`, `sys`, `subprocess` | No system access |
| `open`, `file`, `input` | No I/O |
| Attribute access on non-response objects | No `obj.method()` calls except allowlisted builtins |
| `lambda` | No anonymous function creation |

### 4.4 Safety Implementation

1. `ast.parse(rule, mode='eval')` — parse into AST
2. AST node whitelist walker — reject any node type not in the allowlist
3. `contains_dangerous_pattern()` check (reuses existing guard safety from `agent_actions/utils/constants.py`)
4. Restricted `eval()` with only allowlisted builtins and response dict keys as namespace
5. Rule safety validated at **config parse time** (fail fast), not at runtime

### 4.5 Missing Field Handling

If a rule references a field not present in the response dict:
- The field resolves to `None` in the evaluation namespace
- A `NameError` during evaluation is caught and treated as a rule evaluation error
- A `ContractRuleErrorEvent` (CT003) is emitted
- The condition is treated as **not triggered** (conservative: don't block on evaluation failures)

---

## 5. Runtime Flow

### 5.1 End-to-End Execution Path

```
1. YAML parse → ActionConfig with ContractConfig (Pydantic validation)
2. Expander → agent dict with "contract" key propagated
3. Prompt rendering → contract goal/constraints/failure_conditions injected after template
4. LLM call → response
5. Schema validation (existing, unchanged)
6. Contract evaluation:
   a. Evaluate ALL failure_conditions against response
   b. Fire ContractViolationEvent per triggered condition
   c. Fire ContractEvaluationEvent (summary)
   d. If any error-severity violations → return False (trigger reprompt)
7. Reprompt loop (if violations):
   a. Append specific violation feedback to prompt
   b. Re-call LLM
   c. Re-evaluate contract
   d. Repeat until pass or max_attempts exhausted
8. Output written (with or without violations depending on on_exhausted)
```

### 5.2 Validator Composition Order

The `ContractValidator` is appended to the existing `ComposedValidator` chain:

```
1. UdfValidator        (if reprompt.validation configured)
2. SchemaValidator     (if on_schema_mismatch: reprompt)
3. ContractValidator   (if contract.failure_conditions has error-severity conditions)
```

`ComposedValidator` fails on the first failing validator. This means:
- Schema shape errors are caught before contract semantic rules
- Contract rules only run if the response has the right shape
- This is the correct ordering

### 5.3 Auto-Reprompt Behavior

When a `contract` has error-severity `failure_conditions` and the user has **not** explicitly set a `reprompt:` block, the system auto-enables reprompting with defaults:
- `max_attempts: 2`
- `on_exhausted: return_last`

If the user provides an explicit `reprompt:` block, those settings take precedence.

### 5.4 Reprompt Feedback Format

When contract violations trigger a reprompt, the feedback appended to the prompt is:

```
---
Your response failed validation.

Contract violations:
1. [empty_indicators] (error): Every clause must have at least one risk indicator
   Rule: len(risk_indicators) == 0

2. [orphan_reject] (error): Cannot recommend reject unless risk_level is high
   Rule: recommended_action == "reject" and risk_level != "high"

Your response: { ... truncated JSON ... }

Please correct and respond again.
```

This is significantly more actionable than the current generic "Schema mismatch detected" feedback.

---

## 6. Prompt Injection

### 6.1 Injection Point

Contract content is injected into the `formatted_prompt` **after** Jinja2 template rendering and **before** tools injection. This ensures:
- Template variables are already resolved
- Contract text is provider-agnostic (not tied to MessageBuilder formatting)
- The reprompt loop modifies the same string

### 6.2 Injected Format

```
<rendered prompt from prompt_store>

---
CONTRACT:
Goal: Analyze a single contract clause for risk level, obligations, and deadlines

Constraints:
- Compare clause language against each risk level's indicators
- Identify obligated party; categorize as: payment, delivery, reporting, compliance, notification, cooperation
- Consider industry benchmarks (30-day payment terms, mutual termination rights)

Failure Conditions (your output MUST NOT trigger these):
- [empty_indicators] Every clause must have at least one risk indicator
- [orphan_reject] Cannot recommend reject unless risk_level is high
- [generic_reasoning] Reasoning is too brief to be useful
---
```

### 6.3 Injection Rules

- `goal` — injected if non-empty
- `constraints` — each constraint as a bullet point, injected if list is non-empty
- `failure_conditions` — only `error` and `warning` severity injected; `info` is silent
- If all sections are empty, nothing is appended

---

## 7. Event System

### 7.1 New Event Category

Add `CONTRACT = "contract"` to `EventCategories` in `agent_actions/logging/events/types.py`.

### 7.2 New Events

| Event Class | Code | Level | Category | Fired When |
|-------------|------|-------|----------|------------|
| `ContractEvaluationEvent` | CT001 | DEBUG (all pass) / WARN (any fail) | contract | After all conditions evaluated for an action |
| `ContractViolationEvent` | CT002 | Matches severity (ERROR/WARN/INFO) | contract | Per triggered condition |
| `ContractRuleErrorEvent` | CT003 | ERROR | contract | When a rule expression fails to evaluate |

### 7.3 Event Data Fields

**ContractEvaluationEvent (CT001)**:
```json
{
  "action_name": "analyze_clause",
  "total_conditions": 4,
  "error_count": 2,
  "warning_count": 1,
  "info_count": 0,
  "passed": false,
  "condition_results": [
    {"id": "empty_indicators", "triggered": true, "severity": "error"},
    {"id": "orphan_reject", "triggered": true, "severity": "error"},
    {"id": "generic_reasoning", "triggered": true, "severity": "warning"},
    {"id": "score_outlier", "triggered": false, "severity": "info"}
  ]
}
```

**ContractViolationEvent (CT002)**:
```json
{
  "action_name": "analyze_clause",
  "condition_id": "empty_indicators",
  "severity": "error",
  "rule": "len(risk_indicators) == 0",
  "violation_message": "Every clause must have at least one risk indicator"
}
```

**ContractRuleErrorEvent (CT003)**:
```json
{
  "action_name": "analyze_clause",
  "condition_id": "empty_indicators",
  "rule": "len(risk_indicators) == 0",
  "error": "NameError: 'risk_indicators' is not defined"
}
```

### 7.4 Event Destinations

Events flow through the existing `EventManager` pipeline:
- **Console**: CT001 (WARN only), CT002 (ERROR/WARN), CT003 (ERROR)
- **events.json**: All CT events at all levels
- **errors.json**: CT002 (ERROR severity) and CT003 only

---

## 8. Blast Radius Analysis

### 8.1 Modified Files

| File | Change | Risk |
|------|--------|------|
| `agent_actions/config/schema.py` | Add 3 models + 1 field on ActionConfig | Low — `contract` defaults to `None`, Pydantic `extra="forbid"` means unrecognized keys still rejected |
| `agent_actions/prompt/service.py` | 4-line insertion in 2 methods (after template rendering) | Low — guarded by `if contract:`, no change to existing flow |
| `agent_actions/processing/invocation/factory.py` | Add ContractValidator to composed chain + auto-reprompt logic | Medium — touches validator composition; existing validators unchanged |
| `agent_actions/logging/events/types.py` | Add 1 enum value | None |
| `agent_actions/logging/events/validation_events.py` | Add 3 event classes + update `__all__` | None — additive |
| `agent_actions/output/response/expander_merge.py` | Add 1 line: `agent.setdefault("contract", None)` | None |
| `agent_actions/output/response/expander.py` | Propagate contract from action to agent dict | Low |
| `tests/unit/config/test_schema_extra_forbid.py` | Add `contract` to valid keys test data | None |

### 8.2 New Files

| File | Purpose |
|------|---------|
| `agent_actions/processing/recovery/contract_evaluator.py` | Safe rule expression evaluator |
| `agent_actions/processing/recovery/contract_validator.py` | ResponseValidator implementation for contracts |
| `agent_actions/prompt/contract_injector.py` | Formats and injects contract text into prompts |

### 8.3 Unchanged Systems

| System | Why Unchanged |
|--------|---------------|
| Schema validation (`schema_output_validator.py`) | Contract is post-schema; schema validates shape, contract validates semantics |
| Guard system (`guards/`, `task_preparer.py`) | Guards are pre-execution; contract is post-response |
| Prompt loading (`prompt/handler.py`) | Prompt store files unchanged; contract injected after rendering |
| MessageBuilder (`prompt/message_builder.py`) | Contract is injected at prompt level, not message assembly level |
| LLM providers (`llm/providers/`) | No changes to any provider client |
| Storage backends (`storage/`) | No changes to output persistence |
| CLI commands (`cli/`) | No changes needed for Phase 1 |
| Batch submission (`llm/batch/`) | Phase 2 follow-up; online mode first |

### 8.4 Backward Compatibility

- Workflows without `contract` blocks: **zero impact**. All code paths guard with `if contract:`.
- `ActionConfig` extra="forbid": adding the `contract` field to the Pydantic model is required before any YAML can use it. Existing YAML without `contract` is unaffected because the field defaults to `None`.
- The existing `constraints: Any | None` field on ActionConfig (line 217 of schema.py) is a different field — it's for reprompt UDF context. No collision.

---

## 9. Relationship to Existing Features

### 9.1 contract.goal vs intent

| | `intent` | `contract.goal` |
|--|----------|-----------------|
| Required | Yes | No |
| Length | One line | Paragraph |
| Runtime use | Metadata/logging only | Injected into prompt |
| Purpose | Quick description for tooling | Full success criteria for the LLM |

Both can coexist. `intent` is the brief label. `contract.goal` is the detailed spec.

### 9.2 contract.constraints vs context_scope

| | `context_scope` | `contract.constraints` |
|--|----------------|----------------------|
| What it controls | Which fields the LLM sees | What rules the LLM should follow |
| Mechanism | Field filtering (observe/drop/passthrough) | Prompt text injection |
| Enforcement | Hard (fields physically removed/included) | Soft (LLM sees rules but may ignore them) |

They are complementary. `context_scope` controls data visibility. `contract.constraints` controls behavioral expectations.

### 9.3 contract.failure_conditions vs guard

| | `guard` | `contract.failure_conditions` |
|--|---------|-------------------------------|
| When evaluated | Pre-execution (before LLM call) | Post-response (after LLM returns) |
| Against what | Input record fields | LLM output fields |
| On failure | Skip/filter the action entirely | Reprompt or log (based on severity) |
| Purpose | "Should this action run?" | "Is this output acceptable?" |

### 9.4 contract.failure_conditions vs reprompt.validation

| | `reprompt.validation` (UDF) | `contract.failure_conditions` |
|--|----------------------------|-------------------------------|
| Definition | Python function registered via decorator | YAML expressions in config |
| Feedback | Single message per UDF | Per-condition messages |
| Severity levels | No (pass/fail) | Yes (error/warning/info) |
| Requires code | Yes (write a Python function) | No (declarative YAML) |
| Event granularity | One event per validation run | One event per condition |

Contract failure_conditions provide **declarative, per-rule validation** without writing Python. For complex validation logic that can't be expressed as simple expressions, UDF validators remain the right tool.

### 9.5 Composition

All validators compose via `ComposedValidator`:

```
ComposedValidator([
    UdfValidator,        ← from reprompt.validation (user-written Python)
    SchemaValidator,     ← from on_schema_mismatch: reprompt (shape check)
    ContractValidator,   ← from contract.failure_conditions (semantic rules)
])
```

Fails on first failure. Schema shape is checked before contract semantics.

---

## 10. Batch Mode

### 10.1 Phase 1 (Current Scope)

Online mode only. Batch mode (`run_mode: batch`) does not evaluate contracts during the batch submission phase.

### 10.2 Phase 2 (Follow-Up)

Integrate `ContractValidator` into `agent_actions/llm/batch/services/reprompt_ops.py`:
- After batch results are collected, evaluate contract failure_conditions
- Failed results enter the batch reprompt queue with contract feedback
- Same severity behavior as online mode

---

## 11. File Change Inventory

### New Files (4)

| File | Purpose | Est. Lines |
|------|---------|------------|
| `agent_actions/processing/recovery/contract_evaluator.py` | AST-safe rule expression evaluator | ~150 |
| `agent_actions/processing/recovery/contract_validator.py` | ResponseValidator implementation | ~120 |
| `agent_actions/prompt/contract_injector.py` | Prompt text injection | ~60 |
| (test files — 7 new) | Unit + integration tests | ~400 |

### Modified Files (8)

| File | Lines Changed | What Changes |
|------|--------------|--------------|
| `agent_actions/config/schema.py` | ~40 added | FailureConditionSeverity, FailureConditionConfig, ContractConfig models; contract field on ActionConfig; __all__ update |
| `agent_actions/processing/invocation/factory.py` | ~20 modified | ContractValidator in _build_validator(); auto-reprompt in _create_online_strategy() |
| `agent_actions/prompt/service.py` | ~8 added | Contract injection in _prepare_prompt_internal() and prepare_prompt_with_field_context() |
| `agent_actions/logging/events/types.py` | ~1 added | CONTRACT category |
| `agent_actions/logging/events/validation_events.py` | ~70 added | CT001, CT002, CT003 events; __all__ update |
| `agent_actions/output/response/expander_merge.py` | ~1 added | agent.setdefault("contract", None) |
| `agent_actions/output/response/expander.py` | ~5 added | Propagate contract from action to agent dict |
| `tests/unit/config/test_schema_extra_forbid.py` | ~5 modified | Add contract to valid keys test |

### Manifest Updates (2)

| File | Change |
|------|--------|
| `agent_actions/processing/recovery/_MANIFEST.md` | Add contract_evaluator.py, contract_validator.py |
| `agent_actions/prompt/_MANIFEST.md` | Add contract_injector.py |

---

## 12. Implementation Sequence

| Phase | What | Depends On | Risk |
|-------|------|-----------|------|
| 1 | Pydantic models (schema.py) | — | Low |
| 2 | Rule evaluator (contract_evaluator.py) | — | Medium (security) |
| 3 | Events (validation_events.py, types.py) | — | Low |
| 4 | ContractValidator (contract_validator.py) | Phase 2, 3 | Low |
| 5 | Prompt injection (contract_injector.py, service.py) | Phase 1 | Low |
| 6 | Factory integration (factory.py) | Phase 4 | Medium |
| 7 | Expander pipeline (expander_merge.py, expander.py) | Phase 1 | Low |
| 8 | Tests | All phases | — |
| 9 | Example update (contract_reviewer) | All phases | Low |

Phases 1, 2, 3 can be parallelized. Phase 4 requires 2+3. Phase 5 requires 1. Phase 6 requires 4. Phase 7 requires 1.

---

## 13. Test Plan

| Test File | Scope | Key Cases |
|-----------|-------|-----------|
| `tests/unit/config/test_contract_config.py` | Model validation | Required fields, severity enum, rule safety rejection, extra=forbid, duplicate condition IDs, empty contract |
| `tests/unit/processing/recovery/test_contract_evaluator.py` | Rule evaluation | Simple comparisons, len(), cross-field logic, string ops, nested access. Safety: rejects __import__, exec, os.system. Edge cases: missing fields, non-dict response |
| `tests/unit/processing/recovery/test_contract_validator.py` | Validator protocol | validate() True on pass, False on error violations, True on warning-only. feedback_message content. Composition with ComposedValidator |
| `tests/unit/prompt/test_contract_injector.py` | Prompt injection | Goal/constraints/conditions appear. Info excluded. Empty sections omitted. Formatting correct |
| `tests/unit/processing/invocation/test_factory_contract.py` | Factory composition | ContractValidator in composed chain. Auto-reprompt for error conditions. No auto-reprompt without error conditions. Composition with UDF + schema validators |
| `tests/logging/events/test_contract_events.py` | Event correctness | CT001/CT002/CT003 correct code, level, category, data fields |
| `tests/integration/test_contract_e2e.py` | Full flow | YAML with contract -> parse -> expand -> prompt includes contract -> mock LLM -> validation -> reprompt on error violation -> events emitted |

### Verification Commands

```bash
pytest tests/unit/config/test_contract_config.py -v
pytest tests/unit/processing/recovery/test_contract_evaluator.py -v
pytest tests/unit/processing/recovery/test_contract_validator.py -v
pytest tests/unit/prompt/test_contract_injector.py -v
pytest tests/unit/processing/invocation/test_factory_contract.py -v
pytest tests/logging/events/test_contract_events.py -v
pytest tests/integration/test_contract_e2e.py -v
pytest tests/unit/config/test_schema_extra_forbid.py -v  # existing test still passes
ruff check . && ruff format .
```

---

## 14. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Rule evaluation security (code injection) | Low | High | AST whitelist + restricted builtins + config-time validation + dangerous pattern check |
| Breaking existing workflows | Very Low | High | `contract` defaults to `None`; all codepaths guard with `if contract:` |
| ContractValidator ordering in ComposedValidator | Low | Medium | Appended last; schema shape validated before semantic rules |
| Auto-reprompt without explicit config surprises users | Low | Low | Default to conservative settings (max_attempts=2, on_exhausted=return_last); document behavior |
| Rule expressions too limited for complex validation | Medium | Low | UDF validators remain available for complex logic; contract rules handle the common 80% case |
| Batch mode gap during Phase 1 | Medium | Low | Document as online-only initially; batch follows in Phase 2 |

---

## 15. Open Questions

1. **Should `contract.goal` replace `intent` over time?** — Currently both coexist. Could deprecate `intent` in a future version if `contract.goal` proves sufficient.

2. **Should contract rules support field path access (e.g., `obligations[0].party`)?** — Phase 1 supports top-level field access and subscript. Deep path access (nested object fields) could be added later.

3. **Should there be a `contract` section in `defaults:`?** — Currently no, because contracts are action-specific (goal and failure_conditions reference action-specific fields). Could reconsider if users want shared constraints across all actions.

4. **CLI inspection support?** — `agac inspect action <name>` could display contract details. Not in Phase 1 scope.
