# Record

Single authority for record content assembly. Every action type, granularity, and strategy converges here.

## Modules

| Name | Type | Exports | Signals |
|------|------|---------|---------|
| `envelope.py` | Module | `RecordEnvelope`, `RecordEnvelopeError` | - |
| `tracking.py` | Module | `TrackedItem` | - |
| `__init__.py` | Re-export | `RecordEnvelope`, `RecordEnvelopeError`, `TrackedItem` | - |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `RecordEnvelope.build()` | `agent_io/target/{action}/` | Writes record with action output under namespace | - |
| `RecordEnvelope.build_content()` | `agent_io/target/{action}/` | Writes content dict (no record wrapper) | - |
| `RecordEnvelope.build_skipped()` | `agent_io/target/{action}/` | Writes record with null namespace for guard skip | - |
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
- Framework metadata (`_state`, `_transitions`, `_recovery`) -- callers add these after assembly
- Enrichment (lineage, node_id, target_id) -- `EnrichmentPipeline` handles post-assembly
- Initial source structuring -- `initial_pipeline.py` creates the first `source` namespace
- Observe/passthrough resolution -- `scope_application.py` reads FROM content
