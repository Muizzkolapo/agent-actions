from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class GuardCheck(Check):
    """Verify a guarded action produced correct dispositions.

    Queries the record_disposition table in the SQLite DB for evidence
    that the guard evaluated correctly.

    Args:
        action: action name that has a guard
        behavior: expected guard behavior -- "filter" or "skip"
    """

    action: str
    behavior: str  # "filter" or "skip"

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # The pipeline must have completed for guard evaluation to be meaningful
        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} -- cannot verify guard behavior",
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

        if self.behavior == "filter":
            with sqlite3.connect(str(db_path)) as conn:
                dispositions = conn.execute(
                    "SELECT disposition FROM record_disposition WHERE action_name = ?",
                    (self.action,),
                ).fetchall()

                filtered = [d for d in dispositions if d[0] == "filtered"]
                if filtered:
                    results.append(
                        CheckResult(
                            True,
                            f"guard({self.action}): filtered records found",
                            f"{len(filtered)} records with disposition 'filtered'",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            False,
                            f"guard({self.action}): filtered records found",
                            "no records with disposition 'filtered' in record_disposition",
                        )
                    )

        elif self.behavior == "skip":
            with sqlite3.connect(str(db_path)) as conn:
                # For skip behavior (on_false: skip), records that fail the guard
                # get skipped dispositions. Records that pass may still produce output.
                # Verify that the guard evaluated by checking for skip dispositions
                # OR that the action has no output (all records skipped).
                skip_dispositions = conn.execute(
                    "SELECT disposition FROM record_disposition WHERE action_name = ?",
                    (self.action,),
                ).fetchall()
                skipped = [d for d in skip_dispositions if d[0] == "skipped"]

                target_count = conn.execute(
                    "SELECT COUNT(*) FROM target_data WHERE action_name = ?",
                    (self.action,),
                ).fetchone()[0]

                if skipped or target_count == 0:
                    results.append(
                        CheckResult(
                            True,
                            f"guard({self.action}): skip guard evaluated",
                            f"{len(skipped)} skip dispositions, {target_count} output rows",
                        )
                    )
                else:
                    # Guard configured but no evidence it evaluated
                    results.append(
                        CheckResult(
                            False,
                            f"guard({self.action}): skip guard evaluated",
                            f"no skip dispositions and {target_count} output rows — guard may not have run",
                        )
                    )
        else:
            results.append(
                CheckResult(
                    False,
                    f"guard({self.action}): valid behavior",
                    f"unexpected behavior '{self.behavior}' -- expected 'filter' or 'skip'",
                )
            )

        return results
