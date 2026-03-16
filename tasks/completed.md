# Completed Tasks

All tasks below are done and merged.

---

## Initial Audit Fixes (PRs #1038–#1060)

- [x] CLI correctness bugs and code duplication (#1038)
- [x] Config module hardening: deadlock, validators, path safety, dead code (#1039)
- [x] Config module tech debt (5 items) (#1040)
- [x] Errors module: fix mutation, naming, duplication (#1041)
- [x] Input module: broken contracts, bugs, dead code (#1042)
- [x] LLM module correctness bugs and maintainability debt (#1043)
- [x] Logging module: 5 correctness bugs, dead LSP shim (#1044)
- [x] Output module: 3 correctness bugs, 2 cleanup items (#1045)
- [x] Decompose ActionExpander god object into focused modules (#1048)
- [x] Replace pre-validator with Pydantic extra=forbid (#1049)
- [x] Fix expander not propagating runtime fields (#1051)
- [x] Processing module: correctness bugs and code smells (#1052)
- [x] Prompt module: correctness bugs and code smells (#1053)
- [x] Skills module: sync metadata keys, correct doc errors (#1054)
- [x] Storage module: correctness bugs and security hardening (#1055)
- [x] Tooling module: correctness bugs and connection leak (#1056)
- [x] Utils module: correctness bugs and code smells (#1057)
- [x] Validation module: correctness bugs and code smells (#1058)
- [x] Workflow module: thread-safety bug and code smells (#1059)
- [x] PEP 257 docstring and comment cleanup across all modules (#1060)

---

## Phase 1 — Quality Gates

#### 1. Add mypy gate to CI (#1061)
- **Source:** task1 P2, task7 P2, task10 P2
- **Fix:** Added `task mypy` step to CI. Suppressed 10 noisy modules with `ignore_errors = true`. Fixed 43 errors in 5 enforced modules.

#### 10. Expand Ruff rule coverage (#1062)
- **Source:** task1 P2, task10 P2
- **Fix:** Enabled `F` (pyflakes), `B` (bugbear), `UP` (pyupgrade) rule sets in CI.

#### 12. Fix ~160 pre-existing test failures (#933)
- **Source:** Observed during audit baseline
- **Fix:** Triaged and fixed broken imports and stale tests. `pytest` passes with 0 failures on `main`.

---

## Phase 1 — Architecture / Structural Debt

#### 2. Fix `cwd`/`chdir` process-global state coupling
- **Source:** task1 P1, task3 P1, task4 P1, task5 P1
- **Fix:** Threaded explicit `project_root: Path` through call chain. Removed `os.chdir()` decorator.

#### 3. Break the 14-package circular dependency SCC (#1065)
- **Source:** task7 P1, task8 P1, task10 P1
- **Fix:** Extracted shared types into leaf packages. Inverted key dependencies. Removed lazy-import hacks.

#### 4. Decompose `workflow/coordinator.py` god module (#1070)
- **Source:** task7 P2, task8 P2, task10 P2
- **Fix:** Extracted batch lifecycle, manifest management, skip/resume logic, child workflow dispatch into focused modules.

#### 5. Relocate `llm/realtime/config.py` application-assembly logic (#1066)
- **Source:** task7 P2, task8 P2, task10 P2
- **Fix:** Moved assembly logic to dedicated orchestration module.

#### 6. Decompose remaining god modules (#1071)
- **Source:** task1 P2, task7 P2
- **Fix:** Split `logging/events/types.py` (2,662 lines) and `prompt/context/scope.py` (1,994 lines) by domain.

---

## Phase 1 — Maintainability / Developer Experience

#### 7. Reduce cross-cutting hub fan-in
- **Source:** task7 P2, task10 P2
- **Fix:** Remaining hubs are well-designed standard Python patterns. Removed deprecated `AgentActionsException` alias (migrated 15 files).

#### 8. Enforce `click.echo` / `logger` output policy in CLI (#1073)
- **Source:** task1 P3, task7 P3
- **Fix:** Added Ruff rule to ban bare `print()` in `agent_actions/`. Converted remaining calls.

#### 9. Replace global `sys.path` mutation in UDF module loading (#1064)
- **Source:** task7 P3, task1 P1
- **Fix:** Replaced with `importlib.util.spec_from_file_location()` / `module_from_spec()` pattern.

#### 11. Improve test coverage for orchestration paths (#1074)
- **Source:** task5 P2
- **Fix:** Added integration tests for coordinator, skip/resume, child workflow dispatch, batch error handling. Orchestration modules ≥80%.

---

## Phase 1 — Polish

#### 13. Fix README `agac validate` command reference (#1075)
- **Source:** task1 P0
- **Fix:** Updated README to reference correct CLI invocation.

#### 15. SQLite backend: allow spaces in filenames (#1077)
- **Source:** task11 (todo.md)
- **Fix:** Relaxed path validation to allow spaces and other filesystem-legal characters.

---

## Phase 2 — P0 Runtime Defects (Forensic Audit)

#### 16. Fix `find_project_root` NameError in `path_utils` (#1096)
- **Source:** Audit PRs #1092, #1093
- **Fix:** Fixed undefined name reference in `find_project_root`. Added regression test.

#### 17. Fix executor false-success on storage exceptions (#1097)
- **Source:** Audit PRs #1085, #1090
- **Fix:** Replaced false-success return with reset-to-pending pattern. Storage exceptions now cause re-execution instead of silent success.

#### 18. Fix async token-usage contamination under concurrent tasks (#1098)
- **Source:** Audit PR #1091
- **Fix:** Replaced `threading.local()` with `contextvars.ContextVar` so each asyncio task gets isolated token counters.

#### 19. Fix stale project-root cache in PathManager singleton (#1099)
- **Source:** Audit PRs #1090, #1095
- **Fix:** Track CWD at cache-time, invalidate when CWD changes. Explicitly-provided roots are pinned. Reordered `get_standard_path()` to check root before path cache.

#### 20. Fix path-depth assumption IndexError on shallow paths (#1100)
- **Source:** Audit PR #1088
- **Fix:** Added bounds checks before `.parents[1]` in `service_init.py` and `.parents[2]` in `coordinator.py`. Shallow paths raise clear `ValueError` with expected format hint.

---

## Phase 3 — P1 Safety / Type System

#### 21. Remove remaining mypy `ignore_errors` overrides (#1101–#1108)
- **Source:** Audit PRs #1078, #1081, #1084, #1085, #1087, #1089, #1090
- **Fix:** Incrementally removed `ignore_errors` overrides across all 8 packages, fixing type errors as they surfaced.

#### 22. Add thread-safety locks to singleton initialization (#1109)
- **Source:** Audit PR #1084
- **Fix:** Added `threading.Lock` guards to singleton initialization in `guard_filter` and `get_path_manager()`.

#### 23. Narrow silent exception swallowing in config/docs scanning (#1110)
- **Source:** Audit PRs #1078, #1087
- **Fix:** Bound `as e` and added `logger.debug()`/`logger.warning()` to 12 silent `except: pass` blocks across 4 files.

#### 24. Fix provider-validation drift (#1111)
- **Source:** Audit PRs #1082, #1083, #1090
- **Fix:** Synced preflight vendor validator allowlist with runtime client registry. Added `cohere` and `hitl` providers. Added parity test.

---

## Phase 4 — P2 Architecture / Structural Debt

#### 25. Refactor global singleton state to scoped instances — Phase 1 (#1113)
- **Source:** Audit PRs #1078, #1081, #1084, #1085, #1087, #1095
- **Fix:** Added `set_path_manager()` DI setter, CLI wiring in `RunCommand.execute()`, global autouse fixture resetting all three singletons. Follow-up phases: EventManager/LoggerFactory scoped DI.

#### 26. Migrate deprecated dependencies: google-generativeai → google-genai, PyPDF2 → pypdf (#1112)
- **Source:** Audit PRs #1078, #1084, #1085
- **Fix:** Rewrote realtime Gemini client from module-level `genai.configure()` + `GenerativeModel` to client-based `genai.Client().models.generate_content()` API. Switched error mapping to status-code-based. Replaced `PyPDF2` with `pypdf` (drop-in). Removed deprecated packages from `pyproject.toml`.

#### 27. Improve test coverage for remaining low-coverage modules (#1114–#1116)
- **Source:** Audit PRs #1078, #1087
- **Fix:** Added focused unit/integration tests for `artifacts.py` (98%), `validate_udfs.py` (95%), `dependency.py` (100%), `runner.py` (99%).

#### 28. Decompose remaining large modules (#1118–#1122)
- **Source:** Audit PRs #1078, #1081, #1087
- **Fix:** Decomposed 5 large modules: `scanner.py` → scanner/ package (#1118), `retry.py` → retry.py + retry_legacy.py (#1119), `processing.py` → processing.py + processing_recovery.py (#1120), `pipeline.py` → pipeline.py + pipeline_file_mode.py (#1121), `runner.py` → runner.py + runner_file_processing.py (#1122). All modules now under ~500 LOC.

#### 29. Reduce remaining hub coupling (investigated — no changes needed)
- **Source:** Audit PRs #1087, #1095
- **Fix:** Investigated all 4 flagged hubs (`utils/constants.py` 41 importers, `storage/backend.py` 33, `processing/types.py` 34, `config/types.py` 15). All are appropriately designed — leaf modules defining symbols in-place, textbook interface hubs, or cohesive type families. No problematic re-exports or flat-coupling patterns found. Only minor finding: `config/schema.py` re-exports `Granularity` for backward compat (1 real consumer + 3 doc examples) — harmless.

#### 30. Consolidate duplicated root discovery logic (#1124)
- **Source:** Audit PR #1092
- **Fix:** Consolidated to a single authoritative `find_project_root` in `utils/project_root.py`. Updated all call sites.

---

## Phase 5 — P3 Polish

#### 14. LSP indexer: support multi-project workspaces (already implemented — no code changes)
- **Source:** task11 (todo.md)
- **Fix:** Investigation confirmed multi-project workspace support is already fully implemented. `find_all_project_roots()` discovers all projects, `server.project_indexes: dict[Path, ProjectIndex]` stores per-project indexes, `_index_for_file()` routes files with deepest-match-wins semantics, and `did_save()` handles dynamic project registration. 8 tests verify: two-project discovery, nested projects, deepest-wins routing, disjoint routing, outside-project returns None, per-project rebuild, new project registration, and same-action cross-project resolution. Original todo description was stale.

#### 35. Guard remaining unguarded `.parent` chains on user-provided paths (#1125)
- **Source:** PR #1100 review — broader finding
- **Fix:** Extracted shared `derive_workflow_root()` into `utils/path_utils.py` with 3-tier safe strategy (agent_io fast-path → agent_config walk-up → safe fallback with warning). Updated `initial_pipeline.py` and `batch_source_handler.py` to delegate. Added `agent_config` ancestor walk-up guard in `resolver.py` (supports nested subdirs like `agent_config/versions/`). 13 regression tests.

#### 37. Add test for source_guid=None through RecordProcessor.process() pipeline
- **Source:** PR #1103 review
- **Fix:** Added 3 regression tests in `tests/processing/test_source_guid_none_coercion.py` covering the `source_guid=None` → `or ""` coercion path: (1) all events (`RecordProcessingStartedEvent`, `RecordTransformedEvent`, `RecordProcessingCompleteEvent`) receive `source_guid=""`, (2) `_transform_response` receives `""` as the source_guid argument, (3) `ProcessingResult.source_guid` stays `None` (not coerced).

#### 31. Type `run_mode` as `RunMode` enum (#1127)
- **Source:** Audit PR #1078
- **Fix:** Added `RunMode(str, Enum)` in `config/types.py` with case-insensitive `_missing_()` (matching existing `Granularity` pattern). Updated all Pydantic model fields (`schema.py`, `config_schema.py`), defaults (`config_fields.py`, `manager.py`, `renderer.py`), comparisons (`expander_action_types.py`, `initial_pipeline.py`, `pipeline.py`, `vendor_compatibility_validator.py`), and boundary coercion sites. Unified vocabulary: replaced all `"realtime"` references with `"online"` across source and tests (`prompt/service.py`, `prompt/context/builder.py`, `processing/task_preparer.py`, `output/response/loader.py`). Renamed functions: `build_llm_context_for_realtime` → `build_llm_context_for_online`, `_prepare_realtime_data` → `_prepare_online_data`, `_process_realtime_mode_with_record_processor` → `_process_online_mode_with_record_processor`. Added 9 regression tests for enum coercion.
