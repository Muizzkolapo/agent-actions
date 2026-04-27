"""Unit tests for merge_branch_records() primitive."""

from copy import deepcopy

from agent_actions.workflow.merge import merge_branch_records


class TestMergeBranchRecordsTwoBranches:
    """Two parallel branches merging (fan-in pattern)."""

    def test_each_branch_contributes_own_namespace(self):
        """Each branch contributes only its own namespace to the merged result."""
        branch_a = {
            "source_guid": "guid-1",
            "node_id": "classify_abc",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello"},
                "classify": {"topic": "science"},
            },
            "lineage": ["source_abc", "extract_abc", "classify_abc"],
        }
        branch_b = {
            "source_guid": "guid-1",
            "node_id": "enrich_def",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello"},
                "enrich": {"summary": "about science"},
            },
            "lineage": ["source_abc", "extract_abc", "enrich_def"],
        }

        result = merge_branch_records(
            {"classify": branch_a, "enrich": branch_b}, base_record=branch_a
        )
        content = result["content"]

        assert content["classify"] == {"topic": "science"}
        assert content["enrich"] == {"summary": "about science"}

    def test_upstream_from_base_record_preserved(self):
        """Upstream namespaces come from base_record, not overwritten by branches."""
        branch_a = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello", "_retry_count": 1},
                "classify": {"topic": "science"},
            },
        }
        branch_b = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello"},
                "enrich": {"summary": "about science"},
            },
        }

        result = merge_branch_records(
            {"classify": branch_a, "enrich": branch_b}, base_record=branch_a
        )
        content = result["content"]

        # Upstream preserved from base (branch_a)
        assert content["source"] == {"url": "http://doc.com"}
        assert content["extract"] == {"text": "hello", "_retry_count": 1}

    def test_base_record_upstream_not_overwritten_by_branch_upstream(self):
        """Branches cannot overwrite upstream namespaces — only contribute their own."""
        base = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello", "_retry_count": 1},
            },
        }
        branch_a = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "extract": {"text": "hello"},  # missing _retry_count
                "classify": {"topic": "science"},
            },
        }

        result = merge_branch_records({"classify": branch_a}, base_record=base)
        content = result["content"]

        # Base upstream wins — branch's stale upstream is ignored
        assert content["extract"]["_retry_count"] == 1


class TestMergeBranchRecordsVersionPattern:
    """Three version branches (voter pattern)."""

    def test_three_versions_merge(self):
        """Three version branches each contribute only their own namespace."""
        upstream_content = {
            "source": {"url": "http://doc.com"},
            "upstream_action": {"question": "What is X?"},
        }
        voter_1 = {
            "source_guid": "guid-1",
            "content": {**upstream_content, "voter_1": {"vote": "keep", "confidence": 0.8}},
            "lineage": [{"node_id": "source_0"}, {"node_id": "voter_1_abc"}],
        }
        voter_2 = {
            "source_guid": "guid-1",
            "content": {**upstream_content, "voter_2": {"vote": "reject", "confidence": 0.3}},
            "lineage": [{"node_id": "source_0"}, {"node_id": "voter_2_def"}],
        }
        voter_3 = {
            "source_guid": "guid-1",
            "content": {**upstream_content, "voter_3": {"vote": "keep", "confidence": 0.9}},
            "lineage": [{"node_id": "source_0"}, {"node_id": "voter_3_ghi"}],
        }

        result = merge_branch_records(
            {"voter_1": voter_1, "voter_2": voter_2, "voter_3": voter_3},
            base_record=voter_1,
        )
        content = result["content"]

        # Each version namespace present with correct data
        assert content["voter_1"] == {"vote": "keep", "confidence": 0.8}
        assert content["voter_2"] == {"vote": "reject", "confidence": 0.3}
        assert content["voter_3"] == {"vote": "keep", "confidence": 0.9}

        # Upstream present exactly once
        assert content["source"] == {"url": "http://doc.com"}
        assert content["upstream_action"] == {"question": "What is X?"}

    def test_version_namespaces_do_not_contain_upstream(self):
        """Version namespace values contain only their own output, not nested upstream."""
        voter_1 = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "voter_1": {"vote": "keep"},
            },
        }
        voter_2 = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "voter_2": {"vote": "reject"},
            },
        }

        result = merge_branch_records({"voter_1": voter_1, "voter_2": voter_2}, base_record=voter_1)
        content = result["content"]

        assert "source" not in content["voter_1"]
        assert "source" not in content["voter_2"]


class TestMergeBranchRecordsMissingNamespace:
    """Branch missing its own namespace — warning logged, others proceed."""

    def test_missing_namespace_logs_warning(self, mocker):
        """Branch without own namespace in content logs a warning."""
        mock_warn = mocker.patch("agent_actions.workflow.merge.logger.warning")
        branch_a = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "classify": {"topic": "science"},
            },
        }
        # branch_b is named "enrich" but doesn't have "enrich" in content
        branch_b = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "unexpected": {"data": "oops"},
            },
        }

        result = merge_branch_records(
            {"classify": branch_a, "enrich": branch_b}, base_record=branch_a
        )

        mock_warn.assert_called_once()
        assert "enrich" in mock_warn.call_args[0][1]
        # classify still merged successfully
        assert result["content"]["classify"] == {"topic": "science"}
        # enrich was not merged (not present)
        assert "enrich" not in result["content"]

    def test_other_branches_still_merge_when_one_missing(self):
        """Other branches' namespaces merge even if one branch is malformed."""
        good_branch = {
            "source_guid": "guid-1",
            "content": {"source": {"url": "x"}, "good": {"data": "yes"}},
        }
        bad_branch = {
            "source_guid": "guid-1",
            "content": {"source": {"url": "x"}, "wrong_name": {"data": "no"}},
        }

        result = merge_branch_records(
            {"good": good_branch, "bad": bad_branch}, base_record=good_branch
        )

        assert result["content"]["good"] == {"data": "yes"}
        assert "bad" not in result["content"]


class TestMergeBranchRecordsEmptyInput:
    """Empty or edge-case inputs."""

    def test_empty_branch_records_returns_base(self):
        """Empty branch_records returns base_record unchanged."""
        base = {"source_guid": "guid-1", "content": {"source": {"url": "x"}}}

        result = merge_branch_records({}, base_record=base)

        assert result == base

    def test_empty_branch_records_no_base_returns_empty(self):
        """Empty branch_records with no base returns empty dict."""
        result = merge_branch_records({})

        assert result == {}

    def test_no_base_record_uses_first_branch(self):
        """When base_record is None, first branch is used for upstream content."""
        branch_a = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "branch_a": {"data": "A"},
            },
            "lineage": ["source_0"],
        }
        branch_b = {
            "source_guid": "guid-1",
            "content": {
                "source": {"url": "http://doc.com"},
                "branch_b": {"data": "B"},
            },
            "lineage": ["source_0", "branch_b_node"],
        }

        result = merge_branch_records({"branch_a": branch_a, "branch_b": branch_b})
        content = result["content"]

        assert content["source"] == {"url": "http://doc.com"}
        assert content["branch_a"] == {"data": "A"}
        assert content["branch_b"] == {"data": "B"}


class TestMergeBranchRecordsLineage:
    """Lineage deduplication across branches."""

    def test_lineage_deduplicated_string_entries(self):
        """String lineage entries are deduplicated across branches."""
        branch_a = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "a": {"data": "A"}},
            "lineage": ["source_0", "extract_1", "a_node"],
        }
        branch_b = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "b": {"data": "B"}},
            "lineage": ["source_0", "extract_1", "b_node"],
        }

        result = merge_branch_records({"a": branch_a, "b": branch_b}, base_record=branch_a)

        lineage = result["lineage"]
        # shared entries appear once, branch-specific appear once each
        assert lineage.count("source_0") == 1
        assert lineage.count("extract_1") == 1
        assert "a_node" in lineage
        assert "b_node" in lineage
        assert len(lineage) == 4

    def test_lineage_deduplicated_dict_entries(self):
        """Dict lineage entries are deduplicated by node_id."""
        branch_a = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "a": {"data": "A"}},
            "lineage": [{"node_id": "shared"}, {"node_id": "a_only"}],
        }
        branch_b = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "b": {"data": "B"}},
            "lineage": [{"node_id": "shared"}, {"node_id": "b_only"}],
        }

        result = merge_branch_records({"a": branch_a, "b": branch_b}, base_record=branch_a)

        lineage = result["lineage"]
        node_ids = [e["node_id"] for e in lineage if isinstance(e, dict)]
        assert node_ids.count("shared") == 1
        assert "a_only" in node_ids
        assert "b_only" in node_ids

    def test_branch_without_lineage(self):
        """Branches without lineage field don't cause errors."""
        branch_a = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "a": {"data": "A"}},
            "lineage": ["source_0"],
        }
        branch_b = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "b": {"data": "B"}},
            # no lineage field
        }

        result = merge_branch_records({"a": branch_a, "b": branch_b}, base_record=branch_a)

        assert "source_0" in result["lineage"]


class TestMergeBranchRecordsBaseRecordPreservation:
    """Base record metadata fields are preserved in result."""

    def test_preserves_source_guid(self):
        """source_guid from base_record is in the result."""
        base = {
            "source_guid": "guid-1",
            "target_id": "target-1",
            "node_id": "node-1",
            "content": {"source": {"x": 1}},
        }
        branch = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "branch": {"data": "yes"}},
        }

        result = merge_branch_records({"branch": branch}, base_record=base)

        assert result["source_guid"] == "guid-1"
        assert result["target_id"] == "target-1"
        assert result["node_id"] == "node-1"

    def test_does_not_mutate_inputs(self):
        """merge_branch_records does not mutate the input records."""
        base = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}},
            "lineage": ["node_0"],
        }
        branch = {
            "source_guid": "guid-1",
            "content": {"source": {"x": 1}, "branch": {"data": "yes"}},
            "lineage": ["node_0", "branch_1"],
        }
        base_copy = deepcopy(base)
        branch_copy = deepcopy(branch)

        merge_branch_records({"branch": branch}, base_record=base)

        assert base == base_copy
        assert branch == branch_copy
