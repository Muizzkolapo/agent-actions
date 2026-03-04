"""Tests for configuration error classes."""

from agent_actions.errors.configuration import ConfigValidationError, DuplicateFunctionError


class TestDuplicateFunctionError:
    """Tests for DuplicateFunctionError."""

    def test_suggestions_in_detailed_message(self):
        err = DuplicateFunctionError(
            function_name="aggregate_validation_votes",
            existing_location="qanalabs-quiz-gen.aggregate_validation_votes",
            existing_file="/path/existing.py",
            new_location="code_options_quiz.aggregate_validation_votes",
            new_file="/path/new.py",
        )
        msg = str(err)
        assert "Suggestions:" in msg
        assert "Rename one of the functions" in msg
        assert "shared directory" in msg
        assert "Remove the duplicate" in msg

    def test_suggestions_without_locations(self):
        err = DuplicateFunctionError(function_name="my_func")
        msg = str(err)
        assert "Duplicate UDF function name detected: 'my_func'" in msg
        assert "Suggestions:" in msg

    def test_plain_message_no_suggestions(self):
        err = DuplicateFunctionError("some other error")
        msg = str(err)
        assert "Suggestions:" not in msg


class TestConfigValidationError:
    """Tests for ConfigValidationError calling conventions."""

    def test_positional_style(self):
        err = ConfigValidationError("my_key", "invalid value")
        assert "my_key" in str(err)
        assert "invalid value" in str(err)
        assert err.context["config_key"] == "my_key"
        assert err.context["reason"] == "invalid value"

    def test_keyword_style(self):
        err = ConfigValidationError(config_key="my_key", reason="bad")
        assert "my_key" in str(err)
        assert "bad" in str(err)
        assert err.context["config_key"] == "my_key"

    def test_message_only_style(self):
        err = ConfigValidationError("Something went wrong")
        assert str(err) == "Something went wrong"

    def test_config_key_only(self):
        err = ConfigValidationError(config_key="orphan_key")
        assert "orphan_key" in str(err)
