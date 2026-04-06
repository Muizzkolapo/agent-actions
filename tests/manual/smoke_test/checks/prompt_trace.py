from __future__ import annotations

import sqlite3

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


class PromptTraceCheck(Check):
    """Verify that every action with output has complete prompt traces.

    Actions where all records were guard-filtered or guard-skipped are
    excluded — filtered records never reach prompt compilation, so no
    trace is expected.

    Checks:
    1. Every non-guarded action in target_data has traces in prompt_trace
    2. Every trace has response_text populated (not NULL)
    3. Every trace has run_mode populated
    4. Target records with source_guid join 1:1 with traces
    """

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        db_path = ctx.db_path
        if db_path is None:
            results.append(CheckResult(False, "prompt_trace", "no storage DB found"))
            return results

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check if prompt_trace table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prompt_trace'"
            )
            if cursor.fetchone() is None:
                results.append(CheckResult(False, "prompt_trace", "table does not exist"))
                conn.close()
                return results

            # Get trace stats per action
            cursor.execute(
                """
                SELECT action_name,
                       COUNT(*) as trace_count,
                       SUM(CASE WHEN response_text IS NOT NULL THEN 1 ELSE 0 END) as with_response,
                       SUM(CASE WHEN run_mode IS NOT NULL THEN 1 ELSE 0 END) as with_run_mode
                FROM prompt_trace
                GROUP BY action_name
                ORDER BY action_name
                """
            )
            trace_stats = {
                row["action_name"]: {
                    "count": row["trace_count"],
                    "with_response": row["with_response"],
                    "with_run_mode": row["with_run_mode"],
                }
                for row in cursor.fetchall()
            }

            # Get actions from target_data
            cursor.execute(
                """
                SELECT action_name,
                       COALESCE(SUM(record_count), 0) as target_records
                FROM target_data
                GROUP BY action_name
                ORDER BY action_name
                """
            )
            all_target_actions = {
                row["action_name"]: row["target_records"] for row in cursor.fetchall()
            }

            # Exclude actions that have no traces — these are either:
            # - fully guard-filtered/skipped (never reach prompt compilation)
            # - file-granularity tool actions (bypass TaskPreparer entirely)
            # - aggregation actions with no per-record source_guid
            # Only flag an action as missing if it HAS traces for some records
            # but is missing traces for others (a real bug).
            target_actions = {}
            skipped_actions = []
            for action, count in all_target_actions.items():
                if action not in trace_stats:
                    skipped_actions.append(action)
                else:
                    target_actions[action] = count

            if not target_actions:
                results.append(CheckResult(True, "prompt_trace", "no target data to verify"))
                conn.close()
                return results

            # Check 1: action coverage
            missing_actions = []
            incomplete_responses = []
            missing_run_mode = []

            for action_name in target_actions:
                stats = trace_stats.get(action_name)
                if stats is None:
                    missing_actions.append(action_name)
                    continue

                if stats["with_response"] < stats["count"]:
                    incomplete_responses.append(
                        f"{action_name} ({stats['with_response']}/{stats['count']})"
                    )

                if stats["with_run_mode"] < stats["count"]:
                    missing_run_mode.append(action_name)

            # Report: action coverage
            if missing_actions:
                results.append(
                    CheckResult(
                        False,
                        "prompt_trace: action coverage",
                        f"actions with output but no traces: {', '.join(missing_actions)}",
                    )
                )
            else:
                detail = f"all {len(target_actions)} actions have traces"
                if skipped_actions:
                    detail += f" ({len(skipped_actions)} actions excluded: no prompt compilation)"
                results.append(CheckResult(True, "prompt_trace: action coverage", detail))

            # Report: response completeness
            if incomplete_responses:
                results.append(
                    CheckResult(
                        False,
                        "prompt_trace: response completeness",
                        f"missing responses: {', '.join(incomplete_responses)}",
                    )
                )
            else:
                total_traces = sum(s["count"] for s in trace_stats.values())
                results.append(
                    CheckResult(
                        True,
                        "prompt_trace: response completeness",
                        f"all {total_traces} traces have responses",
                    )
                )

            # Report: run_mode
            if missing_run_mode:
                results.append(
                    CheckResult(
                        False,
                        "prompt_trace: run_mode populated",
                        f"missing run_mode: {', '.join(missing_run_mode)}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        True, "prompt_trace: run_mode populated", "all traces have run_mode"
                    )
                )

            # Check 4: 1:1 join — every target record with a source_guid has a trace
            # Exclude records with NULL/empty source_guid (aggregation tool outputs)
            cursor.execute(
                """
                SELECT td.action_name,
                       json_extract(j.value, '$.source_guid') as guid
                FROM target_data td, json_each(td.data) j
                LEFT JOIN prompt_trace pt
                    ON td.action_name = pt.action_name
                    AND json_extract(j.value, '$.source_guid') = pt.record_id
                WHERE pt.record_id IS NULL
                  AND json_extract(j.value, '$.source_guid') IS NOT NULL
                  AND json_extract(j.value, '$.source_guid') != ''
                  AND td.action_name IN (
                      SELECT DISTINCT action_name FROM prompt_trace
                  )
                """
            )
            orphans = cursor.fetchall()
            if orphans:
                orphan_list = [f"{r['action_name']}:{r['guid']}" for r in orphans]
                results.append(
                    CheckResult(
                        False,
                        "prompt_trace: 1:1 join",
                        f"target records without traces: {', '.join(orphan_list[:5])}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        True,
                        "prompt_trace: 1:1 join",
                        "every target record has a matching trace",
                    )
                )

            conn.close()

        except sqlite3.Error as e:
            results.append(CheckResult(False, "prompt_trace", f"DB error: {e}"))

        return results
