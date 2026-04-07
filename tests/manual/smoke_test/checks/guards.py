from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from agent_actions.storage.backend import DISPOSITION_FILTERED, DISPOSITION_SKIPPED
from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class GuardCheck(Check):
    """Verify a guarded action produced correct dispositions.

    Queries the record_disposition table in the SQLite DB for evidence
    that the guard evaluated correctly.

    Args:
        action: action name that has a guard
        behavior: expected guard behavior
    """

    action: str
    behavior: Literal["filter", "skip"]

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify guard behavior",
                )
            )
            return results

        db_path = ctx.db_path
        if db_path is None:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): storage DB exists",
                    "no storage DB found in target dir",
                )
            )
            return results

        with sqlite3.connect(str(db_path)) as conn:
            if self.behavior == "filter":
                count = conn.execute(
                    "SELECT COUNT(*) FROM record_disposition WHERE action_name = ? AND disposition = ?",
                    (self.action, DISPOSITION_FILTERED),
                ).fetchone()[0]

                results.append(
                    CheckResult(
                        passed=count > 0,
                        name=f"guard({self.action}): filtered records found",
                        message=f"{count} records with disposition '{DISPOSITION_FILTERED}'"
                        if count > 0
                        else f"no records with disposition '{DISPOSITION_FILTERED}' in record_disposition",
                    )
                )

            elif self.behavior == "skip":
                skip_count = conn.execute(
                    "SELECT COUNT(*) FROM record_disposition WHERE action_name = ? AND disposition = ?",
                    (self.action, DISPOSITION_SKIPPED),
                ).fetchone()[0]

                target_count = conn.execute(
                    "SELECT COUNT(*) FROM target_data WHERE action_name = ?",
                    (self.action,),
                ).fetchone()[0]

                results.append(
                    CheckResult(
                        passed=skip_count > 0 or target_count == 0,
                        name=f"guard({self.action}): skip guard evaluated",
                        message=f"{skip_count} skip dispositions, {target_count} output rows",
                    )
                )

        return results
