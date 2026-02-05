# Code Simplification Audit: llm

**Audited path:** `agent_actions/llm/`
**Date:** 2026-02-05
**Modules reviewed:** 71 Python files (~13,638 lines)

## Executive Summary

The `llm` directory is the largest sub-package in the project, spanning four sub-modules (batch, config, providers, realtime) with 71 files totaling ~13,638 lines. The most impactful simplification opportunity is the **massive duplication across the 7 provider client modules** -- identical error-wrapping functions, retry-after extraction, usage tracking, and event firing patterns are copy-pasted into each provider with only the vendor name changed. The second highest-impact finding is the **1,221-line `BatchProcessingService`** in `batch/services/processing.py` which contains multiple 100-300 line methods that should be decomposed. There are also several bugs (a `@staticmethod` referencing `self`, an early `return` inside a `for` loop, a misleading log message), deprecated-but-retained code, and a 843-line test utility (`fake_data.py`) living in production source. Estimated total effort: 2-3 weeks for a thorough cleanup, with the P1 items achievable in 3-5 days.

---

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

**1. Duplicated `_wrap_<vendor>_error()` functions across 7 provider clients**
- **Files:** `providers/openai/client.py:56`, `providers/anthropic/client.py:55`, `providers/gemini/client.py:39`, `providers/cohere/client.py:39`, `providers/groq/client.py:41`, `providers/mistral/client.py:39`, `providers/ollama/client.py:39`
- **What:** Each provider defines its own `_wrap_<vendor>_error(e, model_name, request_id)` function with identical logic: inspect exception type, wrap into `RateLimitError`, `NetworkError`, or `VendorAPIError`. The only difference is the vendor name string.
- **Why:** ~40-60 lines duplicated 7 times (~350 lines total). A single `wrap_vendor_error(e, vendor, model_name, request_id)` function in `client_base.py` or a new shared module would eliminate this.
- **Risk:** Low. All functions have the same signature and semantics.

**2. Duplicated `_extract_retry_after()` in OpenAI and Anthropic clients**
- **Files:** `providers/openai/client.py:36`, `providers/anthropic/client.py:35`
- **What:** Identical function (~15 lines) extracting `retry-after` header from exceptions. Both check `response.headers` with the same fallback logic.
- **Why:** Direct copy-paste. Should be a shared utility in `client_base.py`.
- **Risk:** Low.

**3. `batch/services/processing.py` is 1,221 lines -- far too large**
- **File:** `batch/services/processing.py`
- **What:** `BatchProcessingService` contains `_validate_and_reprompt()` (~300 lines, line 622-920), `_retrieve_results_with_retry()` (~160 lines, line 544-700), and `_process_batch_results()` (~120 lines). Many of these methods have 4+ levels of nesting and high cyclomatic complexity.
- **Why:** Violates single-responsibility. The class handles retrieval, validation, reprompting, result processing, and side-output management. Each of these could be extracted into focused helper classes or functions.
- **Risk:** Moderate. This file has many downstream test dependencies. Decomposition should preserve the public API.

**4. Duplicated `_retrieve_results()` between processing.py and retrieval.py**
- **Files:** `batch/services/processing.py:503`, `batch/services/retrieval.py:136`
- **What:** Both files define `_retrieve_results()` methods with nearly identical logic: resolve client, call `client.retrieve_results()`, write results to file. `processing.py` also has `_retrieve_results_with_retry()` that wraps it.
- **Why:** The retrieval logic should live in one place (likely `retrieval.py`), and `processing.py` should delegate to it.
- **Risk:** Low-moderate. Need to verify that both methods have converged to the same behavior.

**5. Bug: `handlers.py` -- `agent_exists()` references `self` in a `@staticmethod`**
- **File:** `realtime/handlers.py:114`
- **What:** `agent_exists` is decorated with `@staticmethod` but the body calls `self.get_agent_paths(agent_name)`. This will raise `NameError` at runtime.
- **Why:** This is a bug, not just a style issue. Either remove `@staticmethod` or replace `self` with `AgentManager`.
- **Risk:** Low fix, but important for correctness.

**6. Bug: `batch_base.py` -- `retrieve_results()` returns inside for-loop**
- **File:** `providers/batch_base.py:318`
- **What:** In `retrieve_results()`, the `return batch_results` statement appears to be inside the `for line in lines:` loop when no `output_directory` is provided, causing only the first line of results to be processed.
- **Why:** Only the first result line would ever be returned, silently dropping all remaining results. This is a data-loss bug.
- **Risk:** Low fix, critical correctness issue.

---

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

**7. `batch_client_factory.py` uses repetitive if/elif chain instead of a registry**
- **File:** `providers/batch_client_factory.py`
- **What:** A long if/elif chain (~180 lines) maps vendor strings to batch client classes. Each branch has an identical `try/except ImportError` pattern raising `DependencyError`.
- **Why:** Could be replaced with a `BATCH_CLIENT_REGISTRY` dict similar to the `CLIENT_REGISTRY` in `realtime/services/invocation.py`, reducing the file to ~40-50 lines. The `DependencyError` handling could be centralized in each client's `__init__`.
- **Risk:** Low. The existing pattern in `invocation.py` proves the registry approach works.

**8. `providers/agac/fake_data.py` is 843 lines of test utility in production source**
- **File:** `providers/agac/fake_data.py`
- **What:** `FakeDataGenerator` with large word pools, schema-based fake response generation, and ~500 lines of word constants. Used only by `AgacClient` and `AgacBatchClient` for simulated/mock responses.
- **Why:** Test utilities should live under `tests/` or a dedicated test fixtures directory, not in production code. The word pool arrays alone are ~400 lines.
- **Risk:** Moderate. `AgacClient` and `AgacBatchClient` import from it at runtime. Would need a structural change to move to test fixtures.

**9. `realtime/config.py` (`ConfigManager`) is misplaced -- not LLM-specific**
- **File:** `realtime/config.py` (415 lines)
- **What:** `ConfigManager` handles workflow config loading, agent config merging, execution order determination, environment config loading, and pipeline config creation. It imports from `agent_actions.workflow`, `agent_actions.config`, `agent_actions.validation`, `agent_actions.output.response`, and `agent_actions.input.context` -- none of which are LLM-specific.
- **Why:** This class orchestrates workflow-level configuration, not LLM invocation. It belongs in `agent_actions.config` or `agent_actions.workflow`. Its current location creates a misleading dependency: `agent_actions.workflow.coordinator` imports from `agent_actions.llm.realtime.config`, creating a circular-feeling coupling.
- **Risk:** Moderate. 4 external modules import it (`workflow/coordinator.py`, `validation/validate_udfs.py`, `validation/startup_validator.py`, `validation/startup.py`).

**10. Duplicated error-handling boilerplate across provider clients**
- **Files:** All 7 provider `client.py` files
- **What:** Each provider's `invoke()` method follows the exact same pattern: (1) extract model_name from config, (2) create message array, (3) call API in try/except, (4) wrap error with `_wrap_<vendor>_error`, (5) fire `LLMRequestEvent`/`LLMResponseEvent`, (6) extract usage and call `set_last_usage()`, (7) fire `LLMJSONParseErrorEvent` on parse failure. This pattern is ~100-150 lines repeated 7 times.
- **Why:** A template method pattern (already used in `BaseBatchClient`) could eliminate this duplication. The `BaseClient` ABC already exists but doesn't provide enough shared implementation.
- **Risk:** Moderate. Each provider has slight variations in message formatting that need careful handling.

**11. `print()` used instead of `logger` in batch client implementations**
- **Files:** `providers/batch_base.py:553,587,682`, `providers/openai/batch_client.py:99-100`, `providers/anthropic/batch_client.py:287,301-302`, `providers/gemini/batch_client.py:148,154,159,164,218-219`, `providers/groq/batch_client.py:134-135`, `providers/mistral/batch_client.py:134-135`
- **What:** 18+ `print()` calls in production code that should use the module logger. These bypass log configuration, filtering, and formatting.
- **Why:** Inconsistent with the rest of the codebase which uses `logging.getLogger(__name__)`.
- **Risk:** Low.

**12. Deprecated methods retained without migration path enforcement**
- **Files:** `realtime/services/prompt_service.py:11-42` (`prepare_prompt`), `realtime/services/context.py:19-93` (`build_field_context`), `providers/batch_base.py:446` (`compile_schema`)
- **What:** These methods are marked as deprecated with `warnings.warn()` but remain in the codebase with no indication of when they will be removed. `PromptService.prepare_prompt` and `ContextService.build_field_context` both direct users to `PromptPreparationService` but are still called from tests.
- **Why:** Deprecated code increases maintenance burden and confuses new contributors. Should either be removed (if no callers remain) or given a concrete removal timeline.
- **Risk:** Low-moderate. Need to verify no production code paths still call them.

**13. `SchemaService` is a trivial pass-through wrapper**
- **File:** `realtime/services/schema_service.py` (35 lines)
- **What:** `SchemaService.prepare_schema()` is a `@staticmethod` that simply calls `prepare_schema_unified()` with the exact same arguments. No additional logic, validation, or transformation.
- **Why:** Adds a layer of indirection without value. Callers could import `prepare_schema_unified` directly.
- **Risk:** Low. Only called from `realtime/builder.py`.

**14. `batch/infrastructure/batch_source_handler.py` has dead code**
- **File:** `batch/infrastructure/batch_source_handler.py:46-61`
- **What:** Lines 46-53 compute `workflow_root` by traversing parent directories looking for `agent_config/`. Then lines 55-61 immediately override `workflow_root` with a simpler `Path.cwd()` approach, making the traversal logic dead code.
- **Why:** The traversal logic is never used. It appears to be leftover from a previous implementation.
- **Risk:** Low.

**15. `batch/infrastructure/batch_client_resolver.py` has redundant validation**
- **File:** `batch/infrastructure/batch_client_resolver.py:61-88`
- **What:** The `resolve()` method checks `model_vendor` validity twice -- once at the beginning for a quick error, and again when calling `BatchClientFactory.create()` which performs its own validation.
- **Why:** Redundant validation adds complexity without benefit.
- **Risk:** Low.

---

### P3 -- Low Impact (Nice-to-have, minor cleanups)

**16. Duplicate `from pathlib import Path` in `handlers.py`**
- **File:** `realtime/handlers.py:5,9`
- **What:** `Path` is imported twice on lines 5 and 9.
- **Why:** Lint issue. One import should be removed.
- **Risk:** None.

**17. Bug: `cleaner.py` logs misleading message at INFO level**
- **File:** `realtime/cleaner.py:37`
- **What:** `logger.info("Unexpected error while cleaning directories%s", self.agent)` is executed at the start of `_run()`, not during an error. The log message text is misleading ("Unexpected error") and the log level should be DEBUG if kept at all.
- **Why:** This was likely a debugging artifact that was never cleaned up. It will confuse operators reading logs.
- **Risk:** None.

**18. `ollama/failure_injection.py` duplicates pattern from top-level `failure_injection.py`**
- **Files:** `providers/failure_injection.py`, `providers/ollama/failure_injection.py`
- **What:** Two separate failure injection modules with overlapping purpose. The top-level one (`providers/failure_injection.py`) is a general-purpose `FailureInjector` class, while the Ollama-specific one uses module-level functions with module-level state.
- **Why:** Could potentially be consolidated, though they serve slightly different use cases (environment-variable-based vs. programmatic).
- **Risk:** Low.

**19. `BatchJobEntry.status` is `str` instead of `BatchStatus` enum**
- **File:** `batch/core/batch_models.py`
- **What:** The `BatchJobEntry` dataclass defines `status: str` despite `BatchStatus` enum being available and used extensively throughout the codebase.
- **Why:** Type safety lost. Using `str` instead of `BatchStatus` means invalid status values can be assigned without error.
- **Risk:** Low. Would be a non-breaking improvement.

**20. GroqClient uses inline JSON parsing instead of `JSONResponseMixin`**
- **File:** `providers/groq/client.py`
- **What:** `GroqClient` has its own inline JSON parsing logic (~30 lines) instead of using `JSONResponseMixin` which is used by `GeminiClient`, `CohereClient`, and `MistralClient`.
- **Why:** Inconsistency. The mixin exists precisely for this purpose.
- **Risk:** Low.

**21. `batch/infrastructure/registry.py` manually reconstructs `BatchJobEntry`**
- **File:** `batch/infrastructure/registry.py` (in `update_status`)
- **What:** `update_status()` manually constructs a new `BatchJobEntry` dict instead of using `dataclasses.replace()` or similar pattern.
- **Why:** More error-prone than using the dataclass API.
- **Risk:** Low.

**22. `DuplicateAgentError` is defined but never raised**
- **File:** `realtime/config.py:412-415`
- **What:** `DuplicateAgentError(Exception)` is defined at the bottom of the file but is never imported or raised anywhere in the codebase.
- **Why:** Dead code.
- **Risk:** None.

**23. `realtime/config.py` -- `load_configs()` has duplicated try/except blocks**
- **File:** `realtime/config.py:42-109`
- **What:** The user config loading (lines 44-74) and default config loading (lines 79-109) have nearly identical try/except structures with three exception handlers each (`TemplateRenderingError|ConfigurationError`, `yaml.YAMLError`, `Exception`). The only difference is the config path and description string.
- **Why:** Could be extracted into a `_load_config(path, config_type)` helper method, reducing ~70 lines to ~30.
- **Risk:** Low.

**24. `batch/processing/reconciler.py` has duplicated ID collection logic**
- **File:** `batch/processing/reconciler.py`
- **What:** `get_expected_ids()` (instance method) and `collect_expected_custom_ids()` (static method) both extract and return expected custom_ids from context maps using similar logic.
- **Why:** Two methods doing essentially the same thing, likely from different evolutionary paths.
- **Risk:** Low.

**25. `realtime/services/context.py` -- `prepare_context_data()` and `prepare_tool_context()` overlap**
- **File:** `realtime/services/context.py:153-200`
- **What:** `prepare_context_data()` and `prepare_tool_context()` have nearly identical implementations: both check if input is a string and either return it or call `json.dumps()`. The docstrings even note "CRITICAL: Tools and LLMs now share the same llm_context."
- **Why:** Since they share the same context now, `prepare_tool_context()` could be removed and callers could use `prepare_context_data()`.
- **Risk:** Low.

---

## Module-by-Module Breakdown

### `batch/__init__.py`
- **Lines:** ~5
- **Complexity:** None
- **Findings:** Empty module docstring only. No exports defined. Consumers import directly from sub-modules.

### `batch/batch_cli.py`
- **Lines:** ~70
- **Complexity:** Low
- **Findings:** Minor -- duplicated batch_id lookup pattern between `status` and `retrieve` commands. Not worth a finding on its own.

### `batch/service.py`
- **Lines:** ~245
- **Complexity:** Medium (16 constructor parameters, lazy initialization)
- **Findings:** Large constructor surface area. Facade pattern is appropriate. The lazy `_get_*_service()` methods use inline imports which is a common pattern for avoiding circular imports.

### `batch/core/batch_constants.py`
- **Lines:** ~114
- **Complexity:** Low
- **Findings:** Well-structured enums. No issues.

### `batch/core/batch_context_metadata.py`
- **Lines:** ~163
- **Complexity:** Low-medium
- **Findings:** Clean helper class. No issues.

### `batch/core/batch_models.py`
- **Lines:** ~188
- **Complexity:** Low
- **Findings:** [P3-19] `BatchJobEntry.status` should be `BatchStatus` enum.

### `batch/infrastructure/batch_client_resolver.py`
- **Lines:** ~242
- **Complexity:** Medium
- **Findings:** [P2-15] Redundant validation of `model_vendor`.

### `batch/infrastructure/batch_data_loader.py`
- **Lines:** ~48
- **Complexity:** Low
- **Findings:** Clean, simple file loader. No issues.

### `batch/infrastructure/batch_source_handler.py`
- **Lines:** ~73
- **Complexity:** Low
- **Findings:** [P2-14] Dead code -- workflow_root traversal logic overridden immediately.

### `batch/infrastructure/context.py`
- **Lines:** ~183
- **Complexity:** Medium
- **Findings:** Static methods for context map persistence. Well-structured.

### `batch/infrastructure/job_manager.py`
- **Lines:** ~174
- **Complexity:** Medium
- **Findings:** Reads registry files directly, potentially bypassing `BatchRegistryManager` caching. Minor design concern.

### `batch/infrastructure/registry.py`
- **Lines:** ~413
- **Complexity:** Medium-high (thread-safe caching, atomic file writes)
- **Findings:** [P3-21] Manual `BatchJobEntry` reconstruction in `update_status`.

### `batch/processing/batch_passthrough_builder.py`
- **Lines:** ~61
- **Complexity:** Low
- **Findings:** Clean, focused. No issues.

### `batch/processing/preparator.py`
- **Lines:** ~362
- **Complexity:** Medium-high
- **Findings:** Accepts deprecated `filter_service` and `guard_handler` parameters. Otherwise well-structured after recent refactoring.

### `batch/processing/reconciler.py`
- **Lines:** ~298
- **Complexity:** Medium
- **Findings:** [P3-24] Duplicated ID collection logic between `get_expected_ids()` and `collect_expected_custom_ids()`.

### `batch/processing/result_processor.py`
- **Lines:** ~524
- **Complexity:** Medium-high (pipeline pattern with multiple stages)
- **Findings:** The `_apply_context_passthrough` method has a repeated import of `ContextScopeProcessor` inside a loop (lines 349-368), though this is likely an inline-import pattern rather than a performance concern.

### `batch/processing/side_output.py`
- **Lines:** ~86
- **Complexity:** Low
- **Findings:** Clean utility. No issues.

### `batch/services/processing.py`
- **Lines:** 1,221
- **Complexity:** **Very high** -- multiple 100-300 line methods with deep nesting
- **Findings:** [P1-3] Massively oversized. [P1-4] Duplicated `_retrieve_results()`.

### `batch/services/retrieval.py`
- **Lines:** ~176
- **Complexity:** Medium
- **Findings:** [P1-4] Contains `_retrieve_results()` duplicated from `processing.py`.

### `batch/services/submission.py`
- **Lines:** ~307
- **Complexity:** Medium
- **Findings:** Well-structured. No major issues.

### `config/__init__.py`
- **Lines:** ~5
- **Complexity:** None
- **Findings:** Empty.

### `config/vendor.py`
- **Lines:** ~195
- **Complexity:** Low-medium
- **Findings:** Minor naming inconsistency: `GoogleConfig` uses `VendorType.GOOGLE` but the provider directory is `gemini/`.

### `providers/__init__.py`
- **Lines:** ~5
- **Complexity:** None
- **Findings:** Empty docstring.

### `providers/batch_base.py`
- **Lines:** 744
- **Complexity:** High (template method pattern with many hook points)
- **Findings:** [P1-6] Bug: `retrieve_results()` returns inside for-loop. [P2-11] Uses `print()` instead of logger. [P2-12] Deprecated `compile_schema` method retained.

### `providers/batch_client_factory.py`
- **Lines:** ~181
- **Complexity:** Low (but verbose)
- **Findings:** [P2-7] Long if/elif chain should be registry-based.

### `providers/client_base.py`
- **Lines:** ~175
- **Complexity:** Medium
- **Findings:** `call_json` and `call_non_json` are `@staticmethod @abstractmethod` which is unusual. The `_redact_api_key()` method is well-implemented.

### `providers/failure_injection.py`
- **Lines:** ~161
- **Complexity:** Medium
- **Findings:** [P3-18] Overlaps with `ollama/failure_injection.py`.

### `providers/mixins.py`
- **Lines:** ~178
- **Complexity:** Medium
- **Findings:** `JSONResponseMixin`, `GenericErrorHandlerMixin`, `OpenAICompatibleResponseMixin`. Well-designed. `GenericErrorHandlerMixin` is defined but it is unclear if it is used by any client.

### `providers/usage_tracker.py`
- **Lines:** ~76
- **Complexity:** Low
- **Findings:** Clean thread-local implementation. No issues.

### `providers/openai/client.py`
- **Lines:** ~372
- **Complexity:** Medium-high
- **Findings:** [P1-1] Duplicated `_wrap_openai_error`. [P1-2] Duplicated `_extract_retry_after`. [P2-10] Duplicated invoke boilerplate.

### `providers/openai/batch_client.py`
- **Lines:** ~166
- **Complexity:** Medium
- **Findings:** [P2-11] Uses `print()`. Line 95: `open(input_file, "rb")` without context manager (resource leak risk, though file object is passed to API).

### `providers/anthropic/client.py`
- **Lines:** ~303
- **Complexity:** Medium-high
- **Findings:** [P1-1] Duplicated `_wrap_anthropic_error`. [P1-2] Duplicated `_extract_retry_after`. [P2-10] Duplicated invoke boilerplate.

### `providers/anthropic/batch_client.py`
- **Lines:** ~484
- **Complexity:** High
- **Findings:** [P2-11] Uses `print()`. `_fetch_raw_results` raises `NotImplementedError`. `_parse_content_list` is complex (~60 lines, multiple passes).

### `providers/gemini/client.py`
- **Lines:** ~311
- **Complexity:** Medium
- **Findings:** [P1-1] Duplicated `_wrap_gemini_error`. [P2-10] Duplicated invoke boilerplate.

### `providers/gemini/batch_client.py`
- **Lines:** ~236
- **Complexity:** Medium
- **Findings:** [P2-11] Uses `print()` extensively (6 calls).

### `providers/cohere/client.py`
- **Lines:** ~291
- **Complexity:** Medium
- **Findings:** [P1-1] Duplicated `_wrap_cohere_error`. [P2-10] Duplicated invoke boilerplate.

### `providers/groq/client.py`
- **Lines:** ~345
- **Complexity:** Medium-high
- **Findings:** [P1-1] Duplicated `_wrap_groq_error`. [P2-10] Duplicated invoke boilerplate. [P3-20] Inline JSON parsing instead of using `JSONResponseMixin`.

### `providers/groq/batch_client.py`
- **Lines:** ~207
- **Complexity:** Medium
- **Findings:** [P2-11] Uses `print()`.

### `providers/mistral/client.py`
- **Lines:** ~287
- **Complexity:** Medium
- **Findings:** [P1-1] Duplicated `_wrap_mistral_error`. [P2-10] Duplicated invoke boilerplate.

### `providers/mistral/batch_client.py`
- **Lines:** ~237
- **Complexity:** Medium
- **Findings:** [P2-11] Uses `print()`.

### `providers/ollama/client.py`
- **Lines:** ~382
- **Complexity:** Medium-high
- **Findings:** [P1-1] Duplicated `_wrap_ollama_error`. [P2-10] Duplicated invoke boilerplate.

### `providers/ollama/batch_client.py`
- **Lines:** ~305
- **Complexity:** Medium-high (synchronous batch simulation)
- **Findings:** Overrides `retrieve_results()` and marks `_fetch_raw_results()` as `NotImplementedError`. Well-documented rationale.

### `providers/ollama/failure_injection.py`
- **Lines:** ~124
- **Complexity:** Low
- **Findings:** [P3-18] Overlaps with top-level `failure_injection.py`.

### `providers/tools/client.py`
- **Lines:** ~91
- **Complexity:** Low
- **Findings:** Clean. Has inline imports from `batch.core.batch_context_metadata` which is a cross-concern import (realtime client importing batch module).

### `providers/agac/client.py`
- **Lines:** ~264
- **Complexity:** Medium
- **Findings:** Mock/test client in production code. See [P2-8].

### `providers/agac/batch_client.py`
- **Lines:** ~304
- **Complexity:** Medium
- **Findings:** Mock/test client in production code. See [P2-8].

### `providers/agac/fake_data.py`
- **Lines:** 842
- **Complexity:** Low (mostly data)
- **Findings:** [P2-8] 843 lines of test utility in production source. ~400 lines are word pool arrays.

### `realtime/__init__.py`
- **Lines:** ~10
- **Complexity:** None
- **Findings:** Contains a comment referencing `agent_builder` but the actual module is `builder.py`.

### `realtime/builder.py`
- **Lines:** ~142
- **Complexity:** Medium
- **Findings:** Has a TODO on line 86 about `captured_results`. Otherwise well-structured orchestration function.

### `realtime/cleaner.py`
- **Lines:** ~65
- **Complexity:** Low
- **Findings:** [P3-17] Misleading log message at INFO level.

### `realtime/config.py`
- **Lines:** 415
- **Complexity:** High (many responsibilities)
- **Findings:** [P2-9] Misplaced -- not LLM-specific. [P3-22] Dead `DuplicateAgentError` class. [P3-23] Duplicated try/except blocks in `load_configs()`.

### `realtime/handlers.py`
- **Lines:** ~165
- **Complexity:** Medium
- **Findings:** [P1-5] Bug: `agent_exists()` uses `self` in `@staticmethod`. [P3-16] Duplicate `Path` import.

### `realtime/output.py`
- **Lines:** ~146
- **Complexity:** Low-medium
- **Findings:** `save_main_output` and `save_side_output` have duplicated try/except error-handling blocks. Not significant enough for its own finding.

### `realtime/services/invocation.py`
- **Lines:** ~103
- **Complexity:** Low
- **Findings:** `CLIENT_REGISTRY` and `SINGLE_RESPONSE_CLIENTS` pattern is clean. The `if model_vendor == "tool"` / `if model_vendor == "groq"` special cases are reasonable given the different signatures.

### `realtime/services/context.py`
- **Lines:** ~201
- **Complexity:** Medium
- **Findings:** [P2-12] `build_field_context()` is deprecated. [P3-25] `prepare_context_data()` and `prepare_tool_context()` overlap.

### `realtime/services/prompt_service.py`
- **Lines:** ~76
- **Complexity:** Low
- **Findings:** [P2-12] `prepare_prompt()` is deprecated. `debug_print_prompt()` uses `print()` which is intentional for debug output.

### `realtime/services/schema_service.py`
- **Lines:** 35
- **Complexity:** None
- **Findings:** [P2-13] Pure pass-through wrapper with no added value.

---

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions.errors` | `AgentActionsException`, `AgentNotFoundError`, `RateLimitError`, `NetworkError`, `VendorAPIError`, `ConfigurationError`, `DependencyError`, `ProcessingError`, `ExternalServiceError`, `ConfigValidationError`, `TemplateRenderingError`, `ValidationError`, `FileSystemError` | Most modules across all sub-modules |
| `agent_actions.logging` | `fire_event`, `get_manager` | Provider clients, batch infrastructure, batch services, realtime config |
| `agent_actions.logging.events` | `LLMRequestEvent`, `LLMResponseEvent`, `BatchProgressEvent`, `BatchCompleteEvent`, `BatchSubmittedEvent`, `ConfigLoadStartEvent`, `ConfigLoadEvent`, `LLMJSONParseErrorEvent`, `CacheHitEvent`, `CacheMissEvent` | Provider clients, batch services, batch infrastructure, realtime config |
| `agent_actions.utils.constants` | `MODEL_VENDOR_KEY`, `MODEL_NAME_KEY`, `API_KEY_KEY`, `JSON_MODE_KEY` | Provider clients, realtime builder, batch preparator |
| `agent_actions.utils.path_utils` | `topological_sort`, `ensure_directory_exists`, `create_side_output_directory` | Realtime config, batch infrastructure, batch services |
| `agent_actions.utils.module_loader` | `ensure_path_importable`, `load_module_from_path` | Realtime builder, batch services/processing |
| `agent_actions.utils.id_generation` | `IDGenerator` | Batch preparator |
| `agent_actions.utils.tools_resolver` | `resolve_tools_path` | Realtime builder, batch preparator |
| `agent_actions.utils.passthrough_builder` | `PassthroughItemBuilder` | Batch passthrough builder |
| `agent_actions.utils.udf_management.tooling` | `execute_user_defined_function` | Tools client |
| `agent_actions.input.preprocessing.transformation` | `StringProcessor`, `DataTransformer` | Provider clients (openai, anthropic, gemini, cohere, groq, mistral), batch result processor |
| `agent_actions.input.context.normalizer` | `normalize_all_agent_configs` | Realtime config |
| `agent_actions.output.writer` | `FileWriter` | Realtime output, batch services/processing |
| `agent_actions.output.file_handler` | `FileHandler` | Realtime handlers |
| `agent_actions.output.response.schema` | `prepare_schema_unified` | Schema service |
| `agent_actions.output.response.config_schema` | `AgentConfig`, `DefaultAgentConfig` | Realtime config |
| `agent_actions.output.response.expander` | `ActionExpander` | Realtime config |
| `agent_actions.prompt.formatter` | `PromptFormatter` | Prompt service, batch preparator |
| `agent_actions.prompt.render_workflow` | `render_pipeline_with_templates` | Realtime config |
| `agent_actions.prompt.context.static_loader` | `StaticDataLoader`, `StaticDataLoadError` | Context service |
| `agent_actions.prompt.context.scope` | `ContextScopeProcessor` | Realtime builder, realtime config, batch result processor |
| `agent_actions.processing.types` | `RecoveryMetadata`, `RetryMetadata` | Batch services/processing, batch result processor |
| `agent_actions.processing.enrichment` | `EnrichmentPipeline` | Batch result processor |
| `agent_actions.processing.batch_context_adapter` | `BatchContextAdapter` | Batch result processor |
| `agent_actions.processing.prepared_task` | `GuardStatus`, `PreparationContext` | Batch preparator |
| `agent_actions.processing.task_preparer` | `TaskPreparer`, `get_task_preparer` | Batch preparator |
| `agent_actions.validation.config` | `ConfigValidator` | Realtime config |
| `agent_actions.validation.batch_validator` | `BatchCommandArgs` | Batch CLI |
| `agent_actions.config.environment` | `EnvironmentConfig` | Realtime config |
| `agent_actions.config.path_config` | `load_project_config` | Realtime config |
| `agent_actions.config.paths` | `PathManager` | Realtime config |
| `agent_actions.config.di.container` | `registry` | Batch service |
| `agent_actions.config.interfaces` | `IDataLoader`, `ProcessingMode` | Batch data loader |
| `agent_actions.workflow.models` | `WorkflowConfig` | Realtime config |
| `agent_actions.workflow.pipeline` | `PipelineConfig` | Realtime config |
| `agent_actions.cli.cli_decorators` | `handles_user_errors`, `requires_project` | Batch CLI |
| `agent_actions.storage.backend` | `StorageBackend` (TYPE_CHECKING only) | Realtime output |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions.workflow.executor` | `get_last_usage` from `providers/usage_tracker` | Low -- simple function |
| `agent_actions.workflow.pipeline` | `OutputHandler` from `realtime/output`, `BatchService` from `batch/service` | **High** -- core pipeline integration |
| `agent_actions.workflow.coordinator` | `ConfigManager` from `realtime/config`, `BatchService` from `batch/service` | **High** -- orchestration layer |
| `agent_actions.validation.validate_udfs` | `ConfigManager` from `realtime/config` | Medium |
| `agent_actions.validation.startup_validator` | `ConfigManager` from `realtime/config` | Medium |
| `agent_actions.validation.startup` | `ConfigManager` from `realtime/config` | Medium |
| `agent_actions.logging.filters` | `BaseClient` from `providers/client_base` | Low -- type reference |
| `agent_actions.cli.main` | `status`, `retrieve` commands from `batch/batch_cli` | Low -- CLI surface |
| `agent_actions.cli.clean` | `Cleaner` from `realtime/cleaner` | Low |
| `agent_actions.prompt.renderer` | `AgentManager` from `realtime/handlers` | Medium |
| `agent_actions.output.response.expander` | `VendorType` from `config/vendor` | Low -- enum reference |
| `agent_actions.processing.helpers` | `create_dynamic_agent` from `realtime/builder` | **High** -- core processing |
| `agent_actions.config.di.configurator` | `BatchService` from `batch/service` | Medium |
| `agent_actions.config.di.application` | `BatchService` from `batch/service` | Medium |
| `agent_actions.input.loaders` | `BatchDataLoader` from `batch/infrastructure/batch_data_loader` (wildcard import) | Medium |
| `agent_actions.input.preprocessing.staging` | `BatchService` from `batch/service` | Medium |

### Dependency Risks

- **[P2-9] Moving `ConfigManager`** out of `realtime/config.py` would require updating imports in `workflow/coordinator.py`, `validation/validate_udfs.py`, `validation/startup_validator.py`, and `validation/startup.py`. A re-export from the old location could provide backward compatibility.
- **[P1-3] Decomposing `BatchProcessingService`** must preserve the public API surface since it is imported by `batch/service.py` and extensively tested. New extracted classes/functions should be internal to the batch sub-module.
- **[P1-1] Consolidating `_wrap_*_error` functions** would affect all 7 provider client modules. Since these are module-level functions (not part of a public API), the risk is contained within the `llm/providers/` folder.
- **[P2-10] Refactoring the invoke pattern** in provider clients could affect `agent_actions.processing.helpers` which calls `create_dynamic_agent`, which calls `ClientInvocationService.invoke_client`, which calls individual client `invoke()` methods. The chain is long but interfaces are stable.
- **[P2-8] Moving `fake_data.py`** to test fixtures would require updating imports in `agac/client.py` and `agac/batch_client.py`. Since `agac` is a test/mock provider, this is low risk.

---

## Recommended Simplification Order

1. **[P1-5] Fix `agent_exists` bug** in `handlers.py` -- 1-line fix, immediate correctness win.
2. **[P1-6] Fix `retrieve_results` early-return bug** in `batch_base.py` -- critical data-loss fix.
3. **[P3-17] Fix misleading log message** in `cleaner.py` -- trivial fix.
4. **[P3-16] Remove duplicate `Path` import** in `handlers.py` -- trivial cleanup.
5. **[P1-1, P1-2] Consolidate `_wrap_*_error` and `_extract_retry_after`** into a shared utility -- high line-count reduction (~400+ lines eliminated), low risk, self-contained within providers.
6. **[P2-11] Replace `print()` with `logger`** across batch clients -- systematic search-and-replace, low risk.
7. **[P2-7] Convert `batch_client_factory.py`** to registry pattern -- proven pattern exists in `invocation.py`.
8. **[P2-13] Remove `SchemaService` wrapper** -- redirect caller to `prepare_schema_unified` directly.
9. **[P2-14] Remove dead code** in `batch_source_handler.py`.
10. **[P3-22] Remove dead `DuplicateAgentError`** class.
11. **[P3-25] Consolidate `prepare_context_data` and `prepare_tool_context`** in context.py.
12. **[P2-12] Remove deprecated methods** (after confirming no production callers) or add removal timeline.
13. **[P1-4] Deduplicate `_retrieve_results`** between processing.py and retrieval.py.
14. **[P2-10] Extract shared invoke template** in provider clients -- larger effort, requires careful testing.
15. **[P1-3] Decompose `BatchProcessingService`** -- largest effort, highest architectural impact, do last to benefit from other cleanups.
16. **[P2-9] Relocate `ConfigManager`** out of `llm/realtime/` -- moderate effort, cross-folder coordination required.
17. **[P2-8] Move `fake_data.py`** to test fixtures -- requires structural decision about test data location.
