"""A connection's settings, with the values the environment holds read in."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent_actions.errors import ConfigurationError
from agent_actions.logging.filters import register_secret

_WHOLE_ENV_VAR = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_SECRET_WORDS = ("password", "pwd", "token", "secret", "passphrase")

Settings = TypeVar("Settings", bound=BaseModel)


def read_settings(
    name: str,
    raw: Mapping[str, Any],
    model: type[Settings],
    environ: Mapping[str, str] = os.environ,
) -> Settings:
    """Validate connection *name*'s settings, reading each ``${NAME}`` value from *environ*.

    A credential is never written in the project file: a secret setting must be
    a ``${NAME}`` reference, and its value is kept out of the logs.
    """
    resolved: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "type":
            continue
        secret = _is_secret(str(key), model)
        reference = _WHOLE_ENV_VAR.fullmatch(value) if isinstance(value, str) else None
        if secret and reference is None:
            raise ConfigurationError(
                f"Connection '{name}': '{key}' must name an environment variable, "
                f"for example {key}: ${{WAREHOUSE_{str(key).upper()}}}",
                context={"connection": name, "setting": key},
            )
        if reference is not None:
            variable = reference.group(1)
            value = environ.get(variable, "")
            if not value:
                raise ConfigurationError(
                    f"Connection '{name}' reads '{key}' from {variable}, which is not set",
                    context={"connection": name, "setting": key, "variable": variable},
                )
            if secret:
                register_secret(value)
        resolved[str(key)] = value
    try:
        return model(**resolved)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or 'settings'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise ConfigurationError(
            f"Connection '{name}' is not set up: {problems}. "
            f"Its settings are {', '.join(sorted(_setting_names(model)))}",
            context={"connection": name},
        ) from error


def _setting_names(model: type[BaseModel]) -> list[str]:
    return [field.alias or name for name, field in model.model_fields.items()]


def _is_secret(key: str, model: type[BaseModel]) -> bool:
    """Whether *key* holds a credential: by its name, or because *model* marks it one."""
    field = model.model_fields.get(key) or next(
        (field for field in model.model_fields.values() if field.alias == key), None
    )
    marked = bool(
        field
        and isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get("secret")
    )
    return marked or any(word in key.lower() for word in _SECRET_WORDS)
