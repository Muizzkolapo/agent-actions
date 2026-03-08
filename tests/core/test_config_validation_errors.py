"""Tests for configuration validation error message quality."""

import pytest
import os
from agent_actions.output.response.expander import ActionExpander
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.errors import ConfigValidationError, ConfigurationError


class TestConfigValidationErrorMessages:
    """Verify error messages are helpful and actionable."""

    def test_missing_vendor_error_message_includes_fix(self):
        """Verify missing vendor error includes fix instructions."""
        agent = {
            "agent_type": "test_action",
            "name": "test_action",
            "model_name": "gpt-4",
            "api_key": "TEST_KEY",
        }
        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, "test_action")
        error = exc_info.value
        assert error.context is not None
        assert error.context["action_name"] == "test_action"
        assert "action_name" in error.context
        assert "missing_fields" in error.context
        assert "hint" in error.context
        hint = error.context["hint"].lower()
        assert "agent_actions.yml" in hint or "workflow" in hint or "action" in hint

    def test_missing_multiple_fields_error_lists_all(self):
        """Verify error lists all missing fields."""
        agent = {"agent_type": "test_action", "name": "test_action"}
        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_required_fields(agent, "test_action")
        error = exc_info.value
        missing = error.context["missing_fields"]
        assert "model_vendor" in missing
        assert "model_name" in missing
        assert "api_key" in missing
        assert len(missing) == 3

    def test_env_var_error_shows_export_command(self):
        """Verify env var error shows how to set it."""
        agent_config = {"agent_type": "test", "api_key": "${MISSING_VAR_12345}"}
        if "MISSING_VAR_12345" in os.environ:
            del os.environ["MISSING_VAR_12345"]
        with pytest.raises(ConfigurationError) as exc_info:
            BaseClient.get_api_key(agent_config)
        error = exc_info.value
        assert "hint" in error.context
        hint = error.context["hint"]
        assert "export" in hint
        assert "MISSING_VAR_12345" in hint

    def test_reserved_action_name_error_lists_reserved_names(self):
        """Verify reserved action name validation includes reserved list."""
        with pytest.raises(ConfigValidationError) as exc_info:
            ActionExpander._validate_action_name("prompt")
        error = exc_info.value
        assert "prompt" in str(error)
        assert "reserved_names" in error.context

    def test_where_clause_config_validation_empty_clause(self):
        """Test WHERE clause config validation rejects empty clause."""
        from agent_actions.output.response.config_schema import WhereClauseConfig
        from agent_actions.errors import ValidationError

        with pytest.raises(ValidationError, match="WHERE clause cannot be empty"):
            WhereClauseConfig(clause="")
        with pytest.raises(ValidationError, match="WHERE clause cannot be empty"):
            WhereClauseConfig(clause="   ")

    def test_where_clause_config_validation_dangerous_patterns(self):
        """Test WHERE clause config validates against dangerous patterns."""
        from agent_actions.output.response.config_schema import WhereClauseConfig
        from agent_actions.errors import ValidationError

        dangerous_clauses = [
            "field = __import__('os')",
            "field = exec('malicious code')",
            "field = eval('expression')",
            "field = open('/etc/passwd')",
        ]
        for clause in dangerous_clauses:
            with pytest.raises(ValidationError):
                WhereClauseConfig(clause=clause)


class TestSchemaPreValidationErrors:
    """Integration tests: unknown/invalid keys raise ConfigurationError via get_user_agents()."""

    def _make_manager(self, actions, defaults=None):
        """Create a ConfigManager with a new-format workflow config."""
        # Import order avoids circular import between coordinator and ConfigManager.
        import agent_actions.workflow.coordinator  # noqa: F401
        from agent_actions.llm.realtime.config import ConfigManager

        mgr = ConfigManager("test_workflow.yml", "")
        mgr.user_config = {
            "name": "test_workflow",
            "description": "test",
            "version": "1",
            "actions": actions,
        }
        if defaults:
            mgr.user_config["defaults"] = defaults
        return mgr

    def test_unknown_action_key_raises_via_get_user_agents(self):
        """Unknown action key raises ConfigurationError through get_user_agents()."""
        mgr = self._make_manager(actions=[{"name": "a", "intent": "i", "bogus_key": True}])
        with pytest.raises(ConfigurationError) as exc_info:
            mgr.get_user_agents()
        assert exc_info.value.context["action"] == "a"
        assert exc_info.value.__cause__ is not None

    def test_invalid_type_raises_via_get_user_agents(self):
        """Type-invalid value raises ConfigurationError through get_user_agents()."""
        mgr = self._make_manager(actions=[{"name": "a", "intent": "i", "temperature": "banana"}])
        with pytest.raises(ConfigurationError) as exc_info:
            mgr.get_user_agents()
        assert exc_info.value.context["action"] == "a"
        assert "temperature" in str(exc_info.value.__cause__)

    def test_invalid_defaults_type_raises_via_get_user_agents(self):
        """Type-invalid defaults value raises ConfigurationError through get_user_agents()."""
        mgr = self._make_manager(
            actions=[{"name": "a", "intent": "i"}],
            defaults={"temperature": "warm"},
        )
        with pytest.raises(ConfigurationError) as exc_info:
            mgr.get_user_agents()
        assert exc_info.value.context["section"] == "defaults"
        assert "temperature" in str(exc_info.value.__cause__)
