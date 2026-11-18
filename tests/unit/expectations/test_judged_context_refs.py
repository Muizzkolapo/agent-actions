"""What a batch run keeps of a record's LLM context for its judged rules.

`judged_context_refs` names the refs wherever the rules are declared, and
`narrow_context` cuts a context down to them without changing how any ref resolves.
"""

import pytest
import yaml

from agent_actions.expectations.fields import (
    FieldResolutionError,
    narrow_context,
    resolve_context,
)
from agent_actions.expectations.service import judged_context_refs


def _judged(rule_id: str, *refs: str, field: str | None = "summary") -> dict:
    rule = {"id": rule_id, "type": "llm_judge", "params": {"rule": "x", "context": list(refs)}}
    return {**rule, "field": field} if field else rule


def _project(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    (tmp_path / "schema").mkdir()
    return tmp_path


def test_inline_rules_give_each_ref_once_in_order():
    rules = [
        _judged("a", "extract.body", "extract.title"),
        {"id": "plain", "type": "not_null", "field": "summary"},
        _judged("b", "extract.title", "research.findings"),
    ]
    config = {"name": "summarize", "expect": {"repair": "none", "expectations": rules}}

    assert judged_context_refs(config) == ["extract.body", "extract.title", "research.findings"]


def test_rules_declared_on_the_action_s_schema_are_read():
    schema = {
        "name": "out",
        "fields": [
            {
                "id": "summary",
                "type": "string",
                "expectations": [_judged("grounded", "extract.body", field=None)],
            }
        ],
    }
    config = {"name": "summarize", "schema": schema, "expect": {"repair": "none"}}

    assert judged_context_refs(config) == ["extract.body"]


def test_rules_of_a_named_suite_are_read(tmp_path):
    root = _project(tmp_path)
    (root / "schema" / "grounded_rules.yml").write_text(
        yaml.safe_dump({"expectations": [_judged("grounded", "extract.body")]})
    )
    config = {
        "name": "summarize",
        "_project_root": str(root),
        "expect": {"repair": "none", "suite": "grounded_rules"},
    }

    assert judged_context_refs(config) == ["extract.body"]


@pytest.mark.parametrize(
    "config",
    [
        {"name": "a"},
        {"name": "a", "expect": {"expectations": [{"type": "not_null", "field": "summary"}]}},
        {
            "name": "a",
            "expect": {
                "expectations": [{"type": "llm_judge", "field": "summary", "params": {"rule": "x"}}]
            },
        },
    ],
    ids=["no expect block", "nothing judged", "a judge with no context"],
)
def test_an_action_that_references_nothing_gives_no_refs(config):
    assert judged_context_refs(config) == []


CONTEXT = {
    "extract": {"body": "b", "title": "t", "long": "x" * 1000},
    "research": {"findings": ["f"]},
    "seed": "not a mapping",
}


def test_the_narrowed_context_holds_only_what_the_refs_read():
    assert narrow_context(CONTEXT, ["extract.body", "research.findings"]) == {
        "extract": {"body": "b"},
        "research": {"findings": ["f"]},
    }


@pytest.mark.parametrize(
    "refs",
    [
        ["extract.body"],
        ["extract.body", "extract.title", "research.findings"],
        ["extract.missing"],
        ["nowhere.body"],
        ["seed.field"],
        ["no_dot"],
        ["extract.body", "extract.missing"],
    ],
)
def test_every_ref_resolves_over_the_narrowed_context_as_over_the_whole(refs):
    def resolved(context):
        try:
            return resolve_context(context, refs)
        except FieldResolutionError as error:
            return str(error)

    assert resolved(narrow_context(CONTEXT, refs)) == resolved(CONTEXT)


def test_a_context_that_is_not_a_mapping_narrows_to_nothing():
    assert narrow_context(None, ["extract.body"]) == {}
