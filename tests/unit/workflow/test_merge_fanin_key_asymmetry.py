"""Fan-in grouping when branches carry asymmetric correlation keys."""

from agent_actions.workflow.merge import merge_records_by_key


def _branch_record(namespace: str, guid: str, vc: str | None = None, **top: object) -> dict:
    record = {
        "source_guid": guid,
        "target_id": f"tid-{namespace}-{guid}",
        "content": {namespace: {"value": namespace}},
        **top,
    }
    if vc is not None:
        record["version_correlation_id"] = vc
    return record


class TestFanInKeyAsymmetry:
    """Branches of the same logical record must group despite different key sets."""

    def test_vc_branch_merges_with_plain_branch(self):
        """A version-merge descendant and a plain branch of the same record merge."""
        records = [
            _branch_record("branch_a", "guid-1", vc="corr_aaa"),
            _branch_record("branch_b", "guid-1"),
            _branch_record("branch_a", "guid-2", vc="corr_bbb"),
            _branch_record("branch_b", "guid-2"),
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2
        by_guid = {r["source_guid"]: r for r in result}
        for guid in ("guid-1", "guid-2"):
            content = by_guid[guid]["content"]
            assert set(content) == {"branch_a", "branch_b"}

    def test_uniform_vc_pool_groups_by_vc(self):
        """When every record carries a vc id, grouping keys on it as before."""
        records = [
            _branch_record("branch_a", "guid-1", vc="corr_aaa"),
            _branch_record("branch_b", "guid-1", vc="corr_aaa"),
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        assert set(result[0]["content"]) == {"branch_a", "branch_b"}

    def test_same_guid_different_vc_stays_separate(self):
        """Records sharing a guid but carrying distinct vc ids never merge."""
        records = [
            _branch_record("branch_a", "guid-1", vc="corr_aaa"),
            _branch_record("branch_b", "guid-1", vc="corr_zzz"),
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2

    def test_expansion_siblings_with_shared_parent_not_collapsed(self):
        """Expanded siblings share a parent id but are distinct records."""
        records = [
            _branch_record("flat", "guid-1", parent_target_id="parent-1"),
            _branch_record("flat", "guid-2", parent_target_id="parent-1"),
            _branch_record("flat", "guid-3", parent_target_id="parent-1"),
        ]

        result = merge_records_by_key(records)

        assert len(result) == 3
        assert {r["source_guid"] for r in result} == {"guid-1", "guid-2", "guid-3"}

    def test_parent_key_still_groups_records_without_guid(self):
        """Records with only a parent id keep grouping by it."""
        records = [
            {"parent_target_id": "parent-1", "content": {"branch_a": {"value": 1}}},
            {"parent_target_id": "parent-1", "content": {"branch_b": {"value": 2}}},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1

    def test_disjoint_key_spaces_stay_separate(self):
        """With no key shared by all records, per-record grouping still applies."""
        records = [
            {"version_correlation_id": "corr_aaa", "content": {"branch_a": {"value": 1}}},
            {"parent_target_id": "parent-1", "content": {"branch_b": {"value": 2}}},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2
