"""The prompt-size guard knows the context window of the current Claude models.

The windows are the ones Anthropic documents in its model overview.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import PromptTooLargeError
from agent_actions.prompt.message_builder import _MODEL_CONTEXT_LIMITS, MessageBuilder

ONE_MILLION = 1_000_000


@pytest.mark.parametrize(
    "model_name",
    [
        "claude-fable-5-2",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    ],
)
def test_a_current_claude_model_reads_one_million_tokens(model_name):
    assert _MODEL_CONTEXT_LIMITS[model_name] == ONE_MILLION


def test_claude_haiku_4_5_reads_200_000_tokens():
    assert _MODEL_CONTEXT_LIMITS["claude-haiku-4-5"] == 200_000


def test_a_322_119_token_prompt_passes_on_claude_haiku_5_5():
    MessageBuilder.build(
        "anthropic", "x" * (322_119 * 4), "", json_mode=False, model_name="claude-haiku-5-5"
    )


def test_a_prompt_above_one_million_tokens_is_still_refused_on_claude_haiku_5_5():
    with pytest.raises(PromptTooLargeError) as raised:
        MessageBuilder.build(
            "anthropic",
            "x" * (ONE_MILLION * 4 + 8),
            "",
            json_mode=False,
            model_name="claude-haiku-5-5",
        )

    assert raised.value.context["model_limit"] == ONE_MILLION
