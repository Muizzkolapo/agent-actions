"""Deterministic expectation types.

A check receives one resolved value plus the expectation's parameters and
returns ``(passed, detail)``. ``detail`` explains the failure to both a human
reader and the repair composer, so it names the observed value or count rather
than restating the rule.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from agent_actions.errors import DuplicateFunctionError
from agent_actions.expectations.expression import _expression_unreachable
from agent_actions.expectations.judge import _llm_judge_unreachable

Check = Callable[[Any, dict[str, Any]], tuple[bool, str]]

Scope = Literal["field", "record"]

_REGISTRY: dict[str, ExpectationType] = {}

# Accepted by every type: it gates whether the rule runs at all, so it is the
# framework's argument rather than any one check's.
_UNIVERSAL_PARAMS = frozenset({"row_condition"})


@dataclass(frozen=True)
class ExpectationType:
    """A registered check plus the parameters it accepts.

    ``scope`` decides what the check is handed: a field-scoped check receives one
    resolved value per ``field:`` selector, a record-scoped check receives the
    whole record and takes no selector at all.
    """

    name: str
    params: frozenset[str]
    required: frozenset[str]
    check: Check
    scope: Scope = "field"

    def __post_init__(self) -> None:
        # Unioned here rather than at each registration site so no path can
        # register a type that silently rejects the universal arguments.
        object.__setattr__(self, "params", self.params | _UNIVERSAL_PARAMS)


def register(
    name: str,
    params: Iterable[str] = (),
    required: Iterable[str] = (),
    scope: Scope = "field",
) -> Callable[[Check], Check]:
    def decorate(fn: Check) -> Check:
        _REGISTRY[name] = ExpectationType(
            name, frozenset(params) | _UNIVERSAL_PARAMS, frozenset(required), fn, scope
        )
        return fn

    return decorate


def is_record_scoped(name: str) -> bool:
    """Whether *name* is a type that reads the whole record.

    An unregistered name answers False so rule-shape validation reports the
    missing ``field:`` rather than the unknown type; the runner names the
    unknown type, and it is the more useful of the two errors.
    """
    etype = _REGISTRY.get(name)
    return etype is not None and etype.scope == "record"


_USER_CHECK_SOURCES: dict[str, tuple[str, str]] = {}


def expectation_check(
    name: str,
    params: Iterable[str] = (),
    required: Iterable[str] = (),
    scope: Scope = "field",
) -> Callable[[Check], Check]:
    """Register a project-defined expectation type under the built-in check contract.

    ``scope="record"`` hands the check the whole record instead of a resolved
    field, for a rule about no single field.

    Shadowing a built-in raises; the same name from two files raises
    DuplicateFunctionError; re-decorating from the same file is idempotent so
    module re-import during discovery cannot fail.
    """

    def decorate(fn: Check) -> Check:
        location = f"{fn.__module__}.{fn.__name__}"
        try:
            source_file = inspect.getfile(fn)
        except TypeError:
            source_file = f"<builtin:{fn.__module__}>"

        existing = _USER_CHECK_SOURCES.get(name)
        if existing is not None:
            existing_location, existing_file = existing
            # Idempotency requires the same function, not just the same file:
            # a second function claiming the name in one file is a collision.
            if existing_file == source_file and existing_location == location:
                return _REGISTRY[name].check
            raise DuplicateFunctionError(
                function_name=name,
                existing_location=existing_location,
                existing_file=existing_file,
                new_location=location,
                new_file=source_file,
            )
        if name in _REGISTRY:
            raise ValueError(
                f"expectation type '{name}' is a built-in and cannot be redefined; "
                f"choose a different name"
            )
        _REGISTRY[name] = ExpectationType(name, frozenset(params), frozenset(required), fn, scope)
        _USER_CHECK_SOURCES[name] = (location, source_file)
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


@register("no_null_fields", params=("exclude",), scope="record")
def _no_null_fields(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    """No field the model was asked to fill came back null.

    Underscore-prefixed keys are the framework's own and are never the model's
    to fill. Null is not emptiness: an empty string is a value the model chose,
    and ``not_null`` is the rule for rejecting it on a named field.
    """
    if not isinstance(value, dict):
        return False, f"expected a record, found {type(value).__name__}"

    excluded = set(params.get("exclude") or ())
    checked = {
        name: field
        for name, field in value.items()
        if not name.startswith("_") and name not in excluded
    }
    if not checked:
        return False, "record has no fields to check"

    nulls = sorted(name for name, field in checked.items() if field is None)
    if nulls:
        return False, f"null field(s): {', '.join(nulls)}"
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
        empty_at = [i for i, c in enumerate(counts) if c == 0]
        return False, f"cannot compare word counts: item(s) at index {empty_at} are empty"
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


def _like_to_regex(like_pattern: str) -> str:
    """Translate SQL LIKE wildcards; every other character is literal text."""
    return "".join(
        ".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in like_pattern
    )


@register("match_like_pattern", params=("like_pattern", "negate"), required=("like_pattern",))
def _match_like_pattern(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    like_pattern = params["like_pattern"]
    matched = re.fullmatch(_like_to_regex(str(like_pattern)), str(value), re.DOTALL) is not None
    if params.get("negate", False):
        if matched:
            return False, f"value {str(value)!r} matched forbidden pattern {like_pattern!r}"
        return True, ""
    if not matched:
        return False, f"value {str(value)!r} did not match pattern {like_pattern!r}"
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


_REGISTRY["llm_judge"] = ExpectationType(
    "llm_judge",
    frozenset({"rule", "model", "votes", "context"}),
    frozenset({"rule"}),
    _llm_judge_unreachable,
)

_REGISTRY["expression"] = ExpectationType(
    "expression",
    frozenset({"condition"}),
    frozenset({"condition"}),
    _expression_unreachable,
    "record",
)
