"""What `invoke_critique` pulls out of the provider envelope.

The critique text is handed straight back to the model as reprompt feedback, so
reading the wrong key does not fail loudly — it feeds the model the repr of an
envelope instead of the criticism.
"""

from unittest.mock import patch

import pytest

from agent_actions.processing.recovery.critique import invoke_critique

INVOKE = "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client"
CRITIQUE = "The options restate the stem; option 2 needs a distinct mechanism."


def _agent_config():
    return {"model_vendor": "anthropic", "model_name": "claude-sonnet-5", "name": "author"}


def test_critique_text_comes_back_as_the_model_wrote_it():
    with patch(INVOKE, return_value=[{"raw_response": CRITIQUE}]):
        text = invoke_critique(_agent_config(), {"stem": "x"}, "options invalid")
    assert text == CRITIQUE


def test_a_custom_output_field_is_honoured():
    config = {**_agent_config(), "output_field": "analysis"}
    with patch(INVOKE, return_value=[{"analysis": CRITIQUE}]):
        text = invoke_critique(config, {"stem": "x"}, "options invalid")
    assert text == CRITIQUE


def test_a_plain_string_reply_is_returned_unchanged():
    with patch(INVOKE, return_value=[CRITIQUE]):
        text = invoke_critique(_agent_config(), {"stem": "x"}, "options invalid")
    assert text == CRITIQUE


def test_empty_result_raises():
    with patch(INVOKE, return_value=[]), pytest.raises(ValueError, match="empty"):
        invoke_critique(_agent_config(), {"stem": "x"}, "options invalid")
