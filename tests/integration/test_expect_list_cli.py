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


def suite_repair(author, action):
    """The repair policy the runner would resolve for this action."""
    inspector = WorkflowInspector(author, project_root=PROJECT)
    inspector.validate(verify_keys=False)
    config = inspector.action_configs[action]
    service = create_expectation_service_from_config(
        config.get("expect"), action_name=action, agent_config=config
    )
    return service.repair


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
        assert listed[name]["repair"] == suite_repair(author, name)
        for rule, expectation in zip(listed[name]["rules"], suite.expectations, strict=True):
            assert rule["type"] == expectation.type
            assert rule["field"] == expectation.field
            assert rule["severity"] == expectation.severity
            assert rule["params"] == expectation.params
            assert rule["hint"] == expectation.hint


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


def test_an_authored_hint_is_listed(monkeypatch):
    """hint: is an authored rule key and is what repair feeds the model."""
    listed = json.loads(_list("repair_auto", "--json").stdout)["actions"]
    hints = [r["hint"] for entry in listed for r in entry["rules"]]
    assert any(h for h in hints), "no rule carried its authored hint"


def test_listing_one_action_does_not_speak_for_the_whole_workflow(monkeypatch):
    """verdict_guard's summarize declares expectations; publish does not."""
    result = _list("verdict_guard", "--action", "publish")
    assert result.exit_code == 0, result.output
    assert "No action in this workflow declares" not in result.output, result.output
    assert "publish" in result.output


@pytest.fixture
def file_granularity_tool(tmp_path, monkeypatch):
    """A tool action at file granularity — a strategy that never runs expectations."""
    import shutil

    root = tmp_path / "inert"
    shutil.copytree(PROJECT, root)
    cfg = root / "agent_workflow" / "tool_action" / "agent_config" / "tool_action.yml"
    cfg.write_text(cfg.read_text().replace("granularity: Record", "granularity: File"))
    monkeypatch.chdir(root)
    return root


def test_rules_that_the_strategy_will_never_run_are_not_listed_as_live(file_granularity_tool):
    result = CliRunner().invoke(cli, ["expect", "list", "-a", "tool_action", "--json"])
    assert result.exit_code == 0, result.output
    entry = json.loads(result.stdout)["actions"][0]
    assert entry["executes"] is False
    assert entry["rules"], "the rules are still shown — they are authored, just inert"


def test_the_rendered_listing_says_why_inert_rules_will_not_run(file_granularity_tool):
    result = CliRunner().invoke(cli, ["expect", "list", "-a", "tool_action"])
    assert result.exit_code == 0, result.output
    assert "not run" in result.output.lower()
