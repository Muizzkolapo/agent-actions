"""Shared utilities for merging JSON records by correlation key."""

from __future__ import annotations

import json
import logging
from collections.abc import Collection
from pathlib import Path
from typing import Any

from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.processing.record_helpers import FAN_IN_CONSUMED_INTO, upstream_cause
from agent_actions.record.reasons import CONSUMED_INTO_OUTPUT
from agent_actions.record.state import CASCADE_BLOCKING_VALUES, RecordState
from agent_actions.utils import deep_json
from agent_actions.utils.content import get_existing_content

logger = logging.getLogger(__name__)


def deep_merge_record(existing: dict[str, Any], new_record: dict[str, Any]) -> None:
    """Merge new_record into existing in place: content dicts merge, lineage deduplicates, other fields first-wins."""
    for key, value in new_record.items():
        if key == "content" and isinstance(value, dict):
            if "content" not in existing:
                existing["content"] = {}
            if isinstance(existing["content"], dict):
                existing["content"].update(value)
            else:
                existing["content"] = value
        elif key == "lineage" and isinstance(value, list):
            _merge_lineage(existing, value)
        elif key == "lineage_sources":
            pass  # Owned by _populate_lineage_sources below
        elif key not in existing:
            existing[key] = value

    _populate_lineage_sources(existing, new_record)


def _merge_lineage(existing: dict[str, Any], new_lineage: list[Any]) -> None:
    """Merge lineage arrays with deduplication by node_id."""
    if "lineage" not in existing:
        existing["lineage"] = []
    if not isinstance(existing["lineage"], list):
        return

    existing_ids: set = set()
    for entry in existing["lineage"]:
        if isinstance(entry, str):
            existing_ids.add(entry)
        elif isinstance(entry, dict) and "node_id" in entry:
            existing_ids.add(entry["node_id"])

    for entry in new_lineage:
        if isinstance(entry, str):
            if entry not in existing_ids:
                existing["lineage"].append(entry)
                existing_ids.add(entry)
        elif isinstance(entry, dict):
            node_id = entry.get("node_id")
            if node_id:
                if node_id not in existing_ids:
                    existing["lineage"].append(entry)
                    existing_ids.add(node_id)
            else:
                existing["lineage"].append(entry)


def _populate_lineage_sources(existing: dict[str, Any], new_record: dict[str, Any]) -> None:
    """Track branch leaf node_ids in lineage_sources when merging parallel branches."""
    existing_node_id = existing.get("node_id")
    new_node_id = new_record.get("node_id")

    if not existing_node_id or not new_node_id:
        return

    if existing_node_id == new_node_id:
        return

    if "lineage_sources" in existing:
        if new_node_id not in existing["lineage_sources"]:
            existing["lineage_sources"].append(new_node_id)
    else:
        existing["lineage_sources"] = [existing_node_id, new_node_id]


def merge_branch_records(
    branch_records: dict[str, dict[str, Any]],
    base_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge N branch records into one, each contributing only its own namespace.

    Args:
        branch_records: {branch_name: record} — each record has accumulated bus
        base_record: Optional base for upstream content. If None, uses first branch.

    Returns:
        Merged record with upstream namespaces once + each branch's own namespace.
        Lineage is deduplicated across all branches.
    """
    if not branch_records:
        return base_record or {}

    base = base_record or next(iter(branch_records.values()))
    merged_content = dict(get_existing_content(base))

    for branch_name, branch_record in branch_records.items():
        branch_content = get_existing_content(branch_record)
        if branch_name not in branch_content:
            logger.warning(
                "Branch '%s' missing own namespace in content. Keys: %s",
                branch_name,
                sorted(branch_content.keys()),
                extra=DIAGNOSTIC,
            )
        else:
            merged_content[branch_name] = branch_content[branch_name]

    result = {**base, "content": merged_content}
    # Copy lineage list so _merge_lineage doesn't mutate the input base_record
    if "lineage" in result and isinstance(result["lineage"], list):
        result["lineage"] = list(result["lineage"])
    for branch_record in branch_records.values():
        _merge_lineage(result, branch_record.get("lineage", []))

    return result


def get_correlation_value(record: dict[str, Any], key_candidates: list[str]) -> str | None:
    """Return the first truthy correlation value from top-level or content, or None.

    Truthy, not merely present: these ids are framework-assigned, so an empty one means
    unassigned rather than a group named "". Presence-gating it merges every unassigned
    record into one and loses the rest.
    """
    for key_name in key_candidates:
        correlation_value = record.get(key_name)
        if not correlation_value:
            content = record.get("content")
            if isinstance(content, dict):
                correlation_value = content.get(key_name)
        if correlation_value:
            return str(correlation_value)
    return None


def _identify_branch_mapping(
    group: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Identify branch names for a group of fan-in records.

    Returns ``{branch_name: record}`` where each branch_name is a content
    namespace unique to that record.  Returns ``None`` when branches cannot
    be distinguished (e.g. identical content schemas) — caller falls back to
    ``deep_merge_record``.

    When a record owns multiple unique namespaces (diamond dependency), each
    namespace becomes its own entry pointing to the same record.
    """
    if not group:
        return None

    key_sets: list[set[str]] = []
    for rec in group:
        content = get_existing_content(rec)
        if not content:
            return None
        key_sets.append(set(content.keys()))

    shared_keys = key_sets[0].copy()
    for ks in key_sets[1:]:
        shared_keys &= ks

    branch_records: dict[str, dict[str, Any]] = {}
    for rec, ks in zip(group, key_sets, strict=True):
        unique = ks - shared_keys
        if not unique:
            return None  # can't distinguish this record's branch
        for ns_key in sorted(unique):
            branch_records[ns_key] = rec

    return branch_records


def _merge_group_deep(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge a group whose branches cannot be told apart, namespace by namespace."""
    merged: dict[str, Any] = {}
    for record in group:
        deep_merge_record(merged, record)
    return merged


_AUTO_KEY_CANDIDATES = [
    "version_correlation_id",
    "source_guid",
    "root_target_id",
    "parent_target_id",
]


def _has_correlation_key(record: dict[str, Any], key_name: str) -> bool:
    if record.get(key_name):
        return True
    content = record.get("content")
    return isinstance(content, dict) and bool(content.get(key_name))


def _select_universal_key(records: list[dict[str, Any]]) -> str | None:
    """First auto candidate present on every record that carries any candidate.

    Grouping must key every record in the pool on the SAME field: branches of
    one logical record can carry different key sets (a version-merge descendant
    has ``version_correlation_id``, a plain branch does not), and per-record
    key selection would place them in disjoint groups — a silent partial merge.
    Returns None when no candidate is universal (caller falls back to
    per-record selection).
    """
    keyed = [r for r in records if any(_has_correlation_key(r, k) for k in _AUTO_KEY_CANDIDATES)]
    if not keyed:
        return None
    for key_name in _AUTO_KEY_CANDIDATES:
        if all(_has_correlation_key(r, key_name) for r in keyed):
            return key_name
    return None


def merge_records_by_key(records: list[Any]) -> list[Any]:
    """Merge records sharing the same correlation key.

    The grouping key is chosen once for the whole pool (first universal
    candidate, identity keys before lineage keys) so branches carrying
    different key sets still group by their shared identity.  Same-source
    fan-in merges via ``merge_branch_records`` with ``group[0]`` as the
    canonical upstream (its shared namespaces survive); a group whose
    branches cannot be told apart deep-merges instead.
    """
    groups_by_key: dict[str, list[dict[str, Any]]] = {}
    records_without_key: list[Any] = []

    universal_key = _select_universal_key([r for r in records if isinstance(r, dict)])
    auto_candidates = [universal_key] if universal_key is not None else _AUTO_KEY_CANDIDATES

    for record in records:
        if not isinstance(record, dict):
            records_without_key.append(record)
            continue

        correlation_value = get_correlation_value(record, auto_candidates)

        if correlation_value is not None:
            groups_by_key.setdefault(correlation_value, []).append(record)
        else:
            records_without_key.append(record)

    return [_merge_group(group) for group in groups_by_key.values()] + records_without_key


def _merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    """One record from the branch records of one logical record, ``group[0]`` the base."""
    if len(group) == 1:
        # Single-branch passthrough — not a fan-in, so no cascade
        # propagation needed.  The record keeps its original _state.
        return group[0]

    branch_mapping = _identify_branch_mapping(group)
    if branch_mapping is not None:
        merged = merge_branch_records(branch_mapping, base_record=group[0])
        # merge_branch_records handles lineage dedup but not lineage_sources.
        # merged["node_id"] == group[0]["node_id"] (from {**base, ...}).
        for rec in group[1:]:
            _populate_lineage_sources(merged, rec)
    else:
        merged = _merge_group_deep(group)
    _propagate_cascade_blocking(merged, group)
    return merged


def split_from(record: dict[str, Any]) -> list[str]:
    """Source ids of the record *record* was split from: its producer, then its source."""
    producers = record.get("producer_source_guids")
    anchors = list(producers) if isinstance(producers, list) and len(producers) == 1 else []
    parent = record.get("parent_source_guid")
    if parent:
        anchors.append(parent)
    return [a for a in anchors if a and a != record.get("source_guid")]


def _two_branches_split(
    source: str, split_branches: list[str], alone: list[str] | None = None
) -> Exception:
    """*alone*: the branches whose records of *source* pair with no other branch's."""
    from agent_actions.errors import WorkflowError

    alone = alone or split_branches
    others = [branch for branch in split_branches if branch not in alone]
    beside = f"a record {others} hold of it" if others else "another's"
    who = "each holds" if len(alone) > 1 else "it holds"
    return WorkflowError(
        f"Branches {split_branches} of a fan-in hold records split from one source record "
        f"({source}), and no record {alone} hold of it pairs with {beside}: {who} a split "
        "of that source of its own. A fan-in pairs a branch's records one to one with the "
        "others' record for the same source, and a record of one split is no record of "
        "another. Split the source once, in an action upstream of every branch, so the "
        "branches read the same records; let no more than one of them split it; or "
        "gather a branch's split back into one record per source, with a granularity: "
        "File tool naming every record of the split in one output's source_index.",
        context={"source": source, "branches": split_branches, "unpaired": alone},
    )


def _aggregate_unpaired(
    record: str, holders: list[str], made_by: list[str], without: list[str]
) -> Exception:
    from agent_actions.errors import WorkflowError

    return WorkflowError(
        f"Branches {holders} of a fan-in hold a record of no source ({record}): "
        f"{made_by} returned it from a granularity: File tool with source_index: None, "
        f"so branches {without} hold no record to pair it with: a fan-in pairs each "
        "branch's records with the others' records of the same source. Read the "
        "aggregate in an action that depends on the branch that made it alone, or have "
        "every branch of the fan-in read it.",
        context={"record": record, "branches": holders, "aggregated_by": made_by},
    )


def merge_fan_in(sources: list[tuple[str, Any]]) -> list[Any]:
    """Merge the records of a fan-in's branches, one record per logical record.

    *sources* holds ``(branch, records)`` per dependency. Records are grouped as
    ``merge_records_by_key`` groups them. A branch that returned several records for
    one input gives each a new source id, so each lands in a group of its own; such a
    group is paired with the group of the record it was split from, once per split
    record, and a split of a split record with that record's pairing in turn. Two
    branches split from the same record cannot be paired one to one, nor can a branch's
    records of a source beside other branches' when it shares no record of that source
    with any of them; both raise rather than run on records that hold one branch alone.
    So does a record ``aggregated_by`` a FILE tool that not every branch holds: it is of
    no source, and pairs with nothing but itself. A record a branch holds no record of
    because a FILE tool there folded it into another record's row (``folded_sources``) is
    merged ``cascade_skipped``, naming that row, so the action leaves it unprocessed.
    """
    tagged: list[tuple[str, Any]] = []
    for branch, data in sources:
        for record in data if isinstance(data, list) else [data]:
            tagged.append((branch, record))

    universal_key = _select_universal_key([r for _, r in tagged if isinstance(r, dict)])
    auto_candidates = [universal_key] if universal_key is not None else _AUTO_KEY_CANDIDATES

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    without_key: list[Any] = []
    group_of_guid: dict[str, str] = {}
    for branch, record in tagged:
        key = get_correlation_value(record, auto_candidates) if isinstance(record, dict) else None
        if key is None:
            without_key.append(record)
            continue
        groups.setdefault(key, []).append((branch, record))
        if record.get("source_guid"):
            group_of_guid.setdefault(str(record["source_guid"]), key)

    def branches(key: str) -> set[str]:
        return {branch for branch, _ in groups[key]}

    # Under each group, the groups split from it by branch. Every anchor is looked up
    # among all groups, so a split of a split finds its own split record however the
    # branches are ordered, and that record is paired in turn with the one it came from.
    splits: dict[str, dict[str, list[str]]] = {}
    is_split: set[str] = set()
    anchor_of: dict[str, str] = {}
    for key in groups:
        if len(branches(key)) != 1:
            continue
        (branch,) = branches(key)
        for anchor in split_from(groups[key][0][1]):
            anchor_key = group_of_guid.get(anchor)
            if anchor_key in groups and anchor_key != key and branches(anchor_key) - {branch}:
                splits.setdefault(anchor_key, {}).setdefault(branch, []).append(key)
                is_split.add(key)
                anchor_of[key] = anchor_key
                break

    def below(key: str) -> set[str]:
        """The branches of every group split from *key*, however deep."""
        held: set[str] = set()
        for branch, keys in splits.get(key, {}).items():
            held.add(branch)
            for split_key in keys:
                held |= below(split_key)
        return held

    def made_by(key: str) -> list[str]:
        return sorted({str(r["aggregated_by"]) for _, r in groups[key] if r.get("aggregated_by")})

    # A split of an aggregate is judged with it. One whose anchor is a source holds that
    # only because an aggregate is built over its file's first record: it pairs with no
    # one, as a split group is held by one branch alone.
    every = {branch for members in groups.values() for branch, _ in members}
    for key in groups:
        makers = made_by(key)
        if not makers:
            continue
        split_of = anchor_of.get(key)
        if split_of is not None and made_by(split_of):
            continue
        held = branches(key) | (below(key) if split_of is None else set())
        if held != every:
            raise _aggregate_unpaired(key, sorted(held), makers, sorted(every - held))

    # Under each source no record holds, the branches holding a record of it, and those
    # among them sharing a record of it with another branch. A branch that shares none
    # split the source on its own, or kept too little of a split to tell; beside any other
    # branch its records pair with nothing. One that shares some reads the same earlier
    # split as another and lacks some of its records: those run as they are.
    present: dict[str, set[str]] = {}
    paired: dict[str, set[str]] = {}
    roots = {key: members for key, members in groups.items() if key not in is_split}
    for key, members in roots.items():
        held = branches(key) | below(key)
        for anchor in split_from(members[0][1])[-1:]:
            present.setdefault(anchor, set()).update(held)
            if len(held) > 1:
                paired.setdefault(anchor, set()).update(held)
    for anchor, here in present.items():
        alone = here - paired.get(anchor, set())
        if anchor not in group_of_guid and len(here) > 1 and alone:
            raise _two_branches_split(anchor, sorted(here), sorted(alone))

    def to_merge(key: str, above: set[str], one_each: bool) -> list[list[dict[str, Any]]]:
        """The groups to merge for *key*: its own records under each of its splits'.

        *above*: the branches of the groups *key* was split from. A split group's records
        are one each, so each leads a merged record of its own.
        """
        own = [record for _, record in groups[key]]
        units = [[record] for record in own] if one_each else [own]
        split = splits.get(key)
        if not split:
            return units
        held = above | branches(key)
        split_branches = sorted(split)
        if len(split_branches) > 1 or split_branches[0] in held:
            raise _two_branches_split(key, split_branches)
        leads = [
            lead
            for split_key in split[split_branches[0]]
            for lead in to_merge(split_key, held, True)
        ]
        return [lead + unit for lead in leads for unit in units]

    # Which branch folded each record into which of its rows, and with what action.
    by_branch: dict[str, list[Any]] = {}
    for branch, record in tagged:
        by_branch.setdefault(branch, []).append(record)
    folded_into = {branch: rows_folded_into(rows) for branch, rows in by_branch.items()}

    def consumed(key: str) -> tuple[str, str, dict[str, Any]] | None:
        """``(branch, action, row)`` where a branch lacking *key* folded it into a row."""
        guids = {str(r["source_guid"]) for _, r in groups[key] if r.get("source_guid")}
        for branch in sorted(every - branches(key) - below(key)):
            for guid in sorted(guids):
                if guid in folded_into.get(branch, {}):
                    return (branch, *folded_into[branch][guid])
        return None

    merged: list[Any] = []
    skipped: dict[tuple[str, str, str], list[str]] = {}
    for key in roots:
        into = consumed(key)
        for group in to_merge(key, set(), False):
            record = _merge_group(group)
            if into is not None and record.get("_state") not in CASCADE_BLOCKING_VALUES:
                branch, action, row = into
                record = consumed_into_another(record, action=action, row=row)
                where = (branch, action, str(row["source_guid"]))
                skipped.setdefault(where, []).append(str(record.get("source_guid")))
            merged.append(record)
    for (branch, action, row_guid), guids in skipped.items():
        logger.warning(
            "Fan-in: %d record(s) %s were consumed into another record's output (%s) by "
            "'%s' in branch '%s', which holds no record of them; they are left unprocessed "
            "here with reason consumed_into_another_record",
            len(guids),
            guids[:10],
            row_guid,
            action,
            branch,
        )
    return merged + without_key


def rows_folded_into(
    rows: list[Any], by: Collection[str] | None = None
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Each record folded into one of *rows* (``folded_sources``): its action and that row.

    ``folded_sources`` also holds what every action above folded, so *by* keeps only the
    folds those actions made.
    """
    folded_into: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in rows:
        folded = row.get("folded_sources") if isinstance(row, dict) else None
        if isinstance(folded, dict) and row.get("source_guid"):
            for guid, action in folded.items():
                if by is None or str(action) in by:
                    folded_into.setdefault(str(guid), (str(action), row))
    return folded_into


def consumed_into_another(
    record: dict[str, Any], *, action: str, row: dict[str, Any]
) -> dict[str, Any]:
    """*record* blocked at the fan-in: *action* folded it into *row*'s output.

    The namespaces *row*'s branch holds and *record* lacks are null, as on a tombstone:
    the record is present for that branch, with nothing of its own there.
    """
    content = dict(get_existing_content(record))
    for namespace in get_existing_content(row):
        content.setdefault(namespace, None)
    metadata = record.get("metadata")
    return {
        **record,
        "content": content,
        "_state": RecordState.CASCADE_SKIPPED.value,
        "metadata": {
            **(metadata if isinstance(metadata, dict) else {}),
            "upstream_action": action,
            "upstream_reason": CONSUMED_INTO_OUTPUT,
            FAN_IN_CONSUMED_INTO: str(row["source_guid"]),
        },
    }


def _propagate_cascade_blocking(merged: dict[str, Any], group: list[dict[str, Any]]) -> None:
    """If ANY record in the group has cascade-blocking state, propagate it.

    Fan-in merge with mixed quarantine: if record R2 failed in branch A
    but succeeded in branch B, the merged record inherits cascade_skipped.
    Incomplete data from one branch means the merge is incomplete — the
    record should be retried from the branch where it failed.

    This is an all-or-nothing policy: a single failed branch taints the
    entire merge.  The successful branch data is still present in the
    merged content (the merge runs before this function), but downstream
    actions will cascade-skip the record.  A per-merge ``cascade_policy``
    config (e.g. ``any_success``) could relax this in a future iteration.
    """
    for rec in group:
        state = rec.get("_state")
        if state in CASCADE_BLOCKING_VALUES:
            # The merged record's history is the base branch's, which may not be the
            # branch that blocked it; the tombstone below reads the cause from here.
            cause = upstream_cause(rec)
            merged["_state"] = RecordState.CASCADE_SKIPPED.value
            if cause.get("upstream_action"):
                metadata = merged.get("metadata")
                merged["metadata"] = {**(metadata if isinstance(metadata, dict) else {}), **cause}
            logger.debug(
                "Merge fan-in: propagating cascade-blocking state '%s' "
                "from branch to merged record (source_guid=%s)",
                state,
                merged.get("source_guid", "?"),
            )
            return


def merge_json_files(
    file_paths: list[Path],
    unreadable: list[Path] | None = None,
) -> list[Any]:
    """Load and merge JSON records from multiple files by correlation key.

    Reading fails open: one corrupt file must not abort the merge. That leaves
    the caller a short result and no exception, so ``unreadable`` collects the
    paths that were dropped — the only way to learn that records went missing.
    """
    sources: list[tuple[str, Any]] = []
    for file_path in file_paths:
        try:
            with open(file_path, encoding="utf-8") as f:
                sources.append((str(file_path), deep_json.loads(f.read())))
        except (json.JSONDecodeError, OSError) as e:
            if unreadable is not None:
                unreadable.append(file_path)
            logger.warning(
                "Could not read JSON file for merging: %s - %s",
                file_path,
                e,
            )

    merged = merge_fan_in(sources)

    logger.debug(
        "Merged %d records from %d files into %d correlated records",
        sum(len(data) if isinstance(data, list) else 1 for _, data in sources),
        len(file_paths),
        len(merged),
    )

    return merged
