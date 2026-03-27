"""Tests that error constructors do not mutate caller-supplied context dicts."""

import pytest

from agent_actions.errors.configuration import (
    ConfigValidationError,
    DuplicateFunctionError,
    UDFLoadError,
)
from agent_actions.errors.external_services import VendorAPIError
from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.errors.validation import SchemaValidationError


@pytest.mark.parametrize(
    "error_class,kwargs",
    [
        pytest.param(
            PreFlightValidationError,
            {"message": "bad ref", "missing_references": ["x"]},
            id="PreFlightValidationError",
        ),
        pytest.param(
            SchemaValidationError,
            {"message": "bad schema", "missing_fields": ["f1"]},
            id="SchemaValidationError",
        ),
        pytest.param(
            ConfigValidationError,
            {"message": "key", "reason": "bad"},
            id="ConfigValidationError-positional",
        ),
        pytest.param(
            ConfigValidationError,
            {"config_key": "k", "reason": "r"},
            id="ConfigValidationError-keyword",
        ),
        pytest.param(
            DuplicateFunctionError,
            {"function_name": "fn", "existing_location": "a", "new_location": "b"},
            id="DuplicateFunctionError",
        ),
        pytest.param(
            UDFLoadError,
            {"module": "mod", "error": "boom"},
            id="UDFLoadError",
        ),
        pytest.param(
            VendorAPIError,
            {"vendor": "openai", "endpoint": "/chat"},
            id="VendorAPIError",
        ),
    ],
)
def test_context_dict_not_mutated(error_class, kwargs):
    """Constructing an error must not mutate the caller's context dict."""
    original = {"caller_key": "caller_value"}
    snapshot = dict(original)

    # Pop 'message' if present to handle positional arg
    if "message" in kwargs:
        msg = kwargs.pop("message")
        error_class(msg, context=original, **kwargs)
    else:
        error_class(context=original, **kwargs)

    assert original == snapshot, (
        f"{error_class.__name__} mutated the caller's context dict: {original}"
    )


def test_vendor_api_error_rejects_unknown_kwargs():
    """VendorAPIError no longer accepts **kwargs — typos raise TypeError."""
    with pytest.raises(TypeError):
        VendorAPIError("msg", vendro="typo")
