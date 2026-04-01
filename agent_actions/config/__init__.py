"""Workflow configuration schema definitions."""


def __getattr__(name: str):
    if name == "WorkflowConfig":
        from .schema import WorkflowConfig

        globals()["WorkflowConfig"] = WorkflowConfig
        return WorkflowConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkflowConfig"]
