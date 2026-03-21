"""H-5: Parametrized coverage of all 38 exception classes in agent_actions.errors."""

from __future__ import annotations

import pytest

from agent_actions.errors import (
    AgentActionsError,
    AgentExecutionError,
    AgentNotFoundError,
    AnthropicError,
    ConfigurationError,
    ConfigValidationError,
    DataValidationError,
    DependencyError,
    DirectoryError,
    DuplicateFunctionError,
    EmptyOutputError,
    ExternalServiceError,
    FileLoadError,
    FileSystemError,
    FileWriteError,
    FunctionNotFoundError,
    GenerationError,
    InvalidParameterError,
    NetworkError,
    OperationalError,
    PathValidationError,
    PreFlightValidationError,
    ProcessingError,
    ProjectNotFoundError,
    PromptValidationError,
    RateLimitError,
    ResourceError,
    SchemaValidationError,
    SerializationError,
    TemplateRenderingError,
    TransformationError,
    UDFLoadError,
    ValidationError,
    VendorAPIError,
    VendorConfigError,
    WorkflowError,
)
from agent_actions.errors.preflight import ContextStructureError
from agent_actions.errors.operations import TemplateVariableError


# ---------------------------------------------------------------------------
# Factory helpers for classes with non-standard __init__ signatures
# ---------------------------------------------------------------------------

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
    if cls is ConfigValidationError:
        return cls(message="test message", context={"k": "v"})
    if cls is DuplicateFunctionError:
        return cls(message="test message", context={"k": "v"})
    if cls is UDFLoadError:
        return cls(message="test message", context={"k": "v"})
    if cls is VendorAPIError:
        return cls(message="test message", context={"k": "v"})
    if cls is AnthropicError:
        return cls(message="test message", context={"k": "v"})
    if cls is RateLimitError:
        return cls(message="test message", context={"k": "v"})
    if cls is PreFlightValidationError:
        return cls("test message", context={"k": "v"})
    if cls is VendorConfigError:
        return cls("test message", context={"k": "v"})
    if cls is ContextStructureError:
        return cls("test message", context={"k": "v"})
    if cls is PathValidationError:
        return cls("test message", context={"k": "v"})
    if cls is SchemaValidationError:
        return cls("test message", context={"k": "v"})
    # All simple subclasses accept (message, context=None)
    return cls("test message", context={"k": "v"})


# All 38 exception classes
ALL_CLASSES = [
    AgentActionsError,
    InvalidParameterError,
    ConfigurationError,
    ConfigValidationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
    AgentNotFoundError,
    ProjectNotFoundError,
    ValidationError,
    PromptValidationError,
    DataValidationError,
    SchemaValidationError,
    ProcessingError,
    TransformationError,
    GenerationError,
    WorkflowError,
    SerializationError,
    EmptyOutputError,
    ExternalServiceError,
    VendorAPIError,
    AnthropicError,
    NetworkError,
    RateLimitError,
    FileSystemError,
    FileLoadError,
    FileWriteError,
    DirectoryError,
    ResourceError,
    DependencyError,
    OperationalError,
    AgentExecutionError,
    TemplateRenderingError,
    TemplateVariableError,
    PreFlightValidationError,
    ContextStructureError,
    VendorConfigError,
    PathValidationError,
]

def test_all_classes_count():
    """Catch accidental addition/removal of exception classes."""
    assert len(ALL_CLASSES) == 38, f"Expected 38 classes, found {len(ALL_CLASSES)}"


@pytest.mark.parametrize("cls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_is_exception_subclass(cls):
    """Every error class must be an Exception subclass."""
    assert issubclass(cls, Exception)
    assert issubclass(cls, AgentActionsError)


@pytest.mark.parametrize("cls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_can_be_raised_and_caught(cls):
    """Every class must be instantiable and catchable."""
    exc = _make(cls)
    assert isinstance(exc, cls)
    with pytest.raises(cls):
        raise exc


# Classes that expose a `context` parameter at construction time
# (TemplateVariableError stores context internally but doesn't expose the param)
_CONTEXT_CAPABLE_CLASSES = [c for c in ALL_CLASSES if c is not TemplateVariableError]


@pytest.mark.parametrize(
    "cls", _CONTEXT_CAPABLE_CLASSES, ids=[c.__name__ for c in _CONTEXT_CAPABLE_CLASSES]
)
def test_context_dict_is_copied_on_construction(cls):
    """Mutating caller's dict after construction must not affect stored context."""
    original_ctx = {"key": "original"}
    if cls is ConfigValidationError:
        exc = cls(message="msg", context=original_ctx)
    elif cls in (DuplicateFunctionError, UDFLoadError, VendorAPIError, AnthropicError, RateLimitError):
        exc = cls(message="msg", context=original_ctx)
    elif cls in (
        PreFlightValidationError,
        VendorConfigError,
        ContextStructureError,
        PathValidationError,
        SchemaValidationError,
    ):
        exc = cls("msg", context=original_ctx)
    else:
        exc = cls("msg", context=original_ctx)

    # Mutate caller's dict
    original_ctx["key"] = "mutated"

    # Stored context should still have the original value
    assert exc.context.get("key") == "original", (
        f"{cls.__name__}.context was not defensively copied: "
        f"mutation propagated from caller's dict"
    )


@pytest.mark.parametrize(
    "cls",
    [c for c in ALL_CLASSES if c is not TemplateVariableError],
    ids=[c.__name__ for c in ALL_CLASSES if c is not TemplateVariableError],
)
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
