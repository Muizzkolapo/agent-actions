from __future__ import annotations

import json
import re
import sqlite3

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext

# Valid node_id: {action_name}_{identifier}
_NODE_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_-]+$")

# Metadata fields set by LineageEnricher + RequiredFieldsEnricher
_REQUIRED_FIELDS = ("node_id", "target_id", "lineage", "source_guid")


class LineageCheck(Check):
    """Verify lineage metadata on every output record in the storage DB.

    Checks:
    1. Every record has node_id, target_id, lineage, source_guid
    2. node_id matches the {action}_{id} pattern
    3. lineage is a non-empty list of valid node_ids
    4. target_id is unique within each action
    5. Ancestry fields (parent_target_id, root_target_id) are consistent
    """

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        results: list[CheckResult] = []

        if ctx.exit_code != 0:
            results.append(
                CheckResult(
                    False,
                    "lineage: pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify lineage",
                )
            )
            return results

        db_path = ctx.db_path
        if db_path is None:
            results.append(CheckResult(False, "lineage: storage DB exists", "no storage DB found"))
            return results

        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Load all records grouped by action
                cursor.execute("SELECT action_name, data FROM target_data ORDER BY action_name")
                rows = cursor.fetchall()

                if not rows:
                    results.append(CheckResult(True, "lineage", "no target data to verify"))
                    return results

                total_records = 0
                missing_fields: list[str] = []
                bad_node_ids: list[str] = []
                bad_lineages: list[str] = []
                duplicate_targets: list[str] = []
                bad_ancestry: list[str] = []

                for row in rows:
                    action_name = row["action_name"]
                    try:
                        data = json.loads(row["data"])
                    except (json.JSONDecodeError, TypeError):
                        results.append(
                            CheckResult(
                                False,
                                f"lineage({action_name}): parse",
                                "failed to parse JSON",
                            )
                        )
                        continue

                    records = data if isinstance(data, list) else [data]
                    target_ids_seen: set[str] = set()

                    for idx, record in enumerate(records):
                        if not isinstance(record, dict):
                            continue
                        total_records += 1
                        label = f"{action_name}[{idx}]"

                        # Check 1: required fields present
                        for field in _REQUIRED_FIELDS:
                            if field not in record or not record[field]:
                                missing_fields.append(f"{label}.{field}")

                        # Check 2: node_id format
                        nid = record.get("node_id")
                        if isinstance(nid, str) and not _NODE_ID_RE.match(nid):
                            bad_node_ids.append(f"{label}: {nid!r}")

                        # Check 3: lineage format
                        lineage = record.get("lineage")
                        if isinstance(lineage, list):
                            if len(lineage) == 0:
                                bad_lineages.append(f"{label}: empty list")
                            else:
                                for entry in lineage:
                                    if not isinstance(entry, str) or not _NODE_ID_RE.match(entry):
                                        bad_lineages.append(f"{label}: invalid entry {entry!r}")
                                        break
                        elif lineage is not None:
                            bad_lineages.append(f"{label}: not a list ({type(lineage).__name__})")

                        # Check 4: target_id uniqueness within action
                        tid = record.get("target_id")
                        if isinstance(tid, str) and tid:
                            if tid in target_ids_seen:
                                duplicate_targets.append(f"{label}: {tid}")
                            target_ids_seen.add(tid)

                        # Check 5: ancestry consistency
                        parent_tid = record.get("parent_target_id")
                        root_tid = record.get("root_target_id")
                        if parent_tid is not None and not isinstance(parent_tid, str):
                            bad_ancestry.append(f"{label}: parent_target_id not str")
                        if root_tid is not None and not isinstance(root_tid, str):
                            bad_ancestry.append(f"{label}: root_target_id not str")
                        # If parent_target_id exists, root_target_id should too
                        if parent_tid and not root_tid:
                            bad_ancestry.append(
                                f"{label}: has parent_target_id but missing root_target_id"
                            )

                # Report results
                if missing_fields:
                    sample = missing_fields[:5]
                    results.append(
                        CheckResult(
                            False,
                            "lineage: required fields",
                            f"{len(missing_fields)} missing — {', '.join(sample)}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            True,
                            "lineage: required fields",
                            f"all {total_records} records have node_id, target_id, lineage, source_guid",
                        )
                    )

                if bad_node_ids:
                    results.append(
                        CheckResult(
                            False,
                            "lineage: node_id format",
                            f"{len(bad_node_ids)} invalid — {', '.join(bad_node_ids[:3])}",
                        )
                    )
                else:
                    results.append(CheckResult(True, "lineage: node_id format", "all valid"))

                if bad_lineages:
                    results.append(
                        CheckResult(
                            False,
                            "lineage: chain format",
                            f"{len(bad_lineages)} invalid — {', '.join(bad_lineages[:3])}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(True, "lineage: chain format", "all valid non-empty lists")
                    )

                if duplicate_targets:
                    results.append(
                        CheckResult(
                            False,
                            "lineage: target_id uniqueness",
                            f"{len(duplicate_targets)} duplicates — {', '.join(duplicate_targets[:3])}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            True,
                            "lineage: target_id uniqueness",
                            f"{total_records} records, all unique",
                        )
                    )

                if bad_ancestry:
                    results.append(
                        CheckResult(
                            False,
                            "lineage: ancestry consistency",
                            f"{len(bad_ancestry)} issues — {', '.join(bad_ancestry[:3])}",
                        )
                    )
                else:
                    results.append(
                        CheckResult(True, "lineage: ancestry consistency", "all consistent")
                    )

        except sqlite3.Error as e:
            results.append(CheckResult(False, "lineage", f"DB error: {e}"))

        return results
