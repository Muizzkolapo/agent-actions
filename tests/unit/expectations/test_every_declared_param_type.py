"""Every parameter a built-in check declares is held to its declared type."""

import pytest
from pydantic import ValidationError

from agent_actions.expectations import registry
from agent_actions.expectations.types import Expectation

# A value of the wrong type for each kind, and the words the refusal uses for it.
WRONG = {
    "list": (7, "a list"),
    "number": ("7", "a number"),
    "string": (7, "a string"),
    "boolean": ("yes", "a boolean"),
}

# Written out, not read from the registry: the registry derives the parameters a type
# accepts from these declarations, so a dropped one would vanish from both sides.
DECLARED = [
    ("no_null_fields", "exclude", "list"),
    ("item_count", "equals", "number"),
    ("item_count", "max", "number"),
    ("item_count", "min", "number"),
    ("word_count_between", "max", "number"),
    ("word_count_between", "min", "number"),
    ("word_count_ratio", "max_ratio", "number"),
    ("accepted_values", "values", "list"),
    ("matches_regex", "negate", "boolean"),
    ("matches_regex", "pattern", "string"),
    ("match_like_pattern", "like_pattern", "string"),
    ("match_like_pattern", "negate", "boolean"),
    ("no_forbidden_phrases", "case_sensitive", "boolean"),
    ("no_forbidden_phrases", "phrases", "list"),
    ("contains_terms_from", "min_matches", "number"),
    ("contains_terms_from", "terms", "list"),
    ("llm_judge", "rule", "string"),
    ("llm_judge", "model", "string"),
    ("llm_judge", "votes", "number"),
    ("llm_judge", "context", "list"),
    ("expression", "condition", "string"),
]


def _valid_params(etype: registry.ExpectationType) -> dict:
    good = {"list": ["a"], "number": 1, "string": "a", "boolean": False}
    return {name: good[kind] for name, kind in etype.param_types.items()}


def test_the_built_ins_declare_exactly_these_param_types():
    in_registry = sorted(
        (etype.name, param, kind)
        for etype in (registry.get(name) for name in registry.known_types())
        for param, kind in etype.param_types.items()
        if param != "row_condition"
    )

    assert in_registry == sorted(DECLARED)
    for name in {type_name for type_name, _, _ in DECLARED}:
        etype = registry.get(name)
        assert set(etype.param_types) == etype.params


def test_every_type_takes_row_condition_as_a_string():
    for name in registry.known_types():
        assert registry.get(name).param_types["row_condition"] == "string"


@pytest.mark.parametrize(("type_name", "param", "kind"), DECLARED, ids=lambda v: str(v))
def test_each_declared_param_refuses_a_value_of_another_type(type_name, param, kind):
    etype = registry.get(type_name)
    params = _valid_params(etype)
    wrong, words = WRONG[kind]
    params[param] = wrong
    selector = {} if etype.scope == "record" else {"field": "x"}

    with pytest.raises(ValidationError) as caught:
        Expectation(type=type_name, params=params, **selector)

    assert (
        f"type '{type_name}' takes parameter '{param}' as {words}, got "
        f"{type(wrong).__name__} {wrong!r}"
    ) in str(caught.value)


@pytest.mark.parametrize(("type_name", "param", "kind"), DECLARED, ids=lambda v: str(v))
def test_each_declared_param_accepts_a_value_of_its_type(type_name, param, kind):
    etype = registry.get(type_name)
    selector = {} if etype.scope == "record" else {"field": "x"}

    expectation = Expectation(type=type_name, params=_valid_params(etype), **selector)

    assert expectation.params[param] is not None
