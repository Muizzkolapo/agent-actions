"""
Tests for config parsing and validation.

Tests cover config_schema as specified in tests_recommendations.jsonc:
1. config_schema/config_types validate types/defaults/enums; unknown keys flagged
2. WhereClauseConfig validates clause content and dangerous patterns

Note: Legacy where_parser tests removed - module deleted in favor of
modern AST-based implementation in preprocessing/parsing/.
"""

import pytest
from agent_actions.response_processing.config_schema import WhereClauseConfig, FilterScope
from agent_actions.errors import ValidationError


class TestWhereClauseConfig:
    """Test WHERE clause configuration validation."""

    def test_valid_where_clause_config(self):
        """Test valid WHERE clause configuration."""
        config = WhereClauseConfig(
            clause="field = 'value'",
            scope=FilterScope.ITEM,
            passthrough_on_empty=True,
            passthrough_on_error=True,
            cache_enabled=True,
        )
        assert config.clause == "field = 'value'"
        assert config.scope == FilterScope.ITEM
        assert config.passthrough_on_empty is True
        assert config.passthrough_on_error is True
        assert config.cache_enabled is True

    def test_where_clause_config_defaults(self):
        """Test WHERE clause configuration defaults."""
        config = WhereClauseConfig(clause="field = 'value'")
        assert config.scope == FilterScope.ITEM
        assert config.passthrough_on_empty is True
        assert config.passthrough_on_error is True
        assert config.cache_enabled is True

    def test_where_clause_config_validation_empty_clause(self):
        """Test WHERE clause config validation rejects empty clause."""
        with pytest.raises(ValidationError, match="WHERE clause cannot be empty"):
            WhereClauseConfig(clause="")
        with pytest.raises(ValidationError, match="WHERE clause cannot be empty"):
            WhereClauseConfig(clause="   ")

    def test_where_clause_config_validation_dangerous_patterns(self):
        """Test WHERE clause config validates against dangerous patterns."""
        dangerous_clauses = [
            "field = __import__('os')",
            "field = exec('malicious code')",
            "field = eval('expression')",
            "field = open('/etc/passwd')",
        ]
        for clause in dangerous_clauses:
            with pytest.raises(ValidationError):
                WhereClauseConfig(clause=clause)

    def test_filter_scope_enum(self):
        """Test FilterScope enum values."""
        assert FilterScope.ITEM == "item"
        assert FilterScope.AGENT == "agent"
        config = WhereClauseConfig(clause="field = 'value'", scope=FilterScope.AGENT)
        assert config.scope == FilterScope.AGENT
