"""tests/unit/config/test_reprompt_error_messages.py"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig
from agent_actions.processing.recovery.reprompt import create_reprompt_service_from_config


class TestRepromptTrueRejection:
    """reprompt: true must mention both schema-based and UDF-based options."""

    def test_action_config_mentions_schema_option(self):
        with pytest.raises(ValidationError, match="on_schema_mismatch"):
            ActionConfig(
                name="test_action",
                intent="test",
                reprompt=True,  # type: ignore[arg-type]
            )

    def test_defaults_config_mentions_schema_option(self):
        with pytest.raises(ValidationError, match="on_schema_mismatch"):
            DefaultsConfig(reprompt=True)  # type: ignore[arg-type]


class TestRepromptMissingValidator:
    """reprompt with no validator must mention on_schema_mismatch as an option."""

    def test_missing_validator_mentions_schema_option(self):
        with pytest.raises(ValueError, match="on_schema_mismatch"):
            create_reprompt_service_from_config(
                {"max_attempts": 3},  # no validation key, no external validator
            )
