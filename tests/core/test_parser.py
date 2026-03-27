"""
Tests for config parsing and validation.

Tests cover WhereClauseConfig validation of clause content and dangerous patterns.

Note: Legacy where_parser tests removed - module deleted in favor of
modern AST-based implementation in preprocessing/parsing/.
"""

import pytest

from agent_actions.errors import ValidationError
from agent_actions.output.response.config_schema import WhereClauseConfig


class TestWhereClauseConfig:
    """Test WHERE clause configuration validation."""

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
