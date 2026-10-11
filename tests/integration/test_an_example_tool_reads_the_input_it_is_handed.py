"""An example's tool reads the input the run hands it, not a default (1385).

The contract_reviewer FILE tool read each record's fields under their action's name,
and the incident_triage record tools read theirs bare. Neither shape is what a tool
is handed, every `.get` fell to its default, and the run still reported success: one
contract "unknown" with every clause low, and every incident SEV3, then "Unknown".
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import REPO, run_agac

EXAMPLES = REPO / "examples"


def _tool(example: str, name: str):
    source = EXAMPLES / example / "tools" / example / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_contract_report_names_its_contract_and_clauses(tmp_path):
    root = tmp_path / "contract_reviewer"
    shutil.copytree(EXAMPLES / "contract_reviewer", root)
    workflow = root / "agent_workflow" / "contract_reviewer"
    config = workflow / "agent_config" / "contract_reviewer.yml"
    config.write_text(
        re.sub(r"(?m)^(\s*)model_vendor: \S+", r"\1model_vendor: agac-provider", config.read_text())
    )
    contracts = json.loads((workflow / "agent_io" / "staging" / "contracts.json").read_text())

    result = run_agac(root, "run", "-a", "contract_reviewer", "--fresh")
    assert result.returncode == 0, result.stdout + result.stderr

    backend = get_storage_backend(str(workflow), "contract_reviewer")
    backend.initialize()
    try:
        (path,) = backend.list_target_files("aggregate_risk_summary")
        records = backend.read_target("aggregate_risk_summary", path)
    finally:
        backend.close()
    reports = [r["content"]["aggregate_risk_summary"] for r in records]
    reports = [r for r in reports if r is not None]
    named = [(r["contract_id"], r["contract_title"], r["parties"]) for r in reports]
    assert named == [(c["contract_id"], c["title"], c["parties"]) for c in contracts]
    assert len(contracts) > 1
    for report in reports:
        numbers = [o["clause_number"] for o in report["total_obligations"]]
        assert numbers != [] and 0 not in numbers
        assert max(numbers) <= report["total_clauses_analyzed"]
        assert all(o["clause_title"] != "Unknown" for o in report["total_obligations"])


def test_an_incident_is_routed_by_the_severity_it_was_given():
    module = _tool("incident_triage", "assign_team_based_on_impact")
    seeds = EXAMPLES / "incident_triage" / "agent_workflow" / "incident_triage" / "seed_data"
    # A record tool is handed one key per observed action, and its seeds under `seed`.
    assigned = module.assign_team_based_on_impact(
        {
            "aggregate_severity": {"final_severity": "SEV1"},
            "assess_system_impact": {"affected_services": ["database cluster"]},
            "seed": {
                "team_roster": json.loads((seeds / "team_roster.json").read_text()),
                "service_catalog": json.loads((seeds / "service_catalog.json").read_text()),
            },
        }
    )
    assert "SEV1" in assigned["response_message"]
    assert "SEV3" not in assigned["response_message"]


def test_a_triage_is_formatted_from_what_each_action_answered():
    module = _tool("incident_triage", "format_incident_triage")
    # One key per observed action; one whose guard skipped the record is there as None.
    (triage,) = module.format_incident_triage(
        {
            "extract_incident_details": {"title": "Checkout down", "affected_systems": ["api"]},
            "aggregate_severity": {"final_severity": "SEV2", "confidence_score": 0.8},
            "assess_customer_impact": {"customer_impact_level": "HIGH"},
            "assess_system_impact": {"affected_services": ["payments"]},
            "assign_response_team": {
                "assigned_teams": ["backend-oncall"],
                "requires_executive_notification": True,
            },
            "generate_response_plan": {"immediate_actions": ["roll back"]},
            "generate_executive_summary": None,
            "source": {"timestamp": "2024-05-01T10:00:00Z"},
        }
    )
    assert triage["incident"]["title"] == "Checkout down"
    assert triage["severity"] == {
        "final_severity": "SEV2",
        "confidence_score": 0.8,
        "is_split_decision": False,
        "vote_summary": "",
    }
    assert triage["impact"]["customer_impact"]["level"] == "HIGH"
    assert triage["impact"]["system_impact"]["affected_services"] == ["payments"]
    assert triage["teams"]["assigned_teams"] == ["backend-oncall"]
    assert triage["response"]["immediate_actions"] == ["roll back"]
    assert triage["metadata"]["requires_executive_notification"] is True
    assert triage["timestamp"] == "2024-05-01T10:00:00Z"
    assert triage["executive_summary"] == {}
