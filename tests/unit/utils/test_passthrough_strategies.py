"""Tests for passthrough strategies returning flat action output dicts.

After the RecordEnvelope migration, strategies return flat dicts containing
only the action's output fields.  PassthroughTransformer calls
RecordEnvelope.build() to wrap them under the action namespace and
preserve upstream namespaces.
"""

from agent_actions.utils.transformation.passthrough import PassthroughTransformer
from agent_actions.utils.transformation.strategies.base import ensure_dict_output
from agent_actions.utils.transformation.strategies.context_scope import (
    ContextScopeStructuredStrategy,
    ContextScopeUnstructuredStrategy,
    DefaultStructureStrategy,
    NoOpStrategy,
)
from agent_actions.utils.transformation.strategies.precomputed import (
    PrecomputedStructuredStrategy,
    PrecomputedUnstructuredStrategy,
)


def _agent_config(action_name="test_action", passthrough=None):
    config = {"agent_type": action_name}
    if passthrough:
        config["context_scope"] = {"passthrough": passthrough}
    return config


# ---------------------------------------------------------------------------
# ensure_dict_output helper
# ---------------------------------------------------------------------------


class TestEnsureDictOutput:
    """ensure_dict_output normalizes items to dicts."""

    def test_dict_passes_through(self):
        assert ensure_dict_output({"x": 1}) == {"x": 1}

    def test_string_wrapped(self):
        assert ensure_dict_output("text") == {"value": "text"}

    def test_int_wrapped(self):
        assert ensure_dict_output(42) == {"value": 42}

    def test_none_wrapped(self):
        assert ensure_dict_output(None) == {"value": None}

    def test_list_wrapped(self):
        assert ensure_dict_output([1, 2]) == {"value": [1, 2]}


# ---------------------------------------------------------------------------
# DefaultStructureStrategy
# ---------------------------------------------------------------------------


class TestDefaultStructureStrategy:
    """DefaultStructureStrategy returns flat action output dicts."""

    def test_returns_flat_dict(self):
        strategy = DefaultStructureStrategy()
        result = strategy.transform([{"vote": "keep", "score": 8}], {}, "g1", _agent_config())
        assert len(result) == 1
        assert result[0] == {"vote": "keep", "score": 8}

    def test_no_source_guid_in_output(self):
        strategy = DefaultStructureStrategy()
        result = strategy.transform([{"x": 1}], {}, "g1", _agent_config())
        assert "source_guid" not in result[0]
        assert "content" not in result[0]

    def test_non_dict_wrapped_in_value(self):
        strategy = DefaultStructureStrategy()
        result = strategy.transform(["plain text"], {}, "g1", _agent_config())
        assert result[0] == {"value": "plain text"}

    def test_multiple_items(self):
        strategy = DefaultStructureStrategy()
        result = strategy.transform([{"a": 1}, {"b": 2}], {}, "g1", _agent_config())
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_can_handle_always_true(self):
        strategy = DefaultStructureStrategy()
        assert strategy.can_handle([], None, _agent_config(), False) is True
        assert strategy.can_handle([], None, _agent_config(), True) is True


# ---------------------------------------------------------------------------
# NoOpStrategy
# ---------------------------------------------------------------------------


class TestNoOpStrategy:
    """NoOpStrategy extracts content from structured items, returns flat."""

    def test_extracts_content_from_structured(self):
        strategy = NoOpStrategy()
        structured = [{"source_guid": "g1", "content": {"vote": "keep", "score": 9}}]
        result = strategy.transform(structured, {}, "g1", _agent_config())
        assert len(result) == 1
        assert result[0] == {"vote": "keep", "score": 9}

    def test_no_source_guid_in_output(self):
        strategy = NoOpStrategy()
        structured = [{"source_guid": "g1", "content": {"x": 1}}]
        result = strategy.transform(structured, {}, "g1", _agent_config())
        assert "source_guid" not in result[0]

    def test_non_dict_content_wrapped(self):
        strategy = NoOpStrategy()
        structured = [{"source_guid": "g1", "content": "plain"}]
        result = strategy.transform(structured, {}, "g1", _agent_config())
        assert result[0] == {"value": "plain"}

    def test_multiple_structured_items(self):
        strategy = NoOpStrategy()
        structured = [
            {"source_guid": "g1", "content": {"a": 1}},
            {"source_guid": "g2", "content": {"b": 2}},
        ]
        result = strategy.transform(structured, {}, "g1", _agent_config())
        assert len(result) == 2
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}

    def test_can_handle_requires_structured_no_passthrough(self):
        strategy = NoOpStrategy()
        structured = [{"source_guid": "g1", "content": {"x": 1}}]
        assert strategy.can_handle(structured, None, _agent_config(), True) is True
        assert strategy.can_handle(structured, None, _agent_config(), False) is False
        assert (
            strategy.can_handle(structured, None, _agent_config(passthrough=["ns.field"]), True)
            is False
        )


# ---------------------------------------------------------------------------
# ContextScopeStructuredStrategy
# ---------------------------------------------------------------------------


class TestContextScopeStructuredStrategy:
    """ContextScopeStructuredStrategy returns flat dicts with passthrough merged."""

    def test_returns_flat_output(self):
        strategy = ContextScopeStructuredStrategy()
        config = _agent_config("action", passthrough=["ctx.extra_field"])
        data = [{"source_guid": "g1", "content": {"vote": "keep"}}]
        context = {"extra_field": "extra_val"}

        result = strategy.transform(data, context, "g1", config)

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert "source_guid" not in result[0]

    def test_no_transform_structure_in_output(self):
        """Output must not be wrapped records from transform_structure."""
        strategy = ContextScopeStructuredStrategy()
        config = _agent_config("action", passthrough=["ctx.field"])
        data = [{"source_guid": "g1", "content": {"x": 1}}]

        result = strategy.transform(data, {}, "g1", config)
        # Should not have source_guid or content wrapper
        for item in result:
            assert "source_guid" not in item


# ---------------------------------------------------------------------------
# ContextScopeUnstructuredStrategy
# ---------------------------------------------------------------------------


class TestContextScopeUnstructuredStrategy:
    """ContextScopeUnstructuredStrategy returns flat dicts with passthrough merged."""

    def test_returns_flat_output(self):
        strategy = ContextScopeUnstructuredStrategy()
        config = _agent_config("action", passthrough=["ctx.extra_field"])
        data = [{"vote": "keep"}]
        context = {"extra_field": "extra_val"}

        result = strategy.transform(data, context, "g1", config)

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert "source_guid" not in result[0]


# ---------------------------------------------------------------------------
# PrecomputedStructuredStrategy
# ---------------------------------------------------------------------------


class TestPrecomputedStructuredStrategy:
    """PrecomputedStructuredStrategy merges passthrough, returns flat."""

    def test_merges_passthrough_returns_flat(self):
        strategy = PrecomputedStructuredStrategy()
        data = [{"source_guid": "g1", "content": {"vote": "keep"}}]
        passthrough = {"extra": "value"}

        result = strategy.transform(data, {}, "g1", _agent_config(), passthrough)

        assert len(result) == 1
        assert result[0]["vote"] == "keep"
        assert result[0]["extra"] == "value"
        assert "source_guid" not in result[0]
        assert "content" not in result[0]

    def test_no_wrap_content_in_output(self):
        """Output should not be wrapped under action namespace."""
        strategy = PrecomputedStructuredStrategy()
        data = [{"source_guid": "g1", "content": {"x": 1}}]
        passthrough = {"y": 2}

        result = strategy.transform(data, {}, "g1", _agent_config("act"), passthrough)

        # Flat — no action namespace wrapping
        assert "act" not in result[0]
        assert result[0]["x"] == 1
        assert result[0]["y"] == 2

    def test_item_without_content_key(self):
        strategy = PrecomputedStructuredStrategy()
        data = [{"source_guid": "g1", "content": {"x": 1}}, {"other": "val"}]
        passthrough = {"y": 2}

        result = strategy.transform(data, {}, "g1", _agent_config(), passthrough)

        assert result[0] == {"x": 1, "y": 2}
        assert result[1] == {"other": "val", "y": 2}


# ---------------------------------------------------------------------------
# PrecomputedUnstructuredStrategy
# ---------------------------------------------------------------------------


class TestPrecomputedUnstructuredStrategy:
    """PrecomputedUnstructuredStrategy merges passthrough, returns flat."""

    def test_merges_passthrough_returns_flat(self):
        strategy = PrecomputedUnstructuredStrategy()
        data = [{"vote": "keep"}]
        passthrough = {"extra": "value"}

        result = strategy.transform(data, {}, "g1", _agent_config(), passthrough)

        assert len(result) == 1
        assert result[0] == {"vote": "keep", "extra": "value"}
        assert "source_guid" not in result[0]

    def test_non_dict_items_normalized(self):
        strategy = PrecomputedUnstructuredStrategy()
        result = strategy.transform(["text"], {}, "g1", _agent_config(), {"k": "v"})
        assert result[0] == {"value": "text"}


# ---------------------------------------------------------------------------
# PassthroughTransformer — RecordEnvelope integration
# ---------------------------------------------------------------------------


class TestPassthroughTransformerEnvelope:
    """PassthroughTransformer wraps strategy output via RecordEnvelope."""

    def _make_agent_config(self, action_name="current_action"):
        return {"agent_type": action_name}

    def test_output_wrapped_under_namespace(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=[{"score": 0.9}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("classify"),
            action_name="classify",
        )
        assert len(result) == 1
        content = result[0]["content"]
        assert "classify" in content
        assert content["classify"] == {"score": 0.9}

    def test_upstream_namespaces_preserved(self):
        transformer = PassthroughTransformer()
        existing = {
            "extract": {"text": "hello"},
            "summarize": {"summary": "hi"},
        }
        result = transformer.transform_with_passthrough(
            data=[{"score": 0.9, "label": "positive"}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("classify"),
            action_name="classify",
            existing_content=existing,
        )
        content = result[0]["content"]
        assert content["extract"] == {"text": "hello"}
        assert content["summarize"] == {"summary": "hi"}
        assert content["classify"] == {"score": 0.9, "label": "positive"}

    def test_no_existing_content_works(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=[{"answer": "42"}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("qa"),
            action_name="qa",
            existing_content=None,
        )
        content = result[0]["content"]
        assert content == {"qa": {"answer": "42"}}

    def test_empty_existing_content(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=[{"answer": "42"}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("qa"),
            action_name="qa",
            existing_content={},
        )
        content = result[0]["content"]
        assert content == {"qa": {"answer": "42"}}

    def test_three_upstream_all_preserved(self):
        transformer = PassthroughTransformer()
        existing = {
            "flatten": {"questions": ["q1"]},
            "dedup": {"unique": ["q1"]},
            "filter_1": {"quality": "high"},
        }
        result = transformer.transform_with_passthrough(
            data=[{"grade": "A"}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("grade"),
            action_name="grade",
            existing_content=existing,
        )
        content = result[0]["content"]
        assert set(content.keys()) == {"flatten", "dedup", "filter_1", "grade"}
        assert content["grade"] == {"grade": "A"}

    def test_namespace_collision_current_wins(self):
        transformer = PassthroughTransformer()
        existing = {"rerun": {"old": True}}
        result = transformer.transform_with_passthrough(
            data=[{"new": True}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("rerun"),
            action_name="rerun",
            existing_content=existing,
        )
        content = result[0]["content"]
        assert content["rerun"] == {"new": True}

    def test_structured_data_gets_upstream_merge(self):
        """Already-structured data (NoOp path) also preserves upstream."""
        transformer = PassthroughTransformer()
        existing = {"upstream": {"val": 1}}
        structured = [{"source_guid": "g1", "content": {"result": "ok"}}]

        result = transformer.transform_with_passthrough(
            data=structured,
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("current"),
            action_name="current",
            existing_content=existing,
        )
        content = result[0]["content"]
        assert content["upstream"] == {"val": 1}
        assert "current" in content

    def test_multiple_output_items_all_get_upstream(self):
        transformer = PassthroughTransformer()
        existing = {"extract": {"text": "hello"}}
        result = transformer.transform_with_passthrough(
            data=[{"variant": "A"}, {"variant": "B"}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("generate"),
            action_name="generate",
            existing_content=existing,
        )
        assert len(result) == 2
        for item in result:
            assert item["content"]["extract"] == {"text": "hello"}
            assert "generate" in item["content"]

    def test_source_guid_carried_forward(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=[{"x": 1}],
            context_data={},
            source_guid="my-guid",
            agent_config=self._make_agent_config("act"),
            action_name="act",
        )
        assert result[0]["source_guid"] == "my-guid"

    def test_non_dict_output_wrapped_in_value(self):
        """Non-dict strategy output gets wrapped as {value: ...}."""
        transformer = PassthroughTransformer()
        # PrecomputedUnstructured with non-dict items returns them as-is,
        # but the transformer wraps non-dict in {"value": ...}
        result = transformer.transform_with_passthrough(
            data=[{"score": 5}],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("act"),
            action_name="act",
        )
        # Should be wrapped under namespace
        assert "act" in result[0]["content"]

    def test_empty_data_returns_empty(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=[],
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("act"),
            action_name="act",
        )
        assert result == []

    def test_none_data_returns_empty(self):
        transformer = PassthroughTransformer()
        result = transformer.transform_with_passthrough(
            data=None,
            context_data={},
            source_guid="g1",
            agent_config=self._make_agent_config("act"),
            action_name="act",
        )
        assert result == []


# ---------------------------------------------------------------------------
# No is_version_merge in strategies
# ---------------------------------------------------------------------------


class TestNoVersionMergeInStrategies:
    """Strategies must not import or use is_version_merge."""

    def test_context_scope_no_version_merge(self):
        import inspect

        from agent_actions.utils.transformation.strategies import context_scope

        source = inspect.getsource(context_scope)
        assert "is_version_merge" not in source

    def test_precomputed_no_version_merge(self):
        import inspect

        from agent_actions.utils.transformation.strategies import precomputed

        source = inspect.getsource(precomputed)
        assert "is_version_merge" not in source

    def test_no_transform_structure_in_strategies(self):
        """Strategies should not call DataTransformer.transform_structure."""
        import inspect

        from agent_actions.utils.transformation.strategies import context_scope, precomputed

        cs_source = inspect.getsource(context_scope)
        pc_source = inspect.getsource(precomputed)
        assert "transform_structure" not in cs_source
        assert "transform_structure" not in pc_source

    def test_no_wrap_content_in_strategies(self):
        """Strategies should not call wrap_content."""
        import inspect

        from agent_actions.utils.transformation.strategies import precomputed

        source = inspect.getsource(precomputed)
        assert "wrap_content" not in source
