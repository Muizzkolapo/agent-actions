"""
Unit tests for ValidatorRegistry.

Tests validator registration, retrieval, and built-in validators.
"""

import pytest
from agent_actions.validators.registry import (
    ValidatorRegistry,
    validate_word_count,
    validate_char_count,
    validate_keywords
)


class TestValidatorRegistry:
    """Test suite for ValidatorRegistry."""

    @pytest.fixture(autouse=True)
    def clear_registry(self):
        """Clear the registry before and after each test."""
        # Store original validators
        original = ValidatorRegistry._validators.copy()
        yield
        # Restore original validators
        ValidatorRegistry._validators = original

    def test_register_validator(self):
        """Test registering a new validator."""
        @ValidatorRegistry.register("test_validator")
        def test_validator(content: str) -> tuple[bool, str | None]:
            return True, None
        
        assert "test_validator" in ValidatorRegistry._validators
        assert ValidatorRegistry.get("test_validator") == test_validator

    def test_get_existing_validator(self):
        """Test retrieving an existing validator."""
        validator = ValidatorRegistry.get("word_count")
        assert validator is not None
        assert validator == validate_word_count

    def test_get_non_existing_validator(self):
        """Test retrieving a non-existing validator."""
        validator = ValidatorRegistry.get("non_existent")
        assert validator is None

    def test_list_validators(self):
        """Test listing all registered validators."""
        validators = ValidatorRegistry.list_validators()
        
        # Check built-in validators are present
        assert "word_count" in validators
        assert "char_count" in validators
        assert "contains_keywords" in validators

    def test_register_decorator_returns_function(self):
        """Test that register decorator returns the original function."""
        def my_validator(content: str) -> tuple[bool, str | None]:
            return True, None
        
        decorated = ValidatorRegistry.register("my_validator")(my_validator)
        
        assert decorated == my_validator
        assert ValidatorRegistry.get("my_validator") == my_validator

    def test_register_overwrites_existing(self):
        """Test that registering with same name overwrites existing validator."""
        @ValidatorRegistry.register("duplicate")
        def validator1(content: str) -> tuple[bool, str | None]:
            return True, "validator1"
        
        @ValidatorRegistry.register("duplicate")
        def validator2(content: str) -> tuple[bool, str | None]:
            return True, "validator2"
        
        validator = ValidatorRegistry.get("duplicate")
        assert validator == validator2
        result = validator("")
        assert result == (True, "validator2")


class TestBuiltInValidators:
    """Test suite for built-in validators."""

    def test_validate_word_count_exact_match(self):
        """Test word count validator with exact match."""
        success, error = validate_word_count("This is exactly five words", expected=5)
        assert success is True
        assert error is None

    def test_validate_word_count_mismatch(self):
        """Test word count validator with mismatch."""
        success, error = validate_word_count("Too few words", expected=5)
        assert success is False
        assert error == "Expected 5 words, got 3"

    def test_validate_word_count_default(self):
        """Test word count validator with default expected value."""
        success, error = validate_word_count("This is exactly five words")
        assert success is True
        assert error is None

    def test_validate_word_count_empty_string(self):
        """Test word count validator with empty string."""
        success, error = validate_word_count("", expected=0)
        assert success is True
        assert error is None
        
        success, error = validate_word_count("", expected=1)
        assert success is False
        assert error == "Expected 1 words, got 0"

    def test_validate_char_count_within_range(self):
        """Test character count validator within range."""
        success, error = validate_char_count("Hello World", min_chars=5, max_chars=20)
        assert success is True
        assert error is None

    def test_validate_char_count_too_short(self):
        """Test character count validator with too short content."""
        success, error = validate_char_count("Hi", min_chars=5)
        assert success is False
        assert error == "Too short: 2 chars, minimum 5"

    def test_validate_char_count_too_long(self):
        """Test character count validator with too long content."""
        success, error = validate_char_count("Hello World", max_chars=5)
        assert success is False
        assert error == "Too long: 11 chars, maximum 5"

    def test_validate_char_count_no_max(self):
        """Test character count validator with no maximum."""
        success, error = validate_char_count("A" * 1000, min_chars=10)
        assert success is True
        assert error is None

    def test_validate_char_count_defaults(self):
        """Test character count validator with default values."""
        success, error = validate_char_count("Any content")
        assert success is True
        assert error is None

    def test_validate_keywords_all_present(self):
        """Test keywords validator with all keywords present."""
        content = "The quick brown fox jumps over the lazy dog"
        keywords = ["quick", "fox", "dog"]
        
        success, error = validate_keywords(content, keywords)
        assert success is True
        assert error is None

    def test_validate_keywords_missing(self):
        """Test keywords validator with missing keywords."""
        content = "The quick brown fox"
        keywords = ["quick", "dog", "lazy"]
        
        success, error = validate_keywords(content, keywords)
        assert success is False
        assert error == "Missing required keywords: dog, lazy"

    def test_validate_keywords_case_insensitive(self):
        """Test keywords validator is case insensitive."""
        content = "THE QUICK BROWN FOX"
        keywords = ["the", "quick", "fox"]
        
        success, error = validate_keywords(content, keywords)
        assert success is True
        assert error is None

    def test_validate_keywords_empty_list(self):
        """Test keywords validator with empty keyword list."""
        success, error = validate_keywords("Any content", [])
        assert success is True
        assert error is None

    def test_validate_keywords_partial_match(self):
        """Test keywords validator with partial word matches."""
        content = "The quickly brown foxes"
        keywords = ["quick", "fox"]
        
        success, error = validate_keywords(content, keywords)
        assert success is True  # "quick" is in "quickly", "fox" is in "foxes"
        assert error is None

    @pytest.mark.parametrize("content,expected,should_pass", [
        ("one two three", 3, True),
        ("one two three", 4, False),
        ("  multiple   spaces  ", 2, True),
        ("single", 1, True),
        ("", 0, True),
        ("\n\nNewlines\n\n", 1, True),
    ])
    def test_word_count_edge_cases(self, content, expected, should_pass):
        """Test word count validator with edge cases."""
        success, error = validate_word_count(content, expected=expected)
        assert success == should_pass
        if not should_pass:
            assert error is not None

    def test_custom_validator_integration(self):
        """Test integrating a custom validator with the registry."""
        @ValidatorRegistry.register("email_format")
        def validate_email(content: str) -> tuple[bool, str | None]:
            import re
            pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if re.match(pattern, content.strip()):
                return True, None
            return False, "Invalid email format"
        
        # Test the custom validator
        validator = ValidatorRegistry.get("email_format")
        
        success, error = validator("test@example.com")
        assert success is True
        assert error is None
        
        success, error = validator("invalid-email")
        assert success is False
        assert error == "Invalid email format"