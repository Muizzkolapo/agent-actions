"""
Integration tests for online reprompt processing.

Tests the full reprompt flow through RecordProcessor with validation UDFs.
"""

import pytest
from unittest.mock import Mock, patch, call
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import ProcessingContext, ProcessingMode
from agent_actions.processing.recovery.validation import (
    reprompt_validation,
    _VALIDATION_REGISTRY,
)


class TestOnlineRepromptIntegration:
    """Integration tests for online reprompt with RecordProcessor."""

    def setup_method(self):
        """Clear registry and register test UDFs."""
        _VALIDATION_REGISTRY.clear()

        # Register validation UDF that checks for forbidden words
        @reprompt_validation("Response must not contain the word 'forbidden'")
        def check_no_forbidden_words(response: dict) -> bool:
            text = str(response).lower()
            return "forbidden" not in text

        # Register validation UDF that checks for required fields
        @reprompt_validation("Response must contain 'title' and 'author' fields")
        def check_required_fields(response: dict) -> bool:
            return "title" in response and "author" in response

    def test_reprompt_feedback_injected_into_prompt(self):
        """
        CRITICAL TEST: Verify feedback is actually sent to LLM on reprompt.

        This test will FAIL until prompt mutation is implemented.

        Flow:
        1. LLM returns response with forbidden word
        2. Validation fails
        3. RepromptService builds feedback message
        4. LLM called again with original prompt + feedback
        5. Verify LLM receives the feedback in the prompt
        """
        # Setup agent config with reprompt
        agent_config = {
            "name": "test_action",
            "intent": "Test action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
            },
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            },
        }

        processor = RecordProcessor(agent_config, "test_action")

        # Create processing context
        context = ProcessingContext(
            agent_config=agent_config,
            agent_name="test_action",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        # Mock the LLM to track prompts it receives
        llm_calls = []

        def mock_run_dynamic_agent(config, name, content, formatted_prompt, tools_path=None):
            """Track prompts and simulate responses."""
            llm_calls.append(formatted_prompt)

            # First call: return response with forbidden word
            if len(llm_calls) == 1:
                return {"description": "This is a forbidden topic"}, True

            # Second call: return valid response
            return {"description": "This is a safe topic"}, True

        with patch(
            "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
            side_effect=mock_run_dynamic_agent,
        ):
            # Mock prompt preparation
            with patch.object(processor, "_prepare_prompt") as mock_prep:
                mock_prep.return_value = Mock(
                    formatted_prompt="Classify this content: test",
                    passthrough_fields={},
                )

                # Process item
                result = processor.process(item={"text": "test content"}, context=context)

        # Verify LLM was called twice
        assert len(llm_calls) == 2, f"Expected 2 LLM calls, got {len(llm_calls)}"

        # Verify first call used original prompt
        assert llm_calls[0] == "Classify this content: test"

        # CRITICAL ASSERTION: Second call should have feedback appended
        second_prompt = llm_calls[1]
        assert "---" in second_prompt, "Feedback separator not found in second prompt"
        assert "Your response failed validation" in second_prompt, (
            "Validation failure message not in prompt"
        )
        assert "Response must not contain the word 'forbidden'" in second_prompt, (
            "Feedback message not in prompt"
        )
        assert (
            '{"description": "This is a forbidden topic"}' in second_prompt
            or '"description": "This is a forbidden topic"' in second_prompt
        ), "Failed response not shown in feedback"
        assert "Please correct and respond again" in second_prompt, (
            "Correction request not in prompt"
        )

        # Verify result shows reprompt occurred
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 2
        assert result.recovery_metadata.reprompt.passed is True

    def test_reprompt_passes_first_attempt_no_feedback(self):
        """When validation passes on first attempt, no feedback should be sent and no recovery metadata added."""
        agent_config = {
            "name": "test_action",
            "intent": "Test action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
            },
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
            },
        }

        processor = RecordProcessor(agent_config, "test_action")
        context = ProcessingContext(
            agent_config=agent_config,
            agent_name="test_action",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        llm_calls = []

        def mock_run_dynamic_agent(config, name, content, formatted_prompt, tools_path=None):
            llm_calls.append(formatted_prompt)
            # Return valid response immediately
            return {"description": "This is a safe topic"}, True

        with patch(
            "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
            side_effect=mock_run_dynamic_agent,
        ):
            with patch.object(processor, "_prepare_prompt") as mock_prep:
                mock_prep.return_value = Mock(
                    formatted_prompt="Classify this content: test",
                    passthrough_fields={},
                )

                result = processor.process(item={"text": "test content"}, context=context)

        # Should only call LLM once
        assert len(llm_calls) == 1

        # When validation passes on first attempt, no actual reprompting occurred,
        # so recovery_metadata should be None (per commit 0333e726)
        assert result.recovery_metadata is None

    def test_reprompt_exhausted_with_feedback(self):
        """
        When validation exhausts attempts, verify feedback was sent on each attempt.

        This ensures feedback injection works even when validation never passes.
        """
        agent_config = {
            "name": "test_action",
            "intent": "Test action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
            "reprompt": {
                "validation": "check_required_fields",
                "max_attempts": 3,
                "on_exhausted": "return_last",
            },
        }

        processor = RecordProcessor(agent_config, "test_action")
        context = ProcessingContext(
            agent_config=agent_config,
            agent_name="test_action",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        llm_calls = []

        def mock_run_dynamic_agent(config, name, content, formatted_prompt, tools_path=None):
            llm_calls.append(formatted_prompt)
            # Always return invalid response (missing 'author')
            return {"title": "Test Book"}, True

        with patch(
            "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
            side_effect=mock_run_dynamic_agent,
        ):
            with patch.object(processor, "_prepare_prompt") as mock_prep:
                mock_prep.return_value = Mock(
                    formatted_prompt="Extract book info: test",
                    passthrough_fields={},
                )

                result = processor.process(item={"text": "test content"}, context=context)

        # Should call LLM 3 times (max_attempts)
        assert len(llm_calls) == 3

        # First call: original prompt
        assert llm_calls[0] == "Extract book info: test"

        # Second call: should have feedback
        assert "Your response failed validation" in llm_calls[1]
        assert "Response must contain 'title' and 'author' fields" in llm_calls[1]

        # Third call: should have feedback (may reference attempt 2's response)
        assert "Your response failed validation" in llm_calls[2]

        # Verify exhausted status
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 3
        assert result.recovery_metadata.reprompt.passed is False

    def test_reprompt_with_retry_feedback_preserved(self):
        """
        When both retry and reprompt are enabled, verify feedback is preserved
        across retry attempts within a reprompt iteration.
        """
        agent_config = {
            "name": "test_action",
            "intent": "Test action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
            },
            "retry": {
                "enabled": True,
                "max_attempts": 2,
            },
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
            },
        }

        processor = RecordProcessor(agent_config, "test_action")
        context = ProcessingContext(
            agent_config=agent_config,
            agent_name="test_action",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        llm_calls = []
        call_count = [0]

        def mock_run_dynamic_agent(config, name, content, formatted_prompt, tools_path=None):
            llm_calls.append(formatted_prompt)
            call_count[0] += 1

            # First reprompt attempt: return invalid (with forbidden word)
            if call_count[0] <= 1:
                return {"description": "This is a forbidden topic"}, True

            # Second reprompt attempt: return valid
            return {"description": "This is a safe topic"}, True

        with patch(
            "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
            side_effect=mock_run_dynamic_agent,
        ):
            with patch.object(processor, "_prepare_prompt") as mock_prep:
                mock_prep.return_value = Mock(
                    formatted_prompt="Classify this content: test",
                    passthrough_fields={},
                )

                result = processor.process(item={"text": "test content"}, context=context)

        # Verify second call has feedback
        assert len(llm_calls) >= 2
        assert "Your response failed validation" in llm_calls[1]

        # Verify both retry and reprompt metadata present
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 2
        assert result.recovery_metadata.reprompt.passed is True


class TestRepromptFeedbackMessageContent:
    """Tests specifically for feedback message content and structure."""

    def setup_method(self):
        """Clear registry and register test UDF."""
        _VALIDATION_REGISTRY.clear()

        @reprompt_validation("Custom validation message here")
        def test_validator(response: dict) -> bool:
            return response.get("valid", False)

    def test_feedback_contains_all_required_elements(self):
        """Verify feedback message has all RFC-specified elements."""
        agent_config = {
            "name": "test_action",
            "intent": "Test action",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "schema": {"type": "object"},
            "reprompt": {
                "validation": "test_validator",
                "max_attempts": 2,
            },
        }

        processor = RecordProcessor(agent_config, "test_action")
        context = ProcessingContext(
            agent_config=agent_config,
            agent_name="test_action",
            mode=ProcessingMode.ONLINE,
            is_first_stage=True,
        )

        captured_prompts = []

        def mock_run_dynamic_agent(config, name, content, formatted_prompt, tools_path=None):
            captured_prompts.append(formatted_prompt)
            if len(captured_prompts) == 1:
                return {"valid": False, "data": "test"}, True
            return {"valid": True}, True

        with patch(
            "agent_actions.utilities.processor.processor_helpers.run_dynamic_agent",
            side_effect=mock_run_dynamic_agent,
        ):
            with patch.object(processor, "_prepare_prompt") as mock_prep:
                mock_prep.return_value = Mock(
                    formatted_prompt="Original prompt",
                    passthrough_fields={},
                )

                processor.process(item={"text": "test"}, context=context)

        # Check second prompt has all RFC elements
        feedback_prompt = captured_prompts[1]

        # 1. Separator
        assert "---" in feedback_prompt

        # 2. Validation failure message
        assert "Your response failed validation:" in feedback_prompt

        # 3. Custom feedback message from decorator
        assert "Custom validation message here" in feedback_prompt

        # 4. Failed response
        assert "Your response:" in feedback_prompt
        assert '"valid": false' in feedback_prompt.lower() or '"valid": False' in feedback_prompt

        # 5. Correction request
        assert "Please correct and respond again" in feedback_prompt
