"""Tests for apply_context_scope_for_records (FILE mode context_scope).

Covers all 3 directives (observe/drop/passthrough), collision detection,
source resolution, empty observe, None namespace, and directive interactions.
"""

from copy import deepcopy

from agent_actions.prompt.context.scope_application import (
    apply_context_scope_for_records,
)

# ── Test data ──────────────────────────────────────────────────────────

RECORD = {
    "source_guid": "guid-1",
    "node_id": "node_123",
    "content": {
        "extract_qa": {"question": "What is X?", "answer": "Y", "confidence": 0.9},
        "validate": {"pass": True, "violations": [], "internal_token_count": 450},
    },
}

SOURCE_DATA = [
    {
        "source_guid": "guid-1",
        "content": {"page_content": "Doc text", "url": "http://1.com"},
    },
    {
        "source_guid": "guid-2",
        "content": {"page_content": "Other doc", "url": "http://2.com"},
    },
]


# ── All 3 directives ──────────────────────────────────────────────────


class TestAllDirectives:
    def test_drop_removes_field_from_namespace(self):
        """drop: [validate.internal_token_count] removes field from validate namespace."""
        scope = {
            "observe": ["extract_qa.question"],
            "drop": ["validate.internal_token_count"],
        }
        result, _ = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        validate = result[0]["content"]["validate"]
        assert "internal_token_count" not in validate
        assert validate["pass"] is True

    def test_passthrough_fields_preserved_in_namespaces(self):
        """Passthrough fields stay in namespaced content (FILE keeps ALL namespaces)."""
        scope = {
            "observe": ["extract_qa.question"],
            "passthrough": ["extract_qa.confidence"],
        }
        result, _ = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        assert result[0]["content"]["extract_qa"]["confidence"] == 0.9

    def test_observe_injects_flat_keys(self):
        """Observe refs inject flat keys at the top level of content."""
        scope = {"observe": ["extract_qa.question", "extract_qa.answer"]}
        result, _ = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        content = result[0]["content"]
        assert content["question"] == "What is X?"
        assert content["answer"] == "Y"

    def test_all_three_directives_combined(self):
        """observe + drop + passthrough all work together."""
        scope = {
            "observe": ["extract_qa.question", "source.url"],
            "drop": ["validate.internal_token_count"],
            "passthrough": ["extract_qa.confidence"],
        }
        result, _ = apply_context_scope_for_records(
            [deepcopy(RECORD)], scope, action_name="test", source_data=SOURCE_DATA
        )
        content = result[0]["content"]
        # Drop applied
        assert "internal_token_count" not in content["validate"]
        # Observe injected
        assert content["question"] == "What is X?"
        assert content["url"] == "http://1.com"
        # Passthrough preserved in namespace
        assert content["extract_qa"]["confidence"] == 0.9


# ── Guard visibility ──────────────────────────────────────────────────


class TestGuardVisibility:
    def test_all_namespaces_preserved(self):
        """Guards see ALL namespaces, not gated to observed ones only."""
        scope = {"observe": ["extract_qa.question"]}
        result, _ = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        content = result[0]["content"]
        assert "extract_qa" in content
        assert "validate" in content

    def test_metadata_fields_preserved_on_record(self):
        """source_guid, node_id, etc. preserved on the record envelope."""
        scope = {"observe": ["extract_qa.question"]}
        result, _ = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        assert result[0]["source_guid"] == "guid-1"
        assert result[0]["node_id"] == "node_123"


# ── Collision detection ───────────────────────────────────────────────


class TestCollisionDetection:
    def test_multi_wildcard_qualifies_all_keys(self):
        """Two wildcard namespaces with same field names -> keys qualified."""
        record = {
            "content": {
                "action_a": {"name": "Alice", "score": 10},
                "action_b": {"name": "Bob", "grade": "A"},
            },
        }
        scope = {"observe": ["action_a.*", "action_b.*"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["action_a.name"] == "Alice"
        assert content["action_b.name"] == "Bob"
        assert content["action_a.score"] == 10
        assert content["action_b.grade"] == "A"

    def test_specific_field_collision_qualifies(self):
        """Same bare field name from two namespaces -> qualified keys."""
        record = {
            "content": {
                "ns_a": {"id": "a1", "extra": "x"},
                "ns_b": {"id": "b1", "other": "y"},
            },
        }
        scope = {"observe": ["ns_a.id", "ns_b.id"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["ns_a.id"] == "a1"
        assert content["ns_b.id"] == "b1"

    def test_no_collision_uses_bare_keys(self):
        """Different field names across namespaces -> bare keys."""
        record = {
            "content": {
                "ns_a": {"name": "Alice"},
                "ns_b": {"score": 10},
            },
        }
        scope = {"observe": ["ns_a.name", "ns_b.score"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["name"] == "Alice"
        assert content["score"] == 10

    def test_single_wildcard_no_qualification(self):
        """Single wildcard namespace -> bare keys (no qualification needed)."""
        record = {"content": {"dep": {"a": 1, "b": 2}}}
        scope = {"observe": ["dep.*"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["a"] == 1
        assert content["b"] == 2


# ── Empty observe ─────────────────────────────────────────────────────


class TestEmptyObserve:
    def test_empty_scope_returns_records_unchanged(self):
        """No directives = records returned as-is (identity)."""
        records = [deepcopy(RECORD)]
        result, skipped = apply_context_scope_for_records(records, {}, action_name="test")
        assert result is records  # same list reference (no copy)
        assert skipped == []

    def test_empty_lists_returns_records_unchanged(self):
        """Explicit empty lists = records returned as-is."""
        records = [deepcopy(RECORD)]
        scope = {"observe": [], "drop": [], "passthrough": []}
        result, _ = apply_context_scope_for_records(records, scope, action_name="test")
        assert result is records

    def test_empty_records_list(self):
        """Empty input list returns empty output."""
        result, skipped = apply_context_scope_for_records(
            [], {"observe": ["x.y"]}, action_name="test"
        )
        assert result == []
        assert skipped == []


# ── Source resolution ─────────────────────────────────────────────────


class TestSourceResolution:
    def test_source_resolved_per_record_via_guid(self):
        """Each record gets its own source namespace via source_guid."""
        records = [
            {"source_guid": "guid-1", "content": {"dep": {"f": 1}}},
            {"source_guid": "guid-2", "content": {"dep": {"f": 2}}},
        ]
        scope = {"observe": ["source.url", "dep.f"]}
        result, _ = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=SOURCE_DATA
        )
        assert result[0]["content"]["url"] == "http://1.com"
        assert result[1]["content"]["url"] == "http://2.com"

    def test_source_guid_not_found_falls_back_to_first(self):
        """Unknown source_guid falls back to first source record."""
        records = [{"source_guid": "unknown", "content": {"dep": {"f": 1}}}]
        scope = {"observe": ["source.url", "dep.f"]}
        result, _ = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=SOURCE_DATA
        )
        assert result[0]["content"]["url"] == "http://1.com"

    def test_no_source_data_with_source_refs_skips_record(self):
        """Explicit source ref without source_data → record skipped (source namespace absent)."""
        records = [{"source_guid": "g1", "content": {"dep": {"f": 1}}}]
        scope = {"observe": ["source.url"]}
        enriched, skipped = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=None
        )
        assert len(enriched) == 0
        assert len(skipped) == 1
        assert skipped[0]["source_guid"] == "g1"

    def test_no_source_refs_skips_resolution(self):
        """If no directive references source, source_data is ignored."""
        records = [deepcopy(RECORD)]
        scope = {"observe": ["extract_qa.question"]}
        result, _ = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=SOURCE_DATA
        )
        # Source not injected since no source.* refs
        assert "url" not in result[0]["content"]


# ── None namespace (guard-skipped) ────────────────────────────────────


class TestNoneNamespace:
    def test_wildcard_on_none_namespace_graceful(self):
        """Wildcard on guard-skipped (None) namespace resolves to empty."""
        record = {
            "content": {
                "active": {"field": "value"},
                "skipped": None,
            },
        }
        scope = {"observe": ["skipped.*", "active.field"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["field"] == "value"
        assert "skipped" in content  # None namespace preserved for guards

    def test_explicit_ref_on_none_namespace_enriches_with_null_safe(self):
        """Explicit field ref on guard-skipped namespace resolves as None (null-safe)."""
        record = {"content": {"skipped": None}}
        scope = {"observe": ["skipped.field"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        # Record is enriched (not skipped) — null namespace preserved in content
        assert result[0]["content"]["skipped"] is None


# ── Drop + passthrough interaction ────────────────────────────────────


class TestDropPassthroughInteraction:
    def test_drop_wins_over_passthrough_on_same_field(self):
        """Drop on same field as passthrough removes it (drop is nuclear)."""
        record = {"content": {"dep": {"secret": "s", "public": "p"}}}
        scope = {
            "passthrough": ["dep.secret", "dep.public"],
            "drop": ["dep.secret"],
        }
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        assert "secret" not in result[0]["content"]["dep"]
        assert result[0]["content"]["dep"]["public"] == "p"

    def test_wildcard_drop_clears_namespace(self):
        """drop: [dep.*] clears all fields from the namespace."""
        record = {"content": {"dep": {"a": 1, "b": 2}, "other": {"c": 3}}}
        scope = {"observe": ["other.c"], "drop": ["dep.*"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        assert result[0]["content"]["dep"] == {}
        assert result[0]["content"]["other"]["c"] == 3

    def test_drop_does_not_leak_to_flat_keys(self):
        """Dropped fields must not appear as flat observed keys."""
        record = {"content": {"dep": {"secret": "s", "name": "n"}}}
        scope = {"observe": ["dep.*"], "drop": ["dep.secret"]}
        result, _ = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert "secret" not in {k for k in content if not isinstance(content[k], dict)}
        assert content["name"] == "n"


# ── Multiple records ──────────────────────────────────────────────────


class TestMultipleRecords:
    def test_each_record_processed_independently(self):
        """Each record in the list is processed independently."""
        records = [
            {"content": {"dep": {"field": "A"}}},
            {"content": {"dep": {"field": "B"}}},
        ]
        scope = {"observe": ["dep.field"]}
        result, _ = apply_context_scope_for_records(records, scope, action_name="test")
        assert result[0]["content"]["field"] == "A"
        assert result[1]["content"]["field"] == "B"

    def test_input_records_not_mutated(self):
        """Input records must not be mutated."""
        original = deepcopy(RECORD)
        records = [deepcopy(RECORD)]
        scope = {"drop": ["validate.internal_token_count"], "observe": ["extract_qa.*"]}
        apply_context_scope_for_records(records, scope, action_name="test")
        assert records[0]["content"] == original["content"]


# ── Observe field missing from present namespace ─────────────────────


class TestObserveFieldMissing:
    """When upstream ran but produced incomplete output, observe-referenced
    fields that are missing from a present (non-null) namespace should cause
    the record to be skipped — not silently filled with None."""

    def test_missing_observe_field_skips_record(self):
        """Record with present namespace but missing observe field goes to skipped."""
        record = {"source_guid": "g1", "content": {"dep": {"other": "x"}}}
        scope = {"observe": ["dep.nonexistent"]}
        enriched, skipped = apply_context_scope_for_records([record], scope, action_name="test")
        assert len(enriched) == 0
        assert len(skipped) == 1
        assert skipped[0]["source_guid"] == "g1"
        assert skipped[0]["reason"] == "observe_field_missing"

    def test_passthrough_missing_field_still_enriches(self):
        """Passthrough of missing field from present namespace still enriches (None-safe)."""
        record = {"source_guid": "g1", "content": {"dep": {"actual": "value"}}}
        scope = {"passthrough": ["dep.nonexistent"]}
        enriched, skipped = apply_context_scope_for_records([record], scope, action_name="test")
        assert len(enriched) == 1
        assert len(skipped) == 0

    def test_mixed_records_some_skip_some_enrich(self):
        """Batch with good and bad records: good enriched, bad skipped."""
        good = {"source_guid": "g1", "content": {"dep": {"field": "ok"}}}
        bad = {"source_guid": "g2", "content": {"dep": {"other": "x"}}}
        scope = {"observe": ["dep.field"]}
        enriched, skipped = apply_context_scope_for_records([good, bad], scope, action_name="test")
        assert len(enriched) == 1
        assert enriched[0]["source_guid"] == "g1"
        assert len(skipped) == 1
        assert skipped[0]["source_guid"] == "g2"

    def test_summary_warning_logged(self):
        """One summary WARNING for N skipped records, not N individual warnings."""
        from unittest.mock import patch

        records = [{"source_guid": f"g{i}", "content": {"dep": {"other": "x"}}} for i in range(5)]
        scope = {"observe": ["dep.missing_field"]}
        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            enriched, skipped = apply_context_scope_for_records(
                records, scope, action_name="test_action"
            )
        assert len(skipped) == 5
        # Per-record logs are DEBUG, not WARNING
        for call in mock_logger.warning.call_args_list:
            assert "Skipping record" not in str(call)
        # One summary WARNING
        assert mock_logger.warning.call_count == 1
        summary_msg = mock_logger.warning.call_args[0][0] % mock_logger.warning.call_args[0][1:]
        assert "5 of 5 records skipped" in summary_msg

    def test_null_namespace_still_enriches(self):
        """Null namespace (guard-skipped upstream) still enriches — not skipped."""
        record = {"source_guid": "g1", "content": {"skipped": None}}
        scope = {"observe": ["skipped.field"]}
        enriched, skipped = apply_context_scope_for_records([record], scope, action_name="test")
        assert len(enriched) == 1
        assert len(skipped) == 0
