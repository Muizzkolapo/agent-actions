# Code Simplification Audit: input

**Audited path:** `agent_actions/input/`
**Date:** 2026-02-05
**Modules reviewed:** 52 Python files across 3 sub-packages (context, loaders, preprocessing)
**Total lines:** ~9,576

## Executive Summary

The `input` package is moderately healthy but has several significant simplification opportunities. The highest-impact finding is a **four-layer guard evaluation stack** (`GuardFilter` -> `FilterService` -> `GuardHandler` -> `GuardEvaluator`) with substantial code duplication across layers. The `initial_pipeline.py` module (811 lines) is the largest file and contains duplicated logic between batch and realtime preparation paths. The chunking strategies are well-decomposed using the Strategy pattern but the three concrete `ChunkingStrategy` implementations are thin wrappers that all delegate to the same `Tokenizer.split_text_content()` method, adding indirection without value. Estimated effort for all findings: 3-5 days of focused refactoring.

## Priority Findings

### P1 -- High Impact (Significant simplification, low risk)

1. **Four-layer guard evaluation duplication** -- `filtering/evaluator.py` (427 lines), `filtering/service.py` (219 lines), `filtering/guard_handler.py` (469 lines), `filtering/guard_filter.py` (422 lines)
   - The module docstring in `evaluator.py` (lines 1-15) explicitly acknowledges this consolidation is in progress ("consolidates the 4 guard implementations").
   - `FilterService._evaluate_guard()` (service.py:75-97) and `GuardEvaluator._evaluate_guard()` (evaluator.py:269-310) perform nearly identical logic: extract scope/clause/behavior from config, create `FilterItemRequest`, call `guard_filter.filter_item()`, then map the result.
   - `FilterService._evaluate_conditional_clause()` (service.py:99-114) and `GuardEvaluator._evaluate_conditional_clause()` (evaluator.py:246-267) both call `execute_user_defined_function()` with the same error-handling pattern.
   - `GuardHandler.filter_single_item()` (guard_handler.py:171-212) delegates to `FilterService.filter_single_item()`, adding minimal value.
   - Three separate global singleton patterns: `get_global_guard_filter()`, `get_filter_service()`, `get_guard_handler()`, `get_guard_evaluator()` -- all with slightly different thread-safety approaches (only `get_guard_evaluator()` uses a lock).
   - **Risk:** Medium -- downstream consumers import from multiple layers. Requires coordinated changes across `processing/helpers.py`, `processing/task_preparer.py`, `workflow/managers/skip.py`.
   - **Recommendation:** Collapse `FilterService` into `GuardEvaluator`, make `GuardHandler` a thin orchestration layer that delegates to `GuardEvaluator`, and remove the redundant singleton functions.

2. **Duplicated batch/realtime preparation in initial_pipeline.py** -- `staging/initial_pipeline.py` (811 lines)
   - `_prepare_batch_data()` (lines 525-584) and `_prepare_realtime_data()` (lines 587-675) both handle the same file types (`.txt`, `.md`, `.json`, `.csv`, `.xml`) with nearly identical branching structures and repeated loader instantiation.
   - Both functions duplicate chunk configuration extraction (chunk_size, overlap, tokenizer_model, split_method) from `agent_config`.
   - `_save_source_items_helper()` (lines 78-131) and `_should_save_source_items()` (lines 303-400) duplicate the "derive workflow_root from agent_io path" logic (the same if/else block with `parts.index("agent_io")` appears **three times** across lines 101-119, 344-359).
   - **Risk:** Low -- this is internal pipeline code with no public API surface.
   - **Recommendation:** Extract a `_derive_workflow_root(path)` helper. Unify `_prepare_batch_data` and `_prepare_realtime_data` into a single function with a `mode` parameter, handling only the mode-specific differences (batch metadata injection).

3. **Chunking strategies are trivial wrappers** -- `chunking/strategies/chunking_strategies.py` (129 lines)
   - `TiktokenChunkingStrategy.split_text_into_chunks()` (lines 48-71) simply calls `Tokenizer.split_text_content()` with `split_method="tiktoken"`.
   - `CharBasedChunkingStrategy.split_text_into_chunks()` (lines 81-100) calls the same method with `split_method="chars"`.
   - `SpacyChunkingStrategy.split_text_into_chunks()` (lines 110-129) calls the same method with `split_method="spacy"`.
   - All three strategies are one-line delegations. The Strategy pattern adds class overhead without providing distinct behavior -- the actual strategy selection is already handled by `Tokenizer.split_text_content()` via its `split_method` parameter.
   - **Risk:** Low -- only consumed by `FieldChunker._create_chunking_strategy()`.
   - **Recommendation:** Either (a) remove the strategy classes and call `Tokenizer.split_text_content()` directly in `FieldChunker`, or (b) move the actual splitting logic _into_ the strategies so they justify their existence.

### P2 -- Medium Impact (Meaningful improvement, moderate effort)

4. **Duplicate `_get_nested_value` / field resolution paths** -- `guard_filter.py:356-367` wraps `agent_actions.utils.dict.get_nested_value`, `ast_nodes.py:214-224` calls it directly, `resolver.py:319-350` reimplements nested path traversal manually, and `context_provider.py:80-117` (via `to_flat_dict`) does manual flattening.
   - `FieldReferenceResolver._resolve_nested_path()` (resolver.py:319-350) reimplements `get_nested_value()` but adds array index and attribute access support. The guard filter's `_get_nested_value()` is a trivial pass-through wrapper.
   - **Risk:** Low -- internal implementation detail.
   - **Recommendation:** Consolidate into a single `resolve_path()` utility in `utils/dict.py` that supports dict, list index, and attribute access.

5. **`FileReader` overlaps with typed loaders** -- `loaders/file_reader.py` (116 lines)
   - `FileReader` handles `.json`, `.txt`, `.md`, `.csv`, `.pdf`, `.xml`, `.docx`, `.xlsx`, `.html` -- many of the same formats that `JsonLoader`, `TabularLoader`, `XmlLoader`, and `TextLoader` handle.
   - `FileReader` does NOT extend `BaseLoader` and has a completely different interface (constructor takes `file_path`, uses `read()` method).
   - It is only imported in `staging/initial_pipeline.py:218` and `workflow/pipeline.py:9`.
   - **Risk:** Medium -- `FileReader` uses heavy dependencies (PyPDF2, python-docx, pandas, BeautifulSoup) and is the only code path for PDF/DOCX/XLSX reading.
   - **Recommendation:** Extract PDF/DOCX/XLSX reading into dedicated `BaseLoader` subclasses. Consider making `FileReader` a facade that delegates to the typed loaders.

6. **`TemplateYamlLoader` duplicates YAML-to-dict conversion logic** -- `loaders/yaml.py` (283 lines)
   - `_process_multiline_template()` (lines 105-152) and `_process_template_line()` (lines 154-184) share identical YAML line generation logic: both iterate over `param_dict`, format strings/lists/other types, and build `yaml_lines`. The only difference is the first line's list-item handling.
   - **Risk:** Low -- self-contained module.
   - **Recommendation:** Extract shared YAML line generation into a `_format_params_as_yaml(param_dict, indent_str)` helper.

7. **`source_guid` extraction duplicated** -- `context_preprocessor.py:23-28` and `source_path.py:110-120`
   - `ContextPreprocessor.extract_guid_and_content()` extracts `source_guid` from nested dict structure.
   - `SourcePathManager.load_source_content()` (lines 110-120) does the same nested `source_guid` extraction with a slightly different traversal pattern.
   - **Risk:** Low.
   - **Recommendation:** Reuse `ContextPreprocessor.extract_guid_and_content()` in `SourcePathManager.load_source_content()`.

8. **`EvaluationContext` name collision** -- Two different classes named `EvaluationContext` exist:
   - `preprocessing/parsing/ast_nodes.py:193` -- Used for WHERE clause evaluation with `data`, `functions`, and `debug` fields.
   - `preprocessing/field_resolution/context_provider.py:28` -- Used for guard/filter/prompt evaluation with `current_content`, `field_context`, etc.
   - Both are re-exported from `preprocessing/__init__.py` (only the field_resolution one is in `__all__`, but both are importable).
   - **Risk:** Medium -- can cause confusion and import errors.
   - **Recommendation:** Rename one of them. The AST one could become `WhereClauseContext` to be more specific.

9. **`_MANIFEST.md` comment-only __init__.py files** -- Five `__init__.py` files are empty or contain only a docstring (1 line each): `chunking/__init__.py`, `parsing/__init__.py`, `processing/__init__.py`, `staging/__init__.py`, `transformation/__init__.py`.
   - These are necessary for Python packaging but waste cognitive space during navigation.
   - **Risk:** None. This is purely cosmetic.

### P3 -- Low Impact (Nice-to-have, minor cleanups)

10. **`[DEBUG]` prefix in log messages** -- `historical.py` has 10+ `logger.debug()` calls with `[DEBUG]` prefix in the message string (e.g., line 84: `"[DEBUG] Finding node_id..."`). The `[DEBUG]` prefix is redundant since these are already at DEBUG level.
    - Lines: 84, 88, 97-103, 105-107, 131-141, 155-163, 173, 402, 405-410, 439-445, 451, 458, 464, 470, 478, 481.
    - **Risk:** None.
    - **Recommendation:** Remove `[DEBUG]` prefixes from debug-level log messages.

11. **`__version__` in `loaders/base.py`** -- Line 43: `__version__ = "0.1.0"`. This appears to be a leftover from early development. The project has a top-level `__version__.py`.
    - **Risk:** None.
    - **Recommendation:** Remove the module-level `__version__`.

12. **`_node_id` unused parameter** -- `historical.py:368`: `_find_record_by_identifiers` has parameter `_node_id: str` (underscore-prefixed to indicate it is unused) but the docstring says "kept for logging/diagnostics." The parameter is not used in the method body at all.
    - **Risk:** None.
    - **Recommendation:** Remove the parameter if it is truly unused, or add the diagnostic logging if intended.

13. **Wildcard imports in `loaders/__init__.py`** -- Lines 11-17 use `from .base import *`, `from .source_data import *`, etc. This exports all public symbols from each module, making the API surface unclear and potentially creating naming conflicts.
    - **Risk:** Low.
    - **Recommendation:** Replace with explicit imports and define `__all__`.

14. **`supports_filetype()` uses list instead of set** -- `json.py:73`, `tabular.py:82`, `xml.py:84`, `text.py:43` all use `file_extension.lower() in [".json"]` (single-element list). Using a set `{".json"}` would be more idiomatic and marginally faster.
    - **Risk:** None.
    - **Recommendation:** Change `[".json"]` to `{".json"}` etc.

15. **`NotLikeOperator` and `NotBetweenOperator` instantiate new operators each call** -- `comparison.py:236-237`: `NotLikeOperator.evaluate()` creates `LikeOperator()` on every invocation. Similarly `NotBetweenOperator.evaluate()` (line 289) creates `BetweenOperator()` each time.
    - **Risk:** None (negligible performance impact).
    - **Recommendation:** Store the delegate as an instance attribute.

16. **`_operator_map` in `WhereClauseEvaluator` is a static mapping** -- `ast_nodes.py:299-316`. This dictionary could be a class-level constant since it never changes, avoiding reconstruction on each evaluator instantiation.
    - **Risk:** None.
    - **Recommendation:** Move to class attribute.

17. **`loaders/__init__.py` imports from `agent_actions.llm.batch.infrastructure.batch_data_loader`** -- Line 11: `from agent_actions.llm.batch.infrastructure.batch_data_loader import *`. This couples the `input.loaders` package to the `llm.batch` package, which is architecturally surprising (input should not depend on LLM infrastructure).
    - **Risk:** Medium -- removing this import would break backward compatibility for consumers who import batch-related symbols from `input.loaders`.
    - **Recommendation:** Move this import to a compatibility shim or remove it, documenting the direct import path.

18. **`StagingContext` backward-compatibility alias** -- `initial_pipeline.py:49`: `StagingContext = InitialStageContext`. Similarly `generate_staging = process_initial_stage` at line 811. If these aliases are no longer needed, they add confusion.
    - **Risk:** Low -- need to verify no external consumers use the old names.
    - **Recommendation:** Grep for usage and remove if unused.

19. **`SafeExpressionEvaluator` still uses `eval()`** -- `parser.py:527`. Despite the name "Safe," this class uses Python's `eval()` with a restricted context. While the AST validation is thorough, this remains a code smell that could be replaced with the AST-based `WhereClauseParser` for full expressions.
    - **Risk:** Security consideration -- the AST validation appears robust but `eval()` is inherently risky.
    - **Recommendation:** Consider replacing with ast.literal_eval + manual operator handling for simple expressions, or document the security boundary clearly.

20. **`_parse_boolean` returns `None` for non-boolean** -- `yaml.py:195-201`. The method `_parse_boolean()` returns `None` when the value is not a boolean. This means `_parse_param_value()` (line 217) must check for `None`, but `None` is also a valid parsed value for dict types (line 226). This conflation of "not a boolean" with "skip this value" could cause bugs.
    - **Risk:** Low.
    - **Recommendation:** Use a sentinel value or separate the "is boolean" check from the parsing.

## Module-by-Module Breakdown

### `context/__init__.py`
- **Lines:** 12
- **Complexity:** Trivial
- **Findings:** Clean re-export module. No issues.

### `context/context_preprocessor.py`
- **Lines:** 29
- **Complexity:** Low
- **Findings:** P2-7 (duplicated source_guid extraction with source_path.py)

### `context/historical.py`
- **Lines:** 482
- **Complexity:** Medium-high. `_find_record_by_identifiers()` (lines 364-482) has multiple matching strategies with complex branching.
- **Findings:** P3-10 (DEBUG prefix in logs), P3-12 (unused `_node_id` parameter)

### `context/normalizer.py`
- **Lines:** 177
- **Complexity:** Low-medium. Clean structure with directive registry pattern.
- **Findings:** No significant issues. Well-documented mutation contract.

### `loaders/__init__.py`
- **Lines:** 20
- **Complexity:** Low
- **Findings:** P3-13 (wildcard imports), P3-17 (surprising import from llm.batch)

### `loaders/base.py`
- **Lines:** 149
- **Complexity:** Medium. `load_file_async()` has 3 levels of nesting for fallback behavior (anyio -> asyncio.to_thread -> run_in_executor). Similarly `process_async()`.
- **Findings:** P3-11 (`__version__` leftover). The async fallback chain (lines 87-97) could be simplified with a helper.

### `loaders/file_reader.py`
- **Lines:** 116
- **Complexity:** Low-medium
- **Findings:** P2-5 (overlaps with typed loaders)

### `loaders/json.py`
- **Lines:** 73
- **Complexity:** Low
- **Findings:** P3-14 (`supports_filetype` uses list)

### `loaders/source_data.py`
- **Lines:** 81
- **Complexity:** Low. Clean, focused module.
- **Findings:** No significant issues.

### `loaders/tabular.py`
- **Lines:** 82
- **Complexity:** Low
- **Findings:** P3-14 (`supports_filetype` uses list). Error handling re-wraps exceptions with `AgentActionsException` after already calling `handle_processing_error`.

### `loaders/text.py`
- **Lines:** 43
- **Complexity:** Low
- **Findings:** P3-14 (`supports_filetype` uses list)

### `loaders/udf.py`
- **Lines:** 124
- **Complexity:** Low-medium. `validate_udf_references()` uses a nested closure `extract_impl_refs()` for recursive extraction.
- **Findings:** No significant issues. Well-structured.

### `loaders/xml.py`
- **Lines:** 84
- **Complexity:** Low
- **Findings:** P3-14 (`supports_filetype` uses list)

### `loaders/yaml.py`
- **Lines:** 283
- **Complexity:** Medium. `_handle_multiline_templates()` (lines 65-103) uses index-based while-loop iteration with manual `i += 1`.
- **Findings:** P2-6 (duplicated YAML line generation between `_process_multiline_template` and `_process_template_line`)

### `preprocessing/__init__.py`
- **Lines:** 102
- **Complexity:** Low (re-export module)
- **Findings:** P2-8 (EvaluationContext name collision). The commented-out lazy imports (lines 41-51) explain circular dependency constraints but add visual noise.

### `preprocessing/source_path.py`
- **Lines:** 203
- **Complexity:** Medium. `save_source_content()` (lines 133-203) is a 70-line method that handles directory creation, file read/write, array update-or-append, and event firing.
- **Findings:** P2-7 (duplicated source_guid extraction)

### `preprocessing/chunking/errors.py`
- **Lines:** 14
- **Complexity:** Trivial
- **Findings:** No issues.

### `preprocessing/chunking/field_chunking.py`
- **Lines:** 377
- **Complexity:** Medium. Well-decomposed into small methods. `chunk_record()` (lines 298-352) is the main orchestrator.
- **Findings:** No significant issues. Good use of dataclasses for configuration.

### `preprocessing/chunking/strategies/chunking_strategies.py`
- **Lines:** 129
- **Complexity:** Low
- **Findings:** P1-3 (trivial wrappers around Tokenizer)

### `preprocessing/chunking/strategies/fallback_strategies.py`
- **Lines:** 170
- **Complexity:** Low. Clean Strategy pattern implementation.
- **Findings:** No significant issues.

### `preprocessing/chunking/strategies/metadata_strategies.py`
- **Lines:** 172
- **Complexity:** Low-medium
- **Findings:** No significant issues. Well-structured.

### `preprocessing/chunking/strategies/validation.py`
- **Lines:** 163
- **Complexity:** Low-medium
- **Findings:** No significant issues. Error collection pattern is clean.

### `preprocessing/field_resolution/context_provider.py`
- **Lines:** 258
- **Complexity:** Medium
- **Findings:** P2-8 (EvaluationContext name collision)

### `preprocessing/field_resolution/exceptions.py`
- **Lines:** 50
- **Complexity:** Trivial
- **Findings:** No issues. Clean exception hierarchy.

### `preprocessing/field_resolution/reference_parser.py`
- **Lines:** 298
- **Complexity:** Medium. `parse()` method (lines 74-131) has multiple fallback paths.
- **Findings:** No significant issues. Good separation of format-specific parsing.

### `preprocessing/field_resolution/resolver.py`
- **Lines:** 360
- **Complexity:** Medium
- **Findings:** P2-4 (reimplements nested path traversal)

### `preprocessing/field_resolution/schema_field_validator.py`
- **Lines:** 184
- **Complexity:** Low-medium
- **Findings:** No significant issues.

### `preprocessing/field_resolution/validator.py`
- **Lines:** 322
- **Complexity:** Medium. Multiple validation methods with overlapping parameter patterns.
- **Findings:** `_schema_validator` (line 38) is instantiated but `validate_against_schemas()` is the only method using it. Consider lazy initialization.

### `preprocessing/filtering/evaluator.py`
- **Lines:** 427
- **Complexity:** Medium-high
- **Findings:** P1-1 (duplicated guard evaluation logic)

### `preprocessing/filtering/guard_filter.py`
- **Lines:** 422
- **Complexity:** Medium-high. `_evaluate_previous_outputs_count()` (lines 269-297) has a comparisons dict pattern that is clean.
- **Findings:** P1-1 (part of the four-layer duplication), P2-4 (trivial `_get_nested_value` wrapper)

### `preprocessing/filtering/guard_handler.py`
- **Lines:** 469
- **Complexity:** Medium-high. `filter_single_item_with_context()` (lines 214-291) largely duplicates `filter_single_item()` with field_context merging.
- **Findings:** P1-1 (part of the four-layer duplication)

### `preprocessing/filtering/service.py`
- **Lines:** 219
- **Complexity:** Medium
- **Findings:** P1-1 (part of the four-layer duplication)

### `preprocessing/parsing/ast_nodes.py`
- **Lines:** 460
- **Complexity:** Medium. `WhereClauseEvaluator.visit_comparison()` (lines 333-388) is well-documented with clear delegation to operator registry.
- **Findings:** P2-8 (EvaluationContext name collision), P3-16 (static `_operator_map` could be class-level)

### `preprocessing/parsing/parser.py`
- **Lines:** 634
- **Complexity:** High. Grammar construction in `_build_grammar()` (lines 131-192) is inherently complex but well-organized.
- **Findings:** P3-19 (SafeExpressionEvaluator uses eval()). `_map_operator_name()` (lines 326-350) duplicates what the enum already provides.

### `preprocessing/parsing/operator_registry/base.py`
- **Lines:** 120
- **Complexity:** Low
- **Findings:** `ComparisonOperator.evaluate()` and `LogicalOperator.evaluate()` (lines 62-96) raise `NotImplementedError` instead of being `@abstractmethod`. This is inconsistent with `BaseOperator.evaluate()` which IS abstract.

### `preprocessing/parsing/operator_registry/comparison.py`
- **Lines:** 324
- **Complexity:** Low (repetitive but each operator is simple)
- **Findings:** P3-15 (NotLikeOperator/NotBetweenOperator create delegate instances per call)

### `preprocessing/parsing/operator_registry/functions.py`
- **Lines:** 76
- **Complexity:** Low
- **Findings:** No significant issues.

### `preprocessing/parsing/operator_registry/logical.py`
- **Lines:** 46
- **Complexity:** Trivial
- **Findings:** No issues.

### `preprocessing/parsing/operator_registry/registry.py`
- **Lines:** 149
- **Complexity:** Low-medium. Reflection-based auto-discovery in `_discover_and_register_builtin_operators()` is clever but well-documented.
- **Findings:** `register_operator()` has two empty `if` blocks (lines 79-85) with `pass` -- these were likely intended for logging/warnings.

### `preprocessing/processing/data_processor.py`
- **Lines:** 97
- **Complexity:** Low
- **Findings:** `process_item()` returns `None` on error (line 85). This could mask failures silently since `None` is not a `List[Dict]`.

### `preprocessing/staging/initial_pipeline.py`
- **Lines:** 811
- **Complexity:** High. This is the largest and most complex file in the folder.
- **Findings:** P1-2 (duplicated batch/realtime preparation, triplicated workflow_root derivation), P3-18 (backward-compat aliases)

### `preprocessing/transformation/string_transformer.py`
- **Lines:** 330
- **Complexity:** Medium. `Tokenizer.split_text_content()` (lines 146-215) is the central dispatch for all splitting methods.
- **Findings:** `StringProcessor.call_user_function()` (lines 54-112) has deeply nested try/except with manual module loading. Consider whether this overlaps with the UDF system in `loaders/udf.py`.

### `preprocessing/transformation/transformer.py`
- **Lines:** 141
- **Complexity:** Low
- **Findings:** `update_schema_objects()` (lines 64-98) creates deep copies defensively, which is good, but the "create list with both values" behavior (line 94) is surprising and could confuse consumers.

## Cross-Folder Dependencies

### Upstream (imports from)

| Source Folder | Symbols Used | Used In |
|---|---|---|
| `agent_actions.config.interfaces` | `IDataLoader`, `ProcessingMode`, `ISourceDataLoader`, `IDataProcessor` | `loaders/base.py`, `loaders/source_data.py`, `preprocessing/processing/data_processor.py` |
| `agent_actions.config.di.container` | `registry` | `loaders/__init__.py`, `preprocessing/processing/data_processor.py` |
| `agent_actions.errors` | `AgentActionsException`, `DataParseError`, `FileLoadError`, `ValidationError`, `TransformationError`, `DependencyError`, `ConfigurationError`, `UDFLoadError`, `DuplicateFunctionError` | Multiple loaders and preprocessing modules |
| `agent_actions.processing.error_handling` | `ProcessorErrorHandlerMixin` | `loaders/base.py`, `loaders/file_reader.py`, `preprocessing/processing/data_processor.py` |
| `agent_actions.processing.helpers` | `transform_with_passthrough` | `preprocessing/processing/data_processor.py` |
| `agent_actions.processing.processor` | `RecordProcessor` | `staging/initial_pipeline.py` |
| `agent_actions.processing.result_collector` | `ResultCollector` | `staging/initial_pipeline.py` |
| `agent_actions.processing.types` | `ProcessingContext`, `ProcessingMode` | `staging/initial_pipeline.py` |
| `agent_actions.prompt.context.scope` | `ContextScopeProcessor` | `field_resolution/context_provider.py` |
| `agent_actions.prompt.formatter` | `PromptFormatter` | `staging/initial_pipeline.py` |
| `agent_actions.prompt.service` | `PromptPreparationService` | `staging/initial_pipeline.py` (lazy) |
| `agent_actions.output.writer` | `FileWriter` | `staging/initial_pipeline.py` |
| `agent_actions.output.saver` | `UnifiedSourceDataSaver` | `staging/initial_pipeline.py` |
| `agent_actions.output.response.config_types` | `AgentEntryDict` | `loaders/base.py` |
| `agent_actions.logging` | `fire_event` | `preprocessing/source_path.py`, `filtering/guard_filter.py` |
| `agent_actions.logging.events` | `FileWriteStartedEvent`, `FileWriteCompleteEvent`, `GuardEvaluationTimeoutEvent`, `GuardEvaluationErrorEvent` | `preprocessing/source_path.py`, `filtering/guard_filter.py` |
| `agent_actions.utils.service_logger` | `ServiceLogger` | `context/historical.py`, `preprocessing/source_path.py` |
| `agent_actions.utils.dict` | `get_nested_value` | `filtering/guard_filter.py`, `parsing/ast_nodes.py` |
| `agent_actions.utils.constants` | `SPECIAL_NAMESPACES`, `CHUNK_CONFIG_KEY` | `field_resolution/`, `staging/initial_pipeline.py` |
| `agent_actions.utils.module_loader` | `ensure_path_importable` | `loaders/udf.py`, `transformation/string_transformer.py` |
| `agent_actions.utils.udf_management` | `UDF_REGISTRY`, `get_udf`, `execute_user_defined_function` | `loaders/udf.py`, `filtering/evaluator.py`, `filtering/service.py` |
| `agent_actions.utils.field_management.manager` | `FieldManager` | `filtering/guard_handler.py` |
| `agent_actions.utils.output_splitter` | `split_main_and_side_outputs` | `preprocessing/processing/data_processor.py` |
| `agent_actions.utils.id_generation` | `IDGenerator` | `staging/initial_pipeline.py` |
| `agent_actions.storage.backend` | `StorageBackend` | `context/historical.py`, `loaders/source_data.py` (TYPE_CHECKING) |
| `agent_actions.llm.batch.infrastructure.batch_data_loader` | `*` (wildcard) | `loaders/__init__.py` |
| `agent_actions.llm.batch.service` | `BatchService` | `staging/initial_pipeline.py` (lazy) |
| External: `tiktoken`, `pyparsing`, `yaml`, `PyPDF2`, `pandas`, `spacy`, `docx`, `bs4` | Various | `string_transformer.py`, `parser.py`, `yaml.py`, `file_reader.py` |

### Downstream (imported by)

| Consumer Folder | Symbols Consumed | Stability Risk |
|---|---|---|
| `agent_actions.processing.helpers` | `get_guard_evaluator` | Low -- single function |
| `agent_actions.processing.processor` | `DataTransformer` | Low -- utility class |
| `agent_actions.processing.task_preparer` | `DataTransformer`, `get_guard_evaluator` | Medium -- used in core processing |
| `agent_actions.prompt.prompt_utils` | `StringProcessor` | Low -- single static method |
| `agent_actions.prompt.context.scope` | `HistoricalNodeDataLoader`, `HistoricalDataRequest` | High -- central to context building |
| `agent_actions.prompt.context.builder` | `DataTransformer` | Low |
| `agent_actions.output.response.expander` | `ReferenceValidator`, `ReferenceParser` | Medium -- output validation |
| `agent_actions.workflow.pipeline` | `FileReader`, `SourceDataLoader` | Medium -- workflow orchestration |
| `agent_actions.workflow.coordinator` | `discover_udfs` | Low |
| `agent_actions.workflow.strategies` | `process_initial_stage`, `InitialStageContext` | High -- entry point for pipeline |
| `agent_actions.workflow.managers.loop` | `_should_save_source_items` | Medium -- imports a private function |
| `agent_actions.workflow.managers.skip` | `GuardFilter`, `FilterItemRequest`, `get_global_guard_filter` | Medium -- guard evaluation |
| `agent_actions.llm.realtime.config` | `normalize_all_agent_configs` | Medium -- config normalization |
| `agent_actions.llm.providers.*.client` | `StringProcessor`, `DataTransformer` | Low -- utility usage |
| `agent_actions.llm.batch.processing.result_processor` | `DataTransformer` | Low |
| `agent_actions.config.di.configurator` | `DataProcessor` (lazy) | Low |
| `agent_actions.config.di.application` | `SourceDataLoader`, `DataProcessor` | Medium -- DI setup |
| `agent_actions.validation.validate_udfs` | `discover_udfs`, `validate_udf_references` | Low |
| `agent_actions.cli.list_udfs` | `discover_udfs` | Low |
| `agent_actions.utils.transformation.strategies.*` | `DataTransformer` | Low |

### Dependency Risks

- **P1-1 (Guard evaluation consolidation):** Directly affects `processing/helpers.py`, `processing/task_preparer.py`, `workflow/managers/skip.py`. These import from different layers of the guard stack. Consolidation requires updating all three consumers.
- **P1-2 (initial_pipeline simplification):** `workflow/strategies.py` imports `process_initial_stage` and `InitialStageContext`. `workflow/managers/loop.py` imports the private function `_should_save_source_items`. The private function import is fragile and should be promoted to a public API or moved.
- **P2-5 (FileReader consolidation):** `workflow/pipeline.py` directly imports `FileReader`. Changes to its interface would affect the workflow pipeline.
- **P3-17 (llm.batch wildcard import):** Removing this import from `loaders/__init__.py` would break any consumer that currently imports batch-related symbols from `agent_actions.input.loaders`.
- **P2-8 (EvaluationContext rename):** The WHERE clause `EvaluationContext` from `ast_nodes.py` is exported via `preprocessing/__init__.py`. Renaming it requires updating downstream imports in any module using WHERE clause evaluation context.

## Recommended Simplification Order

1. **P3-10, P3-11, P3-14, P3-15, P3-16** -- Quick cosmetic fixes (remove DEBUG prefixes, version string, list-to-set, operator caching). Zero risk, immediate readability improvement. **~1 hour.**

2. **P1-2** -- Extract `_derive_workflow_root()` helper from `initial_pipeline.py`. This eliminates the triplicated path derivation logic and is self-contained. **~2 hours.**

3. **P2-7** -- Consolidate `source_guid` extraction between `context_preprocessor.py` and `source_path.py`. Small, localized change. **~30 minutes.**

4. **P2-6** -- Extract shared YAML formatting helper in `yaml.py`. Self-contained, no cross-folder impact. **~1 hour.**

5. **P1-3** -- Simplify chunking strategies. Either inline `Tokenizer.split_text_content()` calls into `FieldChunker` or move actual splitting logic into the strategies. Self-contained within `chunking/`. **~2 hours.**

6. **P2-8** -- Rename `EvaluationContext` in `ast_nodes.py` to `WhereClauseContext`. Requires updating `preprocessing/__init__.py` exports and any direct importers. **~1 hour.**

7. **P2-4** -- Consolidate nested path resolution into a single utility. Affects `resolver.py`, `guard_filter.py`, and `ast_nodes.py`. **~2 hours.**

8. **P1-1** -- Consolidate the guard evaluation stack. This is the highest-impact change but requires coordinated updates across `filtering/`, `processing/`, and `workflow/` folders. Best done as a dedicated task with thorough testing. **~1-2 days.**

9. **P2-5** -- Consolidate `FileReader` with typed loaders. Requires careful handling of PDF/DOCX/XLSX dependencies. **~4 hours.**

10. **P3-17** -- Address the `llm.batch` wildcard import in `loaders/__init__.py`. Requires deprecation period if external consumers depend on it. **~1 hour + deprecation notice.**
