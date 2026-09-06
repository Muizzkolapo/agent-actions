"""A rule-free `expect:` block: the structural contract, with no semantic rules."""

from __future__ import annotations

import pytest

from agent_actions.expectations.service import create_expectation_service_from_config

SCHEMA_NO_RULES = {
    "name": "act",
    "fields": [
        {"name": "title", "type": "string", "required": True},
        {"name": "score", "type": "integer", "required": True},
    ],
}

SCHEMA_WITH_RULE = {
    "name": "act",
    "fields": [
        {"name": "title", "type": "string", "expectations": [{"type": "not_null"}]},
        {"name": "score", "type": "integer"},
    ],
}


def build(expect, schema=SCHEMA_NO_RULES):
    return create_expectation_service_from_config(
        expect, action_name="act", agent_config={"name": "act", "schema": schema}
    )


@pytest.mark.parametrize("repair", ["auto", "retry"])
def test_a_rule_free_block_builds_a_service_under_a_repair_policy(repair):
    service = build({"repair": repair})

    assert service is not None
    assert list(service.suite.expectations) == []


def test_the_rule_free_service_still_enforces_the_schema():
    """The point of the block: conform to the schema, repair when you do not."""
    service = build({"repair": "auto"})

    verdict, _ = service.verdict_for_response({"title": "ok"}, check_schema=True)

    assert verdict.overall_pass is False
    assert [o.id for o in verdict.failed] == ["_structural"]


def test_the_rule_free_service_passes_a_conforming_record():
    service = build({"repair": "auto"})

    verdict, _ = service.verdict_for_response({"title": "ok", "score": 3}, check_schema=True)

    assert verdict.overall_pass is True


def test_a_rule_free_block_is_still_refused_under_repair_none():
    """Observe mode with nothing to observe: no rules run and nothing regenerates."""
    with pytest.raises(Exception, match="no expectations to run"):
        build({"repair": "none"})


def test_a_schema_with_rules_is_unaffected():
    service = build({"repair": "auto"}, schema=SCHEMA_WITH_RULE)

    assert [e.type for e in service.suite.expectations] == ["not_null"]


def test_observe_mode_still_works_when_the_schema_has_rules():
    service = build({"repair": "none"}, schema=SCHEMA_WITH_RULE)

    assert service is not None
    assert service.repair == "none"


def test_an_action_with_no_schema_at_all_is_still_refused():
    """A bare block reads the action's schema; with none there is nothing to enforce."""
    with pytest.raises(Exception, match="no schema"):
        create_expectation_service_from_config(
            {"repair": "auto"}, action_name="act", agent_config={"name": "act"}
        )


def _preflight(expect, schema=SCHEMA_NO_RULES):
    from pathlib import Path

    from agent_actions.validation.expectations_validator import find_expectation_defects

    # The bare form is only checked when a project root is supplied; the schema
    # here is already an inlined dict, so nothing is read from disk.
    return find_expectation_defects(
        {"act": {"expect": expect, "schema": schema}},
        {"act": {"title", "score"}},
        project_root=Path("."),
    ).get("act", [])


@pytest.mark.parametrize("repair", ["auto", "retry"])
def test_preflight_accepts_a_rule_free_block_under_a_repair_policy(repair):
    assert _preflight({"repair": repair}) == []


def test_preflight_still_refuses_a_rule_free_block_under_repair_none():
    defects = _preflight({"repair": "none"})

    assert any("no rules" in d or "no expectations" in d for d in defects)


def test_preflight_still_accepts_a_schema_that_has_rules():
    assert _preflight({"repair": "none"}, schema=SCHEMA_WITH_RULE) == []
