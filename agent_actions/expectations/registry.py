"""Deterministic expectation types.

A check receives one resolved value plus the expectation's parameters and
returns ``(passed, detail)``. ``detail`` explains the failure to both a human
reader and the repair composer, so it names the observed value or count rather
than restating the rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

Check = Callable[[Any, dict[str, Any]], tuple[bool, str]]

_REGISTRY: dict[str, ExpectationType] = {}


@dataclass(frozen=True)
class ExpectationType:
    """A registered check plus the parameters it accepts."""

    name: str
    params: frozenset[str]
    required: frozenset[str]
    check: Check


def register(
    name: str, params: Iterable[str] = (), required: Iterable[str] = ()
) -> Callable[[Check], Check]:
    def decorate(fn: Check) -> Check:
        _REGISTRY[name] = ExpectationType(name, frozenset(params), frozenset(required), fn)
        return fn

    return decorate


def get(name: str) -> ExpectationType | None:
    return _REGISTRY.get(name)


def known_types() -> list[str]:
    return sorted(_REGISTRY)


def _words(value: Any) -> list[str]:
    return str(value).split()


@register("not_null")
def _not_null(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    if value is None:
        return False, "value is null"
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False, f"value is an empty {type(value).__name__}"
    return True, ""


@register("item_count", params=("equals", "min", "max"))
def _item_count(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(value, list):
        return False, f"expected a list, found {type(value).__name__}"
    count = len(value)
    if params.get("equals") is not None and count != params["equals"]:
        return False, f"expected exactly {params['equals']} items, found {count}"
    if params.get("min") is not None and count < params["min"]:
        return False, f"expected at least {params['min']} items, found {count}"
    if params.get("max") is not None and count > params["max"]:
        return False, f"expected at most {params['max']} items, found {count}"
    return True, ""


@register("word_count_between", params=("min", "max"))
def _word_count_between(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    count = len(_words(value))
    if params.get("min") is not None and count < params["min"]:
        return False, f"{count} words, expected at least {params['min']}"
    if params.get("max") is not None and count > params["max"]:
        return False, f"{count} words, expected at most {params['max']}"
    return True, ""


@register("word_count_ratio", params=("max_ratio",), required=("max_ratio",))
def _word_count_ratio(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(value, list):
        return False, f"expected a list, found {type(value).__name__}"
    counts = [len(_words(item)) for item in value]
    if not counts:
        return False, "no items to compare"
    if min(counts) == 0:
        return False, "cannot compare word counts: an item is empty"
    ratio = max(counts) / min(counts)
    if ratio > params["max_ratio"]:
        return False, f"longest/shortest word ratio {ratio:.2f} exceeds {params['max_ratio']}"
    return True, ""


@register("accepted_values", params=("values",), required=("values",))
def _accepted_values(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    allowed = params["values"]
    if value not in allowed:
        return False, f"value {value!r} is not one of {list(allowed)!r}"
    return True, ""


@register("matches_regex", params=("pattern", "negate"), required=("pattern",))
def _matches_regex(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    pattern = params["pattern"]
    matched = re.search(pattern, str(value)) is not None
    if params.get("negate", False):
        if matched:
            return False, f"value {str(value)!r} matched forbidden pattern {pattern!r}"
        return True, ""
    if not matched:
        return False, f"value {str(value)!r} did not match pattern {pattern!r}"
    return True, ""


@register("no_forbidden_phrases", params=("phrases", "case_sensitive"), required=("phrases",))
def _no_forbidden_phrases(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    cased = params.get("case_sensitive", False)
    haystack = str(value) if cased else str(value).lower()
    found = [p for p in params["phrases"] if (str(p) if cased else str(p).lower()) in haystack]
    if found:
        return False, "contains forbidden phrase(s): " + ", ".join(repr(p) for p in found)
    return True, ""


@register("contains_terms_from", params=("terms", "min_matches"), required=("terms",))
def _contains_terms_from(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    haystack = str(value).lower()
    needed = params.get("min_matches", 1)
    hits = [t for t in params["terms"] if str(t).lower() in haystack]
    if len(hits) < needed:
        return (
            False,
            f"matched {len(hits)} term(s), expected at least {needed} from {list(params['terms'])!r}",
        )
    return True, ""
