"""Tests for configuration error classes."""

from agent_actions.errors.configuration import DuplicateFunctionError


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
