"""An observe or passthrough entry's whole key path is checked, not only its first key.

The removed context-scope check compared the whole path, so `prep.text.sub` (under a
string), `prep.0` and `prep.meta.nosuch` (under a closed object) were refused. With the
type checker owning these entries they passed and every record failed at run time; a
passthrough of one forwarded nothing and exited 0. The runtime walks a path through dicts
only (`get_nested_value`), so a key under a scalar or a list, or one a closed object does
not list, finds nothing.
"""

import pytest

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)

_FLAT = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "score": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}
_NESTED = {
    "type": "object",
    "properties": {
        "meta": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "string"}},
            "additionalProperties": False,
        },
        "open": {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "additionalProperties": True,
        },
        "loose": {"type": "object"},
    },
}
_FIELDS_FORMAT = {
    "name": "prep_out",
    "fields": [
        {"id": "text", "type": "string"},
        {
            "id": "meta",
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "additionalProperties": False,
        },
    ],
}


def _errors(schema, entry, directive="observe"):
    scope = (
        {"observe": [entry]}
        if directive == "observe"
        else {"observe": ["prep.id"], directive: [entry]}
    )
    result = WorkflowStaticAnalyzer(
        {
            "actions": [
                {
                    "name": "prep",
                    "kind": "tool",
                    "impl": "prep_impl",
                    "schema": schema,
                    "context_scope": {"observe": ["source.id"]},
                },
                {
                    "name": "cons",
                    "kind": "tool",
                    "impl": "cons_impl",
                    "dependencies": ["prep"],
                    "schema": {"type": "object", "properties": {"seen": {"type": "string"}}},
                    "context_scope": scope,
                },
            ]
        }
    ).analyze()
    return [e.message for e in result.errors if e.location.raw_reference == entry]


@pytest.mark.parametrize("directive", ["observe", "passthrough"])
@pytest.mark.parametrize(
    ("schema", "entry", "says"),
    [
        (_FLAT, "prep.text.sub", "under 'text', which is string"),
        (_FLAT, "prep.tags.0", "a list is never indexed"),
        (_FLAT, "prep.0", "Field '0' not found"),
        (_NESTED, "prep.meta.nosuch", "whose schema does not list it (it lists: x, y)"),
        (_NESTED, "prep.meta.x.deeper", "under 'meta.x', which is integer"),
        (_FIELDS_FORMAT, "prep.text.sub", "under 'text', which is string"),
        (_FIELDS_FORMAT, "prep.meta.nosuch", "does not list it"),
    ],
)
def test_a_path_that_finds_nothing_is_refused(schema, entry, says, directive):
    errors = _errors(schema, entry, directive)

    assert len(errors) == 1, errors
    assert says in errors[0], errors[0]


@pytest.mark.parametrize("directive", ["observe", "passthrough"])
@pytest.mark.parametrize(
    ("schema", "entry"),
    [
        (_NESTED, "prep.meta.x"),
        (_NESTED, "prep.open.anything"),
        (_NESTED, "prep.loose.anything"),
        (_FIELDS_FORMAT, "prep.meta.x"),
        (_NESTED, "prep.meta.*"),
    ],
)
def test_a_path_the_schema_admits_passes(schema, entry, directive):
    assert _errors(schema, entry, directive) == []
