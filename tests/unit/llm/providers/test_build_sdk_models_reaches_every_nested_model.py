"""build_sdk_models builds every model a response can reach, through any annotation."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypeAliasType

from agent_actions.llm.providers.sdk_models import build_sdk_models


class _Deferred(BaseModel):
    model_config = ConfigDict(defer_build=True)


class _InList(_Deferred):
    x: int


class _InDict(_Deferred):
    x: int


class _InUnion(_Deferred):
    kind: str


class _Other(_Deferred):
    kind: str


class _Deep(_Deferred):
    x: int


class _Middle(_Deferred):
    deep: _Deep | None = None


class _Aliased(_Deferred):
    x: int


_Alias = TypeAliasType("_Alias", list[_Aliased])


class _Root(_Deferred):
    items: list[_InList]
    table: dict[str, _InDict]
    either: Annotated[_InUnion | _Other, "discriminator"]
    middle: _Middle
    aliased: _Alias


_EVERY_MODEL = (_Root, _InList, _InDict, _InUnion, _Other, _Middle, _Deep, _Aliased)


def test_every_reachable_model_is_built_once_called():
    assert not any(model.__pydantic_complete__ for model in _EVERY_MODEL)

    build_sdk_models(_Root, None)

    assert all(model.__pydantic_complete__ for model in _EVERY_MODEL)
