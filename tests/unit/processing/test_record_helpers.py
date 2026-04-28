"""Tests for shared record assembly helpers in processing.record_helpers."""

from agent_actions.processing.record_helpers import (
    CARRY_FORWARD_FIELDS,
    apply_version_merge,
    build_exhausted_tombstone,
    build_tombstone,
    carry_framework_fields,
    extract_existing_content,
)

# ---------------------------------------------------------------------------
# build_tombstone
# ---------------------------------------------------------------------------


class TestBuildTombstone:
    """Tests for build_tombstone()."""

    def test_guard_skip_sets_null_namespace(self):
        input_record = {"content": {"prev_action": {"a": 1}}, "source_guid": "sg1"}
        result = build_tombstone("my_action", input_record, "guard_skip", source_guid="sg1")

        assert result["content"]["my_action"] is None
        assert result["content"]["prev_action"] == {"a": 1}

    def test_metadata_has_reason_and_agent_type(self):
        result = build_tombstone("act", None, "guard_filter")
        assert result["metadata"]["reason"] == "guard_filter"
        assert result["metadata"]["agent_type"] == "tombstone"

    def test_unprocessed_flag_set(self):
        result = build_tombstone("act", None, "guard_skip")
        assert result["_unprocessed"] is True

    def test_source_guid_set_explicitly(self):
        result = build_tombstone("act", None, "guard_skip", source_guid="guid-123")
        assert result["source_guid"] == "guid-123"

    def test_source_guid_defaults_to_none(self):
        result = build_tombstone("act", None, "guard_skip")
        assert result["source_guid"] is None

    def test_extra_metadata_merged(self):
        result = build_tombstone("act", None, "guard_skip", extra_metadata={"retry_count": 3})
        assert result["metadata"]["reason"] == "guard_skip"
        assert result["metadata"]["retry_count"] == 3

    def test_target_id_carried_from_input(self):
        input_record = {"content": {}, "target_id": "tid-1"}
        result = build_tombstone("act", input_record, "guard_skip")
        assert result["target_id"] == "tid-1"

    def test_target_id_not_set_when_missing_from_input(self):
        input_record = {"content": {}}
        result = build_tombstone("act", input_record, "guard_skip")
        assert "target_id" not in result

    def test_none_input_record(self):
        result = build_tombstone("act", None, "guard_skip", source_guid="sg")
        assert result["content"] == {"act": None}
        assert result["_unprocessed"] is True

    def test_preserves_upstream_namespaces(self):
        input_record = {"content": {"ns_a": {"x": 1}, "ns_b": {"y": 2}}}
        result = build_tombstone("ns_c", input_record, "guard_skip")
        assert result["content"]["ns_a"] == {"x": 1}
        assert result["content"]["ns_b"] == {"y": 2}
        assert result["content"]["ns_c"] is None


# ---------------------------------------------------------------------------
# build_exhausted_tombstone
# ---------------------------------------------------------------------------


class TestBuildExhaustedTombstone:
    """Tests for build_exhausted_tombstone()."""

    def test_wraps_empty_content_under_namespace(self):
        input_record = {"content": {"prev": {"a": 1}}, "source_guid": "sg"}
        empty = {"field_a": None, "field_b": None}
        result = build_exhausted_tombstone("my_action", input_record, empty, source_guid="sg")

        assert result["content"]["my_action"] == empty
        assert result["content"]["prev"] == {"a": 1}

    def test_metadata_has_retry_exhausted_and_reason(self):
        result = build_exhausted_tombstone("act", None, {})
        assert result["metadata"]["retry_exhausted"] is True
        assert result["metadata"]["agent_type"] == "tombstone"
        assert result["metadata"]["reason"] == "retry_exhausted"

    def test_unprocessed_flag_set(self):
        result = build_exhausted_tombstone("act", None, {})
        assert result["_unprocessed"] is True

    def test_source_guid_set(self):
        result = build_exhausted_tombstone("act", None, {}, source_guid="sg-1")
        assert result["source_guid"] == "sg-1"

    def test_target_id_carried(self):
        input_record = {"content": {}, "target_id": "tid-2"}
        result = build_exhausted_tombstone("act", input_record, {})
        assert result["target_id"] == "tid-2"

    def test_extra_metadata_merged(self):
        result = build_exhausted_tombstone("act", None, {}, extra_metadata={"custom_key": "val"})
        assert result["metadata"]["custom_key"] == "val"
        assert result["metadata"]["retry_exhausted"] is True

    def test_none_input_record_produces_empty_existing(self):
        result = build_exhausted_tombstone("act", None, {"f": None})
        assert result["content"] == {"act": {"f": None}}


# ---------------------------------------------------------------------------
# carry_framework_fields
# ---------------------------------------------------------------------------


class TestCarryFrameworkFields:
    """Tests for carry_framework_fields()."""

    def test_carries_target_id(self):
        source = {"target_id": "tid-1", "content": {"x": 1}}
        target: dict = {}
        carry_framework_fields(source, target, fields=("target_id",))
        assert target["target_id"] == "tid-1"

    def test_carries_all_default_fields(self):
        source = {
            "target_id": "tid",
            "_unprocessed": True,
            "_recovery": {"attempt": 1},
            "metadata": {"reason": "test"},
        }
        target: dict = {}
        carry_framework_fields(source, target)
        assert target["target_id"] == "tid"
        assert target["_unprocessed"] is True
        assert target["_recovery"] == {"attempt": 1}
        assert target["metadata"]["reason"] == "test"

    def test_skips_missing_fields(self):
        source = {"content": {"x": 1}}
        target: dict = {}
        carry_framework_fields(source, target)
        assert "target_id" not in target
        assert "_unprocessed" not in target

    def test_overwrites_existing_target_value(self):
        source = {"target_id": "new"}
        target = {"target_id": "old"}
        carry_framework_fields(source, target, fields=("target_id",))
        assert target["target_id"] == "new"

    def test_none_source_is_noop(self):
        target = {"x": 1}
        result = carry_framework_fields(None, target)
        assert result == {"x": 1}

    def test_non_dict_source_is_noop(self):
        target = {"x": 1}
        result = carry_framework_fields("not a dict", target)  # type: ignore[arg-type]
        assert result == {"x": 1}

    def test_returns_target_for_chaining(self):
        target: dict = {}
        result = carry_framework_fields({"target_id": "t"}, target, fields=("target_id",))
        assert result is target

    def test_default_fields_match_constant(self):
        assert CARRY_FORWARD_FIELDS == ("target_id", "_unprocessed", "_recovery", "metadata")


# ---------------------------------------------------------------------------
# apply_version_merge
# ---------------------------------------------------------------------------


class TestApplyVersionMerge:
    """Tests for apply_version_merge()."""

    def test_tool_with_version_merge_does_flat_spread(self):
        config = {
            "action_name": "aggregate",
            "kind": "tool",
            "version_consumption_config": {"field": "version"},
        }
        existing = {"ns_a": {"x": 1}}
        output = {"ns_b": {"y": 2}}
        result = apply_version_merge(config, output, existing)
        assert result == {"ns_a": {"x": 1}, "ns_b": {"y": 2}}

    def test_llm_with_version_merge_wraps_under_namespace(self):
        config = {
            "action_name": "review",
            "kind": "llm",
            "version_consumption_config": {"field": "version"},
        }
        existing = {"ns_a": {"x": 1}}
        output = {"rating": 5}
        result = apply_version_merge(config, output, existing)
        assert result == {"ns_a": {"x": 1}, "review": {"rating": 5}}

    def test_no_version_merge_wraps_under_namespace(self):
        config = {"action_name": "my_action", "kind": "tool"}
        output = {"field": "value"}
        result = apply_version_merge(config, output, None)
        assert result == {"my_action": {"field": "value"}}

    def test_existing_content_none_treated_as_empty(self):
        config = {
            "action_name": "agg",
            "kind": "tool",
            "version_consumption_config": {"f": "v"},
        }
        result = apply_version_merge(config, {"k": 1}, None)
        assert result == {"k": 1}

    def test_existing_content_preserved_for_non_version_merge(self):
        config = {"action_name": "act"}
        existing = {"prev": {"a": 1}}
        result = apply_version_merge(config, {"b": 2}, existing)
        assert result == {"prev": {"a": 1}, "act": {"b": 2}}

    def test_no_kind_key_defaults_to_non_tool(self):
        """Missing 'kind' means is_tool is False → namespace wrapping."""
        config = {
            "action_name": "act",
            "version_consumption_config": {"f": "v"},
        }
        result = apply_version_merge(config, {"b": 2}, {"a": {"x": 1}})
        assert result == {"a": {"x": 1}, "act": {"b": 2}}


# ---------------------------------------------------------------------------
# extract_existing_content
# ---------------------------------------------------------------------------


class TestExtractExistingContent:
    """Tests for extract_existing_content()."""

    def test_returns_content_dict(self):
        record = {"content": {"ns_a": {"x": 1}}, "source_guid": "sg"}
        assert extract_existing_content(record) == {"ns_a": {"x": 1}}

    def test_returns_empty_dict_when_no_content(self):
        assert extract_existing_content({"source_guid": "sg"}) == {}

    def test_returns_empty_dict_when_content_is_not_dict(self):
        assert extract_existing_content({"content": "string_value"}) == {}

    def test_first_stage_wraps_raw_fields(self):
        record = {"field_a": 1, "field_b": "two", "source_guid": "sg"}
        result = extract_existing_content(record, is_first_stage=True)
        assert result == {"source": {"field_a": 1, "field_b": "two"}}

    def test_first_stage_excludes_framework_fields(self):
        record = {
            "source_guid": "sg",
            "target_id": "tid",
            "node_id": "nid",
            "metadata": {},
            "user_field": "val",
        }
        result = extract_existing_content(record, is_first_stage=True)
        assert result == {"source": {"user_field": "val"}}

    def test_first_stage_with_existing_content_returns_content(self):
        """First-stage fallback only applies when content is missing."""
        record = {"content": {"ns": {"x": 1}}, "field_a": 1}
        result = extract_existing_content(record, is_first_stage=True)
        assert result == {"ns": {"x": 1}}

    def test_first_stage_empty_raw_fields_returns_empty(self):
        """If only framework fields remain after filtering, return {}."""
        record = {"source_guid": "sg", "target_id": "tid"}
        result = extract_existing_content(record, is_first_stage=True)
        assert result == {}

    def test_non_first_stage_ignores_raw_fields(self):
        record = {"field_a": 1, "field_b": "two"}
        result = extract_existing_content(record, is_first_stage=False)
        assert result == {}
