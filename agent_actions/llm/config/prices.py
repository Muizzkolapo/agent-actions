"""Model prices: the `prices:` block of agent_actions.yml.

A price is what one million tokens cost. The framework ships none: a vendor changes its
prices, and a stale table would give a wrong estimate with nothing to say it is stale.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_actions.errors import ConfigValidationError

_PRICE_HINT = "must be a number, 0 or more: the price of one million tokens"
_DISCOUNT_HINT = "must be a number from 0 to 1: the share taken off the price of a batch call"

# The price each usage field is charged at.
_PRICE_OF = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


class ModelPrice(BaseModel):
    """One validated entry of the `prices:` block: what a model's tokens cost per million."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: float = Field(strict=True, ge=0, allow_inf_nan=False)
    output: float = Field(strict=True, ge=0, allow_inf_nan=False)
    cache_read: float | None = Field(default=None, strict=True, ge=0, allow_inf_nan=False)
    cache_write: float | None = Field(default=None, strict=True, ge=0, allow_inf_nan=False)
    batch_discount: float | None = Field(default=None, strict=True, ge=0, le=1, allow_inf_nan=False)

    def missing_for(self, usage: Mapping[str, Any]) -> str | None:
        """The first key *usage* needs a value for and this entry leaves out, or None."""
        if usage.get("batch") and self.batch_discount is None:
            return "batch_discount"
        for field, price in _PRICE_OF.items():
            if usage.get(field) and getattr(self, price) is None:
                return price
        return None

    def cost(self, usage: Mapping[str, Any]) -> float:
        """What *usage* costs; a price `missing_for` names is taken as 0."""
        full = sum(
            (usage.get(field) or 0) * (getattr(self, price) or 0)
            for field, price in _PRICE_OF.items()
        )
        discount = (self.batch_discount or 0) if usage.get("batch") else 0
        return full * (1 - discount) / 1_000_000


def estimated_cost(
    prices: Mapping[str, ModelPrice], usage: Mapping[str, Any]
) -> tuple[float | None, str | None]:
    """The cost of *usage*, a row naming its ``model`` and whether it is ``batch``.

    When the table cannot price it, the cost is None and the second value says what the
    table lacks, so a caller never shows 0 for a cost it does not know.
    """
    model = str(usage.get("model"))
    price = prices.get(model)
    if price is None:
        return None, f"prices.{model}"
    missing = price.missing_for(usage)
    if missing is not None:
        return None, f"prices.{model}.{missing}"
    return price.cost(usage), None


def parse_prices(raw: Any) -> dict[str, ModelPrice]:
    """Validate the `prices:` block, refusing the first mistake with its key and text."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        _refuse("prices", "must be a mapping of model name to its prices")
    prices: dict[str, ModelPrice] = {}
    for model, settings in raw.items():
        if not isinstance(model, str):
            _refuse("prices", f"a model name must be text; quote it, for example '{model}'")
        key = f"prices.{model}"
        if not isinstance(settings, Mapping):
            _refuse(key, "must be a mapping with input and output")
        for name in settings:
            if not isinstance(name, str):
                _refuse(key, f"unknown key '{name}'")
        try:
            prices[model] = ModelPrice.model_validate(dict(settings))
        except ValidationError as exc:
            _refuse_pydantic(key, exc)
    return prices


def _refuse_pydantic(key: str, exc: ValidationError) -> NoReturn:
    error = exc.errors()[0]
    field = str(error["loc"][0]) if error["loc"] else ""
    if error["type"] == "extra_forbidden":
        _refuse(key, f"unknown key '{field}'")
    if error["type"] == "missing":
        _refuse(key, f"{field} is required")
    _refuse(f"{key}.{field}", _DISCOUNT_HINT if field == "batch_discount" else _PRICE_HINT)


def _refuse(key: str, text: str) -> NoReturn:
    # `from None`: a pydantic error chained under the refusal would be rendered as its
    # root cause, and the user would read pydantic's text instead of the key and text here.
    raise ConfigValidationError("prices", f"{key}: {text}") from None
