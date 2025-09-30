# Schema Validation & Retry Strategy Feature

## Overview

The Schema Validation & Retry Strategy feature addresses a critical gap in the current agent-actions system: **LLM responses are not validated against expected JSON schemas after generation**. This feature introduces comprehensive post-generation validation, intelligent retry mechanisms, and batch-aware error recovery to ensure LLM outputs conform to expected data structures.

## Problem Statement

### Current Issues
1. **No Post-Generation Validation**: LLM responses pass through without schema validation
2. **Inconsistent JSON Parsing**: Different providers handle parsing errors differently  
3. **Silent Failures**: Invalid responses become string content instead of triggering corrections
4. **Batch Processing Gaps**: No mechanism to retry failed batch items while preserving successful ones
5. **Provider-Only Validation**: Relies entirely on provider structured output (OpenAI, Gemini) without fallback

### Impact
- **Data Quality Issues**: Inconsistent or malformed outputs in production
- **Pipeline Failures**: Downstream agents receive unexpected data formats
- **Cost Inefficiency**: No recovery mechanism for expensive LLM calls that produce invalid outputs
- **Reduced Reliability**: Silent failures mask data quality problems

## Solution Architecture

### Core Components

#### 1. Response Validation Engine
```python
class ResponseValidator:
    """Validates LLM responses against expected schemas"""
    
    def validate_response(self, response: Any, schema: Dict, context: Dict) -> ValidationResult:
        """
        Validates response against schema and returns detailed results
        
        Returns:
            ValidationResult with success/failure, missing fields, errors
        """
    
    def generate_retry_prompt(self, original_prompt: str, validation_errors: List[str], 
                            schema: Dict, examples: List[Dict] = None) -> str:
        """
        Generates enhanced prompt for retry attempts including:
        - Original prompt
        - Validation error details
        - Schema specification
        - Corrective examples
        """
```

#### 2. Retry Orchestrator
```python
class RetryOrchestrator:
    """Manages retry attempts with backoff and batching support"""
    
    def process_with_retry(self, items: List[Dict], agent_config: Dict) -> RetryResult:
        """
        Processes items with validation and retry logic
        
        Flow:
        1. Process initial batch
        2. Validate responses
        3. Identify failures
        4. Retry failed items with enhanced prompts
        5. Merge successful + retry results
        """
    
    def handle_batch_retry(self, failed_items: List[Dict], retry_config: Dict) -> BatchResult:
        """
        Handles retry logic for batch processing scenarios
        """
```

#### 3. Validation Result Merger
```python
class ValidationResultMerger:
    """Merges original successful results with retry attempt results"""
    
    def merge_results(self, original_results: List[Dict], 
                     retry_results: List[Dict]) -> List[Dict]:
        """
        Merges results by target_id, prioritizing successful retry results
        """
```

### Data Flow Architecture

```
Input Batch: [Item1, Item2, ..., Item10]
       ↓
Initial LLM Processing
       ↓
Response Validation: [✓Success, ✗Failed, ✓Success, ✗Failed, ...]
       ↓
Failed Items → Retry Queue → Enhanced Prompts → Retry LLM Call
       ↓                                              ↓
Successful Items ←─────────── Result Merger ←────────┘
       ↓
Final Merged Output
```

## Configuration

### Basic Retry Configuration
```yaml
retry_config:
  enabled: true
  max_attempts: 3
  validation_enabled: true
  schema_validation_mode: "strict"  # or "lenient"
  retry_delay: 1.0  # seconds between retries
  exponential_backoff: true
  backoff_multiplier: 2.0
```

### Advanced Retry Configuration
```yaml
retry_config:
  enabled: true
  max_attempts: 3
  validation_enabled: true
  schema_validation_mode: "strict"
  
  # Validation settings
  validation:
    required_field_enforcement: true
    type_checking: true
    additional_properties: false  # Strict schema adherence
    missing_field_threshold: 0.8  # Retry if >80% fields missing
  
  # Retry behavior
  retry_strategy: "exponential_backoff"  # or "fixed_delay", "linear_backoff"
  base_delay: 1.0
  max_delay: 30.0
  backoff_multiplier: 2.0
  jitter: true  # Add randomization to prevent thundering herd
  
  # Batch-specific settings
  batch_retry:
    enabled: true
    min_batch_size: 1  # Minimum items to justify batch retry
    max_retry_batch_size: 50  # Split large retry batches
    preserve_successful: true
    merge_strategy: "target_id"  # How to merge results
  
  # Prompt enhancement
  enhanced_prompts:
    include_validation_errors: true
    include_schema_specification: true
    include_examples: true
    max_examples: 3
    example_selection: "similar_failures"  # or "random", "best_matches"
  
  # Fallback behavior
  fallback_strategy: "partial_success"  # or "fail_all", "best_effort"
  save_failed_attempts: true
  failed_items_output: "retry_failures.json"
```

### Schema Validation Configuration
```yaml
schema_validation:
  enabled: true
  validation_mode: "post_processing"  # or "pre_transformation", "both"
  error_reporting: "detailed"  # or "summary", "silent"
  
  # Validation rules
  rules:
    required_fields: "enforce"  # or "warn", "ignore"
    field_types: "strict"  # or "coerce", "flexible"
    additional_properties: false
    null_values: "reject"  # or "allow", "coerce_to_default"
    empty_strings: "allow"  # or "reject", "coerce_to_null"
  
  # Custom validations
  custom_validators:
    - name: "email_format"
      field_pattern: "*_email"
      validator: "email_validator"
    - name: "date_format"  
      field_pattern: "*_date"
      validator: "iso_date_validator"
```

## Integration with Existing System

### 1. Agent Configuration Integration
```yaml
agents:
  - agent_type: DataExtractor
    # ... existing config ...
    retry_config:
      enabled: true
      max_attempts: 2
      validation_enabled: true
    schema_name: data_extraction_schema
    json_mode: true
    
    # Enhanced error handling
    error_handling:
      validation_failures: "retry"  # or "skip", "fail"
      json_parse_failures: "retry"
      max_total_failures: 0.2  # Fail job if >20% items fail
```

### 2. Response Processing Pipeline Integration

#### Current Flow
```python
# Current: agent_actions/processors/content/response_transformer.py
def transform_response(response, context_data, source_guid, agent_config):
    return transform_with_side_collection(response, context_data, source_guid, agent_config)
```

#### Enhanced Flow
```python
# Enhanced: With validation and retry capability
def transform_response_with_validation(response, context_data, source_guid, agent_config):
    # Step 1: Validate response against schema
    validation_result = ResponseValidator.validate_response(
        response, agent_config.get('schema'), context_data
    )
    
    # Step 2: Handle validation results
    if validation_result.success:
        return transform_with_side_collection(response, context_data, source_guid, agent_config)
    else:
        # Add to retry queue if retries enabled
        retry_config = agent_config.get('retry_config', {})
        if retry_config.get('enabled'):
            return RetryOrchestrator.queue_for_retry(
                response, context_data, source_guid, agent_config, validation_result
            )
        else:
            # Fallback to current behavior or error handling
            return handle_validation_failure(response, validation_result, agent_config)
```

### 3. Batch Processing Integration

#### Enhanced Batch Service
```python
# Enhanced: agent_actions/services/batch_service.py
class BatchService:
    def process_batch_with_retry(self, agent_config: Dict, data: List[Dict], 
                               output_directory: str) -> BatchProcessingResult:
        """
        Process batch with validation and retry capability
        
        Flow:
        1. Submit initial batch to provider
        2. Retrieve and validate results
        3. Identify failed validations
        4. Submit retry batch for failures
        5. Merge results and return final output
        """
        
        # Step 1: Initial batch processing
        initial_results = self.submit_and_retrieve_batch(agent_config, data, output_directory)
        
        # Step 2: Validate results against schema
        validation_results = self.validate_batch_results(initial_results, agent_config)
        
        # Step 3: Process retry if needed
        failed_items = [item for item, result in zip(data, validation_results) 
                       if not result.success]
        
        if failed_items and self.should_retry(agent_config):
            retry_results = self.process_retry_batch(failed_items, agent_config, output_directory)
            final_results = self.merge_batch_results(initial_results, retry_results)
        else:
            final_results = initial_results
            
        return BatchProcessingResult(
            success=True,
            results=final_results,
            retry_stats=self.get_retry_statistics()
        )
```

### 4. Provider Integration

#### Enhanced Provider Response Handling
```python
# Enhanced provider response parsing with validation
class EnhancedOpenAIProvider(OpenAIProvider):
    def parse_provider_response(self, raw_response: Dict) -> BatchResult:
        """Enhanced response parsing with validation"""
        # Current JSON parsing logic
        content = self.parse_json_content(raw_response)
        
        # Add validation step
        if self.validation_enabled:
            validation_result = self.validate_content(content, self.current_schema)
            if not validation_result.success:
                return BatchResult(
                    custom_id=raw_response.get("custom_id"),
                    content=content,
                    success=False,
                    error=f"Validation failed: {validation_result.errors}",
                    metadata={
                        "validation_errors": validation_result.errors,
                        "requires_retry": True,
                        "original_response": content
                    }
                )
        
        return BatchResult(
            custom_id=raw_response.get("custom_id"),
            content=content,
            success=True,
            metadata={"validation_passed": True}
        )
```

## Validation Engine Implementation

### Schema Validation Types

#### 1. JSON Schema Validation
```python
class JSONSchemaValidator:
    """Standard JSON Schema validation using jsonschema library"""
    
    def validate(self, response: Any, schema: Dict) -> ValidationResult:
        try:
            jsonschema.validate(response, schema)
            return ValidationResult(success=True)
        except jsonschema.ValidationError as e:
            return ValidationResult(
                success=False,
                errors=[str(e)],
                missing_fields=self.extract_missing_fields(e),
                invalid_fields=self.extract_invalid_fields(e)
            )
```

#### 2. Pydantic Model Validation
```python
class PydanticValidator:
    """Pydantic-based validation with better error messages"""
    
    def validate(self, response: Any, model_class: BaseModel) -> ValidationResult:
        try:
            validated_model = model_class.parse_obj(response)
            return ValidationResult(success=True, validated_data=validated_model.dict())
        except ValidationError as e:
            return ValidationResult(
                success=False,
                errors=[error['msg'] for error in e.errors()],
                missing_fields=self.extract_missing_fields(e),
                field_errors=e.errors()
            )
```

#### 3. Custom Field Validators
```python
class CustomFieldValidator:
    """Custom validation logic for specific business rules"""
    
    def __init__(self):
        self.validators = {
            'email': self.validate_email,
            'date': self.validate_date_format,
            'url': self.validate_url,
            'required_length': self.validate_min_length
        }
    
    def validate_field(self, field_name: str, value: Any, 
                      validation_rules: Dict) -> FieldValidationResult:
        """Apply custom validation rules to specific fields"""
```

### Validation Result Structure
```python
@dataclass
class ValidationResult:
    success: bool
    errors: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    invalid_fields: Dict[str, str] = field(default_factory=dict)
    validation_score: float = 1.0  # 0.0-1.0 quality score
    validated_data: Optional[Dict] = None
    retry_recommended: bool = False
    metadata: Dict = field(default_factory=dict)
```

## Retry Prompt Engineering

### Enhanced Prompt Generation
```python
class RetryPromptGenerator:
    def generate_retry_prompt(self, original_prompt: str, validation_result: ValidationResult,
                            schema: Dict, successful_examples: List[Dict] = None) -> str:
        """
        Generate enhanced prompt for retry attempts
        
        Components:
        1. Original prompt
        2. Error explanation
        3. Schema specification  
        4. Examples of correct format
        5. Specific guidance for failed fields
        """
        
        retry_prompt = f"""
{original_prompt}

IMPORTANT: Your previous response had validation errors. Please correct the following issues:

VALIDATION ERRORS:
{self.format_validation_errors(validation_result)}

REQUIRED SCHEMA:
{self.format_schema_specification(schema)}

CORRECT EXAMPLES:
{self.format_examples(successful_examples)}

SPECIFIC GUIDANCE:
{self.generate_field_specific_guidance(validation_result.missing_fields, schema)}

Please provide a response that exactly matches the required schema format.
"""
        return retry_prompt
```

### Example Enhanced Prompts

#### Original Prompt
```
Extract key information from this document: {document_text}
Return the data in JSON format.
```

#### Retry Prompt (after validation failure)
```
Extract key information from this document: {document_text}
Return the data in JSON format.

IMPORTANT: Your previous response had validation errors. Please correct the following issues:

VALIDATION ERRORS:
- Missing required field: "title"
- Missing required field: "author" 
- Field "date" has invalid format: expected ISO date (YYYY-MM-DD), got "March 2024"

REQUIRED SCHEMA:
{
  "type": "object",
  "properties": {
    "title": {"type": "string", "minLength": 1},
    "author": {"type": "string", "minLength": 1},
    "date": {"type": "string", "format": "date"},
    "summary": {"type": "string"}
  },
  "required": ["title", "author", "date"]
}

CORRECT EXAMPLES:
{
  "title": "Research Paper on AI",
  "author": "Dr. Smith",
  "date": "2024-03-15",
  "summary": "This paper discusses advanced AI techniques"
}

SPECIFIC GUIDANCE:
- "title": Must be a non-empty string representing the document title
- "author": Must be a non-empty string with the author's name
- "date": Must be in ISO format YYYY-MM-DD, not natural language like "March 2024"

Please provide a response that exactly matches the required schema format.
```

## Batch Processing Scenarios

### Scenario 1: Partial Batch Failure
```
Initial Batch (10 items): [1✓, 2✓, 3✗, 4✓, 5✗, 6✓, 7✗, 8✓, 9✗, 10✗]

Validation Results:
- 5 items passed validation
- 5 items failed validation with missing required fields

Retry Processing:
1. Create retry batch with items [3, 5, 7, 9, 10]
2. Enhance prompts with validation errors + schema + examples
3. Submit retry batch to LLM provider
4. Receive retry results: [3✓, 5✓, 7✗, 9✓, 10✓]
5. Merge with original successful results

Final Result: 9/10 successful (90% success rate)
Failed Items: [7] → saved to retry_failures.json for manual review
```

### Scenario 2: Progressive Retry Strategy
```
Attempt 1: 10 items → 5 successful, 5 failed
Attempt 2: 5 failed items → 3 successful, 2 failed  
Attempt 3: 2 failed items → 1 successful, 1 failed

Final Result: 9/10 successful
Retry Statistics:
- Total attempts: 3
- Final success rate: 90%
- Items requiring multiple retries: 2
- Unrecoverable failures: 1
```

## Error Handling & Fallback Strategies

### Fallback Strategy Configuration
```python
class FallbackStrategies:
    PARTIAL_SUCCESS = "partial_success"  # Return successful items, log failures
    FAIL_ALL = "fail_all"              # Fail entire batch if any item fails
    BEST_EFFORT = "best_effort"        # Try to salvage any usable data
    MANUAL_REVIEW = "manual_review"    # Queue failures for human review
```

### Error Classification
```python
class ValidationErrorTypes:
    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    INVALID_FIELD_TYPES = "invalid_field_types"  
    JSON_PARSE_ERROR = "json_parse_error"
    SCHEMA_MISMATCH = "schema_mismatch"
    EMPTY_RESPONSE = "empty_response"
    PARTIAL_RESPONSE = "partial_response"
    MALFORMED_STRUCTURE = "malformed_structure"
```

### Error-Specific Retry Strategies
```yaml
error_handling:
  missing_required_fields:
    action: "retry"
    max_attempts: 2
    prompt_enhancement: "add_field_examples"
    
  invalid_field_types:
    action: "retry" 
    max_attempts: 1
    prompt_enhancement: "add_type_specification"
    
  json_parse_error:
    action: "retry"
    max_attempts: 1
    prompt_enhancement: "add_json_format_examples"
    
  empty_response:
    action: "fail"
    fallback_strategy: "skip_item"
```

## Performance & Cost Considerations

### Cost Impact Analysis
```python
# Cost calculation for retry scenarios
def calculate_retry_costs(batch_size: int, failure_rate: float, 
                         retry_attempts: int, token_cost_per_item: float) -> Dict:
    
    initial_cost = batch_size * token_cost_per_item
    failed_items = batch_size * failure_rate
    retry_cost = failed_items * retry_attempts * token_cost_per_item
    
    return {
        "initial_cost": initial_cost,
        "retry_cost": retry_cost, 
        "total_cost": initial_cost + retry_cost,
        "cost_increase_percentage": (retry_cost / initial_cost) * 100,
        "cost_per_successful_item": (initial_cost + retry_cost) / (batch_size * (1 - failure_rate))
    }

# Example: 100 items, 20% failure rate, 2 retry attempts, $0.01 per item
# Initial cost: $1.00
# Retry cost: $0.40 (20 items × 2 retries × $0.01)  
# Total cost: $1.40 (40% increase)
# But achieves 95%+ success rate vs 80% without retries
```

### Performance Optimizations

#### 1. Batch Size Optimization
```python
def optimize_batch_sizes(total_items: int, failure_rate: float, 
                        retry_enabled: bool) -> Dict:
    """
    Optimize batch sizes based on failure patterns
    - Smaller batches for high failure rates (faster retry cycles)
    - Larger batches for low failure rates (better throughput)
    """
```

#### 2. Caching Successful Patterns
```python
class ValidationPatternCache:
    """Cache successful response patterns to improve retry prompts"""
    
    def add_successful_pattern(self, schema_name: str, response: Dict):
        """Store successful responses as examples for future retries"""
    
    def get_examples_for_schema(self, schema_name: str, limit: int = 3) -> List[Dict]:
        """Retrieve best examples for retry prompt enhancement"""
```

#### 3. Parallel Retry Processing
```python
async def process_retry_batches_parallel(retry_items: List[Dict], 
                                       batch_size: int = 10) -> List[Dict]:
    """
    Process retry items in parallel batches to reduce total processing time
    """
    batches = [retry_items[i:i+batch_size] for i in range(0, len(retry_items), batch_size)]
    tasks = [process_retry_batch(batch) for batch in batches]
    results = await asyncio.gather(*tasks)
    return flatten_results(results)
```

## Monitoring & Analytics

### Retry Metrics
```python
@dataclass
class RetryMetrics:
    total_items_processed: int
    initial_success_count: int
    initial_failure_count: int
    retry_attempts_made: int
    final_success_count: int
    final_failure_count: int
    
    # Success rates
    initial_success_rate: float
    final_success_rate: float
    retry_effectiveness: float  # (final_success - initial_success) / initial_failure
    
    # Performance metrics
    total_processing_time: float
    average_retry_time: float
    cost_increase_percentage: float
    
    # Error analysis
    error_type_distribution: Dict[str, int]
    fields_most_likely_to_fail: List[str]
    retry_success_by_attempt: List[float]
```

### Dashboard Metrics
```json
{
  "validation_retry_analytics": {
    "period": "last_24h",
    "total_batches_processed": 150,
    "batches_requiring_retry": 45,
    "average_initial_success_rate": 0.78,
    "average_final_success_rate": 0.94,
    "retry_effectiveness": 0.73,
    
    "cost_impact": {
      "additional_cost_percentage": 25.3,
      "cost_per_quality_improvement": "$0.045"
    },
    
    "common_validation_failures": [
      {"type": "missing_required_fields", "frequency": 156, "fields": ["title", "date"]},
      {"type": "invalid_field_types", "frequency": 89, "fields": ["price", "quantity"]},
      {"type": "json_parse_error", "frequency": 23}
    ],
    
    "retry_success_patterns": {
      "first_retry_success_rate": 0.82,
      "second_retry_success_rate": 0.65,
      "third_retry_success_rate": 0.45
    }
  }
}
```

### Alerting & Notifications
```yaml
alerting:
  validation_failure_threshold: 0.5  # Alert if >50% items fail validation
  retry_effectiveness_threshold: 0.3  # Alert if retry success rate <30%
  cost_increase_threshold: 2.0  # Alert if costs increase >200%
  
  notifications:
    - type: "email"
      condition: "validation_failure_rate > 0.5"
      message: "High validation failure rate detected"
    - type: "slack"
      condition: "retry_cost_increase > 200%"
      message: "Retry costs are significantly impacting budget"
```

## Migration Strategy

### Phase 1: Foundation (Weeks 1-2)
- [ ] Implement core `ResponseValidator` component
- [ ] Add schema validation to response processing pipeline
- [ ] Create basic retry orchestration framework
- [ ] Add configuration schema for retry settings

### Phase 2: Basic Retry (Weeks 3-4)  
- [ ] Implement single-item retry logic
- [ ] Add enhanced prompt generation for retries
- [ ] Integrate with existing error handling
- [ ] Create basic monitoring and logging

### Phase 3: Batch Integration (Weeks 5-6)
- [ ] Enhance batch processing with retry capabilities
- [ ] Implement result merging logic
- [ ] Add batch-specific retry strategies
- [ ] Performance optimization for large batches

### Phase 4: Advanced Features (Weeks 7-8)
- [ ] Add intelligent prompt enhancement
- [ ] Implement caching for successful patterns
- [ ] Add comprehensive analytics and monitoring
- [ ] Create alerting and notification system

### Backwards Compatibility
- **Default Disabled**: Retry validation is opt-in via configuration
- **Graceful Fallback**: Falls back to current behavior when disabled
- **Progressive Enablement**: Can enable per-agent or per-workflow
- **Existing API Compatibility**: No changes to existing agent configurations

## Examples

### Example 1: Data Extraction with Retry
```yaml
# Agent Configuration
- agent_type: DocumentExtractor
  schema_name: document_schema
  json_mode: true
  retry_config:
    enabled: true
    max_attempts: 2
    validation_enabled: true
    enhanced_prompts:
      include_validation_errors: true
      include_examples: true
  prompt: $extraction.document_fields
```

```python
# Input Document
document_text = "Research paper titled 'AI Advances' by Dr. Smith, published March 15, 2024"

# Expected Schema
{
  "type": "object",
  "properties": {
    "title": {"type": "string"},
    "author": {"type": "string"}, 
    "publication_date": {"type": "string", "format": "date"},
    "abstract": {"type": "string"}
  },
  "required": ["title", "author", "publication_date"]
}

# First Attempt Response (Invalid)
{
  "title": "AI Advances",
  "author": "Dr. Smith"
  # Missing required field: publication_date
}

# Validation Result: FAILED
# Missing fields: ["publication_date"]

# Retry Prompt Enhancement
"Extract key information from this document: {document_text}
...
VALIDATION ERRORS:
- Missing required field: 'publication_date'

REQUIRED SCHEMA:
{schema specification}

Please ensure you include the publication_date field in ISO format (YYYY-MM-DD)."

# Second Attempt Response (Valid)
{
  "title": "AI Advances", 
  "author": "Dr. Smith",
  "publication_date": "2024-03-15",
  "abstract": "This paper discusses recent advances in artificial intelligence"
}

# Final Result: SUCCESS after 1 retry
```

### Example 2: Batch Processing with Mixed Results
```python
# Batch Input: 5 documents
batch_data = [
  {"doc_id": "1", "text": "Document 1 content..."},
  {"doc_id": "2", "text": "Document 2 content..."}, 
  {"doc_id": "3", "text": "Document 3 content..."},
  {"doc_id": "4", "text": "Document 4 content..."},
  {"doc_id": "5", "text": "Document 5 content..."}
]

# Initial Batch Results
initial_results = [
  {"doc_id": "1", "title": "Doc 1", "author": "Author 1", "date": "2024-01-01"},  # ✓ Valid
  {"doc_id": "2", "title": "Doc 2", "author": "Author 2"},                          # ✗ Missing date
  {"doc_id": "3", "title": "Doc 3", "author": "Author 3", "date": "2024-03-01"},  # ✓ Valid  
  {"doc_id": "4", "title": "Doc 4"},                                                # ✗ Missing author, date
  {"doc_id": "5", "title": "Doc 5", "author": "Author 5", "date": "invalid"}      # ✗ Invalid date format
]

# Validation: 2 successful, 3 failed
# Retry batch: Items 2, 4, 5 with enhanced prompts

# Retry Results  
retry_results = [
  {"doc_id": "2", "title": "Doc 2", "author": "Author 2", "date": "2024-02-01"},  # ✓ Now valid
  {"doc_id": "4", "title": "Doc 4", "author": "Author 4", "date": "2024-04-01"},  # ✓ Now valid
  {"doc_id": "5", "title": "Doc 5", "author": "Author 5", "date": "2024-05-01"}   # ✓ Now valid  
]

# Final Merged Results: 5/5 successful (100% success rate)
# Original successful: 2, Retry successful: 3
```

### Example 3: Cost-Benefit Analysis
```python
# Scenario: 1000 document batch processing
original_scenario = {
    "total_items": 1000,
    "success_rate_without_retry": 0.75,  # 75% success
    "successful_items": 750,
    "failed_items": 250,
    "cost_per_item": 0.01,
    "total_cost": 10.00
}

retry_scenario = {
    "total_items": 1000,
    "initial_success": 750,
    "initial_failures": 250,
    "retry_attempts": 1,
    "retry_success_rate": 0.80,  # 80% of failures recovered
    "retry_successful": 200,  # 250 * 0.80
    "final_success": 950,     # 750 + 200
    "final_success_rate": 0.95,  # 95% total success
    
    "costs": {
        "initial_cost": 10.00,
        "retry_cost": 2.50,  # 250 items * $0.01
        "total_cost": 12.50,
        "cost_increase": 25.0,  # 25% increase
        "cost_per_successful_item": 0.0132  # vs 0.0133 without retry
    }
}

# ROI Analysis:
# - 25% cost increase
# - 95% vs 75% success rate (+20 percentage points)
# - 200 additional successful extractions
# - Better data quality and downstream reliability
```

## Conclusion

The Schema Validation & Retry Strategy feature addresses critical gaps in the current agent-actions system by introducing:

1. **Comprehensive Post-Generation Validation**: Ensures all LLM outputs conform to expected schemas
2. **Intelligent Retry Mechanisms**: Automatically recovers from validation failures with enhanced prompts
3. **Batch-Aware Processing**: Handles partial failures in batch scenarios efficiently
4. **Cost-Effective Quality Improvement**: Provides significant quality improvements with reasonable cost increases
5. **Seamless Integration**: Works with existing workflows while maintaining backwards compatibility

This feature transforms the system from a "fire-and-forget" approach to a quality-assured, self-correcting pipeline that ensures consistent, reliable outputs from LLM processing workflows.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"id": "1", "content": "Analyze current JSON schema validation system", "status": "completed", "priority": "high"}, {"id": "2", "content": "Understand batch processing architecture", "status": "completed", "priority": "high"}, {"id": "3", "content": "Examine LLM response handling and transformation", "status": "completed", "priority": "high"}, {"id": "4", "content": "Design retry strategy architecture", "status": "completed", "priority": "medium"}, {"id": "5", "content": "Create comprehensive features.md document", "status": "completed", "priority": "medium"}]