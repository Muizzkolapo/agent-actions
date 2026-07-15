"""Guard `filter` is authoritative across the DAG.

A record a guard `on_false: filter` excluded ("dead — cannot be carried forward",
per guards/ARCHITECTURE.md) must not re-enter a downstream action's input through
an *unfiltered sibling* dependency. The FILE-mode storage fan-in
(`process_from_storage_backend`) unions dependency outputs by ``source_guid``; a
guid present only in the unfiltered sibling passes straight through. The fix
subtracts any ``source_guid`` a dependency recorded as ``FILTERED`` before the
records reach the downstream action.
"""

import json
from unittest.mock import MagicMock

from agent_actions.storage.backend import DISPOSITION_FILTERED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.runner_file_processing import process_from_storage_backend


def _params(upstream_dirs, output_dir, action_name="dedup_by_concept"):
    params = MagicMock()
    params.upstream_data_dirs = upstream_dirs
    params.output_directory = str(output_dir)
    params.action_config = {}
    params.action_name = action_name
    params.strategy = MagicMock()
    params.idx = 0
    return params


def _storage(target_by_action, filtered_by_action, dependency_graph=None):
    """Backend stub: each dep contributes one file; dispositions per action."""
    storage = MagicMock()
    storage.list_target_files.return_value = ["data.json"]
    storage.read_target.side_effect = lambda action, rel: target_by_action[action]
    # None → the collector falls back to the DIRECT dependency directories.
    storage.load_metadata.return_value = (
        json.dumps(dependency_graph) if dependency_graph is not None else None
    )

    def _get_disposition(action, record_id=None, disposition=None):
        if disposition == DISPOSITION_FILTERED:
            return [
                {"record_id": rid, "disposition": DISPOSITION_FILTERED}
                for rid in filtered_by_action.get(action, [])
            ]
        return []

    storage.get_disposition.side_effect = _get_disposition
    return storage


def _captured_guids(runner):
    call = runner._process_single_file.call_args
    data = call[0][0].data
    return [r["source_guid"] for r in data]


def test_filtered_record_does_not_resurrect_via_unfiltered_sibling(tmp_path):
    # A (tag_code_concept) guard-filtered sg-2 → absent from A's output but recorded
    # FILTERED. B (dedup_code_blocks) never filtered → still carries sg-2. The
    # downstream fan-in must not receive sg-2.
    tag_dir = tmp_path / "tag_code_concept"
    dedup_dir = tmp_path / "dedup_code_blocks"
    output = tmp_path / "out"
    for d in (tag_dir, dedup_dir, output):
        d.mkdir()

    tag_records = [
        {"source_guid": "sg-1", "content": {"tag_code_concept": {"concept_label": "loops"}}},
        {"source_guid": "sg-3", "content": {"tag_code_concept": {"concept_label": "io"}}},
    ]
    dedup_records = [
        {"source_guid": "sg-1", "content": {"dedup_code_blocks": {"code_block": "a"}}},
        {"source_guid": "sg-2", "content": {"dedup_code_blocks": {"code_block": "b"}}},
        {"source_guid": "sg-3", "content": {"dedup_code_blocks": {"code_block": "c"}}},
    ]
    storage = _storage(
        {"tag_code_concept": tag_records, "dedup_code_blocks": dedup_records},
        {"tag_code_concept": ["sg-2"]},
    )
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(tag_dir), str(dedup_dir)], output))

    guids = _captured_guids(runner)
    assert "sg-2" not in guids, f"filtered sg-2 resurrected via dedup_code_blocks: {guids}"
    assert sorted(guids) == ["sg-1", "sg-3"]


def test_filtered_record_dropped_from_single_source_file(tmp_path):
    # The filtering dep produced no output file (all filtered); the file arrives
    # from the unfiltered sibling alone (single-source branch). The filtered guid
    # must still be dropped.
    tag_dir = tmp_path / "tag_code_concept"
    dedup_dir = tmp_path / "dedup_code_blocks"
    output = tmp_path / "out"
    for d in (tag_dir, dedup_dir, output):
        d.mkdir()

    dedup_records = [
        {"source_guid": "sg-1", "content": {"dedup_code_blocks": {"code_block": "a"}}},
        {"source_guid": "sg-2", "content": {"dedup_code_blocks": {"code_block": "b"}}},
    ]

    storage = MagicMock()
    storage.load_metadata.return_value = None
    storage.read_target.side_effect = lambda action, rel: (
        dedup_records if action == "dedup_code_blocks" else []
    )

    def _list_targets(action):
        return ["data.json"] if action == "dedup_code_blocks" else []

    storage.list_target_files.side_effect = _list_targets

    def _get_disposition(action, record_id=None, disposition=None):
        if action == "tag_code_concept" and disposition == DISPOSITION_FILTERED:
            return [{"record_id": "sg-2", "disposition": DISPOSITION_FILTERED}]
        return []

    storage.get_disposition.side_effect = _get_disposition
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(tag_dir), str(dedup_dir)], output))

    guids = _captured_guids(runner)
    assert guids == ["sg-1"], f"filtered sg-2 survived single-source path: {guids}"


def test_transitive_ancestor_filter_is_authoritative(tmp_path):
    # Grandparent G filtered sg-2; it re-enters D via unfiltered branch P2. G is
    # not a DIRECT dep of D — only the dependency graph's transitive ancestors
    # expose it, so direct-dep-only scoping would miss this.
    p1_dir = tmp_path / "p1"
    p2_dir = tmp_path / "p2"
    output = tmp_path / "out"
    for d in (p1_dir, p2_dir, output):
        d.mkdir()

    p1_records = [{"source_guid": "sg-1", "content": {"p1": {"x": 1}}}]
    p2_records = [
        {"source_guid": "sg-1", "content": {"p2": {"y": 2}}},
        {"source_guid": "sg-2", "content": {"p2": {"y": 3}}},  # resurrected via P2
    ]
    storage = _storage(
        {"p1": p1_records, "p2": p2_records},
        {"g": ["sg-2"]},  # only the grandparent recorded the filter
        dependency_graph={"d": ["g", "p1", "p2"]},  # D's transitive ancestors include G
    )
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(
        runner, _params([str(p1_dir), str(p2_dir)], output, action_name="d")
    )

    guids = _captured_guids(runner)
    assert "sg-2" not in guids, f"grandparent-filtered sg-2 resurrected at D: {guids}"
    assert sorted(guids) == ["sg-1"]


def test_record_without_source_guid_is_kept(tmp_path):
    # A record lacking a source_guid key must never be dropped (it cannot match a
    # filtered guid, and dropping it would be silent data loss).
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    output = tmp_path / "out"
    for d in (a_dir, b_dir, output):
        d.mkdir()

    a_records = [{"content": {"a": {"x": 1}}}]  # no source_guid
    b_records = [{"source_guid": "sg-2", "content": {"b": {"y": 2}}}]
    storage = _storage({"a": a_records, "b": b_records}, {"a": ["sg-2"]})
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(a_dir), str(b_dir)], output))

    call = runner._process_single_file.call_args
    data = call[0][0].data
    # The no-guid record survives; sg-2 (filtered by 'a') is dropped.
    assert any("source_guid" not in r for r in data), "no-guid record was wrongly dropped"
    assert all(r.get("source_guid") != "sg-2" for r in data)


def test_get_disposition_error_fails_open(tmp_path):
    # A storage error while reading dispositions must not abort the action — it
    # degrades to no subtraction (matching the surrounding read handlers).
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    output = tmp_path / "out"
    for d in (a_dir, b_dir, output):
        d.mkdir()

    a_records = [{"source_guid": "sg-1", "content": {"a": {"x": 1}}}]
    b_records = [{"source_guid": "sg-2", "content": {"b": {"y": 2}}}]

    storage = MagicMock()
    storage.load_metadata.return_value = None
    storage.list_target_files.return_value = ["data.json"]
    storage.read_target.side_effect = lambda action, rel: ({"a": a_records, "b": b_records}[action])
    storage.get_disposition.side_effect = ValueError("disposition read failed")
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(a_dir), str(b_dir)], output))

    # Action still processed both records (fail-open, no crash).
    guids = _captured_guids(runner)
    assert sorted(guids) == ["sg-1", "sg-2"]


def test_no_filter_preserves_full_union(tmp_path):
    # Regression: two dependencies, no guard filters → full union is preserved.
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    output = tmp_path / "out"
    for d in (a_dir, b_dir, output):
        d.mkdir()

    a_records = [{"source_guid": "sg-1", "content": {"a": {"x": 1}}}]
    b_records = [
        {"source_guid": "sg-1", "content": {"b": {"y": 2}}},
        {"source_guid": "sg-2", "content": {"b": {"y": 3}}},
    ]
    storage = _storage({"a": a_records, "b": b_records}, {})  # no filtered dispositions
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(a_dir), str(b_dir)], output))

    guids = _captured_guids(runner)
    assert sorted(guids) == ["sg-1", "sg-2"], f"union altered without any filter: {guids}"


def test_node_level_filtered_disposition_is_ignored(tmp_path):
    # A node-level FILTERED marker (__node__) must not be treated as a record guid
    # to subtract — only per-record source_guids suppress records.
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    output = tmp_path / "out"
    for d in (a_dir, b_dir, output):
        d.mkdir()

    a_records = [{"source_guid": "sg-1", "content": {"a": {"x": 1}}}]
    b_records = [{"source_guid": "sg-1", "content": {"b": {"y": 2}}}]

    storage = MagicMock()
    storage.load_metadata.return_value = None
    storage.list_target_files.return_value = ["data.json"]
    storage.read_target.side_effect = lambda action, rel: ({"a": a_records, "b": b_records}[action])

    def _get_disposition(action, record_id=None, disposition=None):
        if action == "a" and disposition == DISPOSITION_FILTERED:
            return [{"record_id": NODE_LEVEL_RECORD_ID, "disposition": DISPOSITION_FILTERED}]
        return []

    storage.get_disposition.side_effect = _get_disposition
    runner = MagicMock()
    runner.storage_backend = storage

    process_from_storage_backend(runner, _params([str(a_dir), str(b_dir)], output))

    guids = _captured_guids(runner)
    assert guids == ["sg-1"], f"node-level marker wrongly dropped a record: {guids}"
