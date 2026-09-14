"""`agac expect list` prints the rules the runner would run, for every way to author them.

Parity is asserted against the resolution the runner itself performs, so a
listing that re-derives rules from YAML diverges here rather than in a run.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.services.workflow_inspector import WorkflowInspector

PROJECT = Path(__file__).parent / "fixtures" / "expectation_authors"

ACCEPTED = [
    "batch_field_rules",
    "custom_check",
    "field_scoped_rules",
    "inline_rules",
    "judge_votes_and_budget",
    "pair_and_pattern_rules",
    "record_expression",
    "repair_auto",
    "row_condition_on_optional_field",
    "shared_suite",
    "tool_action",
    "verdict_guard",
]

REFUSED = {
    "array_member_rule": "a selector reaches top-level fields only",
    "judged_context_under_batch": "not available under batch run_mode",
    "many_mistakes": "field 'no_such_field' is not produced by this action",
    "old_flat_shape": "severity 'fail' is now 'error'",
    "repair_auto_at_file_granularity": "use repair: none or record granularity",
}


def _list(author, *extra):
    return CliRunner().invoke(cli, ["expect", "list", "-a", author, *extra])


def _runner_rules(author):
    """What the runner resolves for this workflow, action by action."""
    inspector = WorkflowInspector(author, project_root=PROJECT)
    inspector.validate(verify_keys=False)
    resolved = {}
    for name, config in inspector.action_configs.items():
        service = create_expectation_service_from_config(
            config.get("expect"), action_name=name, agent_config=config
        )
        if service is not None:
            resolved[name] = service.suite
    return resolved


@pytest.fixture(autouse=True)
def _in_project(monkeypatch):
    monkeypatch.chdir(PROJECT)


@pytest.mark.parametrize("author", ACCEPTED)
def test_the_listing_matches_the_suite_the_runner_builds(author):
    result = _list(author, "--json")
    assert result.exit_code == 0, result.output

    listed = {entry["action"]: entry for entry in json.loads(result.stdout)["actions"]}
    expected = _runner_rules(author)

    assert set(listed) == set(expected), f"{author}: actions listed do not match the runner's"
    for name, suite in expected.items():
        assert listed[name]["suite"] == suite.name
        assert [r["id"] for r in listed[name]["rules"]] == [
            e.resolved_id for e in suite.expectations
        ]
        for rule, expectation in zip(listed[name]["rules"], suite.expectations, strict=True):
            assert rule["type"] == expectation.type
            assert rule["field"] == expectation.field
            assert rule["severity"] == expectation.severity
            assert rule["params"] == expectation.params


@pytest.mark.parametrize(("author", "phrase"), sorted(REFUSED.items()))
def test_a_refused_workflow_reports_the_refusal_rather_than_an_empty_list(author, phrase):
    result = _list(author)
    assert result.exit_code != 0, f"{author}: a refused workflow listed cleanly"
    assert phrase in result.output, f"{author}: no mention of {phrase!r}\n{result.output}"


def test_a_bare_block_lists_the_rules_of_the_actions_own_schema():
    """`expect: {repair: none}` resolves through the schema route, not to nothing."""
    result = _list("field_scoped_rules", "--json")
    assert result.exit_code == 0, result.output

    actions = json.loads(result.stdout)["actions"]
    assert actions, "a workflow whose rules live on its schema fields listed no rules"
    assert any(entry["rules"] for entry in actions)


def test_an_action_filter_narrows_the_listing():
    everything = json.loads(_list("inline_rules", "--json").stdout)["actions"]
    one = everything[0]["action"]
    narrowed = json.loads(_list("inline_rules", "--action", one, "--json").stdout)["actions"]
    assert [entry["action"] for entry in narrowed] == [one]


def test_an_unknown_action_is_refused_by_name():
    result = _list("inline_rules", "--action", "no_such_action")
    assert result.exit_code != 0
    assert "no_such_action" in result.output
