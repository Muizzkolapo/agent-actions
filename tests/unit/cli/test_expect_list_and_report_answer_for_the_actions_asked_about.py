"""`agac expect list` and `agac expect report` answer for the actions asked about, and
`--fail-under` fails only for an action a run would have checked.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner
from rich.console import Console

from agent_actions.cli import expect as expect_module
from agent_actions.cli.expect import (
    ExpectListCommand,
    ExpectReportCommand,
    _format_percent,
    _named,
    _shortfall_rate,
    expect,
)
from agent_actions.expectations.report import ActionTally, RuleTally

RULES = {
    "expectations": [
        {"id": "has_summary", "type": "not_null", "field": "summary"},
        {"id": "pair", "type": "not_null", "field": ["a", "b"], "severity": "warn"},
    ],
    "repair": "none",
}


class _Inspector:
    configs: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def __init__(self, name: str, project_root: Path | None = None) -> None:
        self.action_configs = dict(self.configs)
        self.execution_order = list(self.order)

    def validate(self, verify_keys: bool = True) -> None:
        pass

    def load(self) -> None:
        pass


@pytest.fixture
def workflow(monkeypatch):
    def _define(configs: dict[str, dict[str, Any]], order: list[str] | None = None):
        _Inspector.configs = configs
        _Inspector.order = list(configs) if order is None else order
        monkeypatch.setattr(expect_module, "WorkflowInspector", _Inspector)

    return _define


def _listing(**kwargs) -> str:
    command = ExpectListCommand(agent="flow", action=kwargs.pop("action", None), as_json=False)
    command.console = Console(file=io.StringIO(), width=200, no_color=True)
    command.execute(**kwargs)
    return command.console.file.getvalue()


def test_the_listing_shows_every_action_that_declares_rules(workflow):
    workflow({"summarize": {"expect": RULES}, "plain": {}})

    out = _listing()

    assert "2 rules across 1 action" in out
    assert "summarize  suite summarize:inline · repair none" in out
    assert "a, b" in out
    assert "<record>" not in out
    assert "plain" not in out


def test_a_rule_on_the_whole_record_shows_record_as_its_field(workflow):
    workflow(
        {
            "summarize": {
                "expect": {
                    "expectations": [
                        {"id": "whole", "type": "expression", "params": {"expr": "True"}}
                    ]
                }
            }
        }
    )

    out = _listing()

    assert "<record>" in out


def test_a_block_without_rules_says_the_schema_is_the_contract(workflow):
    workflow({"summarize": {"expect": {"expectations": []}}})

    out = _listing()

    assert "0 rules across 1 action" in out
    assert "no rules — the schema is the contract" in out


def test_a_workflow_without_expect_blocks_says_no_action_declares_one(workflow):
    workflow({"plain": {}})

    out = _listing()

    assert "No action in this workflow declares an expect: block." in out


def test_an_action_asked_for_that_declares_nothing_is_named(workflow):
    workflow({"plain": {}, "summarize": {"expect": RULES}})

    out = _listing(action="plain")

    assert "Action 'plain' does not declare an expect: block." in out


def test_an_action_not_in_the_workflow_is_refused_with_the_actions_it_has(workflow):
    workflow({"b": {}, "a": {}})

    with pytest.raises(
        click.ClickException, match="Action 'c' is not in workflow 'flow'. Actions: a, b"
    ):
        _listing(action="c")


def test_the_json_listing_marks_rules_that_will_not_run(workflow, capsys):
    workflow({"flatten": {"expect": RULES, "kind": "tool", "granularity": "file"}})

    ExpectListCommand(agent="flow.yml", action=None, as_json=True).execute()

    listing = json.loads(capsys.readouterr().out)
    assert listing["workflow"] == "flow"
    (entry,) = listing["actions"]
    assert entry["executes"] is False
    assert "will not run" in entry["inert_because"]
    assert [rule["id"] for rule in entry["rules"]] == ["has_summary", "pair"]


def _tally(action: str, passed: int, records: int) -> ActionTally:
    return ActionTally(
        action=action,
        records=records,
        records_passed=passed,
        rules=(RuleTally(id="has_summary", type="not_null", severity="error"),),
        records_total=records,
    )


class _Backend:
    def __init__(self, rows: dict[str, list[dict]], filtered: set[str]) -> None:
        self.rows = rows
        self.filtered = filtered
        self.closed = False

    def initialize(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def list_target_files(self, action: str) -> list[str]:
        return ["part.json"] if action in self.rows else []

    def read_target(self, action: str, path: str) -> list[dict]:
        return self.rows[action]

    def has_disposition(self, action: str, disposition: str) -> bool:
        return action in self.filtered


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store holding rows per action; each row is ``{"passed": bool}`` or ``{}``."""

    def _make(rows: dict[str, list[dict]], filtered: set[str] = frozenset()):
        db = tmp_path / "agent_workflow" / "flow" / "agent_io" / "store" / "flow.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        db.touch()
        backend = _Backend(rows, set(filtered))
        monkeypatch.setattr(expect_module, "get_storage_backend", lambda **_: backend)

        def _produced(records, action):
            return sum(1 for r in records if r)

        def _tally_of(action, records):
            rated = [r for r in records if "passed" in r]
            if not rated:
                return None
            return _tally(action, sum(r["passed"] for r in rated), len(rated))

        monkeypatch.setattr(expect_module, "output_record_count", _produced)
        monkeypatch.setattr(expect_module, "tally_action", _tally_of)
        return backend

    return _make


def _report(tmp_path, fail_under=None, action=None, as_json=False):
    for folder in ("agent_config", "agent_io"):
        (tmp_path / "agent_workflow" / "flow" / folder).mkdir(parents=True, exist_ok=True)
    command = ExpectReportCommand(
        agent="flow", action=action, as_json=as_json, fail_under=fail_under
    )
    command.console = Console(file=io.StringIO(), width=200, no_color=True)
    tallies = command.execute(project_root=tmp_path)
    return tallies, command.console.file.getvalue()


def test_a_report_on_a_workflow_that_never_ran_creates_no_store(workflow, tmp_path):
    workflow({"summarize": {"expect": RULES}})

    tallies, out = _report(tmp_path)

    assert tallies == []
    assert "No stored verdict for summarize." in out
    assert not (tmp_path / "agent_workflow" / "flow" / "agent_io" / "store").exists()


def test_a_report_with_no_verdict_for_many_actions_counts_them(workflow, tmp_path):
    workflow({name: {} for name in "abcde"})

    _, out = _report(tmp_path)

    assert "No stored verdict for 5 actions." in out


def test_a_report_includes_a_disabled_action_that_left_verdicts(workflow, store, tmp_path):
    workflow({"live": {"expect": RULES}, "off": {"expect": RULES}}, order=["live"])
    backend = store({"live": [{"passed": True}], "off": [{"passed": False}]})

    tallies, out = _report(tmp_path)

    assert [t.action for t in tallies] == ["live", "off"]
    assert backend.closed
    assert "off  0/1 records passed" in out


def test_the_gate_fails_when_no_action_declares_rules(workflow, tmp_path):
    workflow({"plain": {}})

    with pytest.raises(click.ClickException, match="no action declares an expect: block"):
        _report(tmp_path, fail_under=90)


def test_the_gate_names_an_action_asked_for(workflow, tmp_path):
    workflow({"plain": {}})

    with pytest.raises(click.ClickException, match="action 'plain' of workflow 'flow'"):
        _report(tmp_path, fail_under=90, action="plain")


def test_the_gate_fails_for_an_action_that_stored_no_verdict(workflow, tmp_path):
    workflow({"summarize": {"expect": RULES}})

    with pytest.raises(click.ClickException) as exc:
        _report(tmp_path, fail_under=90)

    assert "1 of 1 actions whose rules a run would evaluate stored no verdict: summarize" in str(
        exc.value.message
    )


def test_the_gate_fails_for_an_action_under_the_bar_and_shows_its_rate_below_it(
    workflow, store, tmp_path
):
    workflow({"summarize": {"expect": RULES}, "extract": {"expect": RULES}})
    rows = [{"passed": True}] * 949 + [{"passed": False}] * 51
    store({"summarize": rows, "extract": [{"passed": True}]})

    with pytest.raises(click.ClickException) as exc:
        _report(tmp_path, fail_under=95, as_json=True)

    assert exc.value.message == (
        "Expectation gate failed for workflow 'flow': "
        "pass rate under 95%: summarize 94.9% (949/1000)"
    )


def test_the_gate_passes_when_every_checked_action_clears_the_bar(workflow, store, tmp_path):
    workflow({"summarize": {"expect": RULES}})
    store({"summarize": [{"passed": True}] * 3})

    tallies, _ = _report(tmp_path, fail_under=100)

    assert tallies[0].records_passed == 3


@pytest.mark.parametrize(
    ("configs", "order", "rows", "filtered"),
    [
        ({"flatten": {"expect": RULES, "kind": "tool", "granularity": "file"}}, None, {}, ()),
        ({"off": {"expect": RULES}}, [], {}, ()),
        ({"skipped": {"expect": RULES}}, None, {"skipped": [{}, {}]}, ()),
        ({"filtered": {"expect": RULES}}, None, {}, ("filtered",)),
    ],
    ids=["never-evaluated", "switched-off", "skipped-for-every-record", "filtered-entirely"],
)
def test_the_gate_says_nothing_was_gated_when_no_run_could_check_an_action(
    workflow, store, tmp_path, capsys, configs, order, rows, filtered
):
    workflow(configs, order=order)
    store(rows, filtered=set(filtered))

    _report(tmp_path, fail_under=90)

    err = capsys.readouterr().err
    assert f"Nothing gated in workflow 'flow': {next(iter(configs))} was excluded" in err


def test_a_threshold_that_is_not_a_number_is_refused():
    result = CliRunner().invoke(expect, ["report", "-w", "flow", "--fail-under", "nan"])

    assert result.exit_code == 2
    assert "must be a number between 0 and 100" in result.output


def test_a_percent_too_close_to_perfect_for_any_precision_still_reads_imperfect():
    assert _format_percent(100 - 1e-12) == "<100%"
    assert _format_percent(1e-12) == ">0%"


def test_a_shortfall_with_no_records_has_no_rate():
    assert _shortfall_rate(0, 0, 90) == "—"


def test_a_shortfall_too_close_to_the_bar_for_any_precision_reads_under_it():
    assert _shortfall_rate(999_999_999_999, 1_000_000_000_000, 99.9999999999) == "<99.9999999999%"


def test_a_bar_with_many_decimals_is_printed_whole_so_the_rate_reads_under_it(
    workflow, store, tmp_path
):
    workflow({"summarize": {"expect": RULES}})
    store({"summarize": [{"passed": True}] * 999_999 + [{"passed": False}]})

    with pytest.raises(click.ClickException) as exc:
        _report(tmp_path, fail_under=99.99995, as_json=True)

    assert exc.value.message.endswith(
        "pass rate under 99.99995%: summarize 99.9999% (999999/1000000)"
    )


def test_a_long_list_of_names_counts_the_rest():
    assert _named(list("abcdefg")) == "a, b, c, d, e and 2 more"
