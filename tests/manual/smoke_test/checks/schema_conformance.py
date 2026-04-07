from __future__ import annotations

import json
import sqlite3

import yaml

from agent_actions.storage.backend import DISPOSITION_SKIPPED, DISPOSITION_UNPROCESSED
from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


def _unwrap_content(record: dict) -> dict:
    """Extract the LLM response from a storage-wrapped record.

    Storage wraps LLM output in {source_guid, content, target_id, ...}.
    The actual schema fields are inside "content". Returns the inner dict,
    or the original record if no wrapping is detected.
    """
    raw = record.get("content")
    if raw is None:
        return record
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return record
        if isinstance(parsed, dict):
            return parsed
    return record


class SchemaConformance(Check):
    """Verify output JSON fields match the action's schema definition.

    Reads from the SQLite DB (target_data table) instead of action directories.
    Handles versioned action names and skips guard-skipped actions.
    """

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        db_path = ctx.db_path
        if db_path is None:
            return [
                CheckResult(
                    passed=False,
                    name="schema conformance",
                    message="no storage DB found in target dir",
                )
            ]

        config = yaml.safe_load(ctx.config_path.read_text())
        schema_dir = ctx.project_dir / "schema" / ctx.example.workflow
        actions = config.get("actions", [])

        excused_actions: set[str] = set()
        for action_cfg in actions:
            if not isinstance(action_cfg, dict):
                continue
            if action_cfg.get("guard"):
                excused_actions.add(action_cfg.get("name", ""))
            if action_cfg.get("kind") == "tool":
                excused_actions.add(action_cfg.get("name", ""))

        schema_actions_checked = 0

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute("SELECT DISTINCT action_name FROM target_data")
            all_db_actions = {r[0] for r in cursor.fetchall()}

            # Actions with skipped/unprocessed disposition have passthrough data, not LLM output
            skipped_actions = {
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT action_name FROM record_disposition WHERE disposition IN (?, ?)",
                    (DISPOSITION_SKIPPED, DISPOSITION_UNPROCESSED),
                ).fetchall()
            }

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

                schema_def = yaml.safe_load(schema_path.read_text())
                required_fields = schema_def.get("required", [])
                if not required_fields:
                    continue

                cursor = conn.execute(
                    "SELECT data FROM target_data WHERE action_name = ?",
                    (action_name,),
                )
                rows = cursor.fetchall()

                # Check versioned action names (e.g., classify_severity_1, _2, _3)
                if not rows:
                    for v_name in sorted(
                        a for a in all_db_actions if a.startswith(f"{action_name}_")
                    ):
                        rows.extend(
                            conn.execute(
                                "SELECT data FROM target_data WHERE action_name = ?",
                                (v_name,),
                            ).fetchall()
                        )

                if action_name in skipped_actions:
                    continue

                if not rows:
                    if action_name in excused_actions:
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
                            check_target = _unwrap_content(record)
                            missing = [f for f in required_fields if f not in check_target]
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
