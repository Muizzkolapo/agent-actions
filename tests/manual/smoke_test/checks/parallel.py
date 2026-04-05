from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class ParallelVersions(Check):
    """Verify a versioned action produced outputs for all N versions.

    Queries target_data in the SQLite DB for version-tagged action names
    ({action}_1, {action}_2, etc.).

    Args:
        action: action name with versions configured
        versions: expected number of parallel versions
    """

    action: str
    versions: int

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        # The pipeline must have completed for version output to be verifiable
        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    f"parallel({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} -- cannot verify parallel versions",
                )
            )
            return results

        db_path = ctx.db_path
        if db_path is None:
            results.append(
                CheckResult(
                    False,
                    f"parallel({self.action}): storage DB exists",
                    "no storage DB found in target dir",
                )
            )
            return results

        with sqlite3.connect(str(db_path)) as conn:
            missing_versions: list[str] = []
            found_versions: list[str] = []

            for i in range(1, self.versions + 1):
                version_name = f"{self.action}_{i}"
                count = conn.execute(
                    "SELECT COUNT(*) FROM target_data WHERE action_name = ?",
                    (version_name,),
                ).fetchone()[0]

                if count == 0:
                    missing_versions.append(version_name)
                else:
                    found_versions.append(version_name)

            if missing_versions:
                results.append(
                    CheckResult(
                        False,
                        f"parallel({self.action}): all {self.versions} versions have output",
                        f"missing: {', '.join(missing_versions)}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        True,
                        f"parallel({self.action}): all {self.versions} versions have output",
                        f"found: {', '.join(found_versions)}",
                    )
                )

        return results
