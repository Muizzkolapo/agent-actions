"""Configuration validation utilities for field chunking."""

from typing import TYPE_CHECKING, Dict, Any, List

if TYPE_CHECKING:
    from agent_actions.input.preprocessing.chunking.field_chunking import FieldChunkingValidationError
else:

    class FieldChunkingValidationError(ValueError):
        """Raised when field chunking configuration is invalid."""


class ConfigValidator:
    """Validator for field chunking configuration."""

    @staticmethod
    def validate_field_analyzer_config(chunk_config: Dict[str, Any]) -> None:
        """
        Validate FieldAnalyzer configuration.

        Args:
            chunk_config: The chunk configuration dictionary

        Raises:
            ValueError: If configuration is invalid
        """
        errors = []
        field_chunking = chunk_config.get("field_chunking", {})

        # Extract configuration values
        chunk_fields = field_chunking.get("chunk_fields", [])
        preserve_fields = field_chunking.get("preserve_fields", [])
        chunk_threshold = field_chunking.get("chunk_threshold", 0)
        field_rules = field_chunking.get("field_rules", {})
        auto_detection = field_chunking.get("auto_detection", {})
        auto_detect_enabled = auto_detection.get("enabled", False)

        # Validate conflicting fields
        errors.extend(ConfigValidator._validate_conflicting_fields(chunk_fields, preserve_fields))

        # Validate chunk threshold
        if chunk_threshold < 0:
            errors.append("chunk_threshold must be non-negative")

        # Validate that chunk_fields or auto_detection is configured when enabled
        if field_chunking.get("enabled") and not chunk_fields and not auto_detect_enabled:
            errors.append(
                "chunk_fields must be specified when field_chunking is enabled "
                "and auto_detection is disabled"
            )

        # Validate field rules
        errors.extend(ConfigValidator._validate_field_rules(field_rules))

        if errors:
            raise FieldChunkingValidationError(
                f"Invalid field chunking configuration: {'; '.join(errors)}"
            )

    @staticmethod
    def validate_field_chunker_config(chunk_config: Dict[str, Any]) -> None:
        """
        Validate FieldChunker configuration.

        Args:
            chunk_config: The chunk configuration dictionary

        Raises:
            ValueError: If configuration is invalid
        """
        errors = []

        # Extract configuration values
        chunk_size = chunk_config.get("chunk_size", 1000)
        overlap = chunk_config.get("overlap", 200)
        tokenizer_model = chunk_config.get("tokenizer_model", "cl100k_base")
        split_method = chunk_config.get("split_method", "tiktoken")

        # Validate chunk size
        if chunk_size <= 0:
            errors.append("chunk_size must be positive")

        # Validate overlap
        if overlap < 0:
            errors.append("overlap cannot be negative")

        if overlap >= chunk_size:
            errors.append("overlap must be smaller than chunk_size")

        # Validate tokenizer model
        if not isinstance(tokenizer_model, str) or not tokenizer_model.strip():
            errors.append("tokenizer_model must be a non-empty string")

        # Validate split method
        valid_split_methods = ["tiktoken", "chars", "spacy"]
        if split_method not in valid_split_methods:
            if not isinstance(split_method, str) or not split_method.strip():
                errors.append(
                    f"split_method must be a non-empty string, "
                    f"preferably one of: {valid_split_methods}"
                )

        if errors:
            raise FieldChunkingValidationError(f"Invalid chunk configuration: {'; '.join(errors)}")

    @staticmethod
    def _validate_conflicting_fields(
        chunk_fields: List[str], preserve_fields: List[str]
    ) -> List[str]:
        """
        Validate that no fields are both chunked and preserved.

        Args:
            chunk_fields: List of fields to chunk
            preserve_fields: List of fields to preserve

        Returns:
            List of error messages (empty if no conflicts)
        """
        errors = []
        if chunk_fields and preserve_fields:
            conflicting_fields = set(chunk_fields) & set(preserve_fields)
            if conflicting_fields:
                errors.append(
                    f"Fields cannot be both chunked and preserved: {sorted(conflicting_fields)}"
                )
        return errors

    @staticmethod
    def _validate_field_rules(field_rules: Dict[str, Any]) -> List[str]:
        """
        Validate field-specific rules.

        Args:
            field_rules: Dictionary of field-specific rules

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        if not field_rules:
            return errors

        for field_name, field_rule in field_rules.items():
            # Validate that field_rule is a dictionary
            if not isinstance(field_rule, dict):
                errors.append(f"field_rules[{field_name}] must be a dictionary")
                continue

            # Validate chunk_size
            if "chunk_size" in field_rule and field_rule["chunk_size"] <= 0:
                errors.append(f"field_rules[{field_name}].chunk_size must be positive")

            # Validate overlap
            if "overlap" in field_rule and field_rule["overlap"] < 0:
                errors.append(f"field_rules[{field_name}].overlap cannot be negative")

            # Validate chunk_threshold
            if "chunk_threshold" in field_rule and field_rule["chunk_threshold"] < 0:
                errors.append(f"field_rules[{field_name}].chunk_threshold must be non-negative")

            # Validate overlap vs chunk_size relationship
            chunk_size = field_rule.get("chunk_size", 1000)
            overlap = field_rule.get("overlap", 0)
            if overlap >= chunk_size:
                errors.append(f"field_rules[{field_name}].overlap must be smaller than chunk_size")

        return errors
