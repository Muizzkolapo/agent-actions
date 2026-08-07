"""Preflight warnings must aggregate per check, not print one paragraph per field.

A run with N unguaranteed fields used to emit N near-identical multi-line
warnings, each repeating the full remedy. The contract here: one warning
record per check group, fields grouped by action, remedy stated once.
"""

import logging

from agent_actions.services.preflight_service import PreflightService


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
        with caplog.at_level(logging.WARNING):
            _service(configs)._warn_dag_schema_compatibility_gaps()

        dagfit = [r for r in caplog.records if "dag-fit" in r.getMessage()]
        assert len(dagfit) == 1, (
            f"expected ONE aggregated dag-fit warning, got {len(dagfit)} records"
        )

    def test_fields_grouped_per_action_on_one_line(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        with caplog.at_level(logging.WARNING):
            _service(configs)._warn_dag_schema_compatibility_gaps()

        msg = next(r.getMessage() for r in caplog.records if "dag-fit" in r.getMessage())
        assert "flatten: category, key, steps" in msg, msg
        assert "assemble: id, items" in msg, msg

    def test_remedy_stated_once_not_per_field(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        with caplog.at_level(logging.WARNING):
            _service(configs)._warn_dag_schema_compatibility_gaps()

        combined = "\n".join(
            r.getMessage() for r in caplog.records if "dag-fit" in r.getMessage()
        )
        assert combined.count("optional in the consumer schema") == 1, combined

    def test_header_carries_counts(self, caplog):
        configs = {
            "flatten": _tool(["category", "key", "steps"]),
            "assemble": _tool(["id", "items"]),
        }
        with caplog.at_level(logging.WARNING):
            _service(configs)._warn_dag_schema_compatibility_gaps()

        msg = next(r.getMessage() for r in caplog.records if "dag-fit" in r.getMessage())
        first_line = msg.splitlines()[0]
        assert "5" in first_line and "2" in first_line, (
            f"header should carry field and action counts: {first_line!r}"
        )

    def test_quiet_when_no_gaps(self, caplog):
        configs = {"ok": _tool([])}
        with caplog.at_level(logging.WARNING):
            _service(configs)._warn_dag_schema_compatibility_gaps()
        assert not [r for r in caplog.records if "dag-fit" in r.getMessage()]
