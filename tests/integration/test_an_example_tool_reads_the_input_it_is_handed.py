"""An example's tool reads the input the run hands it, not a default (1385).

The contract_reviewer FILE tool read each record's fields under their action's name,
and the incident_triage record tool read its fields bare. Neither shape is what a
tool is handed, every `.get` fell to its default, and the run still reported success:
a contract "unknown" with every clause low, and every incident routed as SEV3.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import REPO, run_agac

EXAMPLES = REPO / "examples"


def test_the_contract_report_names_its_contract_and_clauses(tmp_path):
    root = tmp_path / "contract_reviewer"
    shutil.copytree(EXAMPLES / "contract_reviewer", root)
    workflow = root / "agent_workflow" / "contract_reviewer"
    config = workflow / "agent_config" / "contract_reviewer.yml"
    config.write_text(
        re.sub(r"(?m)^(\s*)model_vendor: \S+", r"\1model_vendor: agac-provider", config.read_text())
    )
    (contract,) = json.loads((workflow / "agent_io" / "staging" / "contracts.json").read_text())[:1]

    result = run_agac(root, "run", "-a", "contract_reviewer", "--fresh")
    assert result.returncode == 0, result.stdout + result.stderr

    backend = get_storage_backend(str(workflow), "contract_reviewer")
    backend.initialize()
    try:
        (path,) = backend.list_target_files("aggregate_risk_summary")
        (record,) = backend.read_target("aggregate_risk_summary", path)
    finally:
        backend.close()
    report = record["content"]["aggregate_risk_summary"]
    assert report["contract_id"] == contract["contract_id"]
    assert report["contract_title"] == contract["title"]
    assert report["parties"] == contract["parties"]
    assert report["total_obligations"] != []
    assert all(o["clause_title"] != "Unknown" for o in report["total_obligations"])
    assert all(o["clause_number"] != 0 for o in report["total_obligations"])


def test_an_incident_is_routed_by_the_severity_it_was_given():
    source = EXAMPLES / "incident_triage" / "tools" / "incident_triage"
    spec = importlib.util.spec_from_file_location(
        "assign_team_based_on_impact", source / "assign_team_based_on_impact.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
