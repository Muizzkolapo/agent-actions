# Implementation Plan

- [ ] 1. Create logging infrastructure module
  - [ ] 1.1 Create `agent_actions/logging/` package structure
    - Create __init__.py with public exports
    - Create config.py with LoggingConfig dataclass
    - Create context.py with CorrelationContext class
    - _Requirements: 2.1, 3.1, 7.1_

  - [ ] 1.2 Implement context management with contextvars
    - Create ExecutionContext dataclass
    - Implement ContextVar storage for thread-safety
    - Add start_workflow, set_agent, clear_context methods
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 1.3 Create custom log filter for context injection
    - Implement ContextInjectingFilter class
    - Inject correlation_id, workflow_name, agent_name, agent_index
    - Add fallback values when context not available
    - _Requirements: 2.2, 2.3, 2.4_

  - [ ] 1.4 Write unit tests for context management
    - Test context creation and retrieval
    - Test context propagation across function calls
    - Test context isolation between executions
    - _Requirements: 2.1, 2.2_

- [ ] 2. Implement log formatters
  - [ ] 2.1 Create JSONFormatter class
    - Format log records as single-line JSON
    - Include all standard fields (timestamp, level, message, source)
    - Include context fields (correlation_id, agent_name, etc.)
    - Handle exception info serialization
    - _Requirements: 3.1, 3.3, 3.4_

  - [ ] 2.2 Create HumanFormatter class
    - Format for console readability with colors
    - Include abbreviated context (correlation_id, agent)
    - Format timestamps as HH:MM:SS.mmm
    - Handle multiline exception output
    - _Requirements: 3.2, 3.4_

  - [ ] 2.3 Write unit tests for formatters
    - Test JSON output is valid and complete
    - Test human format readability
    - Test exception formatting in both modes
    - _Requirements: 3.1, 3.2_

- [ ] 3. Implement LoggerFactory
  - [ ] 3.1 Create LoggerFactory singleton
    - Implement initialize() with configuration loading
    - Create get_logger() method for consistent logger creation
    - Ensure all loggers under agent_actions namespace
    - _Requirements: 7.1, 7.2_

  - [ ] 3.2 Add handler configuration
    - Support console, file, and JSON handlers
    - Implement RotatingFileHandler for file output
    - Add handler-specific log levels
    - _Requirements: 7.4_

  - [ ] 3.3 Add module-specific level configuration
    - Allow per-module log level overrides
    - Control third-party library verbosity
    - Support runtime level changes
    - _Requirements: 4.3, 7.3, 7.5_

  - [ ] 3.4 Write integration tests for LoggerFactory
    - Test initialization with various configs
    - Test handler creation and output
    - Test module-level configuration
    - _Requirements: 7.1, 7.4_

- [ ] 4. Create configuration integration
  - [ ] 4.1 Add logging schema to project configuration
    - Define log_level field in project.yaml schema
    - Add handlers configuration section
    - Add module_levels for fine-grained control
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 4.2 Implement environment variable support
    - Support AGENT_ACTIONS_LOG_LEVEL env var
    - Support AGENT_ACTIONS_LOG_FORMAT env var
    - Document environment configuration
    - _Requirements: 4.5_

  - [ ] 4.3 Add --debug CLI flag support
    - Wire --debug flag to set DEBUG level
    - Override config and env settings when flag present
    - _Requirements: 4.4_

  - [ ] 4.4 Update default log level from CRITICAL to INFO
    - Change default in LoggingConfig
    - Update any hardcoded CRITICAL references
    - Test default behavior
    - _Requirements: 4.2_

- [ ] 5. Fix silent exception handlers (Phase 1: Critical Paths)
  - [ ] 5.1 Fix agent_executor.py exception handling
    - Add logging to _execute_agent_run exception handler (line 347)
    - Add logging to _execute_agent_run_async exception handler (line 415)
    - Preserve exception chains with cause parameter
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ] 5.2 Fix agent_workflow.py exception handling
    - Add logging to workflow execution failures
    - Log workflow completion with metrics
    - Add correlation context initialization
    - _Requirements: 1.1, 1.4, 2.1_

  - [ ] 5.3 Fix validation_interceptor.py exception handling
    - Log validation errors at appropriate levels
    - Include validator_function and validator_args in logs
    - Remove or convert prompt_debug prints to logger
    - _Requirements: 1.1, 1.3, 1.4_

  - [ ] 5.4 Fix vendor API exception handlers
    - Log API errors in openai_vendor.py
    - Log API errors in anthropic_vendor.py
    - Log API errors in google_vendor.py
    - Include request context (model, endpoint) in logs
    - _Requirements: 1.1, 5.1, 5.2_

- [ ] 6. Fix silent exception handlers (Phase 2: Supporting Modules)
  - [ ] 6.1 Audit and fix agent_actions/core/ modules
    - Review parser.py exception handlers
    - Review loader.py exception handlers
    - Review schema_validator.py exception handlers
    - _Requirements: 1.1, 1.3_

  - [ ] 6.2 Audit and fix agent_actions/configuration/ modules
    - Review base.py exception handlers
    - Review env_resolver.py exception handlers
    - Review hierarchy.py exception handlers
    - _Requirements: 1.1, 1.3_

  - [ ] 6.3 Audit and fix agent_actions/tasks/ modules
    - Review services/batch_service.py exception handlers
    - Review file operations exception handlers
    - Add correlation context to batch operations
    - _Requirements: 1.1, 2.4_

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
