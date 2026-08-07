"""Keying tests for VersionIdGenerator.add_version_correlation_id.

Parallel versions of one source record must share a correlation id so a
merge consumer can group them, while 1->N expansions keep unique per-item
ids. These pin both invariants.
"""

from agent_actions.utils.correlation import VersionIdGenerator

_CFG = {"is_versioned_agent": True, "version_base_name": "extract", "workflow_session_id": "s1"}


def test_versioned_same_source_guid_shares_id_across_positions():
    VersionIdGenerator.clear()
    v1 = VersionIdGenerator.add_version_correlation_id({"source_guid": "g1"}, _CFG, record_index=0)
    v2 = VersionIdGenerator.add_version_correlation_id({"source_guid": "g1"}, _CFG, record_index=2)
    assert v1["version_correlation_id"] == v2["version_correlation_id"]


def test_versioned_different_source_guids_get_different_ids():
    VersionIdGenerator.clear()
    a = VersionIdGenerator.add_version_correlation_id({"source_guid": "g1"}, _CFG, record_index=0)
    b = VersionIdGenerator.add_version_correlation_id({"source_guid": "g2"}, _CFG, record_index=0)
    assert a["version_correlation_id"] != b["version_correlation_id"]


def test_expansion_items_keep_unique_ids():
    VersionIdGenerator.clear()
    cfg = {"is_versioned_agent": False, "action_name": "expand", "workflow_session_id": "s1"}
    a = VersionIdGenerator.add_version_correlation_id(
        {"source_guid": "g1"}, cfg, record_index=0, force=True
    )
    b = VersionIdGenerator.add_version_correlation_id(
        {"source_guid": "g1"}, cfg, record_index=1, force=True
    )
    assert a["version_correlation_id"] != b["version_correlation_id"]


def test_versioned_expansion_items_keep_unique_ids():
    """A versioned agent that ALSO expands keeps unique per-item ids (kills the drop-`not force` cheat)."""
    VersionIdGenerator.clear()
    cfg = {"is_versioned_agent": True, "version_base_name": "extract", "workflow_session_id": "s1"}
    a = VersionIdGenerator.add_version_correlation_id(
        {"source_guid": "g1"}, cfg, record_index=0, force=True
    )
    b = VersionIdGenerator.add_version_correlation_id(
        {"source_guid": "g1"}, cfg, record_index=1, force=True
    )
    assert a["version_correlation_id"] != b["version_correlation_id"]


def test_versioned_no_source_guid_falls_back_to_position():
    """Versioned records lacking source_guid keep per-position ids (kills the fallback-collapse cheat)."""
    VersionIdGenerator.clear()
    a = VersionIdGenerator.add_version_correlation_id({}, _CFG, record_index=0)
    b = VersionIdGenerator.add_version_correlation_id({}, _CFG, record_index=1)
    assert a.get("version_correlation_id") != b.get("version_correlation_id")


def test_versioned_shared_id_uses_guid_helper():
    """The shared id is exactly the GUID helper's output (kills inline-hash and clamp-to-0 cheats)."""
    VersionIdGenerator.clear()
    v = VersionIdGenerator.add_version_correlation_id({"source_guid": "g1"}, _CFG, record_index=3)
    assert v["version_correlation_id"] == VersionIdGenerator.get_or_create_version_correlation_id(
        "g1", "extract", "s1"
    )
