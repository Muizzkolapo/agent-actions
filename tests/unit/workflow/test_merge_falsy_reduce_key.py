"""Grouping when a reduce_key carries a legitimately falsy value."""

from agent_actions.workflow.merge import merge_records_by_key


def _record(guid: str, namespace: str, **top: object) -> dict:
    return {
        "source_guid": guid,
        "content": {namespace: {"value": namespace}},
        **top,
    }


def _keyed_record(guid: str, namespace: str, key_name: str, key_value: object) -> dict:
    record = _record(guid, namespace)
    record["content"][key_name] = key_value
    return record


class TestFalsyReduceKeyValue:
    """A falsy reduce_key value is a group label, not a missing key."""

    def test_zero_value_group_merges(self):
        records = [
            _keyed_record("s1", "a", "cluster_id", 0),
            _keyed_record("s2", "b", "cluster_id", 0),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 1
        assert set(result[0]["content"]) == {"cluster_id", "a", "b"}

    def test_empty_string_value_group_merges(self):
        records = [
            _keyed_record("s1", "a", "cluster_id", ""),
            _keyed_record("s2", "b", "cluster_id", ""),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 1
        assert set(result[0]["content"]) == {"cluster_id", "a", "b"}

    def test_false_value_group_merges(self):
        records = [
            _keyed_record("s1", "a", "is_primary", False),
            _keyed_record("s2", "b", "is_primary", False),
        ]

        result = merge_records_by_key(records, reduce_key="is_primary")

        assert len(result) == 1
        assert set(result[0]["content"]) == {"is_primary", "a", "b"}

    def test_truthy_value_group_still_merges(self):
        """Control: the non-falsy path that already worked must keep working."""
        records = [
            _keyed_record("s1", "a", "cluster_id", 7),
            _keyed_record("s2", "b", "cluster_id", 7),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 1
        assert set(result[0]["content"]) == {"cluster_id", "a", "b"}

    def test_zero_group_merges_alongside_nonzero_groups(self):
        """Group 0 aggregates like every other group and stays distinct from them."""
        records = [
            _keyed_record("s1", "a", "cluster_id", 0),
            _keyed_record("s2", "b", "cluster_id", 0),
            _keyed_record("s3", "c", "cluster_id", 1),
            _keyed_record("s4", "d", "cluster_id", 1),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 2
        by_cluster = {r["content"]["cluster_id"]: r for r in result}
        assert set(by_cluster) == {0, 1}
        assert set(by_cluster[0]["content"]) == {"cluster_id", "a", "b"}
        assert set(by_cluster[1]["content"]) == {"cluster_id", "c", "d"}

    def test_zero_value_at_top_level_merges(self):
        """The reduce_key resolves from the record top level as well as its content."""
        records = [
            _record("s1", "a", cluster_id=0),
            _record("s2", "b", cluster_id=0),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 1
        assert set(result[0]["content"]) == {"a", "b"}

    def test_distinct_falsy_values_do_not_group_together(self):
        """0, "" and False are different labels — they must not collapse into one group."""
        records = [
            _keyed_record("s1", "a", "cluster_id", 0),
            _keyed_record("s2", "b", "cluster_id", ""),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 2


class TestReduceKeyAbsence:
    """Only a genuinely absent key means 'this record is unkeyed'."""

    def test_null_value_is_not_a_group_label(self):
        """An explicit JSON null is absence, so records fall through to identity keys."""
        records = [
            _keyed_record("s1", "a", "cluster_id", None),
            _keyed_record("s2", "b", "cluster_id", None),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 2

    def test_absent_key_falls_back_to_identity_keys(self):
        """Records lacking the reduce_key keep grouping by their shared source_guid."""
        records = [
            _record("same", "a"),
            _record("same", "b"),
        ]

        result = merge_records_by_key(records, reduce_key="cluster_id")

        assert len(result) == 1

    def test_empty_identity_key_does_not_collapse_records(self):
        """Identity keys stay truthiness-gated: an unset source_guid is not a group."""
        records = [
            _record("", "a"),
            _record("", "b"),
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2
