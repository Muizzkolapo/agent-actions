"""Checked JSON Schema validators, built once per distinct schema."""

from __future__ import annotations

import functools
import json
from typing import Any

import jsonschema  # type: ignore[import-untyped]


@functools.lru_cache(maxsize=512)
def _build(schema_json: str, cls: Any) -> Any:
    schema = json.loads(schema_json)
    validator_cls = cls if cls is not None else jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def checked_validator(schema: dict[str, Any], cls: Any = None) -> Any:
    """Return a validator for ``schema`` after ``check_schema``; raises ``SchemaError`` if invalid.

    Cached by the schema's canonical JSON, so mutating a dict between calls is safe. A schema
    that is not JSON-serialisable is checked and built fresh each call.
    """
    try:
        schema_json = json.dumps(schema, sort_keys=True)
    except (TypeError, ValueError):
        validator_cls = cls if cls is not None else jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        return validator_cls(schema)
    return _build(schema_json, cls)


def validate(instance: Any, schema: dict[str, Any]) -> None:
    """Drop-in for ``jsonschema.validate`` that reuses the checked validator."""
    error = jsonschema.exceptions.best_match(checked_validator(schema).iter_errors(instance))
    if error is not None:
        raise error
