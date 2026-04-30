## Prompt Contract: Hoist `source` from `content` to envelope top-level

### GOAL
Refactor the agent_actions record envelope so that the user's original staging fields live at
`record["source"]` (top-level, immutable, propagated as a tracking field) instead of at
`record["content"]["source"]` (nested, ducktyped, drift-prone). After the refactor, every multi-action
pipeline can resolve `source.<field>` references from any downstream action regardless of whether
`source_relative_path` is configured. The full pytest suite passes; `ruff check .` and
`ruff format --check .` are clean. No backward compatibility shim — hard cutover on the
`phase-5-record-state-machine` branch.

### FAILURE MODES
1. **Source missing on action 2's record.** Trigger: a downstream action runs against an upstream
   record produced by `RecordEnvelope.build()` without the source field carrying through. Bad
   outcome: `field_context["source"]` is empty; templates/guards referencing `source.field` fail.
   Design must: add `"source"` to `RECORD_TRACKING_FIELDS` so `_carry_tracking_fields` propagates
   it through every `build()` / `build_skipped()` call.

2. **Admission re-hoist on a record that already has `source`.** Trigger: replay, idempotent
   re-admission, or an upstream record being re-admitted. Bad outcome: nested
   `record["source"]["source"]` shape, or framework keys clobbered. Design must: guard
   `admit_staging_row` so it only hoists when `"source"` is absent from the top level. Idempotent.

3. **Source-data table double-wrap on save.** Trigger: `_admit_staging_rows(data_chunk)` mutates
   rows in-place; `_save_source_data` later persists them. CSV/XLSX/XML paths alias
   `src_text = data_chunk` so the save list contains hoisted (envelope-shaped) rows; batch paths
   fall back to `data_chunk` rows directly. Bad outcome: source_data table records have
   `{source: {raw}, source_guid, _state}` instead of flat `{raw, source_guid}` — round-trip
   reads through `_load_source_namespace` produce nested-too-deep namespaces. Design must:
   capture `src_text` snapshots before admission for the aliased paths, and provide a
   `_to_source_table_row(row)` helper that emits the flat shape for batch paths.

4. **Bus reads source from the wrong place.** Trigger: `_load_source_namespace` keeps any
   ducktyping logic. Bad outcome: bug returns the next time the record shape evolves.
   Design must: bus reads `current_item.get("source", {})` and nothing else. No shape probe.
   Remove `source_content` parameter from `build_field_context_with_history`.

5. **`extract_existing_content` keeps synthesising `{"source": raw}`.** Trigger: first-stage
   record has no `content` key. Bad outcome: `content["source"]` reappears in every
   `RecordEnvelope.build()` output, undoing the refactor. Design must: delete the
   `is_first_stage=True` branch entirely; collapse `extract_existing_content(record)` to
   `get_existing_content(record)`.

6. **File-mode tool input loses source.** Trigger: a tool action observes `source.field`
   and `extract_tool_input` only flattens from `record["content"]`. Bad outcome: tool sees
   no source, returns wrong data. Design must: `extract_tool_input` injects
   `record["source"]` into the flattened result when `source.*` is observed (or when no
   observe is configured — the empty-observe branch flattens all namespaces, source included).

7. **Test fixtures drift.** Trigger: production tests build records with
   `{content: {source: ...}}`; after the refactor those fixtures are wrong-shaped and
   tests break in ways that hide real regressions. Design must: rewrite all enumerated
   fixtures to `{source: ..., content: {...}}`. Blast-radius report enumerates files.

8. **Stale documentation in `agent_actions/skills/agac-agent-skills/`.** Trigger: SKILL.md
   describes additive content model with `content["source"]`. Bad outcome: human readers and
   downstream agents internalise the wrong model; future PRs reintroduce the bug. Design
   must: rewrite SKILL.md, udf-reference.md, data-flow-patterns.md, workflow-patterns.md to
   reflect "source on envelope, content is action namespaces only."

9. **Batch text-chunk row breaks at admission.** Trigger: row shape is
   `{content: "<str>", batch_id, batch_uuid, source_guid, target_id}` — `content` is a
   string, not a dict, and `batch_id` / `batch_uuid` are not in `RECORD_FRAMEWORK_FIELDS`
   today. Bad outcome: admission tries to hoist `batch_id` / `batch_uuid` into
   `record["source"]`, or wraps the string `content` as raw data. Design must: add
   `"batch_id"` and `"batch_uuid"` to `RECORD_STAGE_FIELDS`; the hoist excludes them.
   Verified by a targeted test.

10. **Diagnostic blackout.** Trigger: a record loses source mid-pipeline (admission was
    skipped, tracking field was clobbered) and the bus quietly returns empty source. Bad
    outcome: silent data corruption — wrong prompt rendered, no log line. Design must:
    `_load_source_namespace` logs a `warning` when `current_item` is non-null but lacks a
    `"source"` key; `admit_staging_row` logs a `debug` with the count of hoisted fields.

### CONSTRAINTS
- **Hard cutover, no backward compat.** Justified: branch is unmerged; user opted out
  explicitly. Compatibility shim would be tech debt deleted within one release.
- **No new third-party dependencies.** Justified: refactor is data-shape only; standard
  library + existing internals suffice.
- **Logging via `logger = logging.getLogger(__name__)`, never `print()`.** Justified:
  workspace AGENTS.md mandate; mixed logging styles obscure operational signal.
- **Manifest discipline.** Every module touched has its `_MANIFEST.md` updated when the
  `## Modules`, `## Project Surface`, or `## Dependencies` table changes. Justified:
  workspace AGENTS.md mandate; manifests drive impact analysis.
- **`ruff check .` and `ruff format --check .` clean before each commit.** Justified:
  project lint policy.
- **`pytest` green before each commit.** Justified: project test policy; staff DoD says
  evidence required for "done."
- **Source-data SQLite table records remain flat (no `"source"` field at top level).**
  Justified: source-data records *are* the source. Wrapping them under a `"source"` key
  forces every reader to un-wrap and creates self-referential shapes.
- **`RECORD_TRACKING_FIELDS` is the carry mechanism — do not add a parallel one.**
  Justified: `_carry_tracking_fields` already iterates this set; reusing it is one line.
  A new explicit `build(source=...)` parameter duplicates surface area.
- **Source is set once at staging admission and never mutated by actions.** Justified:
  source is identity-of-origin, not state. Actions should not be able to overwrite it.
- **`_state` and `_transitions` semantics are out of scope.** Justified: PR review bugs
  #2-#7 are separate work; mixing them with the data-model fix bloats blast radius.

### FORMAT
**Envelope (`agent_actions/record/envelope.py`):**
- `RECORD_TRACKING_FIELDS = frozenset({"source_guid", "source", "version_correlation_id"})`.
- `RECORD_STAGE_FIELDS` adds `"batch_id"` and `"batch_uuid"`.
- `admit_staging_row(record)`:
  - If `"source"` already at top level: return without touching raw fields (idempotent).
  - Else: collect `raw = {k: v for k, v in record.items() if k not in RECORD_FRAMEWORK_FIELDS}`,
    delete those keys from the top level, set `record["source"] = raw`. Initialise
    `record.setdefault("content", {})` (no-op if content present, even as a string — the string
    case is for batch text chunks; framework field stays untouched).
  - Stamp `record["_state"] = RecordState.ACTIVE.value` if absent.
  - `logger.debug("admit_staging_row: hoisted %d field(s) into source", len(raw))`.
- `RecordEnvelope.build()` and `build_skipped()` unchanged in body — they already call
  `_carry_tracking_fields(result, input_record)` which now propagates `"source"` automatically.

**Bus simplification (`agent_actions/prompt/context/scope_builder.py`):**
- Remove `source_content` parameter from `build_field_context_with_history` signature.
- `_load_source_namespace(field_context, current_item, agent_name)` reads
  `source_namespace = current_item.get("source") if isinstance(current_item, dict) else None`.
  If non-empty dict, assign to `field_context["source"]` and fire
  `ContextNamespaceLoadedEvent`.
- Log `logger.warning("Action '%s' has current_item but no top-level 'source' field — admission may have been skipped", agent_name)` when `current_item` is a non-empty dict that lacks `"source"`.

**Scope namespace (`agent_actions/prompt/context/scope_namespace.py`):**
- `_RECORD_METADATA_KEYS` adds `"source"`.
- Delete `_enrich_source_namespace` (dead).

**Scope application (`agent_actions/prompt/context/scope_application.py`):**
- Delete `_build_source_index`.
- Delete `_resolve_source_content`.
- `apply_context_scope_for_records` reads `record.get("source", {})` directly. Drop
  `source_index` / `source_cache` machinery.
- Drop the `enriched_content["source"] = deepcopy(...)` write — source no longer goes back
  into content; consumers read it from the envelope.

**Task preparer (`agent_actions/processing/task_preparer.py`):**
- Replace `_get_source_content` body with `return item.get("source") if isinstance(item, dict) else None`.
- `prepare()`: `source_content = item.get("source", {}) if isinstance(item, dict) else {}` —
  unified for first-stage and downstream.
- `_load_full_context` no longer takes `source_content` (or accepts it for log purposes only).

**Record helpers (`agent_actions/processing/record_helpers.py`):**
- `extract_existing_content(record, *, is_first_stage=False)`: delete the `is_first_stage`
  branch (lines 195-198). Body becomes `return get_existing_content(record)`. Keep the
  `is_first_stage` parameter as deprecated-and-ignored for one PR cycle (allows PR sequencing
  without mass-renaming call sites in PR 1); remove in PR 3.

**Online LLM strategy (`agent_actions/processing/strategies/online_llm.py:391-395`):**
- Drop `is_first_stage=context.is_first_stage` from the `extract_existing_content` call.

**Passthrough (`agent_actions/utils/transformation/passthrough.py:100-104`):**
- Simplify the `if input_record is not None` branch:
  ```python
  if input_record is not None:
      envelope_input = input_record
  else:
      envelope_input = {"source_guid": source_guid, "content": existing_content or {}}
  ```
- Remove the `existing_content != input_record.get("content")` check — dead.

**File mode tool input (`agent_actions/workflow/pipeline_file_mode.py:134-175`):**
- `extract_tool_input(record, context_scope)`: when no observe is configured (current
  flatten-everything branch), include `record.get("source", {})` keys in the flattened
  business dict. When observe references `source.*` or `source.field`, inject from
  `record.get("source", {})` instead of `record["content"]["source"]`.

**Initial pipeline (`agent_actions/input/preprocessing/staging/initial_pipeline.py`):**
- For aliased paths (CSV/XLSX/XML — currently `src_text = data_chunk`), insert
  `src_text = [row.copy() if isinstance(row, dict) else row for row in data_chunk]` BEFORE
  the trailing `_admit_staging_rows(data_chunk)`. The shallow copy is sufficient because
  admission deletes top-level raw keys but does not mutate nested values.
- Add helper `_to_source_table_row(row)`:
  ```python
  def _to_source_table_row(row: dict) -> dict:
      """Return the flat source-data-table representation of a (possibly admitted) row."""
      if not isinstance(row, dict):
          return row
      if isinstance(row.get("source"), dict):
          flat = dict(row["source"])
          if "source_guid" in row and "source_guid" not in flat:
              flat["source_guid"] = row["source_guid"]
          return flat
      return {k: v for k, v in row.items() if k not in RECORD_FRAMEWORK_FIELDS or k == "source_guid"}
  ```
- Update the `_save_source_data` fallback branch: `source_items = [_to_source_table_row(row) for row in data_chunk if row.get("source_guid")]`.

**Service / context provider (`agent_actions/prompt/service.py`,
`agent_actions/input/preprocessing/field_resolution/context_provider.py`):**
- Drop the `source_content=...` keyword from `build_field_context_with_history` calls.

**Tests:**
- New file `tests/regression/test_source_namespace_hoist.py` containing five tests covering
  the success criteria.
- Update `tests/unit/record/test_tracking_field_propagation.py` for new tracking field set
  membership.
- Update `tests/unit/processing/test_record_helpers.py` — delete first-stage tests.
- Update `tests/unit/utils/test_passthrough_tracking_fields.py` — delete the obsolete test.
- Delete or strip `_enrich_source_namespace` tests in
  `tests/preprocessing/context/test_special_namespaces.py`.
- Update record-shape fixtures in the files enumerated by the blast-radius report:
  `tests/unit/workflow/test_merge_branch_records.py`,
  `tests/unit/workflow/test_merge.py`,
  `tests/unit/workflow/test_pipeline_file_mode_tool.py`,
  `tests/unit/llm/batch/test_result_processor_version_merge.py`,
  `tests/unit/record/test_envelope.py`,
  `tests/unit/llm/batch/test_batch_version_correlation_id.py`,
  `tests/unit/processing/test_unified_processor.py`.
- Sweep namespace-fixture tests for `{"content": {"source": ...}}` patterns; rewrite where
  the test's intent is record-envelope shape, leave alone where the test is asserting on
  field_context shape (which is unchanged).

**Manifests:**
- `agent_actions/record/_MANIFEST.md`: add `source` to the design notes (tracking field
  semantics).
- `agent_actions/processing/_MANIFEST.md`: update the
  `extract_existing_content` description.
- `agent_actions/prompt/context/_MANIFEST.md`: reflect deletion of three helpers.

**Skills documentation (deferred to PR 3 final commit):**
- `agent_actions/skills/agac-agent-skills/SKILL.md`: rewrite the "Data Model (Additive Bus)"
  section. Source is on the envelope; content holds action namespaces only.
- `agent_actions/skills/agac-agent-skills/references/udf-reference.md`: rewrite the
  "FRAMEWORK BUILDS" diagram.
- `agent_actions/skills/agac-agent-skills/references/data-flow-patterns.md`: rewrite the
  file-mode example.
- Other references (`workflow-patterns.md`, `context-scope-guide.md`,
  `aggregation-patterns.md`, `action-anatomy.md`, `yaml-schema.md`): verify
  syntax-level descriptions still hold; touch only if needed.

### DELIVERY
- **Commit 1 — Envelope foundation.** Risk level: low (no consumers depend on the new
  field yet; admission becomes a no-op for already-shaped rows).
  - `agent_actions/record/envelope.py`: tracking-field add, stage-field extension,
    admission hoist.
  - `agent_actions/input/preprocessing/staging/initial_pipeline.py`: pre-admission
    snapshots + `_to_source_table_row`.
  - `tests/unit/record/test_envelope.py` updates + new admission tests.
  - `tests/unit/record/test_tracking_field_propagation.py` updates.
  - `agent_actions/record/_MANIFEST.md` updates.
  - **Verify before commit:** `pytest tests/unit/record/ tests/unit/input/`,
    `ruff check agent_actions/record/ agent_actions/input/`,
    `ruff format --check agent_actions/record/ agent_actions/input/`.

- **Commit 2 — Bus reads from envelope.** Risk level: medium (this is where the bug
  closes; a regression test must lock the fix in place).
  - `agent_actions/prompt/context/scope_builder.py`: remove `source_content` parameter;
    read `current_item["source"]`.
  - `agent_actions/prompt/context/scope_namespace.py`: delete `_enrich_source_namespace`;
    `_RECORD_METADATA_KEYS` adds `"source"`.
  - `agent_actions/prompt/context/scope_application.py`: delete
    `_build_source_index` and `_resolve_source_content`.
  - `agent_actions/processing/task_preparer.py`: simplify `_get_source_content`.
  - `agent_actions/prompt/service.py` and
    `agent_actions/input/preprocessing/field_resolution/context_provider.py`: drop
    `source_content` kwarg.
  - `tests/regression/test_source_namespace_hoist.py`: new file with five regression
    tests (one per success criterion).
  - `agent_actions/prompt/context/_MANIFEST.md` updates.
  - **Verify before commit:** `pytest tests/regression/ tests/unit/prompt/ tests/unit/processing/`,
    full `pytest`, `ruff check .`, `ruff format --check .`.

- **Commit 3 — Cleanup, fixtures, docs.** Risk level: low (refactor + test/doc updates).
  - `agent_actions/processing/record_helpers.py`: delete `is_first_stage` branch;
    drop the parameter.
  - `agent_actions/processing/strategies/online_llm.py:391-395`: drop the kwarg.
  - `agent_actions/utils/transformation/passthrough.py`: simplify branch.
  - `agent_actions/workflow/pipeline_file_mode.py`: `extract_tool_input` reads
    `record["source"]`.
  - `tests/unit/processing/test_record_helpers.py`: delete first-stage tests.
  - `tests/unit/utils/test_passthrough_tracking_fields.py`: delete obsolete test.
  - `tests/preprocessing/context/test_special_namespaces.py`: delete enrich-source tests.
  - All record-shape fixture files from blast-radius enumeration.
  - `agent_actions/skills/agac-agent-skills/SKILL.md` and three references files.
  - `agent_actions/processing/_MANIFEST.md` updates.
  - **Verify before commit:** full `pytest` green, `ruff check .` clean,
    `ruff format --check .` clean.

### FAILURE CONDITIONS
**Design anti-patterns:**
- Source is read from `record["content"]["source"]` anywhere in production code after the
  refactor. (The conflation must die.)
- A boolean / heuristic / shape-probe is reintroduced in `_load_source_namespace` to
  decide whether to unwrap. (The bus must be shape-blind: one location, no branching.)
- `_resolve_source_content`, `_build_source_index`, or `_enrich_source_namespace` is
  preserved as "dead but kept for backward compat." (User opted out of compat;
  preserved-dead-code misleads maintainers into thinking it's load-bearing.)
- `extract_existing_content` keeps its `is_first_stage` branch behind a flag or comment
  saying "may need this later." (The synthesis is the bug; deleting it is the fix.)
- Admission is made non-destructive to "preserve the source-data save path" — anything
  more invasive than pre-admission snapshots is over-engineering.
- A backward-compat shim that reads `record["content"]["source"]` if `record["source"]`
  is empty. (Hard cutover.)
- Tests are weakened (asserts deleted/loosened) instead of fixed when fixtures are
  rewritten.
- Skills/docs left untouched while production code changes — the next AI agent reading
  them will reintroduce the old shape.

**Output defects:**
- Build / typecheck / lint produces errors at any commit.
- `pytest` is not green at any commit.
- A `_MANIFEST.md` is out of sync with its module after Commit 3.
- New code uses `print()` instead of `logger`.
- Any new third-party dependency added.
- A test fixture file is mass-edited with `sed` / find-replace rather than read and
  understood (per the workspace rules: use `StrReplace`, `EditNotebook`, etc.).

### Assumptions I Made
- The `phase-5-record-state-machine` branch is the canonical work line; no merge to a
  release branch is imminent.
- The DB at `agent_io/store/` (none currently exists in this clone) is disposable —
  no production data to preserve.
- `version_correlation_id` semantics are unchanged (it's already a tracking field).
- Existing manifests are accurate as of HEAD; if a manifest is already stale relative to
  its module, this PR does not retroactively fix it (out of scope; file as follow-up).
- `extract_tool_input` needs to inject source for both observe-driven and no-observe
  branches to preserve current tool-API behavior. (Decision 6.)
- The user is not testing on Windows — pre-admission shallow-copy of dict rows is a
  pure-Python operation, no path-handling concerns.
