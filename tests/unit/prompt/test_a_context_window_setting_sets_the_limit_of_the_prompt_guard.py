"""`context_window` sets the limit the prompt-size guard compares the estimate with.

It outranks the model table, so a model agac does not know, or knows with too small a
window, can take a prompt as large as the operator says the model reads.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import PromptTooLargeError
from agent_actions.prompt.message_builder import MessageBuilder

# The guard estimates 4 characters a token: 1,288,476 characters are 322,119 tokens.
PROMPT_OF_322_119_TOKENS = "x" * (322_119 * 4)


def _build(model_name: str | None, context_window: int | None, prompt: str = "") -> None:
    MessageBuilder.build(
        "anthropic",
        prompt or PROMPT_OF_322_119_TOKENS,
        "",
        json_mode=False,
        model_name=model_name,
        context_window=context_window,
    )


def test_a_322_119_token_estimate_passes_with_a_context_window_of_400_000():
    _build("a-model-agac-does-not-know", 400_000)


def test_without_the_setting_an_unknown_model_still_gets_128_000_tokens():
    with pytest.raises(PromptTooLargeError) as raised:
        _build("a-model-agac-does-not-know", None)

    assert raised.value.context["model_limit"] == 128_000


def test_the_setting_outranks_the_model_table():
    with pytest.raises(PromptTooLargeError) as raised:
        MessageBuilder.build(
            "openai", "x" * 40_000, "", json_mode=False, model_name="gpt-4o", context_window=5_000
        )

    assert raised.value.context["model_limit"] == 5_000


def test_the_setting_applies_with_no_model_name():
    _build(None, 400_000)


def test_the_refusal_names_the_setting():
    with pytest.raises(PromptTooLargeError, match="context_window"):
        _build("a-model-agac-does-not-know", 300_000)
