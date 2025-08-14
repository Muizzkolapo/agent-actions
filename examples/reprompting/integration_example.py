#!/usr/bin/env python3
"""
Integration Example: Using Conditional Reprompting in Your Project

This example shows how to integrate the conditional reprompting feature
into an existing agent-actions project.
"""

import yaml
from agent_actions.models.agent_builder import create_dynamic_agent
from agent_actions.validators.registry import ValidatorRegistry


def example_blog_post_generator():
    """Example: Generate a blog post with validation and reprompting."""
    
    # Define agent configuration with interceptors
    agent_config = {
        "agent_type": "BlogPostGenerator",
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "prompt": "Write a blog post about sustainable technology",
        
        # Add interceptors for validation and reprompting
        "interceptors": [
            {
                "type": "validation",
                "config": {
                    "validator": "char_count",
                    "validator_args": {
                        "min_chars": 500,
                        "max_chars": 1500
                    },
                    "on_failure": "retry"
                }
            },
            {
                "type": "validation", 
                "config": {
                    "validator": "contains_keywords",
                    "validator_args": {
                        "required_keywords": ["sustainability", "technology", "environment"]
                    },
                    "on_failure": "retry"
                }
            },
            {
                "type": "reprompt",
                "config": {
                    "strategy": "llm",
                    "max_attempts": 3,
                    "llm_config": {
                        "model_vendor": "openai",
                        "model_name": "gpt-4"
                    }
                }
            }
        ]
    }
    
    # Execute the agent with conditional reprompting
    try:
        result = create_dynamic_agent(
            agent_config=agent_config,
            udf=None,
            context_data_str="",
            formatted_prompt=None
        )
        
        print("✅ Blog post generated successfully!")
        print(f"Content length: {len(str(result[0]))}")
        print(f"Preview: {str(result[0])[:200]}...")
        
        return result
        
    except Exception as e:
        print(f"❌ Failed to generate blog post: {e}")
        return None


def example_with_custom_validator():
    """Example: Using a custom validator for specific business rules."""
    
    # Register a custom validator
    @ValidatorRegistry.register("blog_quality")
    def validate_blog_quality(content: str, min_paragraphs: int = 3) -> tuple[bool, str | None]:
        """Validate blog post quality requirements."""
        paragraphs = content.split('\n\n')
        actual_paragraphs = len([p for p in paragraphs if p.strip()])
        
        if actual_paragraphs < min_paragraphs:
            return False, f"Blog post needs at least {min_paragraphs} paragraphs, got {actual_paragraphs}"
        
        # Check for title (first line should be title-like)
        first_line = content.split('\n')[0].strip()
        if len(first_line) < 10 or not any(char.isupper() for char in first_line):
            return False, "Blog post should start with a clear title"
        
        return True, None
    
    # Use the custom validator
    agent_config = {
        "agent_type": "QualityBlogGenerator",
        "model_vendor": "openai", 
        "model_name": "gpt-4",
        "prompt": "Write a professional blog post about AI ethics",
        
        "interceptors": [
            {
                "type": "validation",
                "config": {
                    "validator": "blog_quality",
                    "validator_args": {
                        "min_paragraphs": 4
                    },
                    "on_failure": "retry"
                }
            },
            {
                "type": "reprompt",
                "config": {
                    "strategy": "template",
                    "max_attempts": 2,
                    "templates": {
                        "blog post needs at least": """
                        {original_prompt}
                        
                        IMPORTANT STRUCTURE REQUIREMENTS:
                        - Start with a compelling title
                        - Write at least {min_paragraphs} well-developed paragraphs
                        - Each paragraph should be 3-5 sentences
                        - Use clear topic sentences and transitions
                        """,
                        "should start with a clear title": """
                        {original_prompt}
                        
                        FORMAT REQUIREMENTS:
                        - First line must be a clear, engaging title
                        - Title should be 10+ characters and use proper capitalization
                        - Follow with well-structured paragraphs
                        """
                    }
                }
            }
        ]
    }
    
    result = create_dynamic_agent(
        agent_config=agent_config,
        udf=None,
        context_data_str="",
        formatted_prompt=None
    )
    
    return result


def load_config_from_yaml():
    """Example: Loading interceptor configuration from YAML file."""
    
    yaml_config = """
    agents:
      - agent_type: ProductReviewer
        model_vendor: "anthropic"
        model_name: "claude-3-sonnet"
        prompt: "Write a balanced product review"
        
        interceptors:
          - type: validation
            config:
              validator: "word_count"
              validator_args:
                expected: 100
              on_failure: retry
              
          - type: validation
            config:
              validator: "contains_keywords"
              validator_args:
                required_keywords: ["pros", "cons", "rating"]
              on_failure: retry
              
          - type: reprompt
            config:
              strategy: "template"
              max_attempts: 3
              templates:
                "expected 100 words": |
                  {original_prompt}
                  
                  WORD COUNT REQUIREMENT: Write exactly 100 words.
                  Current attempt had {word_count} words. Adjust accordingly.
                
                "missing required keywords": |
                  {original_prompt}
                  
                  REQUIRED ELEMENTS: Your review must include:
                  - Pros section highlighting positive aspects
                  - Cons section noting limitations  
                  - Overall rating (1-5 stars)
    """
    
    config = yaml.safe_load(yaml_config)
    agent_config = config['agents'][0]
    
    result = create_dynamic_agent(
        agent_config=agent_config,
        udf=None,
        context_data_str="Product: Wireless Headphones XYZ",
        formatted_prompt=None
    )
    
    return result


if __name__ == "__main__":
    print("🚀 Conditional Reprompting Integration Examples\n")
    
    print("1. Blog Post Generator with Multiple Validations")
    print("-" * 50)
    result1 = example_blog_post_generator()
    
    print("\n2. Custom Validator for Business Rules")
    print("-" * 50)
    result2 = example_with_custom_validator()
    
    print("\n3. Loading Configuration from YAML")
    print("-" * 50) 
    result3 = load_config_from_yaml()
    
    print("\n✅ All examples completed!")
    print("\nNext steps:")
    print("- Customize validators for your specific use cases")
    print("- Experiment with different reprompt strategies")
    print("- Monitor performance and adjust max_attempts")
    print("- Create templates for common failure patterns")