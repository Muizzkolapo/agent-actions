from __future__ import annotations

import json
import re
import sqlite3

import yaml

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext

# Valid node_id: {action_name}_{identifier}
_NODE_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_-]+$")

# Metadata fields set by LineageEnricher + RequiredFieldsEnricher
_REQUIRED_FIELDS = ("node_id", "target_id", "lineage", "source_guid")


def _compute_action_depths(config_path) -> dict[str, int]:
    """Parse workflow config and compute minimum pipeline depth per action.

    Depth 0 = first-stage (no dependencies). Depth N = longest chain from a root.
    Returns {action_name: depth} or empty dict if config can't be parsed.
    """
    try:
        content = config_path.read_text()
        data = yaml.safe_load(content)
    except Exception:
        return {}

    if not data or "actions" not in data:
        return {}

    actions = data["actions"]
    if not isinstance(actions, list):
        return {}

    # Build dependency graph
    deps: dict[str, list[str]] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        name = action.get("name", "")
        deps[name] = action.get("dependencies", []) or []

    # Recursive DFS to compute depths
    depths: dict[str, int] = {}

    def _depth(name: str, visited: set[str]) -> int:
        if name in depths:
            return depths[name]
        if name in visited:
            return 0  # cycle guard
        visited.add(name)
        parent_deps = deps.get(name, [])
        if not parent_deps:
            depths[name] = 0
            return 0
        d = max(_depth(p, visited) for p in parent_deps) + 1
        depths[name] = d
        return d

    for name in deps:
        _depth(name, set())

    return depths


class LineageCheck(Check):
    """Verify lineage metadata on every output record in the storage DB.

    Shape checks (every record):
    1. Required fields present (node_id, target_id, lineage, source_guid)
    2. node_id matches {action}_{id} pattern
    3. lineage is a non-empty list of valid node_ids
    4. target_id unique within each action

    Semantic checks (cross-record / cross-action):
    5. node_id prefix matches the owning action name
    6. Last entry in lineage == record's own node_id
    7. parent_target_id references a real target_id in the DB
    8. root_target_id references a real target_id in the DB
    9. Ancestry consistency (parent_target_id implies root_target_id)
    10. Lineage depth >= pipeline depth from config
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
            # Load pipeline depths from workflow config
            action_depths = _compute_action_depths(ctx.config_path)

            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row

                rows = conn.execute(
                    "SELECT action_name, data FROM target_data ORDER BY action_name"
                ).fetchall()

                if not rows:
                    results.append(CheckResult(True, "lineage", "no target data to verify"))
                    return results

                # --- Phase 1: Collect all records and build index ---
                all_target_ids: set[str] = set()
                action_records: dict[str, list[tuple[int, dict]]] = {}

                for row in rows:
                    action_name = row["action_name"]
                    try:
                        data = json.loads(row["data"])
                    except (json.JSONDecodeError, TypeError):
                        results.append(
                            CheckResult(False, f"lineage({action_name}): parse", "bad JSON")
                        )
                        continue

                    records = data if isinstance(data, list) else [data]
                    indexed = []
                    for idx, record in enumerate(records):
                        if not isinstance(record, dict):
                            continue
                        indexed.append((idx, record))
                        tid = record.get("target_id")
                        if isinstance(tid, str) and tid:
                            all_target_ids.add(tid)

                    action_records.setdefault(action_name, []).extend(indexed)

                total_records = sum(len(recs) for recs in action_records.values())

                # --- Phase 2: Validate ---
                missing_fields: list[str] = []
                bad_node_ids: list[str] = []
                bad_lineages: list[str] = []
                duplicate_targets: list[str] = []
                bad_ancestry: list[str] = []
                bad_prefix: list[str] = []
                bad_lineage_tail: list[str] = []
                dangling_parent: list[str] = []
                dangling_root: list[str] = []
                shallow_lineage: list[str] = []

                for action_name, records in action_records.items():
                    target_ids_seen: set[str] = set()

                    # Resolve depth — versioned actions like "score_quality_1"
                    # may not be in config directly; try base name too
                    depth = action_depths.get(action_name)
                    if depth is None:
                        # Try stripping trailing _N for versioned actions
                        base = re.sub(r"_\d+$", "", action_name)
                        depth = action_depths.get(base)

                    for idx, record in records:
                        label = f"{action_name}[{idx}]"
                        nid = record.get("node_id")
                        lineage = record.get("lineage")
                        tid = record.get("target_id")
                        parent_tid = record.get("parent_target_id")
                        root_tid = record.get("root_target_id")

                        # Check 1: required fields present
                        for field in _REQUIRED_FIELDS:
                            if field not in record or not record[field]:
                                missing_fields.append(f"{label}.{field}")

                        # Check 2: node_id format
                        if isinstance(nid, str) and not _NODE_ID_RE.match(nid):
                            bad_node_ids.append(f"{label}: {nid!r}")

                        # Check 3: lineage format
                        if isinstance(lineage, list):
                            if len(lineage) == 0:
                                bad_lineages.append(f"{label}: empty")
                            else:
                                for entry in lineage:
                                    if not isinstance(entry, str) or not _NODE_ID_RE.match(entry):
                                        bad_lineages.append(f"{label}: bad entry {entry!r}")
                                        break
                        elif lineage is not None:
                            bad_lineages.append(f"{label}: type={type(lineage).__name__}")

                        # Check 4: target_id uniqueness within action
                        if isinstance(tid, str) and tid:
                            if tid in target_ids_seen:
                                duplicate_targets.append(f"{label}: {tid}")
                            target_ids_seen.add(tid)

                        # Check 5: node_id prefix matches action name
                        if isinstance(nid, str) and not nid.startswith(f"{action_name}_"):
                            bad_prefix.append(f"{label}: {nid!r} doesn't start with {action_name}_")

                        # Check 6: last lineage entry == own node_id
                        if isinstance(lineage, list) and lineage and isinstance(nid, str):
                            if lineage[-1] != nid:
                                bad_lineage_tail.append(
                                    f"{label}: tail={lineage[-1]!r} != node_id={nid!r}"
                                )

                        # Check 7: parent_target_id references a real record
                        if isinstance(parent_tid, str) and parent_tid:
                            if parent_tid not in all_target_ids:
                                dangling_parent.append(f"{label}: {parent_tid[:12]}…")

                        # Check 8: root_target_id references a real record
                        if isinstance(root_tid, str) and root_tid:
                            if root_tid not in all_target_ids:
                                dangling_root.append(f"{label}: {root_tid[:12]}…")

                        # Check 9: ancestry consistency
                        if parent_tid is not None and not isinstance(parent_tid, str):
                            bad_ancestry.append(f"{label}: parent_target_id not str")
                        if root_tid is not None and not isinstance(root_tid, str):
                            bad_ancestry.append(f"{label}: root_target_id not str")
                        if parent_tid and not root_tid:
                            bad_ancestry.append(f"{label}: parent without root")

                        # Check 10: lineage depth >= pipeline depth
                        if depth is not None and isinstance(lineage, list) and lineage:
                            expected_min = depth + 1  # depth 0 = 1 node, depth 1 = 2 nodes
                            if len(lineage) < expected_min:
                                shallow_lineage.append(
                                    f"{label}: len={len(lineage)} < expected {expected_min} "
                                    f"(depth {depth})"
                                )

                # --- Phase 3: Report ---
                def _report(name, issues, ok_msg):
                    if issues:
                        sample = ", ".join(issues[:3])
                        results.append(CheckResult(False, name, f"{len(issues)} issues — {sample}"))
                    else:
                        results.append(CheckResult(True, name, ok_msg))

                _report(
                    "lineage: required fields",
                    missing_fields,
                    f"all {total_records} records have node_id, target_id, lineage, source_guid",
                )
                _report("lineage: node_id format", bad_node_ids, "all valid")
                _report("lineage: chain format", bad_lineages, "all valid non-empty lists")
                _report(
                    "lineage: target_id uniqueness",
                    duplicate_targets,
                    f"{total_records} records, all unique",
                )
                _report(
                    "lineage: node_id owns action",
                    bad_prefix,
                    "all node_ids match their action",
                )
                _report(
                    "lineage: chain ends with own node",
                    bad_lineage_tail,
                    "all lineage arrays end with record's node_id",
                )
                _report(
                    "lineage: parent_target_id exists",
                    dangling_parent,
                    "all parent references resolve",
                )
                _report(
                    "lineage: root_target_id exists",
                    dangling_root,
                    "all root references resolve",
                )
                _report("lineage: ancestry consistency", bad_ancestry, "all consistent")
                _report(
                    "lineage: chain depth",
                    shallow_lineage,
                    "all chains meet minimum depth from config"
                    + (
                        f" ({len(action_depths)} actions mapped)"
                        if action_depths
                        else " (no config)"
                    ),
                )

        except sqlite3.Error as e:
            results.append(CheckResult(False, "lineage", f"DB error: {e}"))

        return results
