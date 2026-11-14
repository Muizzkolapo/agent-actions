"""A pre-flight refusal keeps its own message and hint whatever words it contains."""

import pytest

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.logging.errors.translator import ErrorTranslator


@pytest.mark.parametrize(
    ("message", "word_match_title"),
    [
        (
            "API key environment variable 'OPENAI_API_KEY' is not set "
            "(required by action 'a', vendor 'openai')",
            "Invalid Openai API key",
        ),
        ("Unknown model 'gpt-x' for vendor 'openai'", "Invalid model specified"),
        ("Seed file not found for the dispatch function", "Function 'unknown' not found"),
        ("Seed file not found: data.json", "File not found"),
        ("Endpoint 'lab' did not answer: connection refused", "Connection failed"),
    ],
    ids=["authentication", "model", "function", "file", "api"],
)
def test_a_refusal_whose_words_match_another_formatter_keeps_them(message, word_match_title):
    translator = ErrorTranslator()

    refusal = translator.translate(PreFlightValidationError(message, hint="Do this"), {})
    plain = translator.translate(RuntimeError(message), {})

    assert refusal.details == f"PreFlightValidationError: {message}"
    assert refusal.fix == "Do this"
    assert plain.title == word_match_title


_UNSET = (
    "API key environment variable 'OPENAI_API_KEY' is not set "
    "(required by action 'a', vendor 'openai')"
)


def test_a_vendor_authentication_error_still_reads_as_an_invalid_key():
    vendor_error = type("AuthenticationError", (Exception,), {})("the request was refused")

    error = ErrorTranslator().translate(vendor_error, {"provider": "openai"})

    assert error.category == "Authentication Error"
    assert error.title == "Invalid Openai API key"


def test_a_refusal_wrapped_by_another_error_keeps_its_words():
    try:
        try:
            raise PreFlightValidationError(_UNSET, hint="Do this")
        except PreFlightValidationError as refusal:
            raise RuntimeError("load failed") from refusal
    except RuntimeError as wrapper:
        error = ErrorTranslator().translate(wrapper, {})

    assert error.details == f"PreFlightValidationError: {_UNSET}"
    assert error.fix == "Do this"


def test_a_refusal_whose_cause_names_an_api_key_keeps_its_hint():
    refusal = PreFlightValidationError(_UNSET, hint="Do this", cause=ValueError(_UNSET))

    error = ErrorTranslator().translate(refusal, {})

    assert error.title != "Invalid Openai API key"
    assert error.fix == "Do this"
