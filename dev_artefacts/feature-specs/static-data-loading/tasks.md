# Implementation Plan: Context Scope Static Data Loading

## Overview

This implementation plan breaks down the static data loading feature into manageable tasks with clear dependencies and requirement traceability.

---

## Tasks

### Phase 1: Core StaticDataLoader Implementation

- [x] 1. Create StaticDataLoader module and basic structure
  - [x] 1.1 Create module file
    - Create `agent_actions/utilities/static_data_loader.py` ✓
    - Define `StaticDataLoader` class with `__init__` method ✓
    - Set up basic configuration (static_data_dir, cache dict, constants) ✓
    - _Requirements: 1.1, 7.1_

  - [x] 1.2 Implement file path parsing
    - Write `_parse_file_path()` method to extract path from `$file:` prefix ✓
    - Handle both `$file:path` and plain `path` formats ✓
    - Add unit tests for parsing logic (TODO)
    - _Requirements: 1.2_

  - [x] 1.3 Implement path resolution logic
    - Write `_resolve_path()` method to resolve paths relative to static_data_dir ✓
    - Reject absolute paths immediately (security) ✓
    - Add logic to resolve relative paths within static_data/ folder ✓
    - Support subdirectories within static_data/ (e.g., reference/taxonomy.json) ✓
    - Test with various path formats (relative, absolute, with/without `..`) (TODO)
    - _Requirements: 2.1, 2.4, 2.6, 2.7_

  - [x] 1.4 Implement path security validation
    - Write `_validate_path_security()` method ✓
    - Check if resolved path is within static_data_dir using `Path.relative_to()` ✓
    - Raise `StaticDataLoadError` for security violations ✓
    - Add unit tests for path traversal attempts (TODO)
    - Test that paths cannot escape static_data/ folder (TODO)
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

---

### Phase 2: File Loading and Parsing

- [x] 2. Implement file format parsers
  - [x] 2.1 Create file loading orchestrator
    - Write `_load_file()` method that dispatches to format-specific parsers ✓
    - Detect file type from extension ✓
    - Handle file size validation (MAX_FILE_SIZE_BYTES) ✓
    - Raise errors for unsupported formats ✓
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.2_

  - [x] 2.2 Implement JSON parser
    - Write `_load_json()` method using Python's `json` module ✓
    - Handle JSON parse errors with clear messages ✓
    - Add unit tests with valid/invalid JSON files (TODO)
    - _Requirements: 3.1_

  - [x] 2.3 Implement YAML parser
    - Write `_load_yaml()` method using PyYAML ✓
    - Handle YAML parse errors with clear messages ✓
    - Add unit tests with valid/invalid YAML files (TODO)
    - _Requirements: 3.2_

  - [x] 2.4 Implement text/Markdown parser
    - Write `_load_text()` method for plain text and Markdown ✓
    - Read file content as UTF-8 string ✓
    - Add unit tests with various text files (TODO)
    - _Requirements: 3.3_

  - [x] 2.5 Implement CSV parser
    - Write `_load_csv()` method using Python's `csv.DictReader` ✓
    - Parse CSV to list of dictionaries ✓
    - Handle CSV parse errors ✓
    - Add unit tests with valid/invalid CSV files (TODO)
    - _Requirements: 3.4_

---

### Phase 3: Caching and Main Interface

- [x] 3. Implement caching mechanism
  - [x] 3.1 Implement cache logic in load_static_data()
    - Check cache before loading file ✓
    - Store loaded data in cache with file path as key ✓
    - Return cached data on subsequent loads ✓
    - _Requirements: 7.1, 7.2, 7.4_

  - [x] 3.2 Implement cache management methods
    - Write `clear_cache()` method to clear cache between workflow runs ✓
    - Write `get_cache_stats()` method for debugging ✓
    - Add cache size calculation (memory usage) ✓
    - _Requirements: 7.3, 7.5_

  - [x] 3.3 Implement main load_static_data() method
    - Iterate over static_data_config entries ✓
    - Call helper methods for parsing, resolving, validating, loading ✓
    - Aggregate loaded data into result dictionary ✓
    - Handle and propagate errors ✓
    - _Requirements: 1.1, 1.3, 1.4_

---

### Phase 4: Error Handling

- [x] 4. Create custom exception class
  - [x] 4.1 Define StaticDataLoadError exception
    - Create exception class inheriting from `FileSystemError` ✓
    - Include field_name, file_path, error_type in context ✓
    - Add factory methods for common error types (implemented via direct instantiation) ✓
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.2 Add error handling for all failure modes
    - File not found errors with full path ✓
    - File too large errors with size details ✓
    - Unsupported format errors with supported list ✓
    - Parse errors with specific error details ✓
    - Security violation errors with paths ✓
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 4.3 Add logging for debugging
    - Log resolved file paths at DEBUG level ✓
    - Log cache hits/misses at DEBUG level ✓
    - Log loaded data summary at INFO level ✓
    - Log errors at ERROR level before raising ✓
    - _Requirements: 2.5_

---

### Phase 5: PromptPreparationService Integration

- [x] 5. Integrate StaticDataLoader into prompt preparation pipeline
  - [x] 5.1 Add workflow_config_path to agent_config
    - In `AgentWorkflow._load_configs()` method ✓
    - Add `agent_config['workflow_config_path'] = self.constructor_path` for each agent ✓
    - This makes workflow config path available downstream ✓
    - _Requirements: 2.5_

  - [x] 5.2 Implement _determine_static_data_dir() helper
    - Create static method in `PromptPreparationService` ✓
    - Determine workflow root directory from workflow_config_path ✓
    - Handle agent_config/ subdirectory (go up one level to workflow root) ✓
    - Check for static_data/ folder (preferred) ✓
    - Check for seed/ folder (alternative) ✓
    - Raise error if neither exists with helpful message ✓
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 4.6_

  - [x] 5.3 Add static data loading step
    - Import `StaticDataLoader` in `prompt_preparation_service.py` ✓
    - Add Step 2.5 in `prepare_prompt_with_context()` to load static data ✓
    - Extract `context_scope.static_data` from agent_config ✓
    - Get workflow_config_path from agent_config ✓
    - Call `_determine_static_data_dir()` to get static data folder ✓
    - Create `StaticDataLoader(static_data_dir=static_data_dir)` ✓
    - _Requirements: 1.1, 2.1, 6.6_

  - [x] 5.4 Handle errors in static data loading
    - Wrap static data loading in try/except ✓
    - Log errors before re-raising ✓
    - Ensure workflow fails fast on static data errors ✓
    - Handle missing static_data/ folder error gracefully ✓
    - _Requirements: 2.3, 5.6_

  - [x] 5.5 Pass static_data to ContextScopeProcessor
    - Pass loaded static_data dict to `apply_context_scope()` ✓
    - Update method signature to accept optional static_data parameter ✓
    - _Requirements: 6.1, 6.2_

---

### Phase 6: ContextScopeProcessor Integration

- [x] 6. Modify ContextScopeProcessor to handle static data
  - [x] 6.1 Update apply_context_scope() signature
    - Add optional `static_data: Optional[Dict] = None` parameter ✓
    - Update docstring to document static_data parameter ✓
    - _Requirements: 6.1, 6.2_

  - [x] 6.2 Add static data to prompt_context
    - Merge static_data fields into prompt_context as top-level fields ✓
    - Enable field reference replacement for static data (e.g., `{exam_syllabus}`) ✓
    - Log conflict warnings if static data overwrites existing fields ✓
    - _Requirements: 1.3, 6.1, 1.5_

  - [x] 6.3 Add static data to llm_context
    - Merge static_data fields into llm_additional_context ✓
    - Make static data visible to LLM model ✓
    - _Requirements: 6.2_

  - [x] 6.4 Ensure static data works with other directives
    - Test that static data works with `observe` directive (TODO - needs testing)
    - Verify `drop` directive doesn't affect static data (TODO - needs testing)
    - Verify `passthrough` works independently of static data (TODO - needs testing)
    - _Requirements: 6.3, 6.4, 6.5_

---

### Phase 7: Testing

- [ ] 7. Create comprehensive unit tests
  - [ ] 7.1 Test StaticDataLoader file parsing
    - Test `$file:` prefix parsing
    - Test plain path parsing
    - Test various file extensions
    - _Requirements: 1.2_

  - [ ] 7.2 Test path resolution
    - Test relative path resolution within static_data/ folder
    - Test absolute path rejection (should raise error)
    - Test subdirectory paths (e.g., reference/taxonomy.json)
    - Test static_data/ vs seed/ folder detection
    - Test missing static_data/ folder error
    - Test path normalization
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7_

  - [ ] 7.3 Test security validation
    - Test path traversal prevention (`../../etc/passwd`)
    - Test absolute path rejection (`/etc/passwd`)
    - Test escaping static_data/ folder (`../schema/data.json`)
    - Test valid paths within static_data/ folder
    - Test symlink security (if symlink points outside static_data/)
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [ ] 7.4 Test file format parsers
    - Test JSON loading with valid/invalid files
    - Test YAML loading with valid/invalid files
    - Test text/Markdown loading
    - Test CSV loading with valid/invalid files
    - Test unsupported format error
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ] 7.5 Test error handling
    - Test file not found error
    - Test file too large error
    - Test parse errors for each format
    - Test security violation error
    - Verify error messages contain required context
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 7.6 Test caching behavior
    - Test cache hit on second load
    - Test cache sharing across field names
    - Test clear_cache() functionality
    - Test get_cache_stats() output
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 7.7 Test backward compatibility
    - Test workflow without static_data works unchanged
    - Test empty static_data config is skipped
    - Test null static_data config is skipped
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

---

### Phase 8: Integration Testing

- [ ] 8. Create integration tests
  - [ ] 8.1 Test PromptPreparationService integration
    - Create test workflow with static_data config
    - Verify static data is loaded during prompt preparation
    - Verify loaded data appears in formatted_prompt
    - Verify loaded data appears in llm_context
    - _Requirements: 1.1, 1.3, 6.1, 6.2_

  - [ ] 8.2 Test field reference replacement
    - Create prompt with `{static_field}` references
    - Verify static data values are substituted
    - Test with various data types (string, object, array)
    - _Requirements: 1.3_

  - [ ] 8.3 Test context_scope integration
    - Test static_data with observe directive
    - Test static_data with drop directive
    - Test static_data with passthrough directive
    - Test all directives together
    - _Requirements: 6.3, 6.4, 6.5_

  - [ ] 8.4 Test batch and realtime modes
    - Verify static data works in batch mode
    - Verify static data works in realtime mode
    - Verify caching works across records in batch
    - _Requirements: 6.6_

  - [ ] 8.5 Test error propagation
    - Verify static data errors stop workflow
    - Verify error context is preserved
    - Verify error artifacts are created
    - _Requirements: 5.6_

---

### Phase 9: End-to-End Testing

- [ ] 9. Create end-to-end workflow tests
  - [ ] 9.1 Create test workflow with static data
    - Set up test project structure
    - Create workflow config with static_data
    - Create test static data files (JSON, YAML, MD)
    - Create test staging data
    - _Requirements: 1.1_

  - [ ] 9.2 Run complete workflow
    - Execute workflow end-to-end
    - Verify static data is loaded
    - Verify static data is used in prompts
    - Verify output contains expected results
    - _Requirements: All requirements_

  - [ ] 9.3 Test real-world use cases
    - Test exam syllabus reference use case
    - Test taxonomy/ontology use case
    - Test few-shot examples use case
    - _Requirements: 1.1, 1.4_

  - [ ] 9.4 Performance testing
    - Measure file loading time
    - Measure cache lookup time
    - Measure memory overhead
    - Verify performance targets met
    - _Requirements: 7.1, 7.2_

---

### Phase 10: Documentation and Finalization

- [ ] 10. Create user documentation
  - [ ] 10.1 Write user guide
    - Document static_data syntax and usage
    - Provide examples for each file format
    - Explain path resolution rules
    - Document security considerations
    - _Requirements: All requirements_

  - [ ] 10.2 Write API reference
    - Document StaticDataLoader class and methods
    - Document PromptPreparationService changes
    - Document ContextScopeProcessor changes
    - Include code examples
    - _Requirements: All requirements_

  - [ ] 10.3 Write migration guide
    - Document how to migrate from embedded data
    - Provide before/after examples
    - Explain benefits and best practices
    - _Requirements: 1.1_

  - [ ] 10.4 Write troubleshooting guide
    - Document common errors and solutions
    - Provide debugging tips
    - Include FAQ section
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 10.5 Update changelog
    - Add feature to changelog
    - Document breaking changes (if any)
    - Document migration steps
    - _Requirements: 8.1_

---

### Phase 11: Code Review and Refinement

- [ ] 11. Code review and quality assurance
  - [ ] 11.1 Internal code review
    - Review code for best practices
    - Check error handling completeness
    - Verify logging is appropriate
    - Check for security issues
    - _Requirements: All requirements_

  - [ ] 11.2 Performance optimization
    - Profile file loading performance
    - Optimize cache lookups
    - Minimize memory overhead
    - _Requirements: 7.1, 7.2_

  - [ ] 11.3 Security audit
    - Review path traversal prevention
    - Check for injection vulnerabilities
    - Verify file access controls
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ] 11.4 Final testing pass
    - Run all unit tests
    - Run all integration tests
    - Run end-to-end tests
    - Fix any failing tests
    - _Requirements: All requirements_

---

## Task Dependencies

### Critical Path

```
1.1 → 1.2 → 1.3 → 1.4 → 2.1 → 2.2-2.5 → 3.1 → 3.2 → 3.3 → 4.1-4.3 → 5.1-5.4 → 6.1-6.4 → 7.1-7.7 → 8.1-8.5 → 9.1-9.4 → 10.1-10.5 → 11.1-11.4
```

### Parallel Work Opportunities

- Tasks 2.2, 2.3, 2.4, 2.5 can be done in parallel (file parsers)
- Tasks 7.1-7.7 can be done in parallel (unit tests)
- Tasks 8.1-8.5 can be done in parallel (integration tests)
- Tasks 10.1-10.5 can be done in parallel (documentation)

---

## Estimated Effort

| Phase | Tasks | Estimated Hours |
|-------|-------|----------------|
| Phase 1: Core StaticDataLoader | 1.1-1.4 | 6 hours |
| Phase 2: File Parsers | 2.1-2.5 | 6 hours |
| Phase 3: Caching | 3.1-3.3 | 4 hours |
| Phase 4: Error Handling | 4.1-4.3 | 3 hours |
| Phase 5: PromptPrep Integration | 5.1-5.4 | 4 hours |
| Phase 6: ContextScope Integration | 6.1-6.4 | 4 hours |
| Phase 7: Unit Tests | 7.1-7.7 | 8 hours |
| Phase 8: Integration Tests | 8.1-8.5 | 6 hours |
| Phase 9: E2E Tests | 9.1-9.4 | 4 hours |
| Phase 10: Documentation | 10.1-10.5 | 6 hours |
| Phase 11: Review & QA | 11.1-11.4 | 4 hours |
| **Total** | **55 hours** | **~1.5 weeks** |

---

## Success Criteria

- [ ] All unit tests passing (100% coverage of StaticDataLoader)
- [ ] All integration tests passing
- [ ] End-to-end workflow tests passing
- [ ] Performance targets met (<100ms overhead)
- [ ] Security audit passed (no vulnerabilities)
- [ ] Documentation complete and reviewed
- [ ] Zero breaking changes to existing workflows
- [ ] User acceptance testing completed
- [ ] Code reviewed and approved

---

## Rollout Plan

1. **Phase 1**: Merge to development branch
2. **Phase 2**: Internal testing with sample workflows
3. **Phase 3**: Beta release to select users
4. **Phase 4**: Gather feedback and iterate
5. **Phase 5**: General availability release
6. **Phase 6**: Monitor adoption and performance

---

**Created**: 2025-01-20
**Status**: Planning
**Owner**: Agent Actions Core Team
**Target Release**: v1.3.0
