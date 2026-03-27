"""Wave 12 T1-5 regression: KeyError from schema validator must propagate, not be swallowed."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


class TestSchemaValidationKeyErrorPropagates:
    """T1-5: KeyError must NOT be caught after narrowing except clause to ValueError only."""

    def _make_mock_validator(self, side_effect):
        """Return a mock module for schema_output_validator."""
        mock_module = MagicMock()
        mock_module.validate_output_against_schema.side_effect = side_effect
        return mock_module

    def test_key_error_propagates(self):
        """KeyError from validate_output_against_schema must escape to the caller."""
        from agent_actions.processing.helpers import _validate_llm_output_schema

        response = {"result": "value"}
        agent_config = {"schema": {"type": "object"}, "on_schema_mismatch": "warn"}

        mock_mod = self._make_mock_validator(KeyError("unexpected_key"))

        saved = sys.modules.get("agent_actions.validation.schema_output_validator")
        sys.modules["agent_actions.validation.schema_output_validator"] = mock_mod
        try:
            with pytest.raises(KeyError, match="unexpected_key"):
                _validate_llm_output_schema(response, agent_config, "test_agent")
        finally:
            if saved is None:
                sys.modules.pop("agent_actions.validation.schema_output_validator", None)
            else:
                sys.modules["agent_actions.validation.schema_output_validator"] = saved

    def test_value_error_in_warn_mode_is_swallowed(self):
        """ValueError in non-strict mode must be caught (not propagate)."""
        from agent_actions.processing.helpers import _validate_llm_output_schema

        response = {"result": "value"}
        agent_config = {"schema": {"type": "object"}, "on_schema_mismatch": "warn"}

        mock_mod = self._make_mock_validator(ValueError("bad_value"))

        saved = sys.modules.get("agent_actions.validation.schema_output_validator")
        sys.modules["agent_actions.validation.schema_output_validator"] = mock_mod
        try:
            result = _validate_llm_output_schema(response, agent_config, "test_agent")
            assert result == response
        finally:
            if saved is None:
                sys.modules.pop("agent_actions.validation.schema_output_validator", None)
            else:
                sys.modules["agent_actions.validation.schema_output_validator"] = saved
