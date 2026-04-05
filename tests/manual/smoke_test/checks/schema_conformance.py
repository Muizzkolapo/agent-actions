from __future__ import annotations

import json
import sqlite3

import yaml

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


class SchemaConformance(Check):
    """Verify output JSON fields match the action's schema definition.

    Reads from the SQLite DB (target_data table) instead of action directories.
    """

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        db_path = ctx.db_path
        if db_path is None:
            results.append(
                CheckResult(
                    passed=False,
                    name="schema conformance",
                    message="no storage DB found in target dir",
                )
            )
            return results

        # Load workflow config to get action -> schema mapping
        config = yaml.safe_load(ctx.config_path.read_text())
        schema_dir = ctx.project_dir / "schema" / ctx.example.workflow

        actions = config.get("actions", [])

        # Collect actions that have guards configured (may produce no output)
        guarded_actions: set[str] = set()
        for action_cfg in actions:
            if not isinstance(action_cfg, dict):
                continue
            if action_cfg.get("guard"):
                guarded_actions.add(action_cfg.get("name", ""))

        schema_actions_checked = 0

        with sqlite3.connect(str(db_path)) as conn:
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

                # Query target_data for this action
                cursor = conn.execute(
                    "SELECT data FROM target_data WHERE action_name = ?",
                    (action_name,),
                )
                rows = cursor.fetchall()

                if not rows:
                    if action_name in guarded_actions:
                        # Guarded actions may legitimately produce no output
                        continue
                    results.append(
                        CheckResult(
                            passed=False,
                            name=f"schema({action_name})",
                            message="no output found in target_data",
                        )
                    )
                    schema_actions_checked += 1
                    continue

                schema_actions_checked += 1

                for row in rows:
                    try:
                        data = json.loads(row[0])
                        records = data if isinstance(data, list) else [data]
                        for record in records:
                            if not isinstance(record, dict):
                                continue
                            missing = [f for f in required_fields if f not in record]
                            results.append(
                                CheckResult(
                                    passed=len(missing) == 0,
                                    name=f"schema({action_name})",
                                    message=f"missing fields: {missing}"
                                    if missing
                                    else "all required fields present",
                                )
                            )
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        results.append(
                            CheckResult(
                                passed=False,
                                name=f"schema({action_name})",
                                message="failed to parse target_data JSON",
                            )
                        )

        if not results:
            if schema_actions_checked == 0:
                results.append(
                    CheckResult(
                        passed=False,
                        name="schema conformance",
                        message="no schema-bearing actions found in workflow config",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        passed=True,
                        name="schema conformance",
                        message="all schema-bearing actions validated",
                    )
                )

        return results
