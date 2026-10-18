"""The incident_triage example formats every incident, whatever its severity (1519).

Its executive summary is guarded to SEV1/SEV2. With `on_false: filter` an incident the
guard turned away never reached `format_triage_output`, and when the guard turned away
every incident, as it does under the mock provider, that action was skipped and the run
produced no triage output. The guard skips instead, so each incident is formatted.
"""

from __future__ import annotations

import json
import re
import shutil

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import REPO, run_agac


def test_every_incident_reaches_the_triage_output(tmp_path):
    root = tmp_path / "incident_triage"
    shutil.copytree(REPO / "examples" / "incident_triage", root)
    workflow = root / "agent_workflow" / "incident_triage"
    config = workflow / "agent_config" / "incident_triage.yml"
    config.write_text(
        re.sub(r"(?m)^(\s*)model_vendor: \S+", r"\1model_vendor: agac-provider", config.read_text())
    )
    incidents = json.loads(next((workflow / "agent_io" / "staging").glob("*.json")).read_text())

    result = run_agac(root, "run", "-a", "incident_triage", "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Upstream dependency" not in output, output
    backend = get_storage_backend(str(workflow), "incident_triage")
    backend.initialize()
    try:
        (path,) = backend.list_target_files("format_triage_output")
        records = backend.read_target("format_triage_output", path)
        summaries = backend.get_disposition("generate_executive_summary")
    finally:
        backend.close()
    formatted = [r["content"]["format_triage_output"] for r in records]
    assert len(formatted) == len(incidents) > 1
    for triage in formatted:
        assert triage["triage_id"].startswith("triage-")
        # The mock provider never answers SEV1/SEV2, so no summary was written.
        assert triage["executive_summary"] == {}
    assert {row["disposition"] for row in summaries} == {"unprocessed"}
