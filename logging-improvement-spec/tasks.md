# Implementation Plan

- [x] 1. Create logging infrastructure module ✅
  - [x] 1.1 Create `agent_actions/logging/` package structure
    - Create __init__.py with public exports
    - Create config.py with LoggingConfig dataclass
    - Create context.py with CorrelationContext class
    - _Requirements: 2.1, 3.1, 7.1_

  - [x] 1.2 Implement context management with contextvars
    - Create ExecutionContext dataclass
    - Implement ContextVar storage for thread-safety
    - Add start_workflow, set_agent, clear_context methods
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 1.3 Create custom log filter for context injection
    - Implement ContextInjectingFilter class
    - Inject correlation_id, workflow_name, agent_name, agent_index
    - Add fallback values when context not available
    - _Requirements: 2.2, 2.3, 2.4_

  - [x] 1.4 Write unit tests for context management
    - Test context creation and retrieval
    - Test context propagation across function calls
    - Test context isolation between executions
    - _Requirements: 2.1, 2.2_

- [x] 2. Implement log formatters ✅
  - [x] 2.1 Create JSONFormatter class
    - Format log records as single-line JSON
    - Include all standard fields (timestamp, level, message, source)
    - Include context fields (correlation_id, agent_name, etc.)
    - Handle exception info serialization
    - _Requirements: 3.1, 3.3, 3.4_

  - [x] 2.2 Create HumanFormatter class
    - Format for console readability with colors
    - Include abbreviated context (correlation_id, agent)
    - Format timestamps as HH:MM:SS.mmm
    - Handle multiline exception output
    - _Requirements: 3.2, 3.4_

  - [x] 2.3 Write unit tests for formatters
    - Test JSON output is valid and complete
    - Test human format readability
    - Test exception formatting in both modes
    - _Requirements: 3.1, 3.2_

- [x] 3. Implement LoggerFactory ✅
  - [x] 3.1 Create LoggerFactory singleton
    - Implement initialize() with configuration loading
    - Create get_logger() method for consistent logger creation
    - Ensure all loggers under agent_actions namespace
    - _Requirements: 7.1, 7.2_

  - [x] 3.2 Add handler configuration
    - Support console, file, and JSON handlers
    - Implement RotatingFileHandler for file output
    - Add handler-specific log levels
    - _Requirements: 7.4_

  - [x] 3.3 Add module-specific level configuration
    - Allow per-module log level overrides
    - Control third-party library verbosity
    - Support runtime level changes
    - _Requirements: 4.3, 7.3, 7.5_

  - [x] 3.4 Write integration tests for LoggerFactory
    - Test initialization with various configs
    - Test handler creation and output
    - Test module-level configuration
    - _Requirements: 7.1, 7.4_

- [x] 4. Create configuration integration ✅
  - [x] 4.1 Add logging schema to project configuration
    - Define log_level field in project.yaml schema
    - Add handlers configuration section
    - Add module_levels for fine-grained control
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.2 Implement environment variable support
    - Support AGENT_ACTIONS_LOG_LEVEL env var
    - Support AGENT_ACTIONS_LOG_FORMAT env var
    - Document environment configuration
    - _Requirements: 4.5_

  - [x] 4.3 Add --debug CLI flag support
    - Wire --debug flag to set DEBUG level
    - Override config and env settings when flag present
    - _Requirements: 4.4_

  - [x] 4.4 Update default log level from CRITICAL to INFO
    - Change default in LoggingConfig
    - Update any hardcoded CRITICAL references
    - Test default behavior
    - _Requirements: 4.2_

- [x] 5. Fix silent exception handlers (Phase 1: Critical Paths) ✅
  - **Phase 1-2: Additional fixes (not in original spec):**
    - [x] Fixed 2 bare `except:` statements in `output_manager.py` (lines 113, 123)
    - [x] Fixed 2 silent JSON failures in `loop_correlator.py` (lines 120, 140)
    - [x] Added DI fallback logging in `application_container.py` (lines 99-117)
    - _Commit: f405088_

  - [x] 5.1 Fix agent_executor.py exception handling ✅
    - Added structured logging to _execute_agent_run exception handler (sync)
    - Added structured logging to _execute_agent_run_async exception handler (async)
    - Protected cleanup operations in finally blocks with exception handling
    - Includes full execution context: agent_name, agent_idx, duration, is_last_agent
    - Uses ERROR level with exc_info=True for full tracebacks
    - _Commit: 62cedb6_
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 5.2 Fix agent_workflow.py exception handling ✅
    - Added correlation context initialization (CorrelationContext.start_workflow)
    - Set agent context before each execution (CorrelationContext.set_agent)
    - Added workflow start logging with agent_count and concurrency_limit
    - Added workflow completion logging with duration and success metrics
    - Added workflow failure logging with exc_info=True
    - Implemented context cleanup in finally blocks
    - Applied to both run() (sync) and async_run() (async) methods
    - _Commit: 8be2ae7_
    - _Requirements: 1.1, 1.4, 2.1_

  - [x] 5.3 Fix validation_interceptor.py exception handling ✅
    - Converted 19 print statements to structured logging
    - Removed dependency on prompt_debug flag
    - Added proper log levels: DEBUG (config/execution), INFO (results), WARNING (retries), ERROR (failures)
    - Split exception handling: ConfigurationError/AgentActionsException vs unexpected Exception
    - All exceptions logged with exc_info=True for full tracebacks
    - Added structured context to all logs (validator_function, validator_args, error_message)
    - _Commit: bb1ce5d_
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 5.4 Fix vendor API exception handlers (P0 Critical) ✅
    - **gemini_vendor.py**: Added comprehensive exception handling (previously had ZERO)
      - Wrapped json.loads() with JSONDecodeError handling
      - Added API call exception handling
      - DEBUG logging for success, ERROR with exc_info for failures
    - **deepseek_vendor.py**: Added comprehensive exception handling (previously had ZERO)
      - Added empty response validation
      - Added JSON parsing error handling
      - Structured logging with model and operation context
    - **mistral_vendor.py**: Added comprehensive exception handling (previously had ZERO)
      - Added exception handling for both call_json and call_non_json
      - JSON parsing protection with detailed error context
    - **cohere_vendor.py**: Added comprehensive exception handling (previously had ZERO)
      - Added empty response validation
      - JSON parsing error handling with line numbers
      - Full API call exception coverage
    - All vendors now raise VendorAPIError with exception chaining (cause=)
    - All vendors log with structured context: operation, model, error details
    - _Commit: e3004a6_
    - _Requirements: 1.1, 5.1, 5.2_

- [x] 6. Fix silent exception handlers (Phase 2: Supporting Modules) - **ALL P0 & P1 COMPLETE** ✅
  - **Comprehensive audit completed via 3 parallel exploration agents**
  - **Fixed all 8 P0 (Critical) issues causing silent data loss**
  - **Fixed all 17 P1 (High Priority) issues improving debuggability**
  - **Total issues identified: 8 P0, 17 P1, 12 P2 across 37 exception handlers**
  - **Remaining: 12 P2 (Medium Priority) minor debug logging enhancements**

  - [x] **Phase 1 P0: Critical Batch Processing** (Commit: 3355635) ✅
    - Fixed batch_service.py line 206: Silent batch status check failure
    - Fixed batch_service.py line 232: Missing exc_info and batch context in processing failures
    - Fixed batch_service.py line 335: Silent batch registry validation failure
    - Fixed extractors_source_data_loader.py line 135: Silent source content load failure
    - Fixed staging_loader.py line 46: Silent JSON parsing failure in batch mode
    - All handlers now include exc_info=True, structured logging with batch_id/file_name/operation

  - [x] **Phase 2 P0: Critical File Operations** (Commit: 6bcfba7) ✅
    - Fixed template_yaml_loader.py lines 14-23: Added comprehensive exception handling (previously ZERO)
      - File I/O errors: FileNotFoundError, PermissionError, UnicodeDecodeError
      - Template preprocessing errors with full context
      - YAML parsing errors with YAMLError handling
    - Fixed base.py line 28: Silent version retrieval now logs with exc_info=True
    - Fixed config_handler.py line 108: Silent project defaults loading now logs warnings

  - [x] **Phase 3 P1: Core & Configuration Modules** (Commit: 00deeaa) ✅
    - Fixed parser.py lines 378, 239: Added exc_info=True, logging for silent operator fallback
    - Fixed schema_validator.py line 56: Added exc_info and structured context for meta-schema validation
    - Fixed base_async_processor.py lines 104, 125: Added INFO logging for aiofiles ImportError fallback
    - Fixed config_validator.py lines 38, 58: Added exc_info=True for validation errors
    - Fixed bootstrap_bootstrap.py line 68: Added exc_info and error details for startup validation failure

  - [x] **Phase 4 P1: Tasks Modules** (Commits: 5f3e699, 8099dec) ✅
    - Fixed batch_service.py lines 403, 312: Added debug logging for status aggregation, exc_info for file read
    - Fixed batch_side_output_handler.py line 64: Added warning logging for JSON decode with error position
    - Fixed extractors_source_data_loader.py line 75: Added debug logging for path validation failure
    - Fixed where_parser.py lines 188, 209: Added debug logging for where clause evaluation failures
    - Fixed utils_processor_helpers.py lines 100, 119: Added debug logging for where clause check failures
    - Fixed utils_path_utils.py line 143: Added debug logging for path permission validation
    - Fixed operator_registry/registry.py line 46: Added debug logging for operator instantiation during discovery

  - [ ] 6.4 Write integration tests for exception logging
    - Test exception chain preservation
    - Test correlation ID in error logs
    - Test log output format for exceptions
    - _Requirements: 1.1, 1.2, 1.5_

- [ ] 7. Replace print statements with logging
  - [ ] 7.1 Convert validation_interceptor.py print statements
    - Replace prompt_debug prints with DEBUG level logs
    - Use structured logging with validation context
    - Remove prompt_debug flag pattern
    - _Requirements: 3.5, 5.3_

  - [ ] 7.2 Convert agent_runner.py print statements
    - Identify all print() calls
    - Replace with appropriate log levels
    - Include agent context in logs
    - _Requirements: 3.5_

  - [ ] 7.3 Convert CLI output print statements
    - Distinguish user-facing output from diagnostic logs
    - Keep Rich console for user output
    - Route diagnostic messages to logging
    - _Requirements: 3.5_

  - [ ] 7.4 Create migration test to catch new print statements
    - Add test that greps for print() in source
    - Allowlist legitimate print uses (CLI output)
    - Fail CI on new unauthorized prints
    - _Requirements: 3.5_

- [ ] 8. Add performance and debug logging
  - [ ] 8.1 Add execution timing logs
    - Log agent start/complete with duration
    - Log workflow total duration
    - Log API call durations at DEBUG level
    - _Requirements: 6.1, 6.2, 6.5_

  - [ ] 8.2 Add batch processing metrics
    - Log batch size and throughput
    - Log individual item processing at DEBUG
    - Include batch_id in correlation context
    - _Requirements: 6.3_

  - [ ] 8.3 Add retry attempt logging
    - Log retry attempts with attempt number
    - Log wait times between retries
    - Include retry configuration in logs
    - _Requirements: 6.4_

  - [ ] 8.4 Add API request/response DEBUG logging
    - Log sanitized request parameters
    - Log response metadata (status, timing)
    - Implement credential redaction
    - _Requirements: 5.1, 5.2, 5.5_

- [ ] 9. Implement credential redaction
  - [ ] 9.1 Create RedactingFilter class
    - Define patterns for API keys, secrets, tokens
    - Support vendor-specific key patterns (sk-*, anthropic-*)
    - Apply to all log handlers
    - _Requirements: 5.5_

  - [ ] 9.2 Add redaction to extra fields
    - Redact sensitive keys in extra dict
    - Support nested dict redaction
    - Test redaction thoroughness
    - _Requirements: 5.5_

  - [ ] 9.3 Write security tests for redaction
    - Test various API key formats are redacted
    - Test env var values are not leaked
    - Test nested sensitive data
    - _Requirements: 5.5_

- [ ] 10. Add helpful error messages
  - [ ] 10.1 Add fix suggestions to ConfigurationError logs
    - Include valid alternatives for invalid values
    - Link to documentation for complex configs
    - Show example of correct format
    - _Requirements: 8.1_

  - [ ] 10.2 Add context to FileLoadError logs
    - Log attempted path and alternatives found
    - Suggest common file location issues
    - _Requirements: 8.2_

  - [ ] 10.3 Add retry info to NetworkError logs
    - Log current retry configuration
    - Suggest timeout adjustments
    - _Requirements: 8.3_

  - [ ] 10.4 Add field details to ValidationError logs
    - Log specific field that failed
    - Log constraint and actual value
    - _Requirements: 8.4_

- [ ] 11. Integration and documentation
  - [ ] 11.1 Initialize logging in CLI entry points
    - Call LoggerFactory.initialize() in main entry
    - Load config from project.yaml if available
    - Apply environment and CLI overrides
    - _Requirements: 7.1, 4.1_

  - [ ] 11.2 Update error-handling.md documentation
    - Add logging configuration section
    - Document correlation ID usage
    - Add examples for common patterns
    - _Requirements: 7.1_

  - [ ] 11.3 Add logging configuration to schema docs
    - Document log_level options
    - Document handler configuration
    - Document environment variables
    - _Requirements: 4.1, 4.5_

  - [ ] 11.4 Run full test suite and fix regressions
    - Run pytest with logging enabled
    - Fix any tests broken by logging changes
    - Verify log output in integration tests
    - _Requirements: 1.1, 2.1, 3.1_

- [ ] 12. Final audit and cleanup
  - [ ] 12.1 Re-run silent exception audit
    - Grep for bare except clauses
    - Grep for except Exception without logging
    - Verify all handlers log appropriately
    - _Requirements: 1.1, 1.3_

  - [ ] 12.2 Re-run print statement audit
    - Grep for remaining print() calls
    - Verify all are intentional user output
    - Document any exceptions
    - _Requirements: 3.5_

  - [ ] 12.3 Performance testing
    - Measure logging overhead in hot paths
    - Test async logging for batch operations
    - Verify no log-related memory leaks
    - _Requirements: 6.1_

  - [ ] 12.4 Create logging best practices guide
    - Document when to use each log level
    - Document context injection patterns
    - Add code examples for common scenarios
    - _Requirements: 7.1_
