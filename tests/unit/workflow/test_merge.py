"""Dedicated unit tests for workflow/merge.py module."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_actions.workflow.merge import (
    deep_merge_record,
    get_correlation_value,
    merge_json_files,
    merge_records_by_key,
)


class TestDeepMergeRecord:
    """Tests for deep_merge_record function."""

    def test_merges_content_dicts(self):
        """Should deep merge content dictionaries."""
        existing = {"content": {"field_a": "A"}}
        new_record = {"content": {"field_b": "B"}}

        deep_merge_record(existing, new_record)

        assert existing["content"]["field_a"] == "A"
        assert existing["content"]["field_b"] == "B"

    def test_creates_content_if_missing(self):
        """Should create content dict if not present in existing."""
        existing = {"other": "data"}
        new_record = {"content": {"field": "value"}}

        deep_merge_record(existing, new_record)

        assert existing["content"]["field"] == "value"

    def test_overwrites_non_dict_content(self):
        """Should overwrite existing content if it's not a dict."""
        existing = {"content": "string_value"}
        new_record = {"content": {"field": "value"}}

        deep_merge_record(existing, new_record)

        assert existing["content"] == {"field": "value"}

    def test_first_occurrence_wins_for_other_fields(self):
        """Should keep first occurrence for non-mergeable fields."""
        existing = {"field": "first"}
        new_record = {"field": "second", "new_field": "new"}

        deep_merge_record(existing, new_record)

        assert existing["field"] == "first"
        assert existing["new_field"] == "new"


class TestMergeLineage:
    """Tests for lineage merging behavior in deep_merge_record."""

    def test_merges_string_lineage(self):
        """Should merge lineage with string entries."""
        existing = {"lineage": ["node_1", "node_2"]}
        new_record = {"lineage": ["node_2", "node_3"]}

        deep_merge_record(existing, new_record)

        assert len(existing["lineage"]) == 3
        assert set(existing["lineage"]) == {"node_1", "node_2", "node_3"}

    def test_merges_dict_lineage_by_node_id(self):
        """Should deduplicate dict lineage entries by node_id."""
        existing = {"lineage": [{"node_id": "a", "data": 1}]}
        new_record = {"lineage": [{"node_id": "a", "data": 2}, {"node_id": "b", "data": 3}]}

        deep_merge_record(existing, new_record)

        assert len(existing["lineage"]) == 2
        node_ids = {e["node_id"] for e in existing["lineage"]}
        assert node_ids == {"a", "b"}

    def test_creates_lineage_if_missing(self):
        """Should create lineage if not present in existing."""
        existing = {}
        new_record = {"lineage": ["node_1"]}

        deep_merge_record(existing, new_record)

        assert existing["lineage"] == ["node_1"]

    def test_preserves_dict_entries_without_node_id(self):
        """Should preserve dict lineage entries that don't have node_id."""
        existing = {"lineage": [{"node_id": "a", "data": 1}]}
        new_record = {"lineage": [{"custom_annotation": "value", "metadata": 123}]}

        deep_merge_record(existing, new_record)

        assert len(existing["lineage"]) == 2
        # Original entry preserved
        assert existing["lineage"][0] == {"node_id": "a", "data": 1}
        # Entry without node_id also preserved
        assert existing["lineage"][1] == {"custom_annotation": "value", "metadata": 123}

    def test_ignores_non_list_existing_lineage(self):
        """Should not modify lineage if existing is not a list."""
        existing = {"lineage": "invalid"}
        new_record = {"lineage": ["node_1"]}

        deep_merge_record(existing, new_record)

        assert existing["lineage"] == "invalid"


class TestParallelBranchLineageSources:
    """Tests for lineage_sources population during parallel branch merges."""

    def test_two_branch_merge_populates_lineage_sources(self):
        """Merging records from two parallel branches sets lineage_sources with both leaf node_ids."""
        existing = {
            "source_guid": "book-001",
            "node_id": "generate_concept_explanation_def",
            "lineage": ["reconstruct_options_xyz", "generate_concept_explanation_def"],
            "content": {"concept_explanation": "..."},
        }
        new_record = {
            "source_guid": "book-001",
            "node_id": "generate_feynman_explanation_abc",
            "lineage": ["reconstruct_options_xyz", "generate_feynman_explanation_abc"],
            "content": {"feynman_explanation": "..."},
        }

        deep_merge_record(existing, new_record)

        assert existing["lineage_sources"] == [
            "generate_concept_explanation_def",
            "generate_feynman_explanation_abc",
        ]
        assert "generate_concept_explanation_def" in existing["lineage"]
        assert "generate_feynman_explanation_abc" in existing["lineage"]
        assert existing["content"]["concept_explanation"] == "..."
        assert existing["content"]["feynman_explanation"] == "..."

    def test_three_branch_merge_populates_lineage_sources(self):
        """Merging three parallel branches accumulates all leaf node_ids in lineage_sources."""
        branch_a = {
            "source_guid": "book-001",
            "node_id": "node_4_seo",
            "lineage": ["node_0_extract", "node_4_seo"],
            "content": {"seo_score": 85},
        }
        branch_b = {
            "source_guid": "book-001",
            "node_id": "node_5_recs",
            "lineage": ["node_0_extract", "node_5_recs"],
            "content": {"similar_books": ["Refactoring"]},
        }
        branch_c = {
            "source_guid": "book-001",
            "node_id": "node_6_level",
            "lineage": ["node_0_extract", "node_6_level"],
            "content": {"reading_level": "advanced"},
        }

        deep_merge_record(branch_a, branch_b)
        deep_merge_record(branch_a, branch_c)

        assert len(branch_a["lineage_sources"]) == 3
        assert "node_4_seo" in branch_a["lineage_sources"]
        assert "node_5_recs" in branch_a["lineage_sources"]
        assert "node_6_level" in branch_a["lineage_sources"]

    def test_single_branch_no_lineage_sources(self):
        """Merging records with same node_id (same branch) does not set lineage_sources."""
        existing = {
            "source_guid": "abc",
            "node_id": "action_1",
            "lineage": ["root_0", "action_1"],
        }
        new_record = {
            "source_guid": "abc",
            "node_id": "action_1",
            "lineage": ["root_0", "action_1"],
            "content": {"extra": "data"},
        }

        deep_merge_record(existing, new_record)

        assert "lineage_sources" not in existing

    def test_no_lineage_sources_when_no_node_id(self):
        """Records without node_id do not get lineage_sources."""
        existing = {"source_guid": "abc", "field_1": "A"}
        new_record = {"source_guid": "abc", "field_2": "B"}

        deep_merge_record(existing, new_record)

        assert "lineage_sources" not in existing

    def test_merge_records_by_key_populates_lineage_sources(self):
        """End-to-end: merge_records_by_key sets lineage_sources for parallel branch records."""
        records = [
            {
                "source_guid": "book-001",
                "node_id": "branch_a_001",
                "lineage": ["root_0", "branch_a_001"],
                "content": {"field_a": "A"},
            },
            {
                "source_guid": "book-001",
                "node_id": "branch_b_002",
                "lineage": ["root_0", "branch_b_002"],
                "content": {"field_b": "B"},
            },
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        merged = result[0]
        assert merged["lineage_sources"] == ["branch_a_001", "branch_b_002"]
        assert "branch_a_001" in merged["lineage"]
        assert "branch_b_002" in merged["lineage"]

    def test_merge_json_files_populates_lineage_sources(self):
        """End-to-end: merge_json_files from parallel branches sets lineage_sources."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "branch_a.json"
            file2 = Path(tmpdir) / "branch_b.json"

            file1.write_text(
                json.dumps(
                    [
                        {
                            "source_guid": "book-001",
                            "node_id": "gen_concept_def",
                            "lineage": ["root_xyz", "gen_concept_def"],
                            "content": {"concept": "explanation"},
                        }
                    ]
                )
            )
            file2.write_text(
                json.dumps(
                    [
                        {
                            "source_guid": "book-001",
                            "node_id": "gen_feynman_abc",
                            "lineage": ["root_xyz", "gen_feynman_abc"],
                            "content": {"feynman": "explanation"},
                        }
                    ]
                )
            )

            result = merge_json_files([file1, file2])

            assert len(result) == 1
            merged = result[0]
            assert merged["lineage_sources"] == ["gen_concept_def", "gen_feynman_abc"]
            assert merged["content"]["concept"] == "explanation"
            assert merged["content"]["feynman"] == "explanation"


class TestGetCorrelationValue:
    """Tests for get_correlation_value function."""

    def test_finds_top_level_key(self):
        """Should find correlation value at top level."""
        record = {"source_guid": "abc123", "other": "data"}

        result = get_correlation_value(record, ["source_guid"])

        assert result == "abc123"

    def test_finds_nested_in_content(self):
        """Should find correlation value nested in content dict."""
        record = {"content": {"parent_target_id": "xyz"}}

        result = get_correlation_value(record, ["parent_target_id"])

        assert result == "xyz"

    def test_fallback_chain(self):
        """Should try keys in order and return first found."""
        record = {"source_guid": "fallback"}

        result = get_correlation_value(record, ["missing_key", "source_guid"])

        assert result == "fallback"

    def test_returns_none_when_not_found(self):
        """Should return None when no correlation key found."""
        record = {"unrelated": "data"}

        result = get_correlation_value(record, ["source_guid", "parent_target_id"])

        assert result is None

    def test_handles_non_dict_content(self):
        """Should handle non-dict content gracefully."""
        record = {"content": "string_value"}

        result = get_correlation_value(record, ["nested_key"])

        assert result is None

    def test_converts_to_string(self):
        """Should convert correlation value to string."""
        record = {"id": 12345}

        result = get_correlation_value(record, ["id"])

        assert result == "12345"


class TestMergeRecordsByKey:
    """Tests for merge_records_by_key function."""

    def test_merges_by_source_guid(self):
        """Should merge records by source_guid."""
        records = [
            {"source_guid": "abc", "field_1": "A"},
            {"source_guid": "abc", "field_2": "B"},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        assert result[0]["field_1"] == "A"
        assert result[0]["field_2"] == "B"

    def test_merges_by_parent_target_id(self):
        """Should merge records by parent_target_id."""
        records = [
            {"parent_target_id": "xyz", "answer_1": "A"},
            {"parent_target_id": "xyz", "answer_2": "B"},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        assert result[0]["answer_1"] == "A"
        assert result[0]["answer_2"] == "B"

    def test_uses_explicit_reduce_key(self):
        """Should use explicit reduce_key when provided."""
        records = [
            {"custom_id": "123", "source_guid": "diff1", "data": "a"},
            {"custom_id": "123", "source_guid": "diff2", "data": "b"},
        ]

        result = merge_records_by_key(records, reduce_key="custom_id")

        assert len(result) == 1
        assert result[0]["custom_id"] == "123"

    def test_keeps_records_with_different_keys_separate(self):
        """Should not merge records with different correlation keys."""
        records = [
            {"source_guid": "abc", "value": 1},
            {"source_guid": "xyz", "value": 2},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2

    def test_handles_records_without_key(self):
        """Should include records without correlation keys as-is."""
        records = [
            {"source_guid": "abc", "merged": True},
            {"no_key": "orphan"},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2

    def test_handles_non_dict_records(self):
        """Should include non-dict records as-is."""
        records = [
            {"source_guid": "abc", "value": 1},
            "string_record",
            123,
        ]

        result = merge_records_by_key(records)

        assert len(result) == 3
        assert "string_record" in result
        assert 123 in result


class TestMergeJsonFiles:
    """Tests for merge_json_files function."""

    def test_merges_from_multiple_files(self):
        """Should merge records from multiple JSON files."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.json"
            file2 = Path(tmpdir) / "file2.json"

            file1.write_text(json.dumps([{"source_guid": "abc", "field_1": "A"}]))
            file2.write_text(json.dumps([{"source_guid": "abc", "field_2": "B"}]))

            result = merge_json_files([file1, file2])

            assert len(result) == 1
            assert result[0]["field_1"] == "A"
            assert result[0]["field_2"] == "B"

    def test_handles_single_object_json(self):
        """Should handle JSON files containing a single object (not array)."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.json"
            file1.write_text(json.dumps({"source_guid": "abc", "data": "value"}))

            result = merge_json_files([file1])

            assert len(result) == 1
            assert result[0]["data"] == "value"

    def test_handles_invalid_json(self):
        """Should log warning and skip invalid JSON files."""
        with TemporaryDirectory() as tmpdir:
            valid_file = Path(tmpdir) / "valid.json"
            invalid_file = Path(tmpdir) / "invalid.json"

            valid_file.write_text(json.dumps([{"source_guid": "abc", "data": "good"}]))
            invalid_file.write_text("not valid json {{{")

            result = merge_json_files([valid_file, invalid_file])

            assert len(result) == 1
            assert result[0]["data"] == "good"

    def test_handles_missing_file(self):
        """Should log warning and skip missing files."""
        with TemporaryDirectory() as tmpdir:
            valid_file = Path(tmpdir) / "valid.json"
            missing_file = Path(tmpdir) / "missing.json"

            valid_file.write_text(json.dumps([{"source_guid": "abc", "data": "good"}]))

            result = merge_json_files([valid_file, missing_file])

            assert len(result) == 1

    def test_uses_reduce_key(self):
        """Should use reduce_key for correlation."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.json"
            file2 = Path(tmpdir) / "file2.json"

            file1.write_text(json.dumps([{"custom_key": "x", "a": 1}]))
            file2.write_text(json.dumps([{"custom_key": "x", "b": 2}]))

            result = merge_json_files([file1, file2], reduce_key="custom_key")

            assert len(result) == 1
            assert result[0]["a"] == 1
            assert result[0]["b"] == 2
