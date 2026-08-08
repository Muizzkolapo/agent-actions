"""The dag-fit suppression must reach a real registered UDF, not just pure functions.

The service reads each tool's source out of the registry and feeds it to the
output-key reader. That glue is what makes the suppression work in a real run,
so it is pinned here against a genuinely registered UDF rather than a
hand-built source string.
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


def write_rows_probe(records):
    path = "/out/rows.jsonl"
    return FileUDFResult(
        outputs=[{"source_index": 0, "data": {"output_path": path, "written_count": 2}}]
    )


@pytest.fixture
def registered_udf():
    """Register through the real decorator, then drop only what this test added."""
    udf_tool(granularity=Granularity.FILE)(write_rows_probe)
    yield "write_rows_probe"
    UDF_REGISTRY.pop("write_rows_probe", None)
    _registered_modules.discard(__name__)


def _service(action_configs):
    return PreflightService(
        agent_name="wf",
        action_configs=action_configs,
        project_root=None,
        workflow_config_path="wf.yml",
        verify_keys=False,
    )


def _consumer(impl, required):
    return {
        "kind": "tool",
        "impl": impl,
        "dependencies": ["upstream"],
        "json_output_schema": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in required},
            "required": list(required),
        },
    }


_UPSTREAM = {"kind": "tool", "json_output_schema": {"type": "object", "properties": {}}}


def _dagfit_warnings(configs, caplog):
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            _service(configs)._warn_dag_schema_compatibility_gaps()
    finally:
        aa_logger.propagate = original
    return [r for r in caplog.records if "dag-fit" in r.getMessage()]


class TestSynthesizedFieldsReachThePreflightService:
    def test_registered_udf_output_suppresses_the_warning(self, registered_udf, caplog):
        configs = {
            "upstream": _UPSTREAM,
            "writer": _consumer(registered_udf, ["output_path", "written_count"]),
        }
        assert _dagfit_warnings(configs, caplog) == [], (
            "fields the registered UDF provably emits must not be reported"
        )

    def test_field_the_udf_never_emits_is_still_reported(self, registered_udf, caplog):
        configs = {
            "upstream": _UPSTREAM,
            "writer": _consumer(registered_udf, ["output_path", "checksum"]),
        }
        warnings = _dagfit_warnings(configs, caplog)
        assert len(warnings) == 1, warnings
        message = warnings[0].getMessage()
        assert "writer: checksum" in message, message
        assert "output_path" not in message, message

    def test_unregistered_impl_leaves_every_field_reported(self, caplog):
        configs = {
            "upstream": _UPSTREAM,
            "writer": _consumer("not_registered_anywhere", ["output_path"]),
        }
        message = _dagfit_warnings(configs, caplog)[0].getMessage()
        assert "writer: output_path" in message, message
