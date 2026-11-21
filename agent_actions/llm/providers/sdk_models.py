"""Building an SDK's response models before records parse responses on several threads."""

from __future__ import annotations

from typing import Any, get_args

import pydantic


def _model_classes(annotation: Any) -> list[type[pydantic.BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        return [annotation]
    if type(annotation).__name__ == "TypeAliasType":
        return _model_classes(annotation.__value__)
    return [model for arg in get_args(annotation) for model in _model_classes(arg)]


def build_sdk_models(*roots: Any) -> None:
    """Build each model reachable from `roots` that the SDK left to build on first use.

    The openai, anthropic and groq SDKs defer their pydantic builds unless
    DEFER_PYDANTIC_BUILD was false when they were imported. Pydantic's rebuild is not
    thread-safe: while one thread builds a model, another can find the base class's
    placeholder and fail with "BaseModel cannot be instantiated directly". Call this
    on one thread, at import, so no record's parse builds a model.
    """
    pending = [model for root in roots for model in _model_classes(root)]
    seen: set[type[pydantic.BaseModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        if not model.__pydantic_complete__:
            model.model_rebuild(raise_errors=False)
        for field in model.model_fields.values():
            pending.extend(_model_classes(field.annotation))
