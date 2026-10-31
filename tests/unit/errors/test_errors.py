"""Parametrized coverage of every exception class exported by agent_actions.errors."""

from __future__ import annotations

import pytest

import agent_actions.errors as errors_pkg
from agent_actions.errors import (
    AgentActionsError,
    AmbiguousAgentName,
    ConfigValidationError,
    SchemaValidationError,
    TemplateVariableError,
)

ALL_CLASSES = sorted(
    (
        obj
        for obj in (getattr(errors_pkg, name) for name in errors_pkg.__all__)
        if isinstance(obj, type) and issubclass(obj, Exception)
    ),
    key=lambda c: c.__name__,
)

# Classes whose constructor does not take (message, context=...).
_NO_CONTEXT_PARAM = {TemplateVariableError, AmbiguousAgentName}


def _make(cls):
    """Construct any error class with minimal required arguments."""
    if cls is TemplateVariableError:
        return cls(
            missing_variables=["x"],
            available_variables=["y"],
            agent_name="agent",
            mode="batch",
            cause=ValueError("oops"),
        )
    if cls is AmbiguousAgentName:
        return cls("agent", ["wf_a/agent_config/agent", "wf_b/agent_config/agent"])
    return cls("test message", context={"k": "v"})


def test_all_classes_covers_the_known_exports():
    names = {c.__name__ for c in ALL_CLASSES}
    assert {"ProjectNotFoundError", "DispositionsNotStoredError", "TemplateVariableError"} <= names


@pytest.mark.parametrize("cls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_is_exception_subclass(cls):
    """Every error class must be an Exception subclass."""
    assert issubclass(cls, Exception)
    assert issubclass(cls, AgentActionsError)


_CONTEXT_CAPABLE_CLASSES = [c for c in ALL_CLASSES if c not in _NO_CONTEXT_PARAM]


@pytest.mark.parametrize(
    "cls", _CONTEXT_CAPABLE_CLASSES, ids=[c.__name__ for c in _CONTEXT_CAPABLE_CLASSES]
)
def test_context_dict_is_copied_on_construction(cls):
    """Mutating caller's dict after construction must not affect stored context."""
    original_ctx = {"key": "original"}
    exc = cls("msg", context=original_ctx)

    # Mutate caller's dict
    original_ctx["key"] = "mutated"

    # Stored context should still have the original value
    assert exc.context.get("key") == "original", (
        f"{cls.__name__}.context was not defensively copied: mutation propagated from caller's dict"
    )


@pytest.mark.parametrize("cls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_message_is_str(cls):
    """str(exc) must return a string and not raise."""
    exc = _make(cls)
    result = str(exc)
    assert isinstance(result, str)
    assert len(result) > 0


def test_template_variable_error_message_interpolation():
    """TemplateVariableError builds message from missing_variables and agent_name."""
    exc = TemplateVariableError(
        missing_variables=["field_a", "field_b"],
        available_variables=["field_c"],
        agent_name="my_agent",
        mode="batch",
        cause=ValueError("jinja error"),
    )
    msg = str(exc)
    assert "my_agent" in msg
    assert "field_a" in msg
    assert "field_b" in msg


def test_agent_actions_error_cause_chaining():
    """cause= kwarg must chain __cause__ for PEP 3134 compatibility."""
    cause = RuntimeError("root cause")
    exc = AgentActionsError("wrapper", cause=cause)
    assert exc.__cause__ is cause
    assert exc.cause is cause


def test_schema_validation_error_attributes():
    """SchemaValidationError must store all keyword arguments as attributes."""
    exc = SchemaValidationError(
        "msg",
        schema_name="MySchema",
        validation_type="structure",
        action_name="my_action",
        missing_fields=["field_x"],
        extra_fields=["field_y"],
    )
    assert exc.schema_name == "MySchema"
    assert exc.validation_type == "structure"
    assert exc.action_name == "my_action"
    assert "field_x" in exc.missing_fields
    assert "field_y" in exc.extra_fields


def test_config_validation_error_reason_path():
    """ConfigValidationError with reason= builds a descriptive message."""
    exc = ConfigValidationError(config_key="model_vendor", reason="must be non-empty")
    msg = str(exc)
    assert "model_vendor" in msg
    assert "must be non-empty" in msg
