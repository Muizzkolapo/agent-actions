# Framework Contracts

The 20 rules. Non-negotiable. No fallbacks. No silent degradation.

Every violation is a loud failure — an exception with a clear message at the point of origin. We never silently return a default, swallow an error, or degrade to a "best effort" path.

---

## Rule 0: No silent fallbacks

When a contract is violated, the system raises an error. It does not:
- Return `{}` or `None` and continue
- Log a warning and use a fallback
- Catch an exception and swallow it

### Banned patterns (merge-blocking)

```python
# BANNED -- masks missing content
content = record.get("content", {})
# REQUIRED
content = record["content"]

# BANNED -- masks missing action name
action_name = agent_config.get("agent_type", "unknown")
# REQUIRED
action_name = agent_config["agent_type"]

# BANNED -- swallows namespace lookup
namespace = content.get(action_name, {})
# REQUIRED
namespace = content[action_name]

# BANNED -- flat merge (the HITL bug)
merged_content.update(decision_common)
# REQUIRED -- wrap under namespace
record = RecordEnvelope.build(action_name, decision_common, input_record)

# BANNED -- deleting a namespace
del content[namespace]
# The bus is append-only. Namespaces are never removed.
```

---

## Namespace rules

1. **Every action's output is namespaced under `content[action_name]`** — LLM, Tool, HITL all follow this. `RecordEnvelopeError` if violated. Structurally impossible via `RecordEnvelope.build()`.

2. **Every action's output includes ALL upstream namespaces** — nothing is ever dropped. The content dict only grows. `NamespaceLostError` if violated. Structurally impossible via `RecordEnvelope.build()`.

3. **Observe resolves against `content[namespace][field]`**:
   - Missing namespace → `ObserveResolutionError`
   - Missing field in existing namespace → returns `None` (exception to rule 0 — LLM schemas may be partial)
   - Wildcard on null namespace (skipped action) → empty set, no error

## Reference format rules

4. **ALL field references MUST be namespaced** — `namespace.field` in observe, passthrough, drop, guard conditions. Bare fields rejected at preflight.

5. **Preflight validates all references before execution** — namespace exists, is upstream in DAG, field in schema. Workflow does not start if invalid.

## Version rules

6. **Versioned namespace references resolve automatically** — `action.*` expands to `action_1.*`, `action_2.*`, etc.

## Guard rules

7. **`skip` produces null namespace** — `content[action_name] = None`, all upstream preserved.

8. **`filter` removes the record** — gone from pipeline.

## Version merge rules

9. **Version merge combines N records into 1** — each version's namespace coexists.

## Cross-boundary rules

10. **Cross-workflow preserves all namespaces.**

11. **FILE granularity preserves per-record namespaces.**

## Context scope rules

12. **Passthrough fields are zero-token** — merged AFTER LLM call, not before.

13. **Drop excludes from context only** — field stays on bus, hidden from current action's LLM.

## Input rules

14. **Seed data uses `seed.` prefix** — not stored in content. Config key `seed_path:`, reference `seed.name`.

## Mode rules

15. **Non-JSON mode uses `output_field`** — `ConfigurationError` if missing.

16. **Reprompt validation** — `on_exhausted: raise` fails record, `on_exhausted: return_last` accepts last attempt.

## Envelope rules

17. **One module builds all record content dicts** — `RecordEnvelope` is the single authority. CI grep gate enforced.

18. **The record is a bus, context_scope is access control** — actions receive resolved context, not raw record.

## Tool interface rules

19. **Tools receive clean business data only** — no `node_id`, `source_guid`, `content` wrapper, `lineage`, `metadata`. Framework strips all framework fields before calling the tool.

20. **FILE mode provenance is tracked automatically or declared explicitly** — `TrackedItem` for passthrough/filter (automatic), `FileUDFResult` with `source_index` for merge/expand (explicit). Plain dict in list return is an error.

---

## Violation summary

| Contract | Error | When |
|----------|-------|------|
| 0 (fallbacks) | CI grep gate | PR review |
| 1-2 (namespace) | `RecordEnvelopeError` | Build time |
| 3 (observe) | `ObserveResolutionError` | Runtime |
| 4-5 (references) | `PreflightError` | Workflow load |
| 6 (version refs) | `ObserveResolutionError` | Runtime |
| 7 (skip) | Null namespace | Runtime |
| 9 (version merge) | `VersionMergeError` | Runtime |
| 15 (output_field) | `ConfigurationError` | Workflow load |
| 17 (envelope) | CI grep gate | PR review |
| 19-20 (tool) | `ValueError` | Runtime |
