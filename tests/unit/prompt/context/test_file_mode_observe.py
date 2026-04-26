"""Tests for file-mode observe filtering with namespaced content.

With the additive content model, each record's ``content`` is namespaced:
``{"action_a": {"field": "val"}, "action_b": {"field": "val"}}``.
Observe refs select fields from these namespaces — no storage lookup needed.
The only cross-record reference is ``source.*`` (resolved from source_data).
"""

from agent_actions.prompt.context.scope_file_mode import (
    _resolve_observe_refs,
    apply_observe_for_file_mode,
)

# -----------------------------------------------------------------------
# _resolve_observe_refs
# -----------------------------------------------------------------------


class TestResolveObserveRefs:
    """Unit tests for _resolve_observe_refs helper."""

    def test_simple_refs(self):
        refs = ["upstream.question", "upstream.answer"]
        result = _resolve_observe_refs(refs)
        assert result == [
            ("upstream", "question", "question"),
            ("upstream", "answer", "answer"),
        ]

    def test_collision_uses_qualified_keys(self):
        refs = ["dep_a.title", "dep_b.title", "dep_a.body"]
        result = _resolve_observe_refs(refs)
        assert result == [
            ("dep_a", "title", "dep_a.title"),
            ("dep_b", "title", "dep_b.title"),
            ("dep_a", "body", "body"),
        ]

    def test_wildcard_preserved(self):
        refs = ["upstream.*"]
        result = _resolve_observe_refs(refs)
        assert result == [("upstream", "*", "*")]

    def test_invalid_ref_skipped(self):
        refs = ["upstream.question", "bad_ref_no_dot", "upstream.answer"]
        result = _resolve_observe_refs(refs)
        assert len(result) == 2
        assert result[0] == ("upstream", "question", "question")
        assert result[1] == ("upstream", "answer", "answer")

    def test_empty_refs(self):
        assert _resolve_observe_refs([]) == []

    def test_cross_namespace_no_collision(self):
        """Refs from different namespaces with unique bare keys stay bare."""
        refs = ["upstream.question", "source.url"]
        result = _resolve_observe_refs(refs)
        assert result == [
            ("upstream", "question", "question"),
            ("source", "url", "url"),
        ]


# -----------------------------------------------------------------------
# apply_observe_for_file_mode — namespaced content
# -----------------------------------------------------------------------


class TestApplyObserveForFileMode:
    """Integration tests for file-mode observe with namespaced content."""

    def test_single_namespace_specific_fields(self):
        """observe: [extract.text] reads from content["extract"]["text"]."""
        data = [
            {
                "content": {
                    "extract": {"text": "article about physics", "source_url": "wiki.com"},
                }
            },
        ]
        config = {"context_scope": {"observe": ["extract.text"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="classify")
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
        config = {"context_scope": {"observe": ["extract.text", "classify.topic"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="summarize")
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
        config = {"context_scope": {"observe": ["extract.*"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="summarize")
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
        config = {"context_scope": {"observe": ["extract.*", "classify.*"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="summarize")
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
        config = {"context_scope": {"observe": ["extract.text", "source.url"]}}
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="classify",
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
        config = {"context_scope": {"observe": ["extract.text", "source.url"]}}
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="classify",
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
        config = {"context_scope": {"observe": ["extract.text", "source.url"]}}
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "Q"
        assert result[0]["content"]["url"] == "https://fallback.com"

    def test_source_data_flat_format(self):
        """source_data in flat format (no content wrapper) still works."""
        data = [{"content": {"extract": {"text": "Q"}}}]
        source_data = [{"url": "https://example.com", "title": "Example"}]
        config = {"context_scope": {"observe": ["extract.text", "source.url"]}}
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="classify",
            source_data=source_data,
        )
        assert result[0]["content"]["text"] == "Q"
        assert result[0]["content"]["url"] == "https://example.com"

    def test_missing_namespace_skipped_gracefully(self):
        """Observing a field from a skipped action's namespace is graceful — no crash."""
        data = [
            {
                "content": {
                    "generate": {"question": "Q?"},
                    "validate": {"pass": True},
                    # rewrite NOT present (guard-skipped)
                }
            },
        ]
        config = {"context_scope": {"observe": ["rewrite.output", "generate.question"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="review")
        assert result[0]["content"]["question"] == "Q?"
        # rewrite namespace absent — field not injected
        assert "output" not in result[0]["content"]

    def test_no_observe_returns_data_as_is(self):
        data = [{"content": {"extract": {"a": 1}}}]
        result = apply_observe_for_file_mode(data=data, agent_config={}, agent_name="test")
        assert result is data

    def test_non_dict_records_pass_through(self):
        """Primitive entries (strings, ints) pass through unmodified."""
        data = ["just a string", "another string"]
        config = {"context_scope": {"observe": ["upstream.question"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert result == ["just a string", "another string"]

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

        config = {"context_scope": {"observe": ["extract.*"]}}
        apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")

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
        config = {"context_scope": {"observe": ["dep_a.title", "dep_b.title", "dep_a.body"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="merge")
        # "title" collides → qualified keys
        assert result[0]["content"]["dep_a.title"] == "Title from A"
        assert result[0]["content"]["dep_b.title"] == "Title from B"
        assert result[0]["content"]["body"] == "Body A"

    def test_no_storage_lookup(self):
        """With namespaced content, no historical storage lookup is needed.

        All dependency data is on the record. This test verifies the function
        works without agent_indices or file_path.
        """
        data = [
            {
                "content": {
                    "extract": {"text": "hello"},
                    "classify": {"topic": "science"},
                }
            },
        ]
        config = {"context_scope": {"observe": ["extract.text", "classify.topic"]}}
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="summarize",
            agent_indices=None,
            file_path=None,
        )
        assert result[0]["content"]["text"] == "hello"
        assert result[0]["content"]["topic"] == "science"


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
        config = {
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"],
            },
        }
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
        content = result[0]["content"]
        # Multiple wildcard namespaces → qualified keys (ns.field)
        assert content["gen_code_1.code"] == "code_1"
        assert content["gen_code_1.language"] == "lang_1"
        assert content["gen_code_2.code"] == "code_2"
        assert content["gen_code_3.language"] == "lang_3"

    def test_specific_field_resolution_from_version_namespaces(self):
        """Specific field refs resolve from version namespace content."""
        data = self._make_merged_data(2)
        config = {
            "context_scope": {
                "observe": ["gen_code_1.code", "gen_code_2.code"],
            },
        }
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
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
        config = {"context_scope": {"observe": ["gen_code_1.*"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
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
        config = {
            "context_scope": {
                "observe": ["gen_code_1.code", "gen_code_2.code"],
            },
        }
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
        assert result[0]["content"]["gen_code_1.code"] == "code_A1"
        assert result[0]["content"]["gen_code_2.code"] == "code_A2"
        assert result[1]["content"]["gen_code_1.code"] == "code_B1"
        assert result[1]["content"]["gen_code_2.code"] == "code_B2"

    def test_preserves_original_nested_dicts(self):
        """Original nested version namespace dicts are preserved in content."""
        data = self._make_merged_data(2)
        config = {
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*"],
            },
        }
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
        content = result[0]["content"]
        # Original nested dicts preserved alongside expanded keys
        assert isinstance(content["gen_code_1"], dict)
        assert content["gen_code_1"]["code"] == "code_1"
        assert content["gen_code_1.code"] == "code_1"

    def test_does_not_mutate_input(self):
        """Version namespace enrichment must not mutate caller's input data."""
        data = self._make_merged_data(2)
        original_keys = set(data[0]["content"].keys())

        config = {
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*"],
            },
        }
        apply_observe_for_file_mode(data=data, agent_config=config, agent_name="aggregate")
        assert set(data[0]["content"].keys()) == original_keys


# -----------------------------------------------------------------------
# Edge cases and regressions
# -----------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for file-mode observe."""

    def test_empty_content_record(self):
        """Record with empty content {} — no crash, no fields extracted."""
        data = [{"content": {}}]
        config = {"context_scope": {"observe": ["extract.text"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert "text" not in result[0]["content"]

    def test_no_content_key(self):
        """Record without content key — no crash."""
        data = [{"source_guid": "sg-1"}]
        config = {"context_scope": {"observe": ["extract.text"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert result[0]["content"] == {}

    def test_namespace_is_not_dict(self):
        """Namespace value is a string, not dict — treated as empty."""
        data = [{"content": {"extract": "not_a_dict"}}]
        config = {"context_scope": {"observe": ["extract.text"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert "text" not in result[0]["content"]
