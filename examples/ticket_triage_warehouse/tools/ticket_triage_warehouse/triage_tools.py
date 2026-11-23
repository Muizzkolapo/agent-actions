"""Deterministic routing and a file-level digest for the ticket triage sample."""

import json
from collections import Counter
from typing import Any

from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult

_TEAMS = {"billing": "finance", "bug": "engineering", "account": "support"}


@udf_tool()
def route_ticket(data: dict[str, Any]) -> dict[str, Any]:
    category = data["classify"]["category"]
    routed: dict[str, Any] = {
        "team": _TEAMS.get(category, "support"),
        "sla_hours": 4 if int(data["classify"]["urgency"]) >= 4 else 24,
    }
    if "refund" in data["source"]["body"].lower():
        routed["escalation"] = "refund requested"
    return routed


@udf_tool(granularity=Granularity.FILE)
def count_by_team(data: list[dict[str, Any]]) -> FileUDFResult:
    """One row counting the tickets each team received.

    A File tool gets one item a ticket, holding the observed fields under their bare
    names: here `team`, from `route.team`.
    """
    teams = Counter(item["team"] for item in data)
    return FileUDFResult(
        outputs=[
            {
                "source_index": list(range(len(data))),
                "data": {"tickets": len(data), "teams": json.dumps(dict(sorted(teams.items())))},
            }
        ]
    )
