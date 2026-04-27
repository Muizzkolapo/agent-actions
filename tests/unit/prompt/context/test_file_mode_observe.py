"""Tests for file-mode observe filtering with namespaced content.

With the additive content model, each record's ``content`` is namespaced:
``{"action_a": {"field": "val"}, "action_b": {"field": "val"}}``.
Observe refs select fields from these namespaces — no storage lookup needed.
The only cross-record reference is ``source.*`` (resolved from source_data).
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import (
    _resolve_observe_refs_for_flat_keys,
    apply_context_scope_for_records,
)

# -----------------------------------------------------------------------
# _resolve_observe_refs_for_flat_keys
# -----------------------------------------------------------------------


class TestResolveObserveRefsForFlatKeys:
    """Unit tests for _resolve_observe_refs_for_flat_keys helper."""

    def test_simple_refs(self):
        refs = ["upstream.question", "upstream.answer"]
        result, qualify = _resolve_observe_refs_for_flat_keys(refs)
        assert result == [
            ("upstream", "question", "question"),
            ("upstream", "answer", "answer"),
        ]
        assert qualify is False

    def test_collision_uses_qualified_keys(self):
        refs = ["dep_a.title", "dep_b.title", "dep_a.body"]
        result, qualify = _resolve_observe_refs_for_flat_keys(refs)
        assert result == [
            ("dep_a", "title", "dep_a.title"),
            ("dep_b", "title", "dep_b.title"),
            ("dep_a", "body", "body"),
        ]
        assert qualify is False

    def test_wildcard_preserved(self):
        refs = ["upstream.*"]
        result, qualify = _resolve_observe_refs_for_flat_keys(refs)
        assert result == [("upstream", "*", "*")]
        assert qualify is False

    def test_invalid_ref_skipped(self):
        refs = ["upstream.question", "bad_ref_no_dot", "upstream.answer"]
        result, _ = _resolve_observe_refs_for_flat_keys(refs)
        assert len(result) == 2
        assert result[0] == ("upstream", "question", "question")
        assert result[1] == ("upstream", "answer", "answer")

    def test_empty_refs(self):
        result, qualify = _resolve_observe_refs_for_flat_keys([])
        assert result == []
        assert qualify is False

    def test_cross_namespace_no_collision(self):
        """Refs from different namespaces with unique bare keys stay bare."""
        refs = ["upstream.question", "source.url"]
        result, _ = _resolve_observe_refs_for_flat_keys(refs)
        assert result == [
            ("upstream", "question", "question"),
            ("source", "url", "url"),
        ]

    def test_multiple_wildcards_qualify(self):
        """Multiple wildcard namespaces set qualify_wildcards to True."""
        refs = ["dep_a.*", "dep_b.*"]
        _, qualify = _resolve_observe_refs_for_flat_keys(refs)
        assert qualify is True


# -----------------------------------------------------------------------
# apply_context_scope_for_records — namespaced content
# -----------------------------------------------------------------------


class TestApplyContextScopeForRecords:
    """Integration tests for file-mode context_scope with namespaced content."""

    def test_single_namespace_specific_fields(self):
        """observe: [extract.text] reads from content["extract"]["text"]."""
        data = [
            {
                "content": {
                    "extract": {"text": "article about physics", "source_url": "wiki.com"},
                }
            },
        ]
        context_scope = {"observe": ["extract.text"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="classify"
        )
        assert result[0]["content"]["text"] == "article about physics"
        # Original namespace preserved
        assert result[0]["content"]["extract"]["text"] == "article about physics"

    def test_multi_namespace_observe(self):
        """observe: [extract.text, classify.topic] reads from two namespaces."""
        data = [
            {
                "content": {
                    "extract": {"text": "physics article", "source_url": "wiki.com"},
                    "classify": {"topic": "science", "confidence": 0.95},
                }
            },
        ]
        context_scope = {"observe": ["extract.text", "classify.topic"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="summarize"
        )
        assert result[0]["content"]["text"] == "physics article"
        assert result[0]["content"]["topic"] == "science"

    def test_wildcard_observe_single_namespace(self):
        """observe: [extract.*] returns all fields from extract namespace."""
        data = [
            {
                "content": {
                    "extract": {"text": "hello", "source_url": "example.com"},
                    "classify": {"topic": "test"},
                }
            },
        ]
        context_scope = {"observe": ["extract.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="summarize"
        )
        assert result[0]["content"]["text"] == "hello"
        assert result[0]["content"]["source_url"] == "example.com"

    def test_wildcard_multiple_namespaces_qualify_keys(self):
        """Multiple wildcard namespaces produce qualified keys to avoid collisions."""
        data = [
            {
                "content": {
                    "extract": {"text": "hello", "source_url": "ex.com"},
                    "classify": {"topic": "science", "confidence": 0.9},
                }
            },
        ]
        context_scope = {"observe": ["extract.*", "classify.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="summarize"
        )
        # Qualified keys because multiple wildcards
        assert result[0]["content"]["extract.text"] == "hello"
        assert result[0]["content"]["classify.topic"] == "science"

    def test_source_namespace_from_source_data(self):
        """source.url resolves from source_data, not from record content."""
        data = [
            {
                "source_guid": "sg-1",
                "content": {
                    "extract": {"text": "article"},
                },
            },
        ]
        source_data = [
            {"source_guid": "sg-1", "content": {"url": "https://example.com", "title": "Ex"}},
        ]
        context_scope = {"observe": ["extract.text", "source.url"]}
        result = apply_context_scope_for_records(
            records=data,
            context_scope=context_scope,
            action_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "article"
        assert result[0]["content"]["url"] == "https://example.com"

    def test_source_namespace_multi_guid(self):
        """Two records with different source_guid get different source.url values."""
        data = [
            {"source_guid": "sg-A", "content": {"extract": {"text": "Q1"}}},
            {"source_guid": "sg-B", "content": {"extract": {"text": "Q2"}}},
        ]
        source_data = [
            {"source_guid": "sg-A", "content": {"url": "https://a.com"}},
            {"source_guid": "sg-B", "content": {"url": "https://b.com"}},
        ]
        context_scope = {"observe": ["extract.text", "source.url"]}
        result = apply_context_scope_for_records(
            records=data,
            context_scope=context_scope,
            action_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "Q1"
        assert result[0]["content"]["url"] == "https://a.com"
        assert result[1]["content"]["text"] == "Q2"
        assert result[1]["content"]["url"] == "https://b.com"

    def test_source_guid_fallback_to_first_source(self):
        """Record whose source_guid doesn't match falls back to source_data[0]."""
        data = [
            {"source_guid": "sg-unknown", "content": {"extract": {"text": "Q"}}},
        ]
        source_data = [
            {"source_guid": "sg-other", "content": {"url": "https://fallback.com"}},
        ]
        context_scope = {"observe": ["extract.text", "source.url"]}
        result = apply_context_scope_for_records(
            records=data,
            context_scope=context_scope,
            action_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "Q"
        assert result[0]["content"]["url"] == "https://fallback.com"

    def test_source_data_flat_format(self):
        """source_data in flat format (no content wrapper) still works."""
        data = [{"content": {"extract": {"text": "Q"}}}]
        source_data = [{"url": "https://example.com", "title": "Example"}]
        context_scope = {"observe": ["extract.text", "source.url"]}
        result = apply_context_scope_for_records(
            records=data,
            context_scope=context_scope,
            action_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "Q"
        assert result[0]["content"]["url"] == "https://example.com"

    def test_explicit_ref_to_missing_namespace_raises(self):
        """Explicit ref to absent namespace raises ConfigurationError (unified behavior)."""
        data = [
            {
                "content": {
                    "generate": {"question": "Q?"},
                    "validate": {"pass": True},
                }
            },
        ]
        context_scope = {"observe": ["rewrite.output", "generate.question"]}
        with pytest.raises(ConfigurationError):
            apply_context_scope_for_records(
                records=data, context_scope=context_scope, action_name="review"
            )

    def test_wildcard_on_missing_namespace_graceful(self):
        """Wildcard on absent namespace is graceful — no crash, no fields injected."""
        data = [
            {
                "content": {
                    "generate": {"question": "Q?"},
                    "validate": {"pass": True},
                }
            },
        ]
        context_scope = {"observe": ["rewrite.*", "generate.question"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="review"
        )
        assert result[0]["content"]["question"] == "Q?"
        # rewrite namespace absent — no fields injected
        assert "output" not in result[0]["content"]

    def test_no_observe_returns_data_as_is(self):
        data = [{"content": {"extract": {"a": 1}}}]
        result = apply_context_scope_for_records(records=data, context_scope={}, action_name="test")
        assert result is data

    def test_no_mutation_of_input_data(self):
        """Observe enrichment must not mutate the caller's input data."""
        data = [
            {
                "content": {
                    "extract": {"text": "hello", "url": "ex.com"},
                }
            },
        ]
        original_content = dict(data[0]["content"])
        original_keys = set(original_content.keys())

        context_scope = {"observe": ["extract.*"]}
        apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )

        # Input data must not be mutated
        assert set(data[0]["content"].keys()) == original_keys

    def test_collision_across_namespaces(self):
        """dep_a.title and dep_b.title get qualified keys to avoid collision."""
        data = [
            {
                "content": {
                    "dep_a": {"title": "Title from A", "body": "Body A"},
                    "dep_b": {"title": "Title from B", "score": 42},
                }
            },
        ]
        context_scope = {"observe": ["dep_a.title", "dep_b.title", "dep_a.body"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="merge"
        )
        # "title" collides → qualified keys
        assert result[0]["content"]["dep_a.title"] == "Title from A"
        assert result[0]["content"]["dep_b.title"] == "Title from B"
        assert result[0]["content"]["body"] == "Body A"

    def test_no_storage_lookup(self):
        """With namespaced content, no historical storage lookup is needed.

        All dependency data is on the record.
        """
        data = [
            {
                "content": {
                    "extract": {"text": "hello"},
                    "classify": {"topic": "science"},
                }
            },
        ]
        context_scope = {"observe": ["extract.text", "classify.topic"]}
        result = apply_context_scope_for_records(
            records=data,
            context_scope=context_scope,
            action_name="summarize",
        )
        assert result[0]["content"]["text"] == "hello"
        assert result[0]["content"]["topic"] == "science"

    def test_drop_removes_field_from_enriched_records(self):
        """drop directive removes fields from FILE mode enriched records."""
        data = [
            {
                "content": {
                    "extract": {"text": "hello", "secret": "s3cr3t"},
                }
            },
        ]
        context_scope = {"observe": ["extract.text"], "drop": ["extract.secret"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert result[0]["content"]["text"] == "hello"
        assert "secret" not in result[0]["content"].get("extract", {})

    def test_passthrough_with_observe(self):
        """passthrough directive coexists with observe — no crash, content preserved."""
        data = [
            {
                "content": {
                    "extract": {"text": "hello", "metadata": "keep_me"},
                }
            },
        ]
        context_scope = {
            "observe": ["extract.text"],
            "passthrough": ["extract.metadata"],
        }
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert result[0]["content"]["text"] == "hello"
        # Original namespace still present
        assert result[0]["content"]["extract"]["metadata"] == "keep_me"

    def test_drop_plus_observe_wildcard_interaction(self):
        """drop + observe wildcard: dropped field absent from enriched content."""
        data = [
            {
                "content": {
                    "action_a": {"field1": "keep", "secret": "remove_me"},
                }
            },
        ]
        context_scope = {"observe": ["action_a.*"], "drop": ["action_a.secret"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert result[0]["content"]["field1"] == "keep"
        assert "secret" not in result[0]["content"].get("action_a", {})
        # Flat key for secret not injected (drop applied before flat key injection)
        assert "secret" not in result[0]["content"]


# -----------------------------------------------------------------------
# Version namespace resolution (version_consumption merge)
# -----------------------------------------------------------------------


class TestVersionNamespaceObserve:
    """Tests for version namespaces in FILE mode with namespaced content.

    Version action outputs (e.g., gen_code_1, gen_code_2) are regular
    namespaces in the additive model — no special detection needed.
    """

    def _make_merged_data(self, version_count=3):
        """Create version-correlated merged data with namespaced content."""
        content = {}
        for i in range(1, version_count + 1):
            content[f"gen_code_{i}"] = {
                "code": f"code_{i}",
                "language": f"lang_{i}",
            }
        return [{"source_guid": "sg-001", "node_id": "node-1", "content": content}]

    def test_wildcard_expansion_from_version_namespaces(self):
        """Wildcards on version namespaces expand to qualified keys from content."""
        data = self._make_merged_data(3)
        context_scope = {
            "observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"],
        }
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        content = result[0]["content"]
        # Multiple wildcard namespaces → qualified keys (ns.field)
        assert content["gen_code_1.code"] == "code_1"
        assert content["gen_code_1.language"] == "lang_1"
        assert content["gen_code_2.code"] == "code_2"
        assert content["gen_code_3.language"] == "lang_3"

    def test_specific_field_resolution_from_version_namespaces(self):
        """Specific field refs resolve from version namespace content."""
        data = self._make_merged_data(2)
        context_scope = {
            "observe": ["gen_code_1.code", "gen_code_2.code"],
        }
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        content = result[0]["content"]
        # "code" collides across namespaces → qualified keys
        assert content["gen_code_1.code"] == "code_1"
        assert content["gen_code_2.code"] == "code_2"

    def test_single_wildcard_bare_keys(self):
        """Single version namespace wildcard uses bare keys (no ns. prefix)."""
        data = [
            {
                "content": {
                    "gen_code_1": {"code": "code_1", "language": "python"},
                }
            },
        ]
        context_scope = {"observe": ["gen_code_1.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        content = result[0]["content"]
        assert content["code"] == "code_1"
        assert content["language"] == "python"

    def test_version_ns_multiple_records(self):
        """Version namespace resolution works across multiple records."""
        data = [
            {
                "content": {
                    "gen_code_1": {"code": "code_A1"},
                    "gen_code_2": {"code": "code_A2"},
                }
            },
            {
                "content": {
                    "gen_code_1": {"code": "code_B1"},
                    "gen_code_2": {"code": "code_B2"},
                }
            },
        ]
        context_scope = {
            "observe": ["gen_code_1.code", "gen_code_2.code"],
        }
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        assert result[0]["content"]["gen_code_1.code"] == "code_A1"
        assert result[0]["content"]["gen_code_2.code"] == "code_A2"
        assert result[1]["content"]["gen_code_1.code"] == "code_B1"
        assert result[1]["content"]["gen_code_2.code"] == "code_B2"

    def test_preserves_original_nested_dicts(self):
        """Original nested version namespace dicts are preserved in content."""
        data = self._make_merged_data(2)
        context_scope = {
            "observe": ["gen_code_1.*", "gen_code_2.*"],
        }
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        content = result[0]["content"]
        # Original nested dicts preserved alongside expanded keys
        assert isinstance(content["gen_code_1"], dict)
        assert content["gen_code_1"]["code"] == "code_1"
        assert content["gen_code_1.code"] == "code_1"

    def test_does_not_mutate_input(self):
        """Version namespace enrichment must not mutate caller's input data."""
        data = self._make_merged_data(2)
        original_keys = set(data[0]["content"].keys())

        context_scope = {
            "observe": ["gen_code_1.*", "gen_code_2.*"],
        }
        apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="aggregate"
        )
        assert set(data[0]["content"].keys()) == original_keys


# -----------------------------------------------------------------------
# Edge cases and regressions
# -----------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for file-mode context_scope."""

    def test_empty_content_explicit_ref_raises(self):
        """Record with empty content {} — explicit ref raises ConfigurationError."""
        data = [{"content": {}}]
        context_scope = {"observe": ["extract.text"]}
        with pytest.raises(ConfigurationError):
            apply_context_scope_for_records(
                records=data, context_scope=context_scope, action_name="test"
            )

    def test_empty_content_wildcard_graceful(self):
        """Record with empty content {} — wildcard is graceful, no fields extracted."""
        data = [{"content": {}}]
        context_scope = {"observe": ["extract.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert result[0]["content"] == {}

    def test_no_content_key_explicit_ref_raises(self):
        """Record without content key — explicit ref raises ConfigurationError."""
        data = [{"source_guid": "sg-1"}]
        context_scope = {"observe": ["extract.text"]}
        with pytest.raises(ConfigurationError):
            apply_context_scope_for_records(
                records=data, context_scope=context_scope, action_name="test"
            )

    def test_no_content_key_wildcard_graceful(self):
        """Record without content key — wildcard is graceful."""
        data = [{"source_guid": "sg-1"}]
        context_scope = {"observe": ["extract.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert result[0]["content"] == {}

    def test_namespace_is_not_dict_explicit_ref_raises(self):
        """Namespace value is not a dict — explicit ref raises ConfigurationError."""
        data = [{"content": {"extract": "not_a_dict"}}]
        context_scope = {"observe": ["extract.text"]}
        with pytest.raises(ConfigurationError):
            apply_context_scope_for_records(
                records=data, context_scope=context_scope, action_name="test"
            )

    def test_namespace_is_not_dict_wildcard_graceful(self):
        """Namespace value is not a dict — wildcard is graceful."""
        data = [{"content": {"extract": "not_a_dict"}}]
        context_scope = {"observe": ["extract.*"]}
        result = apply_context_scope_for_records(
            records=data, context_scope=context_scope, action_name="test"
        )
        assert "text" not in result[0]["content"]
