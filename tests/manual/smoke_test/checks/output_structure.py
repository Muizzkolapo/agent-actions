from __future__ import annotations

import json
import sqlite3

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


class OutputStructure(Check):
    """Verify the pipeline produced output — either as action directories or in the storage DB."""

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        if not ctx.target_dir.exists():
            results.append(CheckResult(False, "target dir exists", f"missing: {ctx.target_dir}"))
            return results

        results.append(CheckResult(True, "target dir exists", str(ctx.target_dir)))

        # Check for action output directories (file-based output)
        action_dirs = [d for d in ctx.target_dir.iterdir() if d.is_dir()]

        # Check for storage DB (DB-based output)
        db_files = list(ctx.target_dir.glob("*.db"))

        if action_dirs:
            results.append(
                CheckResult(
                    True,
                    f"action output dirs ({len(action_dirs)} found)",
                    ", ".join(sorted(d.name for d in action_dirs)),
                )
            )

            # Verify JSON files in each action dir
            for action_dir in sorted(action_dirs):
                for jf in action_dir.glob("*.json"):
                    try:
                        json.loads(jf.read_text())
                        results.append(
                            CheckResult(True, f"valid JSON: {action_dir.name}/{jf.name}", "")
                        )
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        results.append(
                            CheckResult(False, f"valid JSON: {action_dir.name}/{jf.name}", str(e))
                        )

        elif db_files:
            # Output went to SQLite storage — verify the DB has records
            db_path = db_files[0]
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]
                    records = 0
                    for table in tables:
                        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
                        records += cursor.fetchone()[0]
                results.append(
                    CheckResult(
                        records > 0,
                        f"storage DB ({db_path.name}: {len(tables)} tables, {records} records)",
                        ", ".join(tables),
                    )
                )
            except sqlite3.Error as e:
                results.append(CheckResult(False, f"storage DB ({db_path.name})", str(e)))
        else:
            results.append(
                CheckResult(False, "output exists", "no action dirs or storage DB found")
            )

        # Check for run artifacts (events, results)
        events = ctx.target_dir / "events.json"
        results.append(
            CheckResult(
                events.exists(),
                "events.json exists",
                f"{events.stat().st_size} bytes" if events.exists() else "missing",
            )
        )

        run_results = ctx.target_dir / "run_results.json"
        results.append(
            CheckResult(
                run_results.exists(),
                "run_results.json exists",
                f"{run_results.stat().st_size} bytes" if run_results.exists() else "missing",
            )
        )

        return results
