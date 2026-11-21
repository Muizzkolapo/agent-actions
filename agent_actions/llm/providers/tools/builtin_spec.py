"""The typed ``_builtin`` spec of each tool agac runs itself, validated at load."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_actions.llm.providers.tools.builtin import DEFAULT_CASE, PICK, ROUTE


class RouteSpec(BaseModel):
    """``route``: the case of each record is the value of ``field``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tool: Literal["route"]
    field: str = Field(min_length=1)
    cases: list[str] = Field(min_length=1)
    default: bool
    # Written by the load for `agac inspect`: each case to its entry actions.
    branches: dict[str, Any] | None = None

    @field_validator("cases")
    @classmethod
    def _no_case_named_default(cls, cases: list[str]) -> list[str]:
        if DEFAULT_CASE in cases:
            raise ValueError(f"'{DEFAULT_CASE}' names the default branch and cannot be a case")
        return cases


class PickSpec(BaseModel):
    """``pick``: the output of the one action of ``of`` the record holds an output of."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tool: Literal["pick"]
    of: list[str] = Field(min_length=1)


_SPECS: dict[str, type[BaseModel]] = {ROUTE: RouteSpec, PICK: PickSpec}


def checked_builtin(spec: Any) -> dict[str, Any]:
    """*spec* when it is a valid spec of a built-in tool; raises ``ValueError`` otherwise."""
    if not isinstance(spec, dict):
        raise ValueError("'_builtin' must be a mapping")
    model = _SPECS.get(spec.get("tool"))  # type: ignore[arg-type]
    if model is None:
        raise ValueError(
            f"'_builtin' names tool {spec.get('tool')!r}; the built-in tools are "
            f"{', '.join(sorted(_SPECS))}"
        )
    return model.model_validate(spec).model_dump()
