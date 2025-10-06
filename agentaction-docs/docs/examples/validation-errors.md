---
title: Validation Error Examples
description: Real-world examples of validation errors and how to fix them
sidebar_position: 5
---

# Input Signature Validation Errors

This guide provides real-world examples of validation errors you might encounter and how to fix them.

## Example 1: Dropped Field Reference

### The Error

```yaml
agents:
  - name: document_processor
    output_schema:
      properties:
        summary: {type: string}
        metadata: {type: object}
        processing_stats: {type: object}
    drops: [processing_stats]  # Remove internal metrics
    prompt: "Process and summarize the document"

  - name: report_generator
    prompt: |
      Generate report using:
      Summary: {document_processor.summary}
      Stats: {document_processor.processing_stats}
    depends_on: ["document_processor"]
```

### Error Message

```
❌ {document_processor.processing_stats}
   Field 'processing_stats' not available in 'document_processor' output
   → Available fields: ['summary', 'metadata']
```

### The Fix

**Option 1: Remove from drops**
```yaml
agents:
  - name: document_processor
    output_schema:
      properties:
        summary: {type: string}
        metadata: {type: object}
        processing_stats: {type: object}
    # Don't drop processing_stats
    prompt: "Process and summarize the document"
```

**Option 2: Don't reference the field**
```yaml
  - name: report_generator
    prompt: |
      Generate report using:
      Summary: {document_processor.summary}
      Metadata: {document_processor.metadata}
    depends_on: ["document_processor"]
```

## Example 2: Missing Observe Field

### The Error

```yaml
agents:
  - name: content_extractor
    output_schema:
      properties:
        title: {type: string}
        content: {type: string}
    # Forgot to add document_id to observe!
    prompt: "Extract title and content"

  - name: content_classifier
    prompt: |
      Classify this content from document {content_extractor.document_id}:
      {content_extractor.content}
    depends_on: ["content_extractor"]
```

### Error Message

```
❌ {content_extractor.document_id}
   Field 'document_id' not available in 'content_extractor' output
   → Available fields: ['title', 'content']
```

### The Fix

Add `document_id` to the observe list:

```yaml
agents:
  - name: content_extractor
    output_schema:
      properties:
        title: {type: string}
        content: {type: string}
    observe: [document_id]  # Pass through from input
    prompt: "Extract title and content"

  - name: content_classifier
    prompt: |
      Classify this content from document {content_extractor.document_id}:
      {content_extractor.content}
    depends_on: ["content_extractor"]
    # ✅ Now document_id is available
```

## Example 3: Undeclared Dependency

### The Error

```yaml
agents:
  - name: text_analyzer
    output_schema:
      properties:
        sentiment: {type: string}
        topics: {type: array}
    prompt: "Analyze the text"

  - name: summary_generator
    prompt: |
      Generate summary considering:
      Sentiment: {text_analyzer.sentiment}
      Topics: {text_analyzer.topics}
    # Forgot to declare text_analyzer dependency!
```

### Error Message

```
❌ {text_analyzer.sentiment}
   Agent 'text_analyzer' not in dependencies
   → Add 'text_analyzer' to dependencies list. Available: []
```

### The Fix

Add the dependency:

```yaml
  - name: summary_generator
    prompt: |
      Generate summary considering:
      Sentiment: {text_analyzer.sentiment}
      Topics: {text_analyzer.topics}
    depends_on: ["text_analyzer"]  # ✅ Declare the dependency
```

## Example 4: Typo in Field Name

### The Error

```yaml
agents:
  - name: data_extractor
    output_schema:
      properties:
        extracted_data: {type: object}
        confidence_score: {type: number}
    prompt: "Extract structured data"

  - name: validator
    prompt: |
      Validate with confidence {data_extractor.confidence_scroe}
      Data: {data_extractor.extracted_data}
    depends_on: ["data_extractor"]
```

### Error Message

```
❌ {data_extractor.confidence_scroe}
   Field 'confidence_scroe' not available in 'data_extractor' output
   → Available fields: ['extracted_data', 'confidence_score']
```

### The Fix

Fix the typo (score not scroe):

```yaml
  - name: validator
    prompt: |
      Validate with confidence {data_extractor.confidence_score}
      Data: {data_extractor.extracted_data}
    depends_on: ["data_extractor"]
```

## Example 5: Complex Workflow with Multiple Errors

### The Error

```yaml
agents:
  - name: preprocessor
    output_schema:
      properties:
        cleaned_text: {type: string}
        token_count: {type: number}
    drops: [token_count]

  - name: entity_extractor
    output_schema:
      properties:
        entities: {type: array}
        metadata: {type: object}
    observe: [document_id]

  - name: report_builder
    prompt: |
      Build report:
      Text: {preprocessor.cleaned_text}
      Tokens: {preprocessor.token_count}
      Entities: {entity_extractor.entites}
      Document: {entity_extractor.document_id}
      Source: {unknown_agent.data}
    depends_on: ["preprocessor"]  # Missing entity_extractor!
```

### Error Messages

```
================================================================================
INPUT SIGNATURE VALIDATION ERRORS
================================================================================

Agent: 'report_builder'
--------------------------------------------------------------------------------

  ❌ {preprocessor.token_count}
     Field 'token_count' not available in 'preprocessor' output
     → Available fields: ['cleaned_text']

  ❌ {entity_extractor.entites}
     Agent 'entity_extractor' not in dependencies
     → Add 'entity_extractor' to dependencies list

  ❌ {unknown_agent.data}
     Agent 'unknown_agent' not in dependencies
     → Add 'unknown_agent' to dependencies list

================================================================================
```

### The Fix

Fix all three issues:

```yaml
  - name: preprocessor
    output_schema:
      properties:
        cleaned_text: {type: string}
        token_count: {type: number}
    # Remove drops to make token_count available

  - name: entity_extractor
    output_schema:
      properties:
        entities: {type: array}  # Fixed typo: entities not entites
        metadata: {type: object}
    observe: [document_id]

  - name: report_builder
    prompt: |
      Build report:
      Text: {preprocessor.cleaned_text}
      Tokens: {preprocessor.token_count}
      Entities: {entity_extractor.entities}  # Fixed typo
      Document: {entity_extractor.document_id}
      # Removed unknown_agent reference
    depends_on: ["preprocessor", "entity_extractor"]  # Added entity_extractor
```

## Example 6: observe vs schema Confusion

### The Error

```yaml
agents:
  - name: data_enricher
    output_schema:
      properties:
        enriched_data: {type: object}
        user_id: {type: string}      # Should be in observe!
        timestamp: {type: string}     # Should be in observe!
    prompt: "Enrich the data with additional context"
```

### Why This Is Wrong

- `user_id` and `timestamp` are input fields (not generated by LLM)
- They should be in `observe`, not `output_schema`
- The LLM will try to generate these fields (incorrect)

### The Fix

Use observe for pass-through fields:

```yaml
agents:
  - name: data_enricher
    output_schema:
      properties:
        enriched_data: {type: object}
    observe: [user_id, timestamp]  # ✅ Pass through from input
    prompt: "Enrich the data with additional context"
```

**Next agent can still reference them:**
```yaml
  - name: analyzer
    prompt: |
      Analyze data for user {data_enricher.user_id}
      At time {data_enricher.timestamp}:
      {data_enricher.enriched_data}
    depends_on: ["data_enricher"]
    # ✅ All fields available (schema + observe)
```

## Example 7: Return Collection Reference

### The Error

```yaml
agents:
  - name: batch_processor
    loop:
      mode: sequential
      items_from: "{source.items}"
    output_schema:
      properties:
        results: {type: array}
    # Forgot return_collection: true

  - name: aggregator
    prompt: |
      Aggregate results:
      {batch_processor.results}

      Original data:
      {batch_processor.input_data}
    depends_on: ["batch_processor"]
```

### Error Message

```
❌ {batch_processor.input_data}
   Field 'input_data' not available in 'batch_processor' output
   → Available fields: ['results']
```

### The Fix

Add `return_collection: true`:

```yaml
  - name: batch_processor
    loop:
      mode: sequential
      items_from: "{source.items}"
    return_collection: true  # ✅ Adds input_data to output
    output_schema:
      properties:
        results: {type: array}

  - name: aggregator
    prompt: |
      Aggregate results:
      {batch_processor.results}

      Original data:
      {batch_processor.input_data}  # ✅ Now available
    depends_on: ["batch_processor"]
```

## Common Patterns

### Pattern 1: Field Renamed During Refactoring

**Before:**
```yaml
extractor:
  output_schema:
    properties:
      summary: {type: string}
```

**After Refactoring:**
```yaml
extractor:
  output_schema:
    properties:
      content_summary: {type: string}  # Renamed!
```

**Impact:**
All agents referencing `{extractor.summary}` will fail validation:
```
❌ {extractor.summary}
   Field 'summary' not available in 'extractor' output
   → Available fields: ['content_summary']
```

**Fix:** Update all references:
```yaml
analyzer:
  prompt: "Analyze {extractor.content_summary}"  # Updated
```

### Pattern 2: Gradual Field Removal

**Phase 1: Mark as deprecated (use drops)**
```yaml
extractor:
  output_schema:
    properties:
      new_field: {type: string}
      old_field: {type: string}
  drops: [old_field]  # Force errors for references
```

**Phase 2: Fix all references**
```
❌ {extractor.old_field}
   Field 'old_field' not available
   → Available fields: ['new_field']
```

**Phase 3: Remove from schema**
```yaml
extractor:
  output_schema:
    properties:
      new_field: {type: string}
  # old_field completely removed
```

### Pattern 3: Debug Unknown Fields

**When you see this error:**
```
❌ {extractor.mysterious_field}
   Field 'mysterious_field' not available in 'extractor' output
   → Available fields: ['summary', 'metrics', 'document_id']
```

**Debugging steps:**
1. Check the available fields list
2. Look for similar names (typos)
3. Verify the field is in schema or observe
4. Check if it was dropped

## Best Practices

### 1. Fix Validation Errors Before Execution

```bash
# ❌ Don't ignore validation errors
$ agent-actions run workflow.yml
ERROR: Validation failed
$ # Fix later...

# ✅ Fix immediately
$ agent-actions run workflow.yml
ERROR: Validation failed
$ # Edit workflow.yml to fix
$ agent-actions run workflow.yml
✅ Validation passed
```

### 2. Use Validation for Refactoring

```yaml
# Rename a field confidently:
# 1. Update output_schema
# 2. Run workflow (will show all affected references)
# 3. Fix all references shown in errors
# 4. Run again (validation passes)
```

### 3. Document Field Contracts

```yaml
extractor:
  output_schema:
    properties:
      summary:
        type: string
        description: "Reference via {extractor.summary} in dependent agents"
      metrics:
        type: object
        description: "Performance metrics - available to all downstream agents"
```

## See Also

- [Input Validation Guide](/guides/input-validation) - Complete validation documentation
- [Field Referencing](/core-concepts/field-referencing) - Field reference syntax
- [Workflows](/core-concepts/workflows) - Field directives (drops, observe)
