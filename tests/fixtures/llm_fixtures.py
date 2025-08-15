"""
Test fixtures and mocks for LLM calls.

Provides reusable fixtures for testing LLM-based functionality.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Any, Optional


class LLMResponseFixtures:
    """Collection of common LLM response patterns for testing."""
    
    @staticmethod
    def simple_response(content: str) -> List[Dict[str, str]]:
        """Create a simple LLM response."""
        return [{"content": content}]
    
    @staticmethod
    def response_with_text(text: str) -> List[Dict[str, str]]:
        """Create an LLM response using 'text' key."""
        return [{"text": text}]
    
    @staticmethod
    def multi_turn_response(contents: List[str]) -> List[Dict[str, str]]:
        """Create a multi-turn LLM response."""
        return [{"content": content} for content in contents]
    
    @staticmethod
    def error_response(error: str) -> Dict[str, str]:
        """Create an error response."""
        return {"error": error, "type": "error"}
    
    @staticmethod
    def structured_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a structured LLM response."""
        return [{"content": str(data), "structured_data": data}]


class MockLLMAgent:
    """Mock LLM agent for testing."""
    
    def __init__(self, responses: Optional[List[Any]] = None):
        """Initialize with optional predefined responses."""
        self.responses = responses or []
        self.call_count = 0
        self.call_history = []
    
    def __call__(self, config: Dict[str, Any], *args, **kwargs) -> Any:
        """Simulate LLM call."""
        self.call_history.append({
            "config": config,
            "args": args,
            "kwargs": kwargs
        })
        
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        
        # Default response if no predefined responses left
        return LLMResponseFixtures.simple_response("Default mock response")
    
    def reset(self):
        """Reset call tracking."""
        self.call_count = 0
        self.call_history = []


@pytest.fixture
def mock_llm_agent():
    """Provide a mock LLM agent."""
    return MockLLMAgent()


@pytest.fixture
def mock_agent_builder():
    """Mock the agent_builder module."""
    with patch('agent_actions.models.agent_builder') as mock:
        # Default behavior
        mock.create_dynamic_agent.return_value = LLMResponseFixtures.simple_response("Mock response")
        yield mock


@pytest.fixture
def mock_agent_builder_with_responses():
    """Mock agent_builder with configurable responses."""
    def _create_mock(responses: List[Any]):
        mock_agent = MockLLMAgent(responses)
        with patch('agent_actions.models.agent_builder') as mock:
            mock.create_dynamic_agent.side_effect = mock_agent
            mock._agent = mock_agent  # Store reference for test access
            yield mock
    
    return _create_mock


@pytest.fixture
def reprompt_response_fixtures():
    """Provide common reprompt response patterns."""
    return {
        "simple_improvement": LLMResponseFixtures.simple_response(
            "Please provide exactly 10 words in your response about the given topic."
        ),
        "detailed_improvement": LLMResponseFixtures.simple_response(
            "Your previous response was too short. Please expand your answer to include "
            "at least 100 words, providing specific examples and detailed explanations "
            "about the topic. Make sure to cover multiple aspects."
        ),
        "keyword_improvement": LLMResponseFixtures.simple_response(
            "Your response must include the following keywords: Python, testing, automation. "
            "Please rewrite your response to naturally incorporate these terms."
        ),
        "format_improvement": LLMResponseFixtures.simple_response(
            "Please format your response as a numbered list with exactly 5 items, "
            "where each item is a complete sentence."
        ),
        "constraint_improvement": LLMResponseFixtures.simple_response(
            "Your response must be between 50 and 100 characters long, "
            "and must start with 'The' and end with a period."
        )
    }


@pytest.fixture
def validation_test_cases():
    """Provide test cases for different validation scenarios."""
    return {
        "word_count": {
            "valid": {
                "5_words": "This has exactly five words",
                "10_words": "This sentence contains exactly ten words for testing validation purposes",
                "single": "Word"
            },
            "invalid": {
                "too_short": "Too short",
                "too_long": "This sentence has way too many words and will definitely fail validation",
                "empty": ""
            }
        },
        "char_count": {
            "valid": {
                "in_range": "This text is within the character range",
                "exact_min": "A" * 10,
                "exact_max": "B" * 100
            },
            "invalid": {
                "too_short": "Short",
                "too_long": "L" * 200,
                "empty": ""
            }
        },
        "keywords": {
            "valid": {
                "all_present": "Python testing is important for automation",
                "case_insensitive": "PYTHON TESTING AUTOMATION in uppercase",
                "partial_words": "Pythonic testing automates the process"
            },
            "invalid": {
                "missing_one": "Python testing is important",
                "missing_all": "This has none of the required words",
                "empty": ""
            }
        }
    }


@pytest.fixture
def mock_llm_with_behavior():
    """Create a mock LLM with configurable behavior patterns."""
    class BehaviorMockLLM:
        def __init__(self):
            self.behavior = "default"
            self.call_count = 0
            
        def set_behavior(self, behavior: str):
            """Set the behavior pattern."""
            self.behavior = behavior
            
        def __call__(self, config: Dict[str, Any], *args, **kwargs) -> Any:
            self.call_count += 1
            
            if self.behavior == "always_valid":
                # Always return responses that pass validation
                return LLMResponseFixtures.simple_response(
                    "This response has exactly ten words to pass validation successfully"
                )
            elif self.behavior == "improve_each_time":
                # Improve response with each attempt
                if self.call_count == 1:
                    return LLMResponseFixtures.simple_response("Too short")
                elif self.call_count == 2:
                    return LLMResponseFixtures.simple_response("Getting closer but not quite there yet")
                else:
                    return LLMResponseFixtures.simple_response(
                        "This final response has exactly ten words for validation success"
                    )
            elif self.behavior == "always_invalid":
                # Always return invalid responses
                return LLMResponseFixtures.simple_response("Fail")
            elif self.behavior == "error":
                # Simulate error
                raise Exception("LLM API Error")
            else:
                # Default behavior
                return LLMResponseFixtures.simple_response("Default response")
    
    mock = BehaviorMockLLM()
    with patch('agent_actions.models.agent_builder') as builder_mock:
        builder_mock.create_dynamic_agent.side_effect = mock
        builder_mock._behavior_mock = mock  # Store reference
        yield builder_mock


@pytest.fixture
def interceptor_test_configs():
    """Provide common interceptor configurations for testing."""
    return {
        "validation": {
            "word_count_10": {
                "validator": "word_count",
                "validator_args": {"expected": 10},
                "on_failure": "retry"
            },
            "char_count_range": {
                "validator": "char_count",
                "validator_args": {"min_chars": 50, "max_chars": 200},
                "on_failure": "retry"
            },
            "keywords_required": {
                "validator": "contains_keywords",
                "validator_args": {"required_keywords": ["python", "testing", "code"]},
                "on_failure": "retry"
            },
            "fail_on_error": {
                "validator": "word_count",
                "validator_args": {"expected": 10},
                "on_failure": "fail"
            }
        },
        "reprompt": {
            "llm_default": {
                "strategy": "llm",
                "max_attempts": 3,
                "llm_config": {
                    "model_vendor": "openai",
                    "model_name": "gpt-4"
                }
            },
            "llm_custom": {
                "strategy": "llm",
                "max_attempts": 5,
                "llm_config": {
                    "model_vendor": "anthropic",
                    "model_name": "claude-3",
                    "prompt_template": "Fix this: {validation_error}\nOriginal: {original_prompt}"
                }
            },
            "template_basic": {
                "strategy": "template",
                "max_attempts": 2,
                "templates": {
                    "too short": "Please expand: {original_prompt}",
                    "too long": "Please shorten: {original_prompt}",
                    "missing": "Include required elements: {original_prompt}"
                }
            }
        }
    }


# Helper functions for test setup

def create_mock_chain_response(success: bool = True, content: str = "Mock response") -> Mock:
    """Create a mock response for interceptor chain testing."""
    mock = Mock()
    mock.continue_processing = success
    mock.modified_response = {"content": content} if success else None
    mock.retry_context = None if success else {"retry": True}
    mock.metadata = {}
    return mock


def setup_mock_validator(name: str, behavior: str = "always_pass") -> Mock:
    """Setup a mock validator with specified behavior."""
    mock = Mock()
    
    if behavior == "always_pass":
        mock.return_value = (True, None)
    elif behavior == "always_fail":
        mock.return_value = (False, "Validation failed")
    elif behavior == "conditional":
        # Fails first time, passes second time
        mock.side_effect = [
            (False, "First attempt failed"),
            (True, None)
        ]
    
    with patch.object(ValidatorRegistry, 'get', return_value=mock):
        yield mock