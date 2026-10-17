"""Preflight warnings must aggregate per check, not print one paragraph per field.

A run with N unguaranteed fields used to emit N near-identical multi-line
warnings, each repeating the full remedy. The contract here: one warning
record per check group, fields grouped by action, remedy stated once.

Each action runs a registered tool whose output the check can read and which
writes none of the required fields.
"""

import logging

import pytest

from agent_actions.config.types import Granularity
from agent_actions.services.preflight_service import PreflightService
from agent_actions.utils.udf_management.registry import (
    UDF_REGISTRY,
    FileUDFResult,
    _registered_modules,
    udf_tool,
)

_LOGGER = "agent_actions.services.preflight_service"
_TOOL = "grouping_writes_note"


def grouping_writes_note(records):
    return FileUDFResult(outputs=[{"source_index": 0, "data": {"note": "x"}}])


@pytest.fixture(autouse=True)
def _registered_tool():
    udf_tool(granularity=Granularity.FILE)(grouping_writes_note)
    yield
    UDF_REGISTRY.pop(_TOOL, None)
    _registered_modules.discard(__name__)


def _capture_dagfit(configs, caplog):
    """Run the dag-fit warn path with root propagation forced on for capture."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            _service(configs)._warn_dag_schema_compatibility_gaps()
    finally:
        aa_logger.propagate = original
    return [r for r in caplog.records if "dag-fit" in r.getMessage()]


def _service(action_configs):
    return PreflightService(
        agent_name="wf",
        action_configs=action_configs,
        project_root=None,
        workflow_config_path="wf.yml",
        verify_keys=False,
    )


def _tool(required, properties=None):
    props = properties or {f: {"type": "string"} for f in required}
    return {
        "kind": "tool",
        "impl": _TOOL,
        "dependencies": [],
        "json_output_schema": {
            "type": "object",
            "properties": props,
            "required": list(required),
        },
    }


class TestDagFitGrouping:
    def test_one_warning_record_for_the_whole_group(self, caplog):
        configs = {
            "flatten": _tool(["category", "key"]),
            "assemble": _tool(["id", "items"]),
        }
        dagfit = _capture_dagfit(configs, caplog)
        assert len(dagfit) == 1, (
            f"expected ONE aggregated dag-fit warning, got {len(dagfit)} records"
        )

    def test_fields_grouped_per_action_on_one_line(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        msg = _capture_dagfit(configs, caplog)[0].getMessage()
        assert "flatten: category, key, steps" in msg, msg
        assert "assemble: id, items" in msg, msg

    def test_remedy_stated_once_not_per_field(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        combined = "\n".join(r.getMessage() for r in _capture_dagfit(configs, caplog))
        assert combined.count("optional in the consumer schema") == 1, combined

    def test_header_carries_counts(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        msg = _capture_dagfit(configs, caplog)[0].getMessage()
        first_line = msg.splitlines()[0]
        assert "5" in first_line and "2" in first_line, (
            f"header should carry field and action counts: {first_line!r}"
        )

    def test_quiet_when_no_gaps(self, caplog):
        configs = {"ok": _tool([])}
        assert _capture_dagfit(configs, caplog) == []
