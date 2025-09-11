"""
Custom Validator Example
This shows how to create custom validator functions for use with the conditional reprompting system.
"""

from typing import Tuple, List
import json
import re


# Example 1: JSON Format Validator
def validate_json_format(content: str) -> Tuple[bool, str | None]:
    """Validate that content is valid JSON."""
    try:
        json.loads(content.strip())
        return True, None
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON format: {str(e)}"


# Example 2: Email Format Validator
def validate_email_format(content: str) -> Tuple[bool, str | None]:
    """Validate that content contains a valid email address."""
    email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    if re.match(email_pattern, content.strip()):
        return True, None
    return False, "Content must be a valid email address"


# Example 3: Sentiment Validator
def validate_sentiment(content: str, required_sentiment: str = "positive") -> Tuple[bool, str | None]:
    """Validate content sentiment (simplified example)."""
    positive_words = ["great", "excellent", "amazing", "wonderful", "fantastic", "love", "best"]
    negative_words = ["bad", "terrible", "awful", "horrible", "hate", "worst", "disappointing"]
    
    content_lower = content.lower()
    
    if required_sentiment == "positive":
        if any(word in content_lower for word in positive_words):
            return True, None
        return False, "Content should have positive sentiment with words like 'great', 'excellent', etc."
    
    elif required_sentiment == "negative":
        if any(word in content_lower for word in negative_words):
            return True, None
        return False, "Content should have negative sentiment with words like 'bad', 'terrible', etc."
    
    return True, None  # Neutral sentiment is always valid


# Example 4: Code Structure Validator
def validate_python_function(content: str) -> Tuple[bool, str | None]:
    """Validate that content contains a valid Python function definition."""
    # Check for function definition pattern
    if not re.search(r'def\s+\w+\s*\([^)]*\)\s*:', content):
        return False, "Content must contain a Python function definition (def function_name():)"
    
    # Try to compile the code
    try:
        compile(content, '<string>', 'exec')
        return True, None
    except SyntaxError as e:
        return False, f"Invalid Python syntax: {str(e)}"


# Example 5: Business Rules Validator
def validate_business_rules(
    content: str, 
    max_price: float = 1000.0,
    required_sections: List[str] = None
) -> Tuple[bool, str | None]:
    """Validate content meets business requirements."""
    if required_sections is None:
        required_sections = ["description", "pricing"]
    
    content_lower = content.lower()
    
    # Check required sections
    missing_sections = [section for section in required_sections 
                       if section.lower() not in content_lower]
    if missing_sections:
        return False, f"Missing required sections: {', '.join(missing_sections)}"
    
    # Check price constraints (simple regex for price detection)
    price_match = re.search(r'\$?(\d+(?:\.\d{2})?)', content)
    if price_match:
        price = float(price_match.group(1))
        if price > max_price:
            return False, f"Price ${price} exceeds maximum allowed ${max_price}"
    
    return True, None


# Usage example in YAML config:
"""
agents:
  - agent_type: JSONGenerator
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Generate a JSON object with user data"
    
    interceptors:
      - type: validation
        config:
          validator_function: "examples.reprompting.custom_validator_example.validate_json_format"
          on_failure: retry
          
      - type: reprompt
        config:
          strategy: "template"
          max_attempts: 2
          templates:
            "invalid json": |
              {original_prompt}
              
              IMPORTANT: The output must be valid JSON format.
              Error details: {validation_error}
              
              Example format:
              {
                "name": "John Doe",
                "email": "john@example.com"
              }

# Or for a validator with parameters:
  - agent_type: ProductGenerator
    model_vendor: "anthropic"
    model_name: "claude-3-sonnet"
    prompt: "Generate a product description"
    
    interceptors:
      - type: validation
        config:
          validator_function: "examples.reprompting.custom_validator_example.validate_business_rules"
          validator_args:
            max_price: 500.0
            required_sections: ["description", "pricing", "features"]
          on_failure: retry
"""