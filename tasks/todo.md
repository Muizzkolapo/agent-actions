# 593 — schema-echo reject invariant on every persistence seam

## Goal / acceptance
No record whose action namespace is the compiled output schema (`is_schema_echo`,
title-present) may persist as `success`. Close the two remaining seams:
1. **Checkpoint seam** — `save_checkpoint_records` (`sqlite_backend.py`) is ungated.
2. **Online no-LLM seam** — a `ProcessingResult` carrying a schema-echo namespace
   that reaches the online result→checkpoint funnel must become `_parse_error`/FAILED,
   never `success`.

556 already covers `write_target`→`target_data`; `_reject_schema_echo_items` covers
the executed-LLM response. These two are additive, symmetric.

## Verified facts (verify-first)
- `is_schema_echo` = type:object + properties dict + `title` present (`utils/schema_echo.py`).
- `compile_unified_schema({fields}, "ollama_cloud")` → real title-present echo shape ✅ (ran it).
- **Checkpoint/result records are content-nested** (`{source_guid, content:{action:val}}`),
  NOT top-level as the spec's RED sketches show — `transform_with_passthrough`→
  `RecordEnvelope.build`, and `disposition_gate` uses checkpoint & read_target records
  interchangeably. → gates read `record["content"][action]`. **Deviation from spec, reported.**
- `save_checkpoint_records` only non-test caller is online `_checkpoint_record`.
- No current no-LLM branch produces schema-echo data → RED-2 is a defensive seam test
  (matches spec framing: deterministic, no live repro).

## Plan
- [x] Verify symbols/paths/shape against real code
- [ ] Cycle 1 (checkpoint seam): RED test → Fix 1 → green → commit
  - Fix 1: rename base `_gate_schema_echo_deltas`→`_gate_schema_echo_records` (content-nested,
    shape-generic), call it from `save_checkpoint_records`.
- [ ] Cycle 2 (online seam): RED test → Fix 2 → green → commit
  - Fix 2: `_reject_schema_echo_in_result(result, action_name)` in `online_llm.invoke`
    after `process_record`, before checkpoint/collection; flips to FAILED + `_parse_error`.
- [ ] risk.sh → review → smoke → PR

## Verify
- gate.sh red/green both cycles; 556 gate tests + executed-LLM guard tests stay green.
- Full pytest + ruff + mypy.
