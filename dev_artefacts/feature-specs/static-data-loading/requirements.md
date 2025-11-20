# Requirements Document: Context Scope Static Data Loading

## Introduction

This feature enables loading external static/seed data files in the `context_scope` configuration to make reference data (JSON, YAML, Markdown, etc.) available to all records in a workflow without duplicating the data in each input record. This improves efficiency, maintainability, and reduces memory overhead for workflows that require reference data like exam syllabi, taxonomies, compliance documents, or few-shot examples.

## Requirements

### Requirement 1

**User Story:** As a workflow author, I want to load static reference files in `context_scope.static_data`, so that I can make external data available to all records without embedding it in every source record.

#### Acceptance Criteria

1. WHEN I specify a file reference in `context_scope.static_data` THEN the system SHALL load the file contents and make them available in the prompt context
2. WHEN using the `$file:` prefix syntax THEN the system SHALL recognize it as a file reference and load the file
3. WHEN the static data file is loaded THEN it SHALL be available in prompts using `{field_name}` syntax
4. WHEN the workflow processes multiple records THEN the system SHALL load static data files only once per workflow run (cached)
5. IF a static data field name conflicts with an existing context field THEN the static data SHALL take precedence with a warning logged

#### Example Directory Structure

```
my_workflow/
├── agent_config/
│   └── config.yml
├── static_data/                    # Required folder
│   ├── azure_ds_associate_syllabus.json
│   ├── quality_rubric.yml
│   └── reference/
│       └── taxonomy.json
└── schema/
    └── output_schema.yml
```

#### Example Configuration

```yaml
context_scope:
  static_data:
    # Files are relative to static_data/ folder
    exam_syllabus: $file:azure_ds_associate_syllabus.json
    scoring_rubric: $file:quality_rubric.yml
    taxonomy: $file:reference/taxonomy.json  # Subdirectories allowed
  observe:
    - generate_summary.summary_content
```

#### Example Usage in Prompt

```yaml
prompt: |
  Review this summary against the official exam syllabus:

  Syllabus: {exam_syllabus}

  Summary to review: {generate_summary.summary_content}
```

---

### Requirement 2

**User Story:** As a workflow author, I want static data files to be organized in a designated `static_data/` or `seed/` folder, so that my reference data is clearly separated from other workflow files and easy to locate.

#### Acceptance Criteria

1. WHEN loading static data THEN the system SHALL look for files in a `static_data/` folder at the workflow root
2. IF `static_data/` folder does not exist THEN the system SHALL look for a `seed/` folder as an alternative
3. IF neither `static_data/` nor `seed/` folder exists THEN the system SHALL raise an error indicating which folders were checked
4. WHEN a static data file path is specified (e.g., `syllabus.json`) THEN the system SHALL resolve it relative to the `static_data/` or `seed/` folder
5. WHEN the workflow config is in `agent_workflow/my_workflow/agent_config/config.yml` THEN the system SHALL look for static data in `agent_workflow/my_workflow/static_data/` or `agent_workflow/my_workflow/seed/`
6. WHEN a file path contains subdirectories (e.g., `reference/taxonomy.json`) THEN the system SHALL resolve it as `static_data/reference/taxonomy.json`
7. WHEN a file path is absolute THEN the system SHALL reject it with an error (absolute paths not allowed for security)
8. WHEN resolving file paths THEN the system SHALL log the resolved absolute path for debugging

---

### Requirement 3

**User Story:** As a workflow author, I want support for multiple file formats, so that I can load reference data in the format most appropriate for my use case.

#### Acceptance Criteria

1. WHEN loading a `.json` file THEN the system SHALL parse it as JSON and return the parsed object
2. WHEN loading a `.yml` or `.yaml` file THEN the system SHALL parse it as YAML and return the parsed object
3. WHEN loading a `.md` or `.txt` file THEN the system SHALL return the raw text content as a string
4. WHEN loading a `.csv` file THEN the system SHALL parse it as CSV and return a list of dictionaries (with headers as keys)
5. IF the file extension is not recognized THEN the system SHALL raise an error listing supported formats
6. WHEN file parsing fails THEN the system SHALL raise an error with the file path and specific parsing error

---

### Requirement 4

**User Story:** As a system administrator, I want static data loading to be secure and prevent path traversal attacks, so that workflows can only access files in designated static data folders.

#### Acceptance Criteria

1. WHEN a static data file path contains `..` segments THEN the system SHALL validate the resolved path is within the `static_data/` or `seed/` folder
2. IF a resolved file path escapes the `static_data/` or `seed/` folder THEN the system SHALL reject the load and raise a security error
3. WHEN a file path is absolute (e.g., `/etc/passwd`) THEN the system SHALL reject it immediately without attempting to resolve
4. WHEN validating file paths THEN the system SHALL use Python's `Path.resolve()` to normalize paths before validation
5. WHEN the validation fails THEN the error SHALL include the attempted path and the allowed static data directory for debugging
6. WHEN neither `static_data/` nor `seed/` folder exists THEN the system SHALL raise a clear error before attempting to load any files

---

### Requirement 5

**User Story:** As a workflow author, I want clear error messages when static data files fail to load, so that I can quickly diagnose and fix configuration issues.

#### Acceptance Criteria

1. WHEN a static data file does not exist THEN the system SHALL raise an error with the full resolved file path
2. WHEN a static data file is too large (>10MB) THEN the system SHALL raise an error with the file size and limit
3. WHEN a file format is not supported THEN the system SHALL raise an error listing the supported formats
4. WHEN a file parsing error occurs THEN the system SHALL include the file path and specific parsing error details
5. WHEN a security violation is detected THEN the system SHALL include the attempted path and the project directory boundary
6. WHEN any static data error occurs THEN the workflow SHALL fail fast before processing any records

---

### Requirement 6

**User Story:** As a workflow author, I want static data to integrate with `context_scope` transformations, so that I can use static data alongside observe/drop/passthrough directives.

#### Acceptance Criteria

1. WHEN static data is loaded THEN it SHALL be added to the prompt context for field reference replacement
2. WHEN static data is loaded THEN it SHALL be added to the LLM additional context for model visibility
3. WHEN using `observe` directive with static data THEN both SHALL be merged into the LLM context
4. WHEN using `drop` directive THEN static data SHALL NOT be affected (drop only applies to action fields)
5. WHEN using `passthrough` directive with static data THEN both SHALL work independently
6. WHEN static data is present THEN it SHALL be available in both batch and realtime modes

---

### Requirement 7

**User Story:** As a performance engineer, I want static data to be cached efficiently, so that large reference files are not loaded repeatedly for each record.

#### Acceptance Criteria

1. WHEN a static data file is loaded for the first time THEN the system SHALL cache the parsed content in memory
2. WHEN the same file is referenced again in the same workflow run THEN the system SHALL use the cached content
3. WHEN a workflow run completes THEN the cache SHALL be cleared for the next run
4. WHEN multiple agents reference the same static file THEN the system SHALL share the cached content
5. IF memory usage becomes a concern THEN the system SHALL provide cache statistics for monitoring

---

### Requirement 8

**User Story:** As a workflow author, I want static data loading to be optional, so that workflows without static data continue to work unchanged.

#### Acceptance Criteria

1. WHEN `context_scope` does not include `static_data` THEN the system SHALL process the workflow normally without loading any files
2. WHEN `context_scope.static_data` is empty or null THEN the system SHALL skip file loading without errors
3. WHEN `context_scope.static_data` is defined but empty (`{}`) THEN the system SHALL process normally without loading files
4. IF `static_data` contains invalid entries THEN the system SHALL raise an error for those entries only
5. WHEN static data loading is skipped THEN no performance overhead SHALL be added to the workflow

---

## Success Metrics

1. **Efficiency**: Static data files loaded once per workflow run (not per record)
2. **Memory Reduction**: 90%+ reduction in input file size for workflows with large reference data
3. **Performance**: File loading adds <100ms overhead per workflow run
4. **Reliability**: 100% of file loading errors provide actionable error messages
5. **Security**: Zero path traversal vulnerabilities in production
6. **Adoption**: Used in 50%+ of workflows with reference data within 3 months

---

## Out of Scope

The following are explicitly out of scope for this feature:

1. **Remote URL loading** (`$url:https://...`) - May be added in future
2. **Environment variable substitution** in file paths - Use existing mechanisms
3. **File watching/hot reload** - Static data is loaded once per workflow run
4. **Binary file formats** (PDF, DOCX, etc.) - Only text-based formats supported
5. **Compression support** (`.gz`, `.zip`) - Files must be uncompressed
6. **Template/variable substitution** in loaded file contents - Load as-is

---

## Dependencies

- Python `pathlib` for path resolution and validation
- Python `json` module for JSON parsing
- Python `yaml` module (PyYAML) for YAML parsing
- Python `csv` module for CSV parsing
- Existing `PromptPreparationService` for integration
- Existing `ContextScopeProcessor` for context_scope handling

---

## Assumptions

1. Workflow config files are stored in accessible file system locations
2. Static data files are text-based and UTF-8 encoded
3. Static data files are relatively small (<10MB) and can be loaded into memory
4. Workflow authors have file system access to organize reference data files
5. Project directory structure follows agent-actions conventions

---

**Created**: 2025-01-20
**Status**: Draft
**Owner**: Agent Actions Core Team
**Priority**: High
