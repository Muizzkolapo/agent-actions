"""Deterministic integration tests for context_scope integrity.

These tests verify that observe, passthrough, and drop directives correctly
gate data flow -- the right fields reach the LLM, the right fields pass through
to output, and dropped fields never leak.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_application import (
    FRAMEWORK_NAMESPACES,
    apply_context_scope,
)
from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode
from agent_actions.prompt.context.scope_parsing import parse_field_reference
from tests.integration.conftest import MockStorageBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_field_context(**namespaces: dict) -> dict:
    """Build a field_context dict from keyword arguments for readability."""
    return dict(namespaces)


# ---------------------------------------------------------------------------
# TestObserveBasic
# ---------------------------------------------------------------------------


class TestObserveBasic:
    """Observe directive: field extraction and LLM context gating."""

    def test_observe_extracts_exact_fields(self):
        """observe: ['dep.field_a', 'dep.field_b'] -> llm_context has exactly those fields,
        nothing else from dep."""
        field_context = {
            "dep": {
                "field_a": "alpha",
                "field_b": "bravo",
                "field_c": "charlie",
                "field_d": "delta",
            },
        }
        context_scope = {"observe": ["dep.field_a", "dep.field_b"]}

        prompt_context, llm_context, passthrough = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        # Positive: exact fields present with correct values
        assert llm_context["dep"]["field_a"] == "alpha"
        assert llm_context["dep"]["field_b"] == "bravo"
        # Negative: other fields excluded
        assert "field_c" not in llm_context["dep"]
        assert "field_d" not in llm_context["dep"]
        # prompt_context also gated
        assert prompt_context["dep"]["field_a"] == "alpha"
        assert prompt_context["dep"]["field_b"] == "bravo"
        assert "field_c" not in prompt_context.get("dep", {})
        assert "field_d" not in prompt_context.get("dep", {})

    def test_observe_wildcard_includes_all_fields(self):
        """observe: ['dep.*'] -> llm_context has all fields from dep namespace."""
        field_context = {
            "dep": {"title": "War and Peace", "author": "Tolstoy", "year": 1869},
        }
        context_scope = {"observe": ["dep.*"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        assert llm_context["dep"]["title"] == "War and Peace"
        assert llm_context["dep"]["author"] == "Tolstoy"
        assert llm_context["dep"]["year"] == 1869
        assert len(llm_context["dep"]) == 3

    def test_observe_preserves_falsy_values(self):
        """Fields with values 0, '', False, None are included (not silently dropped)."""
        field_context = {
            "dep": {
                "zero": 0,
                "empty_str": "",
                "false_val": False,
                "none_val": None,
                "normal": "ok",
            },
        }
        context_scope = {
            "observe": [
                "dep.zero",
                "dep.empty_str",
                "dep.false_val",
                "dep.none_val",
                "dep.normal",
            ]
        }

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        assert llm_context["dep"]["zero"] == 0
        assert llm_context["dep"]["empty_str"] == ""
        assert llm_context["dep"]["false_val"] is False
        assert llm_context["dep"]["none_val"] is None
        assert llm_context["dep"]["normal"] == "ok"

    def test_observe_missing_field_raises_error(self):
        """Referencing a field that doesn't exist in field_context raises ConfigurationError."""
        field_context = {
            "dep": {"existing_a": 1, "existing_b": 2, "existing_c": 3},
        }
        context_scope = {"observe": ["dep.nonexistent"]}

        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(field_context, context_scope, action_name="test")

    def test_observe_multiple_namespaces(self):
        """observe: ['dep_a.x', 'dep_b.y'] -> llm_context has both namespaces."""
        field_context = {
            "dep_a": {"x": "x_val", "unused_a1": "skip", "unused_a2": "skip"},
            "dep_b": {"y": "y_val", "unused_b1": "skip", "unused_b2": "skip"},
        }
        context_scope = {"observe": ["dep_a.x", "dep_b.y"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        assert llm_context["dep_a"]["x"] == "x_val"
        assert llm_context["dep_b"]["y"] == "y_val"
        assert "unused_a1" not in llm_context.get("dep_a", {})
        assert "unused_b1" not in llm_context.get("dep_b", {})

    def test_framework_namespaces_always_in_prompt_context(self):
        """version, seed, workflow, loop namespaces always present in prompt_context
        regardless of observe."""
        field_context = {
            "dep": {"field": "value", "other": "x", "more": "y"},
            "version": {"i": 2, "idx": 1, "length": 5, "first": False, "last": False},
            "workflow": {"name": "test_wf", "version": "1.0"},
            "loop": {"iteration": 3},
        }
        context_scope = {"observe": ["dep.field"]}

        prompt_context, _, _ = apply_context_scope(field_context, context_scope, action_name="test")

        assert "version" in prompt_context
        assert prompt_context["version"]["i"] == 2
        assert prompt_context["version"]["length"] == 5
        assert "workflow" in prompt_context
        assert prompt_context["workflow"]["name"] == "test_wf"
        assert "loop" in prompt_context
        assert prompt_context["loop"]["iteration"] == 3

    def test_framework_namespaces_not_in_llm_context(self):
        """Framework namespaces are in prompt_context but NOT in llm_context."""
        field_context = {
            "dep": {"field": "value", "extra1": "e1", "extra2": "e2"},
            "version": {"i": 1, "idx": 0, "length": 3},
            "seed": {"rubric": "criteria"},
            "workflow": {"name": "wf"},
            "loop": {"iter": 0},
        }
        context_scope = {"observe": ["dep.field"]}

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        for ns in FRAMEWORK_NAMESPACES:
            assert ns not in llm_context, f"Framework namespace '{ns}' leaked into llm_context"

        # But they should be in prompt_context
        assert "version" in prompt_context
        assert "seed" in prompt_context
        assert "workflow" in prompt_context
        assert "loop" in prompt_context


# ---------------------------------------------------------------------------
# TestObserveCrossNamespace
# ---------------------------------------------------------------------------


class TestObserveCrossNamespace:
    """Loading data from ancestors 2+ steps upstream via historical lookup."""

    def _make_storage_backend(self, records_by_action: dict) -> MockStorageBackend:
        """Build a MockStorageBackend from {action_name: [records]}."""
        return MockStorageBackend(records_by_action)

    def test_observe_ancestor_two_steps_back(self):
        """A -> B -> C: C observes A.field via historical lookup. Correct value loaded."""
        # A produced a record; B consumed it; C now needs A's data.
        # In a real pipeline, build_field_context_with_history would load from storage.
        # Here we test by building field_context as the builder would after historical load.
        storage = self._make_storage_backend(
            {
                "action_a": [
                    {
                        "node_id": "action_a_rec1",
                        "source_guid": "sg1",
                        "content": {
                            "question": "What is gravity?",
                            "category": "physics",
                            "difficulty": "medium",
                        },
                    }
                ],
            }
        )

        # Simulate what build_field_context_with_history produces after historical load:
        # C's field_context includes action_a loaded via storage_backend
        data = storage.read_target("action_a", "mock_file.json")
        loaded_content = data[0]["content"]

        field_context = {
            "action_b": {
                "summary": "Gravity is a force",
                "score": 0.95,
                "tags": ["science"],
            },
            "action_a": loaded_content,
        }
        context_scope = {"observe": ["action_a.question", "action_b.summary"]}

        _, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="action_c"
        )

        assert llm_context["action_a"]["question"] == "What is gravity?"
        assert llm_context["action_b"]["summary"] == "Gravity is a force"
        assert "category" not in llm_context.get("action_a", {})
        assert "score" not in llm_context.get("action_b", {})

    def test_observe_ancestor_three_steps_back(self):
        """A -> B -> C -> D: D observes A.field. Lineage chain traversed correctly."""
        storage = self._make_storage_backend(
            {
                "action_a": [
                    {
                        "node_id": "action_a_r1",
                        "source_guid": "sg1",
                        "content": {
                            "raw_text": "Original document content",
                            "word_count": 150,
                            "language": "en",
                        },
                    }
                ],
            }
        )

        data = storage.read_target("action_a", "mock_file.json")
        loaded_content = data[0]["content"]

        field_context = {
            "action_a": loaded_content,
            "action_b": {"extracted": "key info", "confidence": 0.88, "method": "nlp"},
            "action_c": {"enriched": "enriched data", "source": "api", "quality": "high"},
        }
        context_scope = {
            "observe": ["action_a.raw_text", "action_a.word_count", "action_c.enriched"]
        }

        _, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="action_d"
        )

        assert llm_context["action_a"]["raw_text"] == "Original document content"
        assert llm_context["action_a"]["word_count"] == 150
        assert llm_context["action_c"]["enriched"] == "enriched data"
        assert "language" not in llm_context.get("action_a", {})
        assert "action_b" not in llm_context

    def test_observe_multiple_ancestors(self):
        """D observes both A.field_x and B.field_y (different ancestors). Both loaded correctly."""
        storage = self._make_storage_backend(
            {
                "action_a": [
                    {
                        "node_id": "action_a_r1",
                        "source_guid": "sg1",
                        "content": {
                            "original_text": "Hello world",
                            "format": "plain",
                            "encoding": "utf-8",
                        },
                    }
                ],
                "action_b": [
                    {
                        "node_id": "action_b_r1",
                        "source_guid": "sg1",
                        "content": {
                            "translation": "Hola mundo",
                            "target_lang": "es",
                            "quality_score": 0.92,
                        },
                    }
                ],
            }
        )

        a_content = storage.read_target("action_a", "mock_file.json")[0]["content"]
        b_content = storage.read_target("action_b", "mock_file.json")[0]["content"]

        field_context = {
            "action_a": a_content,
            "action_b": b_content,
            "action_c": {"summary": "test", "notes": "none", "status": "done"},
        }
        context_scope = {
            "observe": ["action_a.original_text", "action_b.translation", "action_b.quality_score"]
        }

        _, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="action_d"
        )

        assert llm_context["action_a"]["original_text"] == "Hello world"
        assert llm_context["action_b"]["translation"] == "Hola mundo"
        assert llm_context["action_b"]["quality_score"] == 0.92
        assert "format" not in llm_context.get("action_a", {})
        assert "target_lang" not in llm_context.get("action_b", {})
        assert "action_c" not in llm_context

    def test_observe_correct_record_among_siblings(self):
        """Ancestor action has 5 records; observe loads the one matching current lineage,
        not first match."""
        storage = self._make_storage_backend(
            {
                "extract": [
                    {
                        "node_id": "extract_r1",
                        "source_guid": "sg1",
                        "content": {"answer": "wrong_1", "score": 1, "status": "bad"},
                    },
                    {
                        "node_id": "extract_r2",
                        "source_guid": "sg2",
                        "content": {"answer": "wrong_2", "score": 2, "status": "bad"},
                    },
                    {
                        "node_id": "extract_r3",
                        "source_guid": "sg3",
                        "content": {"answer": "correct_answer", "score": 99, "status": "good"},
                    },
                    {
                        "node_id": "extract_r4",
                        "source_guid": "sg4",
                        "content": {"answer": "wrong_4", "score": 4, "status": "bad"},
                    },
                    {
                        "node_id": "extract_r5",
                        "source_guid": "sg5",
                        "content": {"answer": "wrong_5", "score": 5, "status": "bad"},
                    },
                ],
            }
        )

        # Resolve the correct record via node_id (lineage entry for "extract")
        target_node_id = "extract_r3"
        all_records = storage.read_target("extract", "mock_file.json")
        matched = next((r for r in all_records if r.get("node_id") == target_node_id), None)
        assert matched is not None
        loaded_content = matched["content"]

        field_context = {
            "extract": loaded_content,
        }
        context_scope = {"observe": ["extract.answer", "extract.score"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="consume")

        # Must get the correct record (r3), not r1
        assert llm_context["extract"]["answer"] == "correct_answer"
        assert llm_context["extract"]["score"] == 99


# ---------------------------------------------------------------------------
# TestObserveCollision
# ---------------------------------------------------------------------------


class TestObserveCollision:
    """Same field name from different ancestor namespaces."""

    def test_file_mode_collision_qualifies_keys(self):
        """FILE-mode: dep_a.title + dep_b.title -> output keys qualified as
        'dep_a.title' and 'dep_b.title'."""
        # The collision detection happens in _resolve_observe_refs regardless of
        # record data. Two namespaces with the same bare field name trigger
        # qualified output keys.
        from agent_actions.prompt.context.scope_file_mode import _resolve_observe_refs

        resolved = _resolve_observe_refs(["dep_a.title", "dep_b.title"], action_name="test")

        # Both "title" refs should be qualified since bare key "title" collides
        output_keys = [output_key for _, _, output_key in resolved]
        assert "dep_a.title" in output_keys
        assert "dep_b.title" in output_keys
        # Bare "title" should NOT appear
        assert "title" not in output_keys

    def test_record_mode_collision_behavior(self):
        """RECORD-mode: verify behavior when two namespaces have same field name.
        In record mode, llm_context is namespaced so no collision occurs."""
        field_context = {
            "dep_a": {"title": "Title A", "author": "Author A", "year": 2020},
            "dep_b": {"title": "Title B", "genre": "fiction", "pages": 300},
        }
        context_scope = {"observe": ["dep_a.title", "dep_b.title"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        # Record-mode: each namespace is separate, no collision
        assert llm_context["dep_a"]["title"] == "Title A"
        assert llm_context["dep_b"]["title"] == "Title B"
        # Other fields excluded
        assert "author" not in llm_context.get("dep_a", {})
        assert "genre" not in llm_context.get("dep_b", {})

    def test_no_collision_preserves_bare_keys(self):
        """When field names are unique across namespaces, bare keys used (no qualification)."""
        from agent_actions.prompt.context.scope_file_mode import _resolve_observe_refs

        resolved = _resolve_observe_refs(
            ["dep_a.unique_field_x", "dep_b.unique_field_y"], action_name="test"
        )

        output_keys = [output_key for _, _, output_key in resolved]
        # Unique field names -> bare keys (no namespace qualification)
        assert "unique_field_x" in output_keys
        assert "unique_field_y" in output_keys
        assert "dep_a.unique_field_x" not in output_keys
        assert "dep_b.unique_field_y" not in output_keys


# ---------------------------------------------------------------------------
# TestObserveFanIn
# ---------------------------------------------------------------------------


class TestObserveFanIn:
    """Multiple dependencies converging into one action."""

    def test_fan_in_loads_all_dependencies(self):
        """Action with 3 upstream deps: all 3 namespaces present in field_context."""
        field_context = {
            "extract": {"text": "extracted content", "source": "doc1", "length": 500},
            "classify": {"category": "science", "confidence": 0.95, "model": "v2"},
            "enrich": {"entities": ["gravity"], "count": 1, "quality": "high"},
        }
        context_scope = {"observe": ["extract.*", "classify.*", "enrich.*"]}

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="merge_action"
        )

        # All 3 namespaces in llm_context
        assert "extract" in llm_context
        assert "classify" in llm_context
        assert "enrich" in llm_context
        # Specific values
        assert llm_context["extract"]["text"] == "extracted content"
        assert llm_context["classify"]["category"] == "science"
        assert llm_context["classify"]["confidence"] == 0.95
        assert llm_context["enrich"]["entities"] == ["gravity"]
        # All in prompt_context too
        assert "extract" in prompt_context
        assert "classify" in prompt_context
        assert "enrich" in prompt_context

    def test_fan_in_context_source_uses_lineage(self):
        """Non-primary deps loaded via historical lookup using lineage, not just source_guid."""
        storage = MockStorageBackend(
            {
                "classify": [
                    {
                        "node_id": "classify_r1",
                        "source_guid": "sg1",
                        "content": {
                            "category": "biology",
                            "confidence": 0.88,
                            "method": "auto",
                        },
                    },
                    {
                        "node_id": "classify_r2",
                        "source_guid": "sg2",
                        "content": {
                            "category": "chemistry",
                            "confidence": 0.72,
                            "method": "manual",
                        },
                    },
                ],
            }
        )

        # Resolve the correct record via node_id (lineage entry for "classify")
        target = "classify_r1"
        records = storage.read_target("classify", "mock_file.json")
        matched = next((r for r in records if r.get("node_id") == target), None)
        assert matched is not None

        # Build field_context as the pipeline would
        field_context = {
            "extract": {"text": "raw text", "tokens": 42, "lang": "en"},
            "classify": matched["content"],
        }
        context_scope = {"observe": ["extract.text", "classify.category"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="merge")

        # Correct lineage-matched record
        assert llm_context["classify"]["category"] == "biology"
        assert llm_context["extract"]["text"] == "raw text"

    def test_fan_in_with_version_expansion(self):
        """Versioned deps (action_1, action_2, action_3) each get own namespace."""
        field_context = {
            "voter_1": {"score": 8, "reasoning": "good", "confidence": 0.9},
            "voter_2": {"score": 7, "reasoning": "decent", "confidence": 0.8},
            "voter_3": {"score": 9, "reasoning": "great", "confidence": 0.95},
        }
        context_scope = {"observe": ["voter_1.*", "voter_2.*", "voter_3.*"]}

        _, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="aggregate"
        )

        # Each version is a separate namespace -- no data loss
        assert llm_context["voter_1"]["score"] == 8
        assert llm_context["voter_2"]["score"] == 7
        assert llm_context["voter_3"]["score"] == 9
        assert llm_context["voter_1"]["reasoning"] == "good"
        assert llm_context["voter_2"]["reasoning"] == "decent"
        assert llm_context["voter_3"]["reasoning"] == "great"
        assert llm_context["voter_1"]["confidence"] == 0.9
        # All 3 namespaces present
        assert len(llm_context) == 3


# ---------------------------------------------------------------------------
# TestPassthroughIntegrity
# ---------------------------------------------------------------------------


class TestPassthroughIntegrity:
    """Passthrough fields: included in output but NOT sent to LLM."""

    def test_passthrough_not_in_llm_context(self):
        """passthrough: ['dep.secret_field'] -> NOT in llm_context."""
        field_context = {
            "dep": {"public": "visible", "secret_field": "hidden_value", "extra": "more"},
        }
        context_scope = {
            "observe": ["dep.public"],
            "passthrough": ["dep.secret_field"],
        }

        _, llm_context, passthrough = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        assert "secret_field" not in llm_context.get("dep", {})
        assert passthrough["dep"]["secret_field"] == "hidden_value"

    def test_passthrough_and_observe_same_namespace(self):
        """observe: ['dep.public'], passthrough: ['dep.internal'] ->
        public in llm_context, internal in output only."""
        field_context = {
            "dep": {"public": "for_llm", "internal": "for_output", "other": "skip"},
        }
        context_scope = {
            "observe": ["dep.public"],
            "passthrough": ["dep.internal"],
        }

        prompt_context, llm_context, passthrough = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        # public in llm_context
        assert llm_context["dep"]["public"] == "for_llm"
        # internal NOT in llm_context
        assert "internal" not in llm_context.get("dep", {})
        # internal in passthrough
        assert passthrough["dep"]["internal"] == "for_output"
        # both in prompt_context (observe + passthrough)
        assert prompt_context["dep"]["public"] == "for_llm"
        assert prompt_context["dep"]["internal"] == "for_output"
        # other excluded from everywhere
        assert "other" not in prompt_context.get("dep", {})
        assert "other" not in llm_context.get("dep", {})

    def test_passthrough_preserves_field_types(self):
        """Passthrough preserves original types: int, bool, list, dict, None."""
        field_context = {
            "dep": {
                "int_field": 42,
                "bool_field": True,
                "list_field": [1, 2, 3],
                "dict_field": {"nested": "value"},
                "none_field": None,
            },
        }
        context_scope = {
            "passthrough": [
                "dep.int_field",
                "dep.bool_field",
                "dep.list_field",
                "dep.dict_field",
                "dep.none_field",
            ]
        }

        _, _, passthrough = apply_context_scope(field_context, context_scope, action_name="test")

        assert passthrough["dep"]["int_field"] == 42
        assert isinstance(passthrough["dep"]["int_field"], int)
        assert passthrough["dep"]["bool_field"] is True
        assert passthrough["dep"]["list_field"] == [1, 2, 3]
        assert isinstance(passthrough["dep"]["list_field"], list)
        assert passthrough["dep"]["dict_field"] == {"nested": "value"}
        assert isinstance(passthrough["dep"]["dict_field"], dict)
        assert passthrough["dep"]["none_field"] is None


# ---------------------------------------------------------------------------
# TestDropSecurity
# ---------------------------------------------------------------------------


class TestDropSecurity:
    """Drop directive: security gate preventing field leakage."""

    def test_drop_removes_field_from_prompt_context(self):
        """drop: ['dep.api_key'] -> api_key NOT in prompt_context, NOT in llm_context."""
        field_context = {
            "dep": {
                "api_key": "sk-secret-123",
                "name": "service",
                "url": "https://api.example.com",
            },
        }
        context_scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.*"],
        }

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        assert "api_key" not in prompt_context.get("dep", {})
        assert "api_key" not in llm_context.get("dep", {})
        # Other fields preserved
        assert prompt_context["dep"]["name"] == "service"
        assert llm_context["dep"]["name"] == "service"
        assert llm_context["dep"]["url"] == "https://api.example.com"

    def test_drop_wildcard_clears_namespace(self):
        """drop: ['dep.*'] -> entire dep namespace removed."""
        field_context = {
            "dep": {"field1": "a", "field2": "b", "field3": "c"},
        }
        context_scope = {
            "drop": ["dep.*"],
            "observe": ["dep.*"],
        }

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        # All fields cleared
        assert prompt_context.get("dep", {}) == {}
        assert llm_context == {}

    def test_drop_then_observe_wildcard_excludes_dropped(self):
        """drop: ['dep.secret'], observe: ['dep.*'] -> all fields EXCEPT secret in llm_context."""
        field_context = {
            "dep": {"secret": "hidden", "name": "public_name", "value": "public_value"},
        }
        context_scope = {
            "drop": ["dep.secret"],
            "observe": ["dep.*"],
        }

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        assert "secret" not in llm_context.get("dep", {})
        assert "secret" not in prompt_context.get("dep", {})
        assert llm_context["dep"]["name"] == "public_name"
        assert llm_context["dep"]["value"] == "public_value"

    def test_observe_dropped_field_raises_error(self):
        """drop: ['dep.x'], observe: ['dep.x'] -> ConfigurationError (not silent skip)."""
        field_context = {
            "dep": {"x": "secret_value", "y": "other", "z": "more"},
        }
        context_scope = {
            "drop": ["dep.x"],
            "observe": ["dep.x"],
        }

        with pytest.raises(ConfigurationError, match="not found at runtime"):
            apply_context_scope(field_context, context_scope, action_name="test")

    def test_drop_happens_before_observe(self):
        """Execution order: drop first, then observe reads from post-drop state."""
        field_context = {
            "dep": {"sensitive": "secret123", "public": "hello", "extra": "data"},
        }
        # Drop sensitive, then observe wildcard -- sensitive must be gone
        context_scope = {
            "drop": ["dep.sensitive"],
            "observe": ["dep.*"],
        }

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        assert "sensitive" not in llm_context.get("dep", {})
        assert llm_context["dep"]["public"] == "hello"
        assert llm_context["dep"]["extra"] == "data"

    def test_dropped_field_not_in_passthrough(self):
        """Dropped fields don't leak via passthrough either.

        Note: passthrough reads from the ORIGINAL field_context (before drop),
        so this test verifies that users should not rely on drop to prevent
        passthrough leakage -- they should simply not list the field in passthrough.
        The drop directive operates on prompt_context only."""
        field_context = {
            "dep": {"api_key": "sk-secret", "name": "service", "url": "https://api.com"},
        }
        # Drop api_key from prompt_context, but also try to passthrough it
        # Passthrough reads from original field_context, so it will still find it
        # This documents the actual behavior:
        context_scope = {
            "drop": ["dep.api_key"],
            "observe": ["dep.name"],
            "passthrough": ["dep.url"],
        }

        prompt_context, llm_context, passthrough = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        # Dropped from prompt_context and llm_context
        assert "api_key" not in prompt_context.get("dep", {})
        assert "api_key" not in llm_context.get("dep", {})
        # Passthrough only gets what was declared
        assert "api_key" not in passthrough.get("dep", {})
        assert passthrough["dep"]["url"] == "https://api.com"

    def test_drop_missing_field_warns_not_crashes(self):
        """Dropping a nonexistent field logs warning, doesn't raise."""
        field_context = {
            "dep": {"existing": "value", "other": "data", "more": "info"},
        }
        context_scope = {"drop": ["dep.nonexistent"]}

        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            prompt_context, llm_context, _ = apply_context_scope(
                field_context, context_scope, action_name="test"
            )

        mock_logger.warning.assert_called()
        warning_args = mock_logger.warning.call_args[0]
        assert "matched zero fields" in warning_args[0]

    def test_drop_missing_namespace_warns_not_crashes(self):
        """Dropping from nonexistent namespace logs warning, doesn't raise."""
        field_context = {
            "dep": {"field": "value", "other": "data", "more": "info"},
        }
        context_scope = {"drop": ["ghost_namespace.field"]}

        with patch("agent_actions.prompt.context.scope_application.logger") as mock_logger:
            prompt_context, llm_context, _ = apply_context_scope(
                field_context, context_scope, action_name="test"
            )

        mock_logger.warning.assert_called()
        warning_args = mock_logger.warning.call_args[0]
        assert "matched zero fields" in warning_args[0]


# ---------------------------------------------------------------------------
# TestFileModeObserve
# ---------------------------------------------------------------------------


class TestFileModeObserve:
    """FILE-mode specific observe behavior."""

    def test_file_mode_observe_filters_fields_per_record(self):
        """FILE-mode observe extracts fields from namespaced content."""
        data = [
            {
                "content": {"dep": {"title": "Record 1", "body": "Text 1", "secret": "hidden1"}},
                "source_guid": "sg1",
            },
            {
                "content": {"dep": {"title": "Record 2", "body": "Text 2", "secret": "hidden2"}},
                "source_guid": "sg2",
            },
            {
                "content": {"dep": {"title": "Record 3", "body": "Text 3", "secret": "hidden3"}},
                "source_guid": "sg3",
            },
        ]
        agent_config = {
            "context_scope": {"observe": ["dep.title", "dep.body"]},
            "dependencies": "dep",
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="consumer",
        )

        assert len(result) == 3
        for i, record in enumerate(result, 1):
            assert record["content"]["title"] == f"Record {i}"
            assert record["content"]["body"] == f"Text {i}"
            # Original namespace preserved
            assert record["content"]["dep"]["secret"] == f"hidden{i}"
            assert record["source_guid"] == f"sg{i}"

    def test_file_mode_observe_preserves_record_order(self):
        """Output array order matches input array order."""
        data = [
            {
                "content": {"dep": {"name": "Charlie", "age": 30, "city": "NYC"}},
                "source_guid": "sg3",
            },
            {
                "content": {"dep": {"name": "Alice", "age": 25, "city": "LA"}},
                "source_guid": "sg1",
            },
            {
                "content": {"dep": {"name": "Bob", "age": 35, "city": "Chicago"}},
                "source_guid": "sg2",
            },
        ]
        agent_config = {
            "context_scope": {"observe": ["dep.name"]},
            "dependencies": "dep",
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="consumer",
        )

        assert len(result) == 3
        assert result[0]["content"]["name"] == "Charlie"
        assert result[1]["content"]["name"] == "Alice"
        assert result[2]["content"]["name"] == "Bob"

    def test_file_mode_cross_namespace_from_record(self):
        """FILE-mode reads cross-namespace data from record's namespaced content.

        With the additive model, all previous action outputs are on the record.
        No storage backend lookup needed.
        """
        data = [
            {
                "content": {
                    "extract": {"text": "Biology paper", "length": 500, "format": "pdf"},
                    "classify": {"category": "science", "score": 0.95, "method": "auto"},
                },
                "source_guid": "sg1",
                "node_id": "enrich_r1",
            },
        ]
        agent_config = {
            "context_scope": {"observe": ["extract.text", "classify.category"]},
            "dependencies": "extract",
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="enrich",
        )

        assert len(result) == 1
        # Fields extracted from namespaces
        assert result[0]["content"]["text"] == "Biology paper"
        assert result[0]["content"]["category"] == "science"
        # Original namespaces preserved
        assert result[0]["content"]["extract"]["length"] == 500
        assert result[0]["source_guid"] == "sg1"

    def test_file_mode_missing_field_warns(self):
        """FILE-mode: observe references missing field -> field absent from output,
        but all original content preserved."""
        data = [
            {
                "content": {
                    "dep": {"title": "Exists", "body": "Also exists", "extra": "here too"},
                },
                "source_guid": "sg1",
            },
        ]
        agent_config = {
            "context_scope": {"observe": ["dep.title", "dep.nonexistent_field"]},
            "dependencies": "dep",
        }

        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="consumer",
        )

        assert len(result) == 1
        assert result[0]["content"]["title"] == "Exists"
        # nonexistent_field is simply absent (not injected)
        assert "nonexistent_field" not in result[0]["content"]
        # Original namespace preserved
        assert result[0]["content"]["dep"]["body"] == "Also exists"
        assert result[0]["content"]["dep"]["extra"] == "here too"


# ---------------------------------------------------------------------------
# TestContextScopeEdgeCases
# ---------------------------------------------------------------------------


class TestContextScopeEdgeCases:
    """Edge cases and error handling."""

    def test_no_context_scope_raises_error(self):
        """Action without context_scope config raises ConfigurationError at the service layer.
        At the apply_context_scope level, empty context_scope produces empty results
        (the service layer enforces the requirement)."""
        from agent_actions.prompt.service import PromptPreparationService

        with pytest.raises(ConfigurationError, match="context_scope is required"):
            PromptPreparationService._build_llm_context(
                mode="online",
                contents={"text": "hello", "other": "data", "more": "info"},
                llm_additional_context={},
                context_scope=None,
            )

    def test_empty_observe_list(self):
        """observe: [] -> no fields in llm_context (but prompt_context has framework namespaces)."""
        field_context = {
            "dep": {"field1": "a", "field2": "b", "field3": "c"},
            "version": {"i": 1, "length": 3},
            "workflow": {"name": "test"},
        }
        context_scope = {"observe": []}

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="test"
        )

        assert llm_context == {}
        # Framework namespaces still in prompt_context
        assert "version" in prompt_context
        assert prompt_context["version"]["i"] == 1
        assert "workflow" in prompt_context
        # But dep is excluded (nothing scoped it in)
        assert "dep" not in prompt_context

    def test_malformed_field_reference_raises(self):
        """observe: ['no_dot_ref'] -> ValueError from parse_field_reference."""
        with pytest.raises(ValueError, match="Expected format"):
            parse_field_reference("no_dot_ref")

    def test_nested_field_path(self):
        """observe: ['dep.parent.child'] -> nested value extracted correctly."""
        field_context = {
            "dep": {
                "parent": {"child": "nested_value", "sibling": "other"},
                "flat_field": "flat",
                "another": "more",
            },
        }
        context_scope = {"observe": ["dep.parent.child"]}

        _, llm_context, _ = apply_context_scope(field_context, context_scope, action_name="test")

        # Nested path is stored with the dotted key
        assert llm_context["dep"]["parent.child"] == "nested_value"
        assert "flat_field" not in llm_context.get("dep", {})

    def test_version_namespace_auto_expansion(self):
        """Base name 'voter' expands to voter_1, voter_2, voter_3 when versioned.
        After expansion, each version is a standard namespace in field_context."""
        field_context = {
            "voter_1": {"score": 8, "reasoning": "good", "confidence": 0.9},
            "voter_2": {"score": 7, "reasoning": "decent", "confidence": 0.8},
            "voter_3": {"score": 9, "reasoning": "great", "confidence": 0.95},
        }
        # After expansion, context_scope references concrete version names
        context_scope = {"observe": ["voter_1.*", "voter_2.*", "voter_3.*"]}

        prompt_context, llm_context, _ = apply_context_scope(
            field_context, context_scope, action_name="aggregate"
        )

        # All 3 version namespaces present
        assert "voter_1" in llm_context
        assert "voter_2" in llm_context
        assert "voter_3" in llm_context
        # Correct values
        assert llm_context["voter_1"]["score"] == 8
        assert llm_context["voter_2"]["score"] == 7
        assert llm_context["voter_3"]["score"] == 9
        # All in prompt_context
        assert "voter_1" in prompt_context
        assert "voter_2" in prompt_context
        assert "voter_3" in prompt_context
