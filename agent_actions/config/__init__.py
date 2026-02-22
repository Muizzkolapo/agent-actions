"""Workflow configuration schema definitions."""

__all__ = ["WorkflowConfigV2"]


def __getattr__(name: str):
    if name == "WorkflowConfigV2":
        from .schema import WorkflowConfigV2

        return WorkflowConfigV2
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
