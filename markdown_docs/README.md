# Conditional Reprompting Examples

This directory contains examples demonstrating how to use the conditional reprompting feature in agent-actions.

## Overview

The conditional reprompting system allows you to:
1. **Validate** LLM outputs against custom criteria
2. **Automatically retry** with improved prompts when validation fails
3. **Learn from failures** to generate better prompts using LLM or templates

## Examples

### 1. Basic Word Count (`basic_word_count.yaml`)
- Simple validation for exact word count
- LLM-based reprompt generation
- Good starting point for understanding the system

### 2. Advanced Product Description (`advanced_product_description.yaml`)
- Multiple validation criteria (character count + keywords)
- Template-based reprompting with specific error patterns
- Shows how to chain multiple validators

### 3. Custom Validators (`custom_validator_example.py`)
- How to create and register custom validation functions
- Examples for JSON, email, sentiment, and business rule validation
- Integration patterns with the validator registry

## Configuration Structure

```yaml
agents:
  - agent_type: YourAgentType
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Your base prompt"
    
    interceptors:
      # Validation interceptors
      - type: validation
        config:
          validator: "validator_name"
          validator_args:
            param1: value1
            param2: value2
          on_failure: retry  # or "fail" or "continue"
      
      # Reprompt interceptor
      - type: reprompt
        config:
          strategy: "llm"  # or "template"
          max_attempts: 3
          llm_config:  # For LLM strategy
            model_vendor: "openai"
            model_name: "gpt-4"
          templates:  # For template strategy
            "error_pattern": "Improved prompt template"
```

## Built-in Validators

| Validator | Parameters | Description |
|-----------|------------|-------------|
| `word_count` | `expected: int` | Validates exact word count |
| `char_count` | `min_chars: int, max_chars: int` | Validates character count range |
| `contains_keywords` | `required_keywords: List[str]` | Validates presence of keywords |

## Reprompt Strategies

### LLM Strategy
Uses an LLM to analyze the failure and generate an improved prompt:
- Analyzes the original prompt, validation error, and failed response
- Generates contextually appropriate improvements
- Highly flexible but requires additional LLM calls

### Template Strategy
Uses predefined templates matched to error patterns:
- Fast and deterministic
- Good for known failure patterns
- Templates can use variables from validation context

## Best Practices

1. **Start Simple**: Begin with built-in validators before creating custom ones
2. **Chain Wisely**: Order validators from most to least restrictive
3. **Limit Attempts**: Set reasonable `max_attempts` to avoid infinite loops
4. **Template Patterns**: Use specific error message patterns in templates
5. **Test Thoroughly**: Validate your validation logic with edge cases

## Custom Validator Guidelines

When creating custom validators:

```python
from agent_actions.validators.registry import ValidatorRegistry
from typing import Tuple

@ValidatorRegistry.register("your_validator_name")
def your_validator(content: str, **kwargs) -> Tuple[bool, str | None]:
    \"\"\"
    Your validator description.
    
    Args:
        content: The LLM response content to validate
        **kwargs: Additional validation parameters
    
    Returns:
        Tuple of (success: bool, error_message: str | None)
    \"\"\"
    # Your validation logic here
    if validation_passes:
        return True, None
    else:
        return False, "Descriptive error message"
```

## Integration with Existing Workflows

The interceptor system is backward compatible. Agents without interceptors work exactly as before. Add interceptors gradually to existing configurations.

## Performance Considerations

- **Caching**: Successful prompts for similar validation criteria could be cached (future feature)
- **Early Exit**: Set reasonable max attempts to avoid excessive retries
- **Template Strategy**: Generally faster than LLM strategy for known patterns
- **Validation Order**: Put cheaper validations before expensive ones