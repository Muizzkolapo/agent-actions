from __future__ import annotations

import json

import yaml

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


class SchemaConformance(Check):
    """Verify output JSON fields match the action's schema definition."""

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # Load workflow config to get action -> schema mapping
        config = yaml.safe_load(ctx.config_path.read_text())
        schema_dir = ctx.project_dir / "schema" / ctx.example.workflow

        # Actions is a list of dicts (each with a "name" key)
        actions = config.get("actions", [])
        for action_cfg in actions:
            if not isinstance(action_cfg, dict):
                continue

            action_name = action_cfg.get("name", "")
            schema_name = action_cfg.get("schema")
            if not schema_name:
                continue

            schema_path = schema_dir / f"{schema_name}.yml"
            if not schema_path.exists():
                continue

            schema = yaml.safe_load(schema_path.read_text())
            required_fields = schema.get("required", [])
            if not required_fields:
                continue

            # Check output files for this action
            action_dir = ctx.target_dir / action_name
            if not action_dir.exists():
                continue  # might be guarded/skipped

            for jf in action_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                    records = data if isinstance(data, list) else [data]
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        missing = [f for f in required_fields if f not in record]
                        results.append(
                            CheckResult(
                                passed=len(missing) == 0,
                                name=f"schema: {action_name}/{jf.name}",
                                message=f"missing fields: {missing}"
                                if missing
                                else "all required fields present",
                            )
                        )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # OutputStructure check catches this

        if not results:
            results.append(
                CheckResult(
                    True,
                    "schema conformance",
                    "no schema-bearing actions with output",
                )
            )

        return results
