# Record

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

Single authority for record content assembly. Every action type, granularity, and strategy converges here.

## Modules

| Name | Type | Exports | Signals |
|------|------|---------|---------|
| `envelope.py` | Module | `RecordEnvelope`, `RecordEnvelopeError` | - |
| `tracking.py` | Module | `TrackedItem` | - |
| `state.py` | Module | `RecordState`, `PROCESSABLE_STATES`, `SETTLED_STATES`, `RESETTABLE_DOWNSTREAM_STATES`, `CASCADE_BLOCKING_STATES`, `RETRIABLE_STATES`, `is_processable`, `is_settled`, `is_retriable` | - |
| `__init__.py` | Re-export | `RecordEnvelope`, `RecordEnvelopeError`, `RecordState`, `TrackedItem` | - |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `RecordEnvelope.build()` | `agent_io/target/{action}/` | Writes record with action output under namespace | - |
| `RecordEnvelope.build_content()` | `agent_io/target/{action}/` | Writes content dict (no record wrapper) | - |
| `RecordEnvelope.build_skipped()` | `agent_io/target/{action}/` | Writes record with null namespace for guard skip | - |
| `RecordEnvelope.transition()` | `agent_io/target/{action}/` | Only sanctioned writer of `_state`, `_state_history`, `_state_schema_version` | - |
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

The module does NOT own:
- Framework metadata (`_unprocessed`, `metadata`, `_recovery`) -- callers add these after assembly
- Enrichment (lineage, node_id, target_id) -- `EnrichmentPipeline` handles post-assembly
- Initial source structuring -- `initial_pipeline.py` creates the first `source` namespace
- Observe/passthrough resolution -- `scope_application.py` reads FROM content

### transition() — legal state edges

| From | To | Allowed? |
|------|----|----------|
| `None` (new record) | any | Yes — first write |
| `ACTIVE` | any settled | Yes — normal progression |
| `PROCESSED`, `COMMITTED`, `GUARD_SKIPPED`, `GUARD_DEFERRED` | `ACTIVE` | Yes — downstream reset |
| any | same state | Yes — idempotent re-application |
| `CASCADE_SKIPPED`, `FAILED`, `EXHAUSTED` | `ACTIVE` | **No** — cascade-blocking states cannot be reset |
| settled | different settled | **No** — cross-settled writes are not valid |

History is capped at 64 entries (oldest drops on overflow). Schema version bumps when a required key is added to history entries or an existing key changes semantics.
