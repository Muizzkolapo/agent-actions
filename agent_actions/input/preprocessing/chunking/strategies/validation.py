"""Configuration validation utilities for field chunking."""

from typing import Any

from agent_actions.input.preprocessing.chunking.errors import FieldChunkingValidationError
from agent_actions.output.response.config_fields import get_default


class ConfigValidator:
    """Validator for field chunking configuration."""

    @staticmethod
    def validate_field_analyzer_config(chunk_config: dict[str, Any]) -> None:
        """Validate FieldAnalyzer configuration.

        Raises:
            FieldChunkingValidationError: If configuration is invalid.
        """
        errors = []
        field_chunking = chunk_config.get("field_chunking", {})

        chunk_fields = field_chunking.get("chunk_fields", [])
        preserve_fields = field_chunking.get("preserve_fields", [])
        chunk_threshold = field_chunking.get("chunk_threshold", 0)
        field_rules = field_chunking.get("field_rules", {})
        auto_detection = field_chunking.get("auto_detection", {})
        auto_detect_enabled = auto_detection.get("enabled", False)

        errors.extend(ConfigValidator._validate_conflicting_fields(chunk_fields, preserve_fields))

        if chunk_threshold < 0:
            errors.append("chunk_threshold must be non-negative")

        if field_chunking.get("enabled") and not chunk_fields and not auto_detect_enabled:
            errors.append(
                "chunk_fields must be specified when field_chunking is enabled "
                "and auto_detection is disabled"
            )

        errors.extend(ConfigValidator._validate_field_rules(field_rules))

        if errors:
            raise FieldChunkingValidationError(
                f"Invalid field chunking configuration: {'; '.join(errors)}"
            )

    @staticmethod
    def validate_field_chunker_config(chunk_config: dict[str, Any]) -> None:
        """Validate FieldChunker configuration.

        Raises:
            FieldChunkingValidationError: If configuration is invalid.
        """
        errors = []

        chunk_size = chunk_config.get("chunk_size", get_default("chunk_size"))
        overlap = chunk_config.get("overlap", get_default("chunk_overlap"))
        tokenizer_model = chunk_config.get("tokenizer_model", get_default("tokenizer_model"))
        split_method = chunk_config.get("split_method", get_default("split_method"))

        if chunk_size <= 0:
            errors.append("chunk_size must be positive")

        if overlap < 0:
            errors.append("overlap cannot be negative")

        if overlap >= chunk_size:
            errors.append("overlap must be smaller than chunk_size")

        if not isinstance(tokenizer_model, str) or not tokenizer_model.strip():
            errors.append("tokenizer_model must be a non-empty string")

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
        chunk_fields: list[str], preserve_fields: list[str]
    ) -> list[str]:
        """Return error messages for fields that are both chunked and preserved."""
        errors = []
        if chunk_fields and preserve_fields:
            conflicting_fields = set(chunk_fields) & set(preserve_fields)
            if conflicting_fields:
                errors.append(
                    f"Fields cannot be both chunked and preserved: {sorted(conflicting_fields)}"
                )
        return errors

    @staticmethod
    def _validate_field_rules(field_rules: dict[str, Any]) -> list[str]:
        """Return error messages for invalid field-specific rules."""
        errors: list[str] = []
        if not field_rules:
            return errors

        for field_name, field_rule in field_rules.items():
            if not isinstance(field_rule, dict):
                errors.append(f"field_rules[{field_name}] must be a dictionary")
                continue

            if "chunk_size" in field_rule and field_rule["chunk_size"] <= 0:
                errors.append(f"field_rules[{field_name}].chunk_size must be positive")

            if "overlap" in field_rule and field_rule["overlap"] < 0:
                errors.append(f"field_rules[{field_name}].overlap cannot be negative")

            if "chunk_threshold" in field_rule and field_rule["chunk_threshold"] < 0:
                errors.append(f"field_rules[{field_name}].chunk_threshold must be non-negative")

            chunk_size = field_rule.get("chunk_size", get_default("chunk_size"))
            overlap = field_rule.get("overlap", 0)
            if overlap >= chunk_size:
                errors.append(f"field_rules[{field_name}].overlap must be smaller than chunk_size")

        return errors
