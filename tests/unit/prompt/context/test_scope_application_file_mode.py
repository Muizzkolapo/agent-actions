"""Tests for apply_context_scope_for_records (FILE mode context_scope).

Covers all 3 directives (observe/drop/passthrough), collision detection,
source resolution, empty observe, None namespace, and directive interactions.
"""

from copy import deepcopy

import pytest

from agent_actions.errors import ConfigurationError
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
        result = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        validate = result[0]["content"]["validate"]
        assert "internal_token_count" not in validate
        assert validate["pass"] is True

    def test_passthrough_fields_preserved_in_namespaces(self):
        """Passthrough fields stay in namespaced content (FILE keeps ALL namespaces)."""
        scope = {
            "observe": ["extract_qa.question"],
            "passthrough": ["extract_qa.confidence"],
        }
        result = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        assert result[0]["content"]["extract_qa"]["confidence"] == 0.9

    def test_observe_injects_flat_keys(self):
        """Observe refs inject flat keys at the top level of content."""
        scope = {"observe": ["extract_qa.question", "extract_qa.answer"]}
        result = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
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
        result = apply_context_scope_for_records(
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
        result = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
        content = result[0]["content"]
        assert "extract_qa" in content
        assert "validate" in content

    def test_metadata_fields_preserved_on_record(self):
        """source_guid, node_id, etc. preserved on the record envelope."""
        scope = {"observe": ["extract_qa.question"]}
        result = apply_context_scope_for_records([deepcopy(RECORD)], scope, action_name="test")
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
        result = apply_context_scope_for_records([record], scope, action_name="test")
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
        result = apply_context_scope_for_records([record], scope, action_name="test")
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
        result = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["name"] == "Alice"
        assert content["score"] == 10

    def test_single_wildcard_no_qualification(self):
        """Single wildcard namespace -> bare keys (no qualification needed)."""
        record = {"content": {"dep": {"a": 1, "b": 2}}}
        scope = {"observe": ["dep.*"]}
        result = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["a"] == 1
        assert content["b"] == 2


# ── Empty observe ─────────────────────────────────────────────────────


class TestEmptyObserve:
    def test_empty_scope_returns_records_unchanged(self):
        """No directives = records returned as-is (identity)."""
        records = [deepcopy(RECORD)]
        result = apply_context_scope_for_records(records, {}, action_name="test")
        assert result is records  # same list reference (no copy)

    def test_empty_lists_returns_records_unchanged(self):
        """Explicit empty lists = records returned as-is."""
        records = [deepcopy(RECORD)]
        scope = {"observe": [], "drop": [], "passthrough": []}
        result = apply_context_scope_for_records(records, scope, action_name="test")
        assert result is records

    def test_empty_records_list(self):
        """Empty input list returns empty output."""
        result = apply_context_scope_for_records([], {"observe": ["x.y"]}, action_name="test")
        assert result == []


# ── Source resolution ─────────────────────────────────────────────────


class TestSourceResolution:
    def test_source_resolved_per_record_via_guid(self):
        """Each record gets its own source namespace via source_guid."""
        records = [
            {"source_guid": "guid-1", "content": {"dep": {"f": 1}}},
            {"source_guid": "guid-2", "content": {"dep": {"f": 2}}},
        ]
        scope = {"observe": ["source.url", "dep.f"]}
        result = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=SOURCE_DATA
        )
        assert result[0]["content"]["url"] == "http://1.com"
        assert result[1]["content"]["url"] == "http://2.com"

    def test_source_guid_not_found_falls_back_to_first(self):
        """Unknown source_guid falls back to first source record."""
        records = [{"source_guid": "unknown", "content": {"dep": {"f": 1}}}]
        scope = {"observe": ["source.url", "dep.f"]}
        result = apply_context_scope_for_records(
            records, scope, action_name="test", source_data=SOURCE_DATA
        )
        assert result[0]["content"]["url"] == "http://1.com"

    def test_no_source_data_with_source_refs_raises(self):
        """Explicit source ref without source_data raises ConfigurationError."""
        records = [{"content": {"dep": {"f": 1}}}]
        scope = {"observe": ["source.url"]}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope_for_records(records, scope, action_name="test", source_data=None)

    def test_no_source_refs_skips_resolution(self):
        """If no directive references source, source_data is ignored."""
        records = [deepcopy(RECORD)]
        scope = {"observe": ["extract_qa.question"]}
        result = apply_context_scope_for_records(
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
        result = apply_context_scope_for_records([record], scope, action_name="test")
        content = result[0]["content"]
        assert content["field"] == "value"
        assert "skipped" in content  # None namespace preserved for guards

    def test_explicit_ref_on_none_namespace_raises(self):
        """Explicit field ref on guard-skipped namespace raises ConfigurationError."""
        record = {"content": {"skipped": None}}
        scope = {"observe": ["skipped.field"]}
        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope_for_records([record], scope, action_name="test")


# ── Drop + passthrough interaction ────────────────────────────────────


class TestDropPassthroughInteraction:
    def test_drop_wins_over_passthrough_on_same_field(self):
        """Drop on same field as passthrough removes it (drop is nuclear)."""
        record = {"content": {"dep": {"secret": "s", "public": "p"}}}
        scope = {
            "passthrough": ["dep.secret", "dep.public"],
            "drop": ["dep.secret"],
        }
        result = apply_context_scope_for_records([record], scope, action_name="test")
        assert "secret" not in result[0]["content"]["dep"]
        assert result[0]["content"]["dep"]["public"] == "p"

    def test_wildcard_drop_clears_namespace(self):
        """drop: [dep.*] clears all fields from the namespace."""
        record = {"content": {"dep": {"a": 1, "b": 2}, "other": {"c": 3}}}
        scope = {"observe": ["other.c"], "drop": ["dep.*"]}
        result = apply_context_scope_for_records([record], scope, action_name="test")
        assert result[0]["content"]["dep"] == {}
        assert result[0]["content"]["other"]["c"] == 3

    def test_drop_does_not_leak_to_flat_keys(self):
        """Dropped fields must not appear as flat observed keys."""
        record = {"content": {"dep": {"secret": "s", "name": "n"}}}
        scope = {"observe": ["dep.*"], "drop": ["dep.secret"]}
        result = apply_context_scope_for_records([record], scope, action_name="test")
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
        result = apply_context_scope_for_records(records, scope, action_name="test")
        assert result[0]["content"]["field"] == "A"
        assert result[1]["content"]["field"] == "B"

    def test_input_records_not_mutated(self):
        """Input records must not be mutated."""
        original = deepcopy(RECORD)
        records = [deepcopy(RECORD)]
        scope = {"drop": ["validate.internal_token_count"], "observe": ["extract_qa.*"]}
        apply_context_scope_for_records(records, scope, action_name="test")
        assert records[0]["content"] == original["content"]
