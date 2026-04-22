"""Tests for file-mode observe filtering helpers.

Covers cross-namespace resolution, collision handling, graceful degradation,
and backward compatibility with the old _apply_observe_filter behaviour.
"""

from unittest.mock import patch

from agent_actions.prompt.context.scope_file_mode import (
    _load_file_mode_cross_namespace_data,
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
# _load_file_mode_cross_namespace_data
# -----------------------------------------------------------------------


class TestLoadFileModeCrossNamespaceData:
    """Unit tests for cross-namespace data loading."""

    def test_source_namespace_from_source_record(self):
        """source.* refs should be loaded from source_record."""
        source_record = {"content": {"url": "https://example.com", "title": "Example"}}
        result = _load_file_mode_cross_namespace_data(
            needed_ns={"source"},
            record={"source_guid": "sg-1", "content": {"question": "Q?"}},
            agent_name="test",
            source_record=source_record,
        )
        assert "source" in result
        assert result["source"]["url"] == "https://example.com"

    def test_source_namespace_missing_source_record(self):
        """source refs with no source_record should warn but not crash."""
        result = _load_file_mode_cross_namespace_data(
            needed_ns={"source"},
            record={"content": {"q": 1}},
            agent_name="test",
            source_record=None,
        )
        # Empty — graceful degradation
        assert "source" not in result

    def test_input_source_refs_not_loaded(self):
        """Caller excludes input sources from needed_ns; helper gets empty set."""
        result = _load_file_mode_cross_namespace_data(
            needed_ns=set(),
            record={"content": {"question": "Q?"}},
            agent_name="test",
        )
        assert result == {}

    def test_context_dep_loaded_via_historical(self):
        """Context dep namespace should be loaded via _load_historical_node."""
        record = {
            "source_guid": "sg-1",
            "lineage": ["classify_node"],
            "content": {"question": "Q?"},
        }
        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"category": "science", "confidence": 0.9},
        ) as mock_load:
            result = _load_file_mode_cross_namespace_data(
                needed_ns={"classify"},
                record=record,
                agent_name="test",
                agent_indices={"classify": 0, "test": 1},
                file_path="/tmp/test.json",
            )
        assert result["classify"]["category"] == "science"
        mock_load.assert_called_once()

    def test_context_dep_not_in_agent_indices_warns(self):
        """Namespace not in agent_indices should be skipped with warning."""
        result = _load_file_mode_cross_namespace_data(
            needed_ns={"unknown_action"},
            record={"source_guid": "sg-1", "content": {}},
            agent_name="test",
            agent_indices={"test": 0},
            file_path="/tmp/test.json",
        )
        assert result == {}

    def test_empty_needed_ns(self):
        """Empty needed_ns should return empty dict immediately."""
        result = _load_file_mode_cross_namespace_data(
            needed_ns=set(),
            record={"content": {"q": 1}},
            agent_name="test",
        )
        assert result == {}


# -----------------------------------------------------------------------
# apply_observe_for_file_mode (integration)
# -----------------------------------------------------------------------


class TestApplyObserveForFileMode:
    """Integration tests for the main file-mode observe filter."""

    def test_cross_namespace_resolution(self):
        """observe: [upstream.question, source.url] enriches records with cross-ns data."""
        data = [
            {"source_guid": "sg-1", "content": {"question": "What is X?", "answer": "Y"}},
            {"source_guid": "sg-2", "content": {"question": "What is Z?", "answer": "W"}},
        ]
        source_data = [
            {"source_guid": "sg-1", "content": {"url": "https://one.com", "title": "One"}},
            {"source_guid": "sg-2", "content": {"url": "https://two.com", "title": "Two"}},
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question", "source.url"]},
        }
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            source_data=source_data,
        )
        assert len(result) == 2
        # Full records returned; cross-namespace url injected into content
        assert result[0]["content"]["question"] == "What is X?"
        assert result[0]["content"]["url"] == "https://one.com"
        assert result[0]["source_guid"] == "sg-1"
        assert result[1]["content"]["question"] == "What is Z?"
        assert result[1]["content"]["url"] == "https://two.com"
        assert result[1]["source_guid"] == "sg-2"

    def test_multi_dep_collision_distinct_values(self):
        """dep_a.title and dep_b.title from different namespaces get distinct values."""
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["dep_a_node"],
                "content": {"title": "Title from A", "body": "Body A"},
            }
        ]
        config = {
            "dependencies": "dep_a",
            "context_scope": {"observe": ["dep_a.title", "dep_b.title", "dep_a.body"]},
        }

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"title": "Title from B", "score": 42},
        ):
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="merge_action",
                agent_indices={"dep_a": 0, "dep_b": 1, "merge_action": 2},
                file_path="/tmp/test.json",
            )

        assert len(result) == 1
        # "title" collides: dep_a.title stays as original "title" in content (input source),
        # dep_b.title injected with qualified key from historical lookup
        assert result[0]["content"]["title"] == "Title from A"
        assert result[0]["content"]["dep_b.title"] == "Title from B"
        assert result[0]["content"]["body"] == "Body A"

    def test_context_source_loading(self):
        """Observe ref targeting an action NOT in dependencies loads via historical."""
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["classify_node"],
                "content": {"question": "Q?"},
            }
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {
                "observe": ["upstream.question", "classify.category"],
            },
        }

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"category": "science"},
        ):
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="review",
                agent_indices={"upstream": 0, "classify": 1, "review": 2},
                file_path="/tmp/test.json",
            )

        assert result[0]["content"]["question"] == "Q?"
        assert result[0]["content"]["category"] == "science"
        assert result[0]["source_guid"] == "sg-1"

    def test_single_upstream_preserves_full_records(self):
        """Single-upstream observe returns full records with all content preserved."""
        data = [
            {"content": {"question": "Q1", "answer": "A1", "extra": "kept"}},
            {"content": {"question": "Q2", "answer": "A2", "extra": "kept"}},
        ]
        config = {
            "context_scope": {"observe": ["upstream.question", "upstream.answer"]},
        }
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert len(result) == 2
        # NiFi enrichment: full records returned, all content fields preserved
        assert result[0]["content"]["question"] == "Q1"
        assert result[0]["content"]["answer"] == "A1"
        assert result[0]["content"]["extra"] == "kept"
        assert result[1]["content"]["question"] == "Q2"
        assert result[1]["content"]["answer"] == "A2"

    def test_graceful_degradation_unresolvable_namespace(self):
        """Unresolvable namespace warns and skips — doesn't crash."""
        data = [
            {
                "source_guid": "sg-1",
                "content": {"question": "Q?"},
            }
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {
                "observe": ["upstream.question", "nonexistent.field"],
            },
        }
        # No agent_indices for nonexistent → graceful skip
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            agent_indices={"upstream": 0, "review": 1},
            file_path="/tmp/test.json",
        )
        # Full record returned; upstream.question present in content
        assert result[0]["content"]["question"] == "Q?"
        assert result[0]["source_guid"] == "sg-1"

    def test_unresolved_non_input_ns_does_not_leak_record_field(self):
        """Non-input namespace field must NOT fall back to a same-named record field.

        Regression: without the ns-in-input_source_names guard, dep_b.score
        would silently copy the primary record's 'score' field and label it as
        dep_b's data — producing incorrect context.
        """
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["dep_a_node"],
                "content": {"question": "Q?", "score": 99},
            }
        ]
        config = {
            "dependencies": "dep_a",
            "context_scope": {
                "observe": ["dep_a.question", "dep_b.score"],
            },
        }
        # dep_b has no historical data (load returns None) — its field should
        # not be injected from cross-namespace. The record's own "score" field
        # is still in content (NiFi enrichment preserves all original fields).
        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value=None,
        ):
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="merge",
                agent_indices={"dep_a": 0, "dep_b": 1, "merge": 2},
                file_path="/tmp/test.json",
            )
        # dep_a.question resolved from record content
        assert result[0]["content"]["question"] == "Q?"
        # dep_b.score was not injected (no historical data)
        assert "dep_b.score" not in result[0]["content"]
        # The record's own "score" field is preserved (NiFi: no stripping)
        assert result[0]["content"]["score"] == 99

    def test_no_deps_with_agent_indices_skips_historical_load(self):
        """Without explicit deps, historical load must NOT shadow live record content.

        Regression: when input_source_names is built from content keys (heuristic),
        the namespace "upstream" is not in that set, so needed_ns incorrectly
        includes it and triggers a historical lookup.  If that lookup succeeds,
        the stale historical value takes priority over the current record,
        producing silently inconsistent output.
        """
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["upstream_node"],
                "content": {"question": "LIVE Q", "answer": "LIVE A"},
            }
        ]
        # No dependencies / depends_on — forces content-key heuristic.
        config = {
            "context_scope": {"observe": ["upstream.question", "upstream.answer"]},
        }

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"question": "STALE Q", "answer": "STALE A"},
        ) as mock_load:
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="review",
                agent_indices={"upstream": 0, "review": 1},
                file_path="/tmp/test.json",
            )
        # Historical load should NOT have been attempted.
        mock_load.assert_not_called()
        # Live record values must be used (full record returned).
        assert result[0]["content"]["question"] == "LIVE Q"
        assert result[0]["content"]["answer"] == "LIVE A"
        assert result[0]["source_guid"] == "sg-1"

    def test_source_ref_resolves_without_explicit_deps(self):
        """source.url must load from source_data even when no dependencies are declared.

        Regression: the has_reliable_ns gate blocked all cross-namespace loading
        when deps were absent, causing source.url to silently return an empty
        object despite source_data being available.
        """
        data = [{"content": {"question": "Q?"}}]
        source_data = [{"content": {"url": "https://example.com", "title": "Ex"}}]
        # No dependencies / depends_on — forces content-key heuristic.
        config = {
            "context_scope": {"observe": ["upstream.question", "source.url"]},
        }
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            source_data=source_data,
        )
        assert result[0]["content"]["question"] == "Q?"
        assert result[0]["content"]["url"] == "https://example.com"

    def test_no_observe_returns_data_as_is(self):
        data = [{"content": {"a": 1}}]
        result = apply_observe_for_file_mode(data=data, agent_config={}, agent_name="test")
        assert result is data

    def test_wildcard_returns_full_record_with_content(self):
        """Wildcard observe returns full records with all content preserved."""
        data = [{"content": {"a": 1, "b": 2}}]
        config = {"context_scope": {"observe": ["upstream.*"]}}
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        assert result[0]["content"] == {"a": 1, "b": 2}

    def test_non_dict_records_do_not_crash_heuristic(self):
        """Primitive entries (strings, ints) must not crash the content-key heuristic.

        Regression: without an isinstance check, data[0].get() raises
        AttributeError when the first element is a string or number.
        """
        data = ["just a string", "another string"]
        config = {"context_scope": {"observe": ["upstream.question"]}}
        # No dependencies → triggers heuristic fallback path.
        result = apply_observe_for_file_mode(data=data, agent_config=config, agent_name="test")
        # Non-dict items pass through unmodified.
        assert result == ["just a string", "another string"]

    def test_hitl_merge_back_unaffected(self):
        """No cross-namespace refs → fast path returns data as-is.
        Original is unmodified because nothing was injected.
        """
        original = [
            {"source_guid": "sg-1", "content": {"question": "Q?", "secret": "hidden"}},
        ]
        config = {"context_scope": {"observe": ["upstream.question"]}}
        filtered = apply_observe_for_file_mode(
            data=original, agent_config=config, agent_name="test"
        )
        assert filtered[0]["content"]["question"] == "Q?"
        assert filtered[0]["content"]["secret"] == "hidden"
        # No cross-namespace refs → fast path returns data directly
        assert filtered is original
        assert original[0]["content"]["secret"] == "hidden"

    def test_source_data_flat_format(self):
        """source_data in flat format (no content wrapper) should still work."""
        data = [{"content": {"question": "Q?"}}]
        source_data = [{"url": "https://example.com", "title": "Example"}]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question", "source.url"]},
        }
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="test",
            source_data=source_data,
        )
        assert result[0]["content"]["question"] == "Q?"
        assert result[0]["content"]["url"] == "https://example.com"

    def test_multi_source_guid_source_namespace(self):
        """Two records with different source_guid get different source.url values."""
        data = [
            {"source_guid": "sg-A", "content": {"question": "Q1"}},
            {"source_guid": "sg-B", "content": {"question": "Q2"}},
        ]
        source_data = [
            {"source_guid": "sg-A", "content": {"url": "https://a.com"}},
            {"source_guid": "sg-B", "content": {"url": "https://b.com"}},
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question", "source.url"]},
        }
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            source_data=source_data,
        )
        assert result[0]["content"]["question"] == "Q1"
        assert result[0]["content"]["url"] == "https://a.com"
        assert result[1]["content"]["question"] == "Q2"
        assert result[1]["content"]["url"] == "https://b.com"

    def test_multi_source_guid_context_dep(self):
        """Two records with different source_guid trigger separate historical loads."""
        data = [
            {"source_guid": "sg-A", "lineage": ["c_node"], "content": {"q": "Q1"}},
            {"source_guid": "sg-B", "lineage": ["c_node"], "content": {"q": "Q2"}},
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.q", "classify.category"]},
        }

        def fake_load(*, action_name, source_guid, **kw):
            return {"category": f"cat-{source_guid}"}

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            side_effect=fake_load,
        ) as mock_load:
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="review",
                agent_indices={"upstream": 0, "classify": 1, "review": 2},
                file_path="/tmp/test.json",
            )
        assert result[0]["content"]["q"] == "Q1"
        assert result[0]["content"]["category"] == "cat-sg-A"
        assert result[1]["content"]["q"] == "Q2"
        assert result[1]["content"]["category"] == "cat-sg-B"
        assert mock_load.call_count == 2

    def test_ancestry_cache_avoids_redundant_loads(self):
        """Two records with identical ancestry result in exactly one historical load."""
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["c_node"],
                "parent_target_id": "p1",
                "content": {"q": "Q1"},
            },
            {
                "source_guid": "sg-1",
                "lineage": ["c_node"],
                "parent_target_id": "p1",
                "content": {"q": "Q2"},
            },
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.q", "classify.category"]},
        }
        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"category": "science"},
        ) as mock_load:
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="review",
                agent_indices={"upstream": 0, "classify": 1, "review": 2},
                file_path="/tmp/test.json",
            )
        assert result[0]["content"]["category"] == "science"
        assert result[1]["content"]["category"] == "science"
        # Only one load — cache hit for the second record.
        mock_load.assert_called_once()

    def test_source_guid_fallback_to_first_source(self):
        """Record whose source_guid doesn't match any source record falls back to source_data[0]."""
        data = [
            {"source_guid": "sg-unknown", "content": {"q": "Q1"}},
        ]
        source_data = [
            {"source_guid": "sg-other", "content": {"url": "https://fallback.com"}},
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.q", "source.url"]},
        }
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            source_data=source_data,
        )
        assert result[0]["content"]["q"] == "Q1"
        assert result[0]["content"]["url"] == "https://fallback.com"
        assert result[0]["source_guid"] == "sg-unknown"

    def test_fan_in_non_primary_dep_loaded_historically(self):
        """In a fan-in flow, non-primary deps must be loaded via historical lookup."""
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["dep_a_node", "dep_b_node"],
                "content": {"question": "Q?"},
            }
        ]
        config = {
            # Fan-in: two different deps → first is primary input, second is context.
            "dependencies": ["dep_a", "dep_b"],
            "context_scope": {
                "observe": ["dep_a.question", "dep_b.score"],
            },
        }
        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"score": 42, "extra": "ignored"},
        ) as mock_load:
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="merge",
                agent_indices={"dep_a": 0, "dep_b": 1, "merge": 2},
                file_path="/tmp/test.json",
            )
        # dep_a.question from record content; dep_b.score injected from historical.
        assert result[0]["content"]["question"] == "Q?"
        assert result[0]["content"]["score"] == 42
        assert result[0]["source_guid"] == "sg-1"
        mock_load.assert_called_once()

    def test_ancestry_divergent_records_get_separate_lookups(self):
        """Records with same source_guid but different lineage get separate cache entries."""
        data = [
            {
                "source_guid": "sg-1",
                "lineage": ["branch_a"],
                "parent_target_id": "parent-a",
                "content": {"q": "Q1"},
            },
            {
                "source_guid": "sg-1",
                "lineage": ["branch_b"],
                "parent_target_id": "parent-b",
                "content": {"q": "Q2"},
            },
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.q", "classify.label"]},
        }

        call_count = [0]

        def fake_load(*, action_name, lineage, parent_target_id, **kw):
            call_count[0] += 1
            label = "label-A" if parent_target_id == "parent-a" else "label-B"
            return {"label": label}

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            side_effect=fake_load,
        ):
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="review",
                agent_indices={"upstream": 0, "classify": 1, "review": 2},
                file_path="/tmp/test.json",
            )
        assert result[0]["content"]["q"] == "Q1"
        assert result[0]["content"]["label"] == "label-A"
        assert result[1]["content"]["q"] == "Q2"
        assert result[1]["content"]["label"] == "label-B"
        # Two separate loads — different ancestry despite same source_guid.
        assert call_count[0] == 2


# -----------------------------------------------------------------------
# Version namespace detection and injection (version_consumption merge)
# -----------------------------------------------------------------------


class TestVersionNamespaceObserve:
    """Tests for version-correlated namespace resolution in FILE mode.

    When upstream actions use version_consumption with merge pattern,
    records contain nested dicts keyed by version action names. The
    observe filter must detect these and resolve fields from content
    directly — not via historical lookup (which fails for version keys).
    """

    def _make_merged_data(self, version_count=3):
        """Create version-correlated merged data as VersionOutputCorrelator produces."""
        content = {}
        for i in range(1, version_count + 1):
            content[f"gen_code_{i}"] = {
                "code": f"code_{i}",
                "language": f"lang_{i}",
            }
        return [
            {
                "source_guid": "sg-001",
                "node_id": "node-1",
                "content": content,
                "lineage": ["lineage-1"],
            }
        ]

    def test_wildcard_expansion_from_version_namespaces(self):
        """Wildcards on version namespaces expand to qualified keys from content."""
        data = self._make_merged_data(3)
        config = {
            "dependencies": ["gen_code_1", "gen_code_2", "gen_code_3"],
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "gen_code_3": 3,
            "aggregate": 4,
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
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
        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": ["gen_code_1.code", "gen_code_2.code"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "aggregate": 3,
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        content = result[0]["content"]
        # "code" collides across namespaces → qualified keys
        assert content["gen_code_1.code"] == "code_1"
        assert content["gen_code_2.code"] == "code_2"

    def test_version_ns_does_not_trigger_historical_lookup(self):
        """Version namespaces in content must NOT attempt historical lookup."""
        data = self._make_merged_data(2)
        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "aggregate": 3,
        }

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
        ) as mock_load:
            apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="aggregate",
                agent_indices=indices,
                file_path="/tmp/test.json",
            )

        # No historical loads — version data resolved from content directly.
        mock_load.assert_not_called()

    def test_version_ns_with_non_version_context_dep(self):
        """Version namespaces + non-version context dep: both resolve correctly."""
        data = [
            {
                "source_guid": "sg-1",
                "node_id": "node-1",
                "content": {
                    "gen_code_1": {"code": "code_1"},
                    "gen_code_2": {"code": "code_2"},
                },
                "lineage": ["lineage-1"],
            }
        ]
        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": [
                    "gen_code_1.code",
                    "gen_code_2.code",
                    "classify.category",
                ],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "classify": 3,
            "aggregate": 4,
        }

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value={"category": "science"},
        ) as mock_load:
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="aggregate",
                agent_indices=indices,
                file_path="/tmp/test.json",
            )

        content = result[0]["content"]
        # Version fields from content
        assert content["gen_code_1.code"] == "code_1"
        assert content["gen_code_2.code"] == "code_2"
        # Context dep from historical lookup
        assert content["category"] == "science"
        # Historical load only for classify, not version namespaces
        mock_load.assert_called_once()

    def test_version_ns_single_wildcard_no_qualification(self):
        """Single version namespace wildcard uses bare keys (no ns. prefix)."""
        data = [
            {
                "source_guid": "sg-1",
                "node_id": "node-1",
                "content": {
                    "gen_code_1": {"code": "code_1", "language": "python"},
                },
                "lineage": ["lineage-1"],
            }
        ]
        config = {
            "dependencies": ["gen_code_1"],
            "context_scope": {"observe": ["gen_code_1.*"]},
        }
        indices = {"source": 0, "gen_code_1": 1, "aggregate": 2}

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        content = result[0]["content"]
        # Single wildcard → bare keys (no qualification)
        assert content["code"] == "code_1"
        assert content["language"] == "python"

    def test_version_ns_multiple_records(self):
        """Version namespace resolution works across multiple records."""
        data = [
            {
                "source_guid": "sg-1",
                "node_id": "node-1",
                "content": {
                    "gen_code_1": {"code": "code_A1"},
                    "gen_code_2": {"code": "code_A2"},
                },
                "lineage": ["lineage-1"],
            },
            {
                "source_guid": "sg-2",
                "node_id": "node-2",
                "content": {
                    "gen_code_1": {"code": "code_B1"},
                    "gen_code_2": {"code": "code_B2"},
                },
                "lineage": ["lineage-2"],
            },
        ]
        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": ["gen_code_1.code", "gen_code_2.code"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "aggregate": 3,
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        # First record
        assert result[0]["content"]["gen_code_1.code"] == "code_A1"
        assert result[0]["content"]["gen_code_2.code"] == "code_A2"
        # Second record — different per-record content
        assert result[1]["content"]["gen_code_1.code"] == "code_B1"
        assert result[1]["content"]["gen_code_2.code"] == "code_B2"

    def test_version_ns_preserves_original_nested_dicts(self):
        """Original nested version namespace dicts are preserved in content."""
        data = self._make_merged_data(2)
        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "aggregate": 3,
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        content = result[0]["content"]
        # Original nested dicts are preserved alongside expanded keys
        assert isinstance(content["gen_code_1"], dict)
        assert content["gen_code_1"]["code"] == "code_1"
        # Expanded keys also present
        assert content["gen_code_1.code"] == "code_1"

    def test_version_ns_does_not_mutate_input_data(self):
        """Version namespace enrichment must not mutate caller's input data."""
        data = self._make_merged_data(2)
        original_content = dict(data[0]["content"])
        original_keys = set(original_content.keys())

        config = {
            "dependencies": ["gen_code_1", "gen_code_2"],
            "context_scope": {
                "observe": ["gen_code_1.*", "gen_code_2.*"],
            },
        }
        indices = {
            "source": 0,
            "gen_code_1": 1,
            "gen_code_2": 2,
            "aggregate": 3,
        }

        apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="aggregate",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        # Input data must not be mutated.
        assert set(data[0]["content"].keys()) == original_keys

    def test_empty_content_fallback(self):
        """Record with empty content {} falls back to item-level keys.

        Regression: data.get("content", data) returns {} when content
        exists but is empty, instead of falling back to the full item.
        """
        source_data = [{"source_guid": "sg-1", "content": {"url": "https://ex.com"}}]
        data = [
            {
                "source_guid": "sg-1",
                "node_id": "node-1",
                "content": {},
                "question": "Q?",
                "lineage": ["lineage-1"],
            }
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {
                "observe": ["source.url", "upstream.question"],
            },
        }
        indices = {"source": 0, "upstream": 1, "downstream": 2}

        with patch(
            "agent_actions.prompt.context.scope_file_mode._load_historical_node",
            return_value=None,
        ):
            result = apply_observe_for_file_mode(
                data=data,
                agent_config=config,
                agent_name="downstream",
                agent_indices=indices,
                file_path="/tmp/test.json",
                source_data=source_data,
            )

        content = result[0]["content"]
        # source.url from source_data
        assert content["url"] == "https://ex.com"
        # upstream.question from item-level fallback (content was empty)
        assert content["question"] == "Q?"
        # Metadata keys must NOT leak into enriched content
        assert "source_guid" not in content
        assert "lineage" not in content
        assert "node_id" not in content

    def test_non_version_input_source_not_treated_as_version_ns(self):
        """Non-version input source keys in content are NOT treated as version namespaces.

        Regression: only keys matching the _N pattern should be detected as
        version namespaces.  A regular namespace like "upstream" that happens
        to be a dict in content should NOT trigger version namespace injection.
        """
        data = [
            {
                "source_guid": "sg-1",
                "content": {"question": "Q?", "answer": "A!"},
            }
        ]
        config = {
            "dependencies": "upstream",
            "context_scope": {"observe": ["upstream.question"]},
        }
        indices = {"source": 0, "upstream": 1, "review": 2}

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=config,
            agent_name="review",
            agent_indices=indices,
            file_path="/tmp/test.json",
        )

        # Fast path should fire — no version namespaces detected.
        assert result is data
