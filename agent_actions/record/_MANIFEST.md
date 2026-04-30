# Record

Single authority for record content assembly. Every action type, granularity, and strategy converges here.

## Modules

| Name | Type | Exports | Signals |
|------|------|---------|---------|
| `envelope.py` | Module | `RecordEnvelope`, `RecordEnvelopeError`, `RECORD_TRACKING_FIELDS`, `RECORD_FRAMEWORK_FIELDS`, `RECORD_STAGE_FIELDS` | - |
| `tracking.py` | Module | `TrackedItem` | - |
| `__init__.py` | Re-export | `RecordEnvelope`, `RecordEnvelopeError`, `TrackedItem` | - |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `RecordEnvelope.build()` | `agent_io/target/{action}/` | Writes record with action output under namespace; carries `source_guid`, `source`, `version_correlation_id` verbatim | - |
| `RecordEnvelope.build_content()` | `agent_io/target/{action}/` | Writes content dict (no record wrapper) | - |
| `RecordEnvelope.build_skipped()` | `agent_io/target/{action}/` | Writes record with null namespace for guard skip; preserves top-level `source` | - |
| `RecordEnvelope.admit_staging_row()` | `agent_io/staging/` | Hoists raw row fields into top-level `record["source"]`, stamps `_state=ACTIVE`, idempotent | - |
| `TrackedItem` | `tools/{workflow}/*.py` | FILE tool input: dict subclass with hidden `_source_index` provenance | - |

## Dependencies

| Direction | Module | Why |
|-----------|--------|-----|
| **Depended on by** | `utils/content.py` | `wrap_content()` delegates to `build_content()` |
| **Depended on by** | `utils/transformation/passthrough.py` | (Phase 2) record assembly after strategy |
| **Depended on by** | `workflow/pipeline_file_mode.py` | FILE mode tool + HITL assembly; TrackedItem wrapping |
| **Depended on by** | `llm/providers/tools/client.py` | TrackedItem preservation in `_strip_internal_fields` |
| **Depended on by** | `processing/record_processor.py` | (Phase 2) tombstone builder |
| **Depended on by** | `processing/exhausted_builder.py` | (Phase 2) exhausted record builder |
| **Depended on by** | `llm/batch/processing/batch_result_strategy.py` | (Phase 2) batch result assembly |
| **Depended on by** | `workflow/managers/loop.py` | (Phase 2) version correlator |

## Notes

RecordEnvelope is a stateless utility -- all methods are `@staticmethod` and return plain dicts. There is no `RecordEnvelope` instance.

### Record shape invariants (post source-hoist)

A record envelope has three field tiers:

1. **Tracking fields** (`RECORD_TRACKING_FIELDS`): `source_guid`, `source`, `version_correlation_id`. Set once at staging admission, propagated verbatim by `build()`. Identity-of-origin -- never mutated by actions.
2. **Stage fields** (`RECORD_STAGE_FIELDS`): per-stage operational state (`target_id`, `chunk_info`, `batch_id`, `batch_uuid`, `_state`, `_transitions`, `_recovery`, ...). Updated as records flow through stages.
3. **Content** (`content`): action-namespaced outputs only. `record["content"][action_name]` holds each action's output. **Never contains `source`.**

### Source namespace policy

- `record["source"]` is the canonical location for source/origin data.
- `record["content"]["source"]` is forbidden -- bus-layer reads from envelope only.
- `admit_staging_row` is the single point that hoists raw loader fields into `record["source"]`.

The module does NOT own:
- Framework metadata transitions (`_transitions`, `_recovery`) -- state machine handles these
- Enrichment (lineage, node_id, target_id) -- `EnrichmentPipeline` handles post-assembly
- Observe/passthrough resolution -- `scope_application.py` reads FROM `record["source"]` and `record["content"]`
