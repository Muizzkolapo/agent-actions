# Tracing Requirements for Reprompting Optimization

## Context
We've implemented sophisticated reprompting strategies with:
- Validation interceptors with custom validators
- Research-based focused correction prompts  
- Dynamic template variable interpolation
- Workflow-agnostic context passing

## Critical: Span & Trace Integration Required

### What Needs Tracing:

#### 1. Reprompt Interceptor Operations
- **Span Name**: `reprompt_interceptor.intercept`
- **Attributes**:
  - `attempt_number`: Current retry attempt
  - `max_attempts`: Configuration limit
  - `strategy_type`: "simple", "llm", "template"
  - `validation_error`: The specific error that triggered reprompt
  - `original_prompt_length`: Character count
  - `improved_prompt_length`: Character count
  - `template_variables`: JSON of variables used

#### 2. Validation Interceptor Operations  
- **Span Name**: `validation_interceptor.intercept`
- **Attributes**:
  - `validator_function`: Function name (e.g., "validate_distractor_word_counts")
  - `validation_success`: Boolean
  - `validation_error`: Error message if failed
  - `response_type`: "list", "dict", "string"
  - `tolerance`: Configured tolerance value

#### 3. Strategy Execution
- **Span Name**: `reprompt_strategy.generate_improved_prompt`
- **Attributes**:
  - `strategy_class`: "LLMRepromptStrategy", "TemplateRepromptStrategy"
  - `feedback_template_used`: Boolean
  - `context_fields_available`: List of available context keys
  - `target_relationship`: "longer_than", "shorter_than", "equal_to"
  - `prompt_construction_method`: "focused_correction", "simple_append", "template_match"

#### 4. Template Variable Resolution
- **Span Name**: `template_variables.resolve`
- **Attributes**:
  - `template_vars_requested`: List of variables in template
  - `template_vars_resolved`: List of successfully resolved variables
  - `template_vars_missing`: List of missing variables
  - `validation_criteria_keys`: Available context data keys

### Artifacts to Include in Spans:

#### 1. Prompt Evolution Artifacts
```json
{
  "original_prompt": "...",
  "improved_prompt": "...", 
  "validation_error": "...",
  "template_variables": {...},
  "attempt_history": [...]
}
```

#### 2. Validation Artifacts
```json
{
  "validator_function": "validate_distractor_word_counts",
  "validation_input": {...},
  "validation_result": true/false,
  "validation_details": "...",
  "context_data_used": {...}
}
```

#### 3. Strategy Decision Artifacts
```json
{
  "strategy_selected": "focused_correction",
  "feedback_template": "...",
  "context_fields_mapped": {...},
  "prompt_construction_logic": "..."
}
```

## Implementation Points:

### 1. Interceptor Base Class Updates
Add tracing decorators to:
- `configure()` method
- `intercept()` method  

### 2. Strategy Base Class Updates
Add tracing to:
- `generate_improved_prompt()` method
- Template variable resolution
- Context data extraction

### 3. Configuration Tracing
Track:
- Interceptor chain configuration
- Strategy selection logic
- Template compilation

## Integration with Existing Tracing:
- Must work with current span context
- Should nest properly under agent execution spans
- Need parent-child relationship with validation spans
- Artifacts should be queryable for optimization analysis

## Why This Matters:
1. **Debugging**: Track why reprompts succeeded/failed
2. **Optimization**: Analyze which strategies work best
3. **Performance**: Monitor prompt generation overhead
4. **Auditability**: Full workflow traceability
5. **Research**: Data for improving prompt engineering strategies

## Action Items:
- [ ] Add span instrumentation to interceptor classes
- [ ] Create artifact collection for prompt evolution 
- [ ] Implement trace correlation across retry attempts
- [ ] Add configuration for trace detail levels
- [ ] Test trace integration with existing telemetry